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

# Impala tests for queries that query metadata and set session settings

import pytest

from tests.beeswax.impala_beeswax import ImpalaBeeswaxException
from tests.common.impala_test_suite import ImpalaTestSuite
from tests.common.skip import SkipIfIsilon, SkipIfS3, SkipIfLocal
from tests.common.test_dimensions import ALL_NODES_ONLY
from tests.common.test_dimensions import create_exec_option_dimension
from tests.common.test_dimensions import create_uncompressed_text_dimension
from tests.util.filesystem_utils import get_fs_path

# TODO: For these tests to pass, all table metadata must be created exhaustively.
# the tests should be modified to remove that requirement.
class TestMetadataQueryStatements(ImpalaTestSuite):

  CREATE_DATA_SRC_STMT = ("CREATE DATA SOURCE %s LOCATION '" +
      get_fs_path("/test-warehouse/data-sources/test-data-source.jar") +
      "' CLASS 'org.apache.impala.extdatasource.AllTypesDataSource' API_VERSION 'V1'")
  DROP_DATA_SRC_STMT = "DROP DATA SOURCE IF EXISTS %s"
  TEST_DATA_SRC_NAMES = ["show_test_ds1", "show_test_ds2"]
  AVRO_SCHEMA_LOC = get_fs_path("/test-warehouse/avro_schemas/functional/alltypes.json")

  @classmethod
  def get_workload(self):
    return 'functional-query'

  @classmethod
  def add_test_dimensions(cls):
    super(TestMetadataQueryStatements, cls).add_test_dimensions()
    sync_ddl_opts = [0, 1]
    if cls.exploration_strategy() != 'exhaustive':
      # Cut down on test runtime by only running with SYNC_DDL=0
      sync_ddl_opts = [0]

    cls.TestMatrix.add_dimension(create_exec_option_dimension(
        cluster_sizes=ALL_NODES_ONLY,
        disable_codegen_options=[False],
        batch_sizes=[0],
        sync_ddl=sync_ddl_opts))
    cls.TestMatrix.add_dimension(create_uncompressed_text_dimension(cls.get_workload()))

  def test_use(self, vector):
    self.run_test_case('QueryTest/use', vector)

  def test_show(self, vector):
    self.run_test_case('QueryTest/show', vector)

  def test_show_stats(self, vector):
    self.run_test_case('QueryTest/show-stats', vector, "functional")

  def test_describe_path(self, vector, unique_database):
    self.run_test_case('QueryTest/describe-path', vector, unique_database)

  # Missing Coverage: Describe formatted compatibility between Impala and Hive when the
  # data doesn't reside in hdfs.
  @SkipIfIsilon.hive
  @SkipIfS3.hive
  @SkipIfLocal.hive
  def test_describe_formatted(self, vector, unique_database):
    # Describe a partitioned table.
    self.exec_and_compare_hive_and_impala_hs2("describe formatted functional.alltypes")
    self.exec_and_compare_hive_and_impala_hs2(
        "describe formatted functional_text_lzo.alltypes")
    # Describe an unpartitioned table.
    self.exec_and_compare_hive_and_impala_hs2("describe formatted tpch.lineitem")
    self.exec_and_compare_hive_and_impala_hs2("describe formatted functional.jointbl")

    # Create and describe an unpartitioned and partitioned Avro table created
    # by Impala without any column definitions.
    # TODO: Instead of creating new tables here, change one of the existing
    # Avro tables to be created without any column definitions.
    self.client.execute("create database if not exists %s" % unique_database)
    self.client.execute((
        "create table %s.%s with serdeproperties ('avro.schema.url'='%s') stored as avro"
        % (unique_database, "avro_alltypes_nopart", self.AVRO_SCHEMA_LOC)))
    self.exec_and_compare_hive_and_impala_hs2("describe formatted avro_alltypes_nopart")

    self.client.execute((
        "create table %s.%s partitioned by (year int, month int) "
        "with serdeproperties ('avro.schema.url'='%s') stored as avro"
        % (unique_database, "avro_alltypes_part", self.AVRO_SCHEMA_LOC)))
    self.exec_and_compare_hive_and_impala_hs2("describe formatted avro_alltypes_part")

    try:
      # Describe a view
      self.exec_and_compare_hive_and_impala_hs2(\
          "describe formatted functional.alltypes_view_sub")
    except AssertionError:
      pytest.xfail("Investigate minor difference in displaying null vs empty values")

  @pytest.mark.execute_serially # due to data src setup/teardown
  def test_show_data_sources(self, vector):
    try:
      self.__create_data_sources()
      self.run_test_case('QueryTest/show-data-sources', vector)
    finally:
      self.__drop_data_sources()

  def __drop_data_sources(self):
    for name in self.TEST_DATA_SRC_NAMES:
      self.client.execute(self.DROP_DATA_SRC_STMT % (name,))

  def __create_data_sources(self):
    self.__drop_data_sources()
    for name in self.TEST_DATA_SRC_NAMES:
      self.client.execute(self.CREATE_DATA_SRC_STMT % (name,))

  @SkipIfS3.hive
  @SkipIfIsilon.hive
  @SkipIfLocal.hive
  @pytest.mark.execute_serially # because of invalidate metadata
  def test_describe_db(self, vector):
    self.__test_describe_db_cleanup()
    try:
      self.client.execute("create database impala_test_desc_db1")
      self.client.execute("create database impala_test_desc_db2 "
                          "comment 'test comment'")
      self.client.execute("create database impala_test_desc_db3 "
                          "location '" + get_fs_path("/testdb") + "'")
      self.client.execute("create database impala_test_desc_db4 comment 'test comment' "
                          "location \"" + get_fs_path("/test2.db") + "\"")
      self.run_stmt_in_hive("create database hive_test_desc_db comment 'test comment' "
                           "with dbproperties('pi' = '3.14', 'e' = '2.82')")
      self.run_stmt_in_hive("alter database hive_test_desc_db set owner user test")
      self.client.execute("invalidate metadata")
      self.run_test_case('QueryTest/describe-db', vector)
    finally:
      self.__test_describe_db_cleanup()

  def __test_describe_db_cleanup(self):
    self.cleanup_db('hive_test_desc_db')
    self.cleanup_db('impala_test_desc_db1')
    self.cleanup_db('impala_test_desc_db2')
    self.cleanup_db('impala_test_desc_db3')
    self.cleanup_db('impala_test_desc_db4')
