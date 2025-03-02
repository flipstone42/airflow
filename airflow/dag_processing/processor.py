# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import datetime
import logging
import multiprocessing
import os
import signal
import threading
import time
from contextlib import redirect_stderr, redirect_stdout, suppress
from datetime import timedelta
from multiprocessing.connection import Connection as MultiprocessingConnection
from typing import Iterator, List, Optional, Set, Tuple

from setproctitle import setproctitle
from sqlalchemy import func, or_
from sqlalchemy.orm.session import Session

from airflow import models, settings
from airflow.callbacks.callback_requests import (
    CallbackRequest,
    DagCallbackRequest,
    SlaCallbackRequest,
    TaskCallbackRequest,
)
from airflow.configuration import conf
from airflow.exceptions import AirflowException, TaskNotFound
from airflow.models import SlaMiss, errors
from airflow.models.dag import DAG, DagModel
from airflow.models.dagbag import DagBag
from airflow.stats import Stats
from airflow.utils import timezone
from airflow.utils.email import get_email_address_list, send_email
from airflow.utils.log.logging_mixin import LoggingMixin, StreamLogWriter, set_context
from airflow.utils.mixins import MultiprocessingStartMethodMixin
from airflow.utils.session import NEW_SESSION, provide_session
from airflow.utils.state import State

DR = models.DagRun
TI = models.TaskInstance


class DagFileProcessorProcess(LoggingMixin, MultiprocessingStartMethodMixin):
    """Runs DAG processing in a separate process using DagFileProcessor

    :param file_path: a Python file containing Airflow DAG definitions
    :param pickle_dags: whether to serialize the DAG objects to the DB
    :param dag_ids: If specified, only look at these DAG ID's
    :param callback_requests: failure callback to execute
    """

    # Counter that increments every time an instance of this class is created
    class_creation_counter = 0

    def __init__(
        self,
        file_path: str,
        pickle_dags: bool,
        dag_ids: Optional[List[str]],
        callback_requests: List[CallbackRequest],
    ):
        super().__init__()
        self._file_path = file_path
        self._pickle_dags = pickle_dags
        self._dag_ids = dag_ids
        self._callback_requests = callback_requests

        # The process that was launched to process the given .
        self._process: Optional[multiprocessing.process.BaseProcess] = None
        # The result of DagFileProcessor.process_file(file_path).
        self._result: Optional[Tuple[int, int]] = None
        # Whether the process is done running.
        self._done = False
        # When the process started.
        self._start_time: Optional[datetime.datetime] = None
        # This ID is use to uniquely name the process / thread that's launched
        # by this processor instance
        self._instance_id = DagFileProcessorProcess.class_creation_counter

        self._parent_channel: Optional[MultiprocessingConnection] = None
        DagFileProcessorProcess.class_creation_counter += 1

    @property
    def file_path(self) -> str:
        return self._file_path

    @staticmethod
    def _run_file_processor(
        result_channel: MultiprocessingConnection,
        parent_channel: MultiprocessingConnection,
        file_path: str,
        pickle_dags: bool,
        dag_ids: Optional[List[str]],
        thread_name: str,
        callback_requests: List[CallbackRequest],
    ) -> None:
        """
        Process the given file.

        :param result_channel: the connection to use for passing back the result
        :param parent_channel: the parent end of the channel to close in the child
        :param file_path: the file to process
        :param pickle_dags: whether to pickle the DAGs found in the file and
            save them to the DB
        :param dag_ids: if specified, only examine DAG ID's that are
            in this list
        :param thread_name: the name to use for the process that is launched
        :param callback_requests: failure callback to execute
        :return: the process that was launched
        :rtype: multiprocessing.Process
        """
        # This helper runs in the newly created process
        log: logging.Logger = logging.getLogger("airflow.processor")

        # Since we share all open FDs from the parent, we need to close the parent side of the pipe here in
        # the child, else it won't get closed properly until we exit.
        log.info("Closing parent pipe")

        parent_channel.close()
        del parent_channel

        set_context(log, file_path)
        setproctitle(f"airflow scheduler - DagFileProcessor {file_path}")

        try:
            # redirect stdout/stderr to log
            with redirect_stdout(StreamLogWriter(log, logging.INFO)), redirect_stderr(
                StreamLogWriter(log, logging.WARN)
            ), Stats.timer() as timer:
                # Re-configure the ORM engine as there are issues with multiple processes
                settings.configure_orm()

                # Change the thread name to differentiate log lines. This is
                # really a separate process, but changing the name of the
                # process doesn't work, so changing the thread name instead.
                threading.current_thread().name = thread_name

                log.info("Started process (PID=%s) to work on %s", os.getpid(), file_path)
                dag_file_processor = DagFileProcessor(dag_ids=dag_ids, log=log)
                result: Tuple[int, int] = dag_file_processor.process_file(
                    file_path=file_path,
                    pickle_dags=pickle_dags,
                    callback_requests=callback_requests,
                )
                result_channel.send(result)
            log.info("Processing %s took %.3f seconds", file_path, timer.duration)
        except Exception:
            # Log exceptions through the logging framework.
            log.exception("Got an exception! Propagating...")
            raise
        finally:
            # We re-initialized the ORM within this Process above so we need to
            # tear it down manually here
            settings.dispose_orm()

            result_channel.close()

    def start(self) -> None:
        """Launch the process and start processing the DAG."""
        start_method = self._get_multiprocessing_start_method()
        context = multiprocessing.get_context(start_method)

        _parent_channel, _child_channel = context.Pipe(duplex=False)
        process = context.Process(
            target=type(self)._run_file_processor,
            args=(
                _child_channel,
                _parent_channel,
                self.file_path,
                self._pickle_dags,
                self._dag_ids,
                f"DagFileProcessor{self._instance_id}",
                self._callback_requests,
            ),
            name=f"DagFileProcessor{self._instance_id}-Process",
        )
        self._process = process
        self._start_time = timezone.utcnow()
        process.start()

        # Close the child side of the pipe now the subprocess has started -- otherwise this would prevent it
        # from closing in some cases
        _child_channel.close()
        del _child_channel

        # Don't store it on self until after we've started the child process - we don't want to keep it from
        # getting GCd/closed
        self._parent_channel = _parent_channel

    def kill(self) -> None:
        """Kill the process launched to process the file, and ensure consistent state."""
        if self._process is None:
            raise AirflowException("Tried to kill before starting!")
        self._kill_process()

    def terminate(self, sigkill: bool = False) -> None:
        """
        Terminate (and then kill) the process launched to process the file.

        :param sigkill: whether to issue a SIGKILL if SIGTERM doesn't work.
        """
        if self._process is None or self._parent_channel is None:
            raise AirflowException("Tried to call terminate before starting!")

        self._process.terminate()
        # Arbitrarily wait 5s for the process to die
        with suppress(TimeoutError):
            self._process._popen.wait(5)  # type: ignore
        if sigkill:
            self._kill_process()
        self._parent_channel.close()

    def _kill_process(self) -> None:
        if self._process is None:
            raise AirflowException("Tried to kill process before starting!")

        if self._process.is_alive() and self._process.pid:
            self.log.warning("Killing DAGFileProcessorProcess (PID=%d)", self._process.pid)
            os.kill(self._process.pid, signal.SIGKILL)

            # Reap the spawned zombie. We active wait, because in Python 3.9 `waitpid` might lead to an
            # exception, due to change in Python standard library and possibility of race condition
            # see https://bugs.python.org/issue42558
            while self._process._popen.poll() is None:  # type: ignore
                time.sleep(0.001)
        if self._parent_channel:
            self._parent_channel.close()

    @property
    def pid(self) -> int:
        """
        :return: the PID of the process launched to process the given file
        :rtype: int
        """
        if self._process is None or self._process.pid is None:
            raise AirflowException("Tried to get PID before starting!")
        return self._process.pid

    @property
    def exit_code(self) -> Optional[int]:
        """
        After the process is finished, this can be called to get the return code

        :return: the exit code of the process
        :rtype: int
        """
        if self._process is None:
            raise AirflowException("Tried to get exit code before starting!")
        if not self._done:
            raise AirflowException("Tried to call retcode before process was finished!")
        return self._process.exitcode

    @property
    def done(self) -> bool:
        """
        Check if the process launched to process this file is done.

        :return: whether the process is finished running
        :rtype: bool
        """
        if self._process is None or self._parent_channel is None:
            raise AirflowException("Tried to see if it's done before starting!")

        if self._done:
            return True

        if self._parent_channel.poll():
            try:
                self._result = self._parent_channel.recv()
                self._done = True
                self.log.debug("Waiting for %s", self._process)
                self._process.join()
                self._parent_channel.close()
                return True
            except EOFError:
                # If we get an EOFError, it means the child end of the pipe has been closed. This only happens
                # in the finally block. But due to a possible race condition, the process may have not yet
                # terminated (it could be doing cleanup/python shutdown still). So we kill it here after a
                # "suitable" timeout.
                self._done = True
                # Arbitrary timeout -- error/race condition only, so this doesn't need to be tunable.
                self._process.join(timeout=5)
                if self._process.is_alive():
                    # Didn't shut down cleanly - kill it
                    self._kill_process()

        if not self._process.is_alive():
            self._done = True
            self.log.debug("Waiting for %s", self._process)
            self._process.join()
            self._parent_channel.close()
            return True

        return False

    @property
    def result(self) -> Optional[Tuple[int, int]]:
        """
        :return: result of running DagFileProcessor.process_file()
        :rtype: tuple[int, int] or None
        """
        if not self.done:
            raise AirflowException("Tried to get the result before it's done!")
        return self._result

    @property
    def start_time(self) -> datetime.datetime:
        """
        :return: when this started to process the file
        :rtype: datetime
        """
        if self._start_time is None:
            raise AirflowException("Tried to get start time before it started!")
        return self._start_time

    @property
    def waitable_handle(self):
        return self._process.sentinel


class DagFileProcessor(LoggingMixin):
    """
    Process a Python file containing Airflow DAGs.

    This includes:

    1. Execute the file and look for DAG objects in the namespace.
    2. Execute any Callbacks if passed to DagFileProcessor.process_file
    3. Serialize the DAGs and save it to DB (or update existing record in the DB).
    4. Pickle the DAG and save it to the DB (if necessary).
    5. Record any errors importing the file into ORM

    Returns a tuple of 'number of dags found' and 'the count of import errors'

    :param dag_ids: If specified, only look at these DAG ID's
    :param log: Logger to save the processing process
    """

    UNIT_TEST_MODE: bool = conf.getboolean('core', 'UNIT_TEST_MODE')

    def __init__(self, dag_ids: Optional[List[str]], log: logging.Logger):
        super().__init__()
        self.dag_ids = dag_ids
        self._log = log

    @provide_session
    def manage_slas(self, dag: DAG, session: Session = None) -> None:
        """
        Finding all tasks that have SLAs defined, and sending alert emails
        where needed. New SLA misses are also recorded in the database.

        We are assuming that the scheduler runs often, so we only check for
        tasks that should have succeeded in the past hour.
        """
        self.log.info("Running SLA Checks for %s", dag.dag_id)
        if not any(isinstance(ti.sla, timedelta) for ti in dag.tasks):
            self.log.info("Skipping SLA check for %s because no tasks in DAG have SLAs", dag)
            return

        qry = (
            session.query(TI.task_id, func.max(DR.execution_date).label('max_ti'))
            .join(TI.dag_run)
            .with_hint(TI, 'USE INDEX (PRIMARY)', dialect_name='mysql')
            .filter(TI.dag_id == dag.dag_id)
            .filter(or_(TI.state == State.SUCCESS, TI.state == State.SKIPPED))
            .filter(TI.task_id.in_(dag.task_ids))
            .group_by(TI.task_id)
            .subquery('sq')
        )
        # get recorded SlaMiss
        recorded_slas_query = set(
            session.query(SlaMiss.dag_id, SlaMiss.task_id, SlaMiss.execution_date).filter(
                SlaMiss.dag_id == dag.dag_id, SlaMiss.task_id.in_(dag.task_ids)
            )
        )

        max_tis: Iterator[TI] = (
            session.query(TI)
            .join(TI.dag_run)
            .filter(
                TI.dag_id == dag.dag_id,
                TI.task_id == qry.c.task_id,
                DR.execution_date == qry.c.max_ti,
            )
        )

        ts = timezone.utcnow()

        for ti in max_tis:
            task = dag.get_task(ti.task_id)
            if not task.sla:
                continue

            if not isinstance(task.sla, timedelta):
                raise TypeError(
                    f"SLA is expected to be timedelta object, got "
                    f"{type(task.sla)} in {task.dag_id}:{task.task_id}"
                )

            sla_misses = []
            next_info = dag.next_dagrun_info(dag.get_run_data_interval(ti.dag_run), restricted=False)
            if next_info is None:
                self.log.info("Skipping SLA check for %s because task does not have scheduled date", ti)
            else:
                while next_info.logical_date < ts:
                    next_info = dag.next_dagrun_info(next_info.data_interval, restricted=False)

                    if next_info is None:
                        break
                    if (ti.dag_id, ti.task_id, next_info.logical_date) in recorded_slas_query:
                        break
                    if next_info.logical_date + task.sla < ts:

                        sla_miss = SlaMiss(
                            task_id=ti.task_id,
                            dag_id=ti.dag_id,
                            execution_date=next_info.logical_date,
                            timestamp=ts,
                        )
                        sla_misses.append(sla_miss)
            if sla_misses:
                session.add_all(sla_misses)
        session.commit()

        slas: List[SlaMiss] = (
            session.query(SlaMiss)
            .filter(SlaMiss.notification_sent == False, SlaMiss.dag_id == dag.dag_id)  # noqa
            .all()
        )
        if slas:
            sla_dates: List[datetime.datetime] = [sla.execution_date for sla in slas]
            fetched_tis: List[TI] = (
                session.query(TI)
                .filter(TI.state != State.SUCCESS, TI.execution_date.in_(sla_dates), TI.dag_id == dag.dag_id)
                .all()
            )
            blocking_tis: List[TI] = []
            for ti in fetched_tis:
                if ti.task_id in dag.task_ids:
                    ti.task = dag.get_task(ti.task_id)
                    blocking_tis.append(ti)
                else:
                    session.delete(ti)
                    session.commit()

            task_list = "\n".join(sla.task_id + ' on ' + sla.execution_date.isoformat() for sla in slas)
            blocking_task_list = "\n".join(
                ti.task_id + ' on ' + ti.execution_date.isoformat() for ti in blocking_tis
            )
            # Track whether email or any alert notification sent
            # We consider email or the alert callback as notifications
            email_sent = False
            notification_sent = False
            if dag.sla_miss_callback:
                # Execute the alert callback
                self.log.info('Calling SLA miss callback')
                try:
                    dag.sla_miss_callback(dag, task_list, blocking_task_list, slas, blocking_tis)
                    notification_sent = True
                except Exception:
                    Stats.incr('sla_callback_notification_failure')
                    self.log.exception("Could not call sla_miss_callback for DAG %s", dag.dag_id)
            email_content = f"""\
            Here's a list of tasks that missed their SLAs:
            <pre><code>{task_list}\n<code></pre>
            Blocking tasks:
            <pre><code>{blocking_task_list}<code></pre>
            Airflow Webserver URL: {conf.get(section='webserver', key='base_url')}
            """

            tasks_missed_sla = []
            for sla in slas:
                try:
                    task = dag.get_task(sla.task_id)
                except TaskNotFound:
                    # task already deleted from DAG, skip it
                    self.log.warning(
                        "Task %s doesn't exist in DAG anymore, skipping SLA miss notification.", sla.task_id
                    )
                    continue
                tasks_missed_sla.append(task)

            emails: Set[str] = set()
            for task in tasks_missed_sla:
                if task.email:
                    if isinstance(task.email, str):
                        emails |= set(get_email_address_list(task.email))
                    elif isinstance(task.email, (list, tuple)):
                        emails |= set(task.email)
            if emails:
                try:
                    send_email(emails, f"[airflow] SLA miss on DAG={dag.dag_id}", email_content)
                    email_sent = True
                    notification_sent = True
                except Exception:
                    Stats.incr('sla_email_notification_failure')
                    self.log.exception("Could not send SLA Miss email notification for DAG %s", dag.dag_id)
            # If we sent any notification, update the sla_miss table
            if notification_sent:
                for sla in slas:
                    sla.email_sent = email_sent
                    sla.notification_sent = True
                    session.merge(sla)
            session.commit()

    @staticmethod
    def update_import_errors(session: Session, dagbag: DagBag) -> None:
        """
        For the DAGs in the given DagBag, record any associated import errors and clears
        errors for files that no longer have them. These are usually displayed through the
        Airflow UI so that users know that there are issues parsing DAGs.

        :param session: session for ORM operations
        :param dagbag: DagBag containing DAGs with import errors
        """
        # Clear the errors of the processed files
        for dagbag_file in dagbag.file_last_changed:
            session.query(errors.ImportError).filter(
                errors.ImportError.filename.startswith(dagbag_file)
            ).delete(synchronize_session="fetch")

        # Add the errors of the processed files
        for filename, stacktrace in dagbag.import_errors.items():
            (
                session.query(DagModel)
                .filter(DagModel.fileloc == filename)
                .update({'has_import_errors': True}, synchronize_session='fetch')
            )

            session.add(
                errors.ImportError(filename=filename, timestamp=timezone.utcnow(), stacktrace=stacktrace)
            )
        session.commit()

    @provide_session
    def execute_callbacks(
        self, dagbag: DagBag, callback_requests: List[CallbackRequest], session: Session = NEW_SESSION
    ) -> None:
        """
        Execute on failure callbacks. These objects can come from SchedulerJob or from
        DagFileProcessorManager.

        :param dagbag: Dag Bag of dags
        :param callback_requests: failure callbacks to execute
        :param session: DB session.
        """
        for request in callback_requests:
            self.log.debug("Processing Callback Request: %s", request)
            try:
                if isinstance(request, TaskCallbackRequest):
                    self._execute_task_callbacks(dagbag, request)
                elif isinstance(request, SlaCallbackRequest):
                    self.manage_slas(dagbag.get_dag(request.dag_id), session=session)
                elif isinstance(request, DagCallbackRequest):
                    self._execute_dag_callbacks(dagbag, request, session)
            except Exception:
                self.log.exception(
                    "Error executing %s callback for file: %s",
                    request.__class__.__name__,
                    request.full_filepath,
                )

        session.commit()

    @provide_session
    def _execute_dag_callbacks(self, dagbag: DagBag, request: DagCallbackRequest, session: Session):
        dag = dagbag.dags[request.dag_id]
        dag_run = dag.get_dagrun(run_id=request.run_id, session=session)
        dag.handle_callback(
            dagrun=dag_run, success=not request.is_failure_callback, reason=request.msg, session=session
        )

    def _execute_task_callbacks(self, dagbag: DagBag, request: TaskCallbackRequest):
        simple_ti = request.simple_task_instance
        if simple_ti.dag_id in dagbag.dags:
            dag = dagbag.dags[simple_ti.dag_id]
            if simple_ti.task_id in dag.task_ids:
                task = dag.get_task(simple_ti.task_id)
                if request.is_failure_callback:
                    ti = TI(task, run_id=simple_ti.run_id)
                    # TODO: Use simple_ti to improve performance here in the future
                    ti.refresh_from_db()
                    ti.handle_failure_with_callback(error=request.msg, test_mode=self.UNIT_TEST_MODE)
                    self.log.info('Executed failure callback for %s in state %s', ti, ti.state)

    @provide_session
    def process_file(
        self,
        file_path: str,
        callback_requests: List[CallbackRequest],
        pickle_dags: bool = False,
        session: Session = None,
    ) -> Tuple[int, int]:
        """
        Process a Python file containing Airflow DAGs.

        This includes:

        1. Execute the file and look for DAG objects in the namespace.
        2. Execute any Callbacks if passed to this method.
        3. Serialize the DAGs and save it to DB (or update existing record in the DB).
        4. Pickle the DAG and save it to the DB (if necessary).
        5. Mark any DAGs which are no longer present as inactive
        6. Record any errors importing the file into ORM

        :param file_path: the path to the Python file that should be executed
        :param callback_requests: failure callback to execute
        :param pickle_dags: whether serialize the DAGs found in the file and
            save them to the db
        :param session: Sqlalchemy ORM Session
        :return: number of dags found, count of import errors
        :rtype: Tuple[int, int]
        """
        self.log.info("Processing file %s for tasks to queue", file_path)

        try:
            dagbag = DagBag(file_path, include_examples=False, include_smart_sensor=False)
        except Exception:
            self.log.exception("Failed at reloading the DAG file %s", file_path)
            Stats.incr('dag_file_refresh_error', 1, 1)
            return 0, 0

        if len(dagbag.dags) > 0:
            self.log.info("DAG(s) %s retrieved from %s", dagbag.dags.keys(), file_path)
        else:
            self.log.warning("No viable dags retrieved from %s", file_path)
            self.update_import_errors(session, dagbag)
            return 0, len(dagbag.import_errors)

        self.execute_callbacks(dagbag, callback_requests)

        # Save individual DAGs in the ORM
        dagbag.sync_to_db()

        if pickle_dags:
            paused_dag_ids = DagModel.get_paused_dag_ids(dag_ids=dagbag.dag_ids)

            unpaused_dags: List[DAG] = [
                dag for dag_id, dag in dagbag.dags.items() if dag_id not in paused_dag_ids
            ]

            for dag in unpaused_dags:
                dag.pickle(session)

        # Record import errors into the ORM
        try:
            self.update_import_errors(session, dagbag)
        except Exception:
            self.log.exception("Error logging import errors!")

        return len(dagbag.dags), len(dagbag.import_errors)
