/*!
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

import React from 'react';
import {
  Table,
  Tbody,
  Tr,
  Td,
  Tag,
  Link,
  Button,
  Flex,
  Heading,
} from '@chakra-ui/react';
import { mean } from 'lodash';

import { getDuration, formatDuration } from '../../../datetime_utils';
import { finalStatesMap, getMetaValue } from '../../../utils';
import { useDag, useTasks, useTreeData } from '../../api';
import Time from '../../Time';

const dagId = getMetaValue('dag_id');
const dagDetailsUrl = getMetaValue('dag_details_url');

const Dag = () => {
  const { data: dag } = useDag(dagId);
  const { data: taskData } = useTasks(dagId);
  const { data: { dagRuns = [] } } = useTreeData();
  if (!dag || !taskData) return null;
  const { tasks = [], totalEntries = '' } = taskData;
  const { description, tags } = dag;

  // Build a key/value object of operator counts, the name is hidden inside of t.classRef.className
  const operators = {};
  tasks.forEach((t) => {
    if (!operators[t.classRef.className]) {
      operators[t.classRef.className] = 1;
    } else {
      operators[t.classRef.className] += 1;
    }
  });

  const numMap = finalStatesMap();
  const durations = [];
  dagRuns.forEach((dagRun) => {
    durations.push(getDuration(dagRun.startDate, dagRun.endDate));
    const stateKey = dagRun.state == null ? 'no_status' : dagRun.state;
    if (numMap.has(stateKey)) numMap.set(stateKey, numMap.get(stateKey) + 1);
  });

  const stateSummary = [];
  numMap.forEach((key, val) => {
    if (key > 0) {
      stateSummary.push(
        // eslint-disable-next-line react/no-array-index-key
        <Tr key={val}>
          <Td>
            Total
            {' '}
            {val}
          </Td>
          <Td>
            {key}
          </Td>
        </Tr>,
      );
    }
  });

  // calculate dag run bar heights relative to max
  const max = Math.max.apply(null, durations);
  const min = Math.min.apply(null, durations);
  const avg = mean(durations);

  return (
    <>
      <Button as={Link} variant="ghost" colorScheme="blue" href={dagDetailsUrl}>
        DAG Details
      </Button>
      {durations.length > 0 && (
        <>
          <Heading size="md" mt={4} mb={2}>DAG Runs Summary</Heading>
          <Table variant="striped">
            <Tbody>
              <Tr>
                <Td>Total Runs Displayed</Td>
                <Td>
                  {durations.length}
                </Td>
              </Tr>
              <Tr>
                <Td>First Run Start</Td>
                <Td>
                  <Time dateTime={dagRuns[0].startDate} />
                </Td>
              </Tr>
              <Tr>
                <Td>Last Run Start</Td>
                <Td>
                  <Time dateTime={dagRuns[dagRuns.length - 1].startDate} />
                </Td>
              </Tr>
              <Tr>
                <Td>Max Run Duration</Td>
                <Td>
                  {formatDuration(max)}
                </Td>
              </Tr>
              <Tr>
                <Td>Mean Run Duration</Td>
                <Td>
                  {formatDuration(avg)}
                </Td>
              </Tr>
              <Tr>
                <Td>Min Run Duration</Td>
                <Td>
                  {formatDuration(min)}
                </Td>
              </Tr>
              {stateSummary}
            </Tbody>
          </Table>
        </>
      )}
      <Heading size="md" mt={4} mb={2}>DAG Summary</Heading>
      <Table variant="striped">
        <Tbody>
          {description && (
          <Tr>
            <Td>Description</Td>
            <Td>{description}</Td>
          </Tr>
          )}
          <Tr>
            <Td>Total Tasks</Td>
            <Td>{totalEntries}</Td>
          </Tr>
          {Object.entries(operators).map(([key, value]) => (
            <Tr key={key}>
              <Td>
                {key}
                {value > 1 && 's'}
              </Td>
              <Td>{value}</Td>
            </Tr>
          ))}
          {!!tags.length && (
          <Tr>
            <Td>Tags</Td>
            <Td>
              <Flex flexWrap="wrap">
                {tags.map((tag) => (
                  <Link key={tag.name} href={`/home?tags=${tag.name}`} mr={1}>
                    <Tag colorScheme="blue" size="lg">{tag.name}</Tag>
                  </Link>
                ))}
              </Flex>
            </Td>
          </Tr>
          )}
        </Tbody>
      </Table>
    </>
  );
};

export default Dag;
