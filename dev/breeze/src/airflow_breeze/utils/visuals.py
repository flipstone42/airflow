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
"""
Visuals displayed to the user when entering Breeze shell.
"""

from airflow_breeze.global_constants import (
    FLOWER_HOST_PORT,
    MSSQL_HOST_PORT,
    MYSQL_HOST_PORT,
    POSTGRES_HOST_PORT,
    REDIS_HOST_PORT,
    SSH_PORT,
    WEBSERVER_HOST_PORT,
)
from airflow_breeze.utils.path_utils import AIRFLOW_SOURCES_ROOT

ASCIIART = """




                                  @&&&&&&@
                                 @&&&&&&&&&&&@
                                &&&&&&&&&&&&&&&&
                                        &&&&&&&&&&
                                            &&&&&&&
                                             &&&&&&&
                           @@@@@@@@@@@@@@@@   &&&&&&
                          @&&&&&&&&&&&&&&&&&&&&&&&&&&
                         &&&&&&&&&&&&&&&&&&&&&&&&&&&&
                                         &&&&&&&&&&&&
                                             &&&&&&&&&
                                           &&&&&&&&&&&&
                                      @@&&&&&&&&&&&&&&&@
                   @&&&&&&&&&&&&&&&&&&&&&&&&&&&&  &&&&&&
                  &&&&&&&&&&&&&&&&&&&&&&&&&&&&    &&&&&&
                 &&&&&&&&&&&&&&&&&&&&&&&&         &&&&&&
                                                 &&&&&&
                                               &&&&&&&
                                            @&&&&&&&&
            @&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&
           &&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&
          &&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&



     @&&&@       &&  @&&&&&&&&&&&   &&&&&&&&&&&&  &&            &&&&&&&&&&  &&&     &&&     &&&
    &&& &&&      &&  @&&       &&&  &&            &&          &&&       &&&@ &&&   &&&&&   &&&
   &&&   &&&     &&  @&&&&&&&&&&&&  &&&&&&&&&&&   &&          &&         &&&  &&& &&& &&@ &&&
  &&&&&&&&&&&    &&  @&&&&&&&&&     &&            &&          &&@        &&&   &&@&&   &&@&&
 &&&       &&&   &&  @&&     &&&@   &&            &&&&&&&&&&&  &&&&&&&&&&&&     &&&&   &&&&

&&&&&&&&&&&&   &&&&&&&&&&&&   &&&&&&&&&&&@  &&&&&&&&&&&&   &&&&&&&&&&&   &&&&&&&&&&&
&&&       &&&  &&        &&&  &&            &&&                  &&&&    &&
&&&&&&&&&&&&@  &&&&&&&&&&&&   &&&&&&&&&&&   &&&&&&&&&&&       &&&&       &&&&&&&&&&
&&&        &&  &&   &&&&      &&            &&&             &&&&         &&
&&&&&&&&&&&&&  &&     &&&&@   &&&&&&&&&&&@  &&&&&&&&&&&&  @&&&&&&&&&&&   &&&&&&&&&&&

"""
CHEATSHEET = f"""

                       [bold][bright_blue]Airflow Breeze Cheatsheet[/][/]

    [bright_blue]* Installation[/]

        When you have multiple copies of Airflow, it's better if you use `./Breeze2` from those
        repository as it will have the latest version of Breeze2 and it's dependencies.

        However if you only have one Airflow repository and you have `pipx` installed, you can use
        `pipx` to install `Breeze2` command in your path (`Breeze2` command is run from this repository then)

            pipx install -e ./dev/breeze --force

        In case you use `pipx`, you might need to occasionally reinstall `Breeze2` with the `--force` flag
        when dependencies change for it. You do not have to do it when you use it via `./Breeze2`

    [bright_blue]* Port forwarding:[/]

        Ports are forwarded to the running docker containers for webserver and database
          * {SSH_PORT} -> forwarded to Airflow ssh server -> airflow:22
          * {WEBSERVER_HOST_PORT} -> forwarded to Airflow webserver -> airflow:8080
          * {FLOWER_HOST_PORT} -> forwarded to Flower dashboard -> airflow:5555
          * {POSTGRES_HOST_PORT} -> forwarded to Postgres database -> postgres:5432
          * {MYSQL_HOST_PORT} -> forwarded to MySQL database  -> mysql:3306
          * {MSSQL_HOST_PORT} -> forwarded to MSSQL database  -> mssql:1443
          * {REDIS_HOST_PORT} -> forwarded to Redis broker -> redis:6379

        Direct links to those services that you can use from the host:

          * ssh connection for remote debugging: ssh -p {SSH_PORT} airflow@127.0.0.1 (password: airflow)
          * Webserver: http://127.0.0.1:{WEBSERVER_HOST_PORT}
          * Flower:    http://127.0.0.1:{FLOWER_HOST_PORT}
          * Postgres:  jdbc:postgresql://127.0.0.1:{POSTGRES_HOST_PORT}/airflow?user=postgres&password=airflow
          * Mysql:     jdbc:mysql://127.0.0.1:{MYSQL_HOST_PORT}/airflow?user=root
          * Redis:     redis://127.0.0.1:{REDIS_HOST_PORT}/0

    [bright_blue]* How can I add my stuff in Breeze:[/]

        * Your dags for webserver and scheduler are read from `/files/dags` directory
          which is mounted from folder in Airflow sources:
          * `{AIRFLOW_SOURCES_ROOT}/files/dags`

        * You can add `airflow-breeze-config` directory. Place it in
          `{AIRFLOW_SOURCES_ROOT}/files/airflow-breeze-config` and:
            * Add `variables.env` - to make breeze source the variables automatically for you
            * Add `.tmux.conf` - to add extra initial configuration to `tmux`
            * Add `init.sh` - this file will be sourced when you enter container, so you can add
              any custom code there.

        * You can put any other files. You can add them in
          `{AIRFLOW_SOURCES_ROOT}/files` folder
          and they will be visible in `/files/` folder inside the container

        [bright_blue]* Other options[/]

        Check out `--help` for ./Breeze2 commands. It will show you other options, such as running
        integration or starting complete Airflow using `start-airflow` command as well as ways
        of cleaning up the installation.

        Make sure to run `setup-autocomplete` to get the commands and options auto-completable
        in your shell.

        You can disable this cheatsheet by running:

            ./Breeze2 config --no-cheatsheet

"""
CHEATSHEET_STYLE = "white"
ASCIIART_STYLE = "white"
