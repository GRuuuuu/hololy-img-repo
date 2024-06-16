from pyspark.sql import SparkSession
from pyspark.sql.functions import col
import os

def init_spark():
    spark = SparkSession.builder \
        .appName("lh-hms-cloud") \
        .config("spark.hadoop.fs.s3a.bucket.{BUCKET_NAME}.endpoint" ,"{BUCKET_ENDPOINT}") \
        .config("spark.hadoop.fs.s3a.bucket.{BUCKET_NAME}.access.key" ,"{BUCKET_ACCESSKEY}") \
        .config("spark.hadoop.fs.s3a.bucket.{BUCKET_NAME}.secret.key" ,"{BUCKET_SECRETKEY}") \
        .config("fs.s3a.path.style.access", "true") \
        .enableHiveSupport() \
        .getOrCreate()
    return spark

def spark_conf(spark):
    sc = spark.sparkContext
    #check spark configuration
    sparkConfig = sc.getConf().getAll()
    for i in sparkConfig:
        print(i)

def create_schema(spark):
    # Create a database in the lakehouse catalog
    spark.sql("create schema if not exists {CATALOG_NAME}.{SCHEMA_NAME} LOCATION 's3a://{BUCKET_NAME}/'")

def list_schemas(spark):
    # list the database under lakehouse catalog
    spark.sql("show schemas from {CATALOG_NAME}").show()

def basic_iceberg_table_operations(spark):
    # demonstration: Create a basic Iceberg table, insert some data and then query table
    spark.sql("create table if not exists {CATALOG_NAME}.{SCHEMA_NAME}.testTable(id INTEGER, name VARCHAR(10), age INTEGER, salary DECIMAL(10, 2)) using iceberg").show()
    spark.sql("insert into {CATALOG_NAME}.{SCHEMA_NAME}.testTable values(1,'Alan',23,3400.00),(2,'Ben',30,5500.00),(3,'Chen',35,6500.00)")
    spark.sql("select * from {CATALOG_NAME}.{SCHEMA_NAME}.testTable").show()

def create_table_from_parquet_data(spark):
    # load parquet data into dataframce
    df = spark.read.option("header",True).parquet("file:///mnts/{CPD_PV_NAME}/yellow_tripdata_2022-01.parquet")
    df = df.drop("tpep_pickup_datetime", "tpep_dropoff_datetime")
    # write the dataframe into an Iceberg table
    df.writeTo("{CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}").create()
    # describe the table created
    spark.sql('describe table {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}').show(25)
    # query the table
    spark.sql('select * from {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}').count()

def ingest_from_csv_temp_table(spark):
    # load csv data into a dataframe
    csvDF = spark.read.option("header",True).csv("file:///mnts/{CPD_PV_NAME}/zipcodes.csv")
    csvDF.createOrReplaceTempView("tempCSVTable")
    # load temporary table into an Iceberg table
    spark.sql('create or replace table {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME2} using iceberg as select * from tempCSVTable')
    # describe the table created
    spark.sql('describe table {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME2}').show(25)
    # query the table
    spark.sql('select * from {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME2}').show()

def ingest_monthly_data(spark):
    df_feb = spark.read.option("header",True).parquet("file:///mnts/{CPD_PV_NAME}/yellow_tripdata_2022-02.parquet")
    df_march = spark.read.option("header",True).parquet("file:///mnts/{CPD_PV_NAME}/yellow_tripdata_2022-03.parquet")
    df_april = spark.read.option("header",True).parquet("file:///mnts/{CPD_PV_NAME}/yellow_tripdata_2022-04.parquet")
    df_may = spark.read.option("header",True).parquet("file:///mnts/{CPD_PV_NAME}/yellow_tripdata_2022-05.parquet")
    df_june = spark.read.option("header",True).parquet("file:///mnts/{CPD_PV_NAME}/yellow_tripdata_2022-06.parquet")
    df_q1_q2 = df_feb.union(df_march).union(df_april).union(df_may).union(df_june)
    df_q1_q2 = df_q1_q2.drop("tpep_pickup_datetime", "tpep_dropoff_datetime")
    df_q1_q2.write.insertInto("{CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}")

def perform_table_maintenance_operations(spark):
    # Query the metadata files table to list underlying data files
    spark.sql("SELECT file_path, file_size_in_bytes FROM {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}.files").show()
    # There are many smaller files compact them into files of 200MB each using the
    # `rewrite_data_files` Iceberg Spark procedure
    spark.sql(f"CALL {CATALOG_NAME}.system.rewrite_data_files(table => '{SCHEMA_NAME}.{TABLE_NAME1}', options => map('target-file-size-bytes','209715200'))").show()
    # Again, query the metadata files table to list underlying data files; 6 files are compacted
    # to 3 files
    spark.sql("SELECT file_path, file_size_in_bytes FROM {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}.files").show()
    # List all the snapshots
    # Expire earlier snapshots. Only latest one with comacted data is required
    # Again, List all the snapshots to see only 1 left
    spark.sql("SELECT committed_at, snapshot_id, operation FROM {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}.snapshots").show()
    #retain only the latest one
    latest_snapshot_committed_at = spark.sql("SELECT committed_at, snapshot_id, operation FROM {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}.snapshots").tail(1)[0].committed_at
    print (latest_snapshot_committed_at)
    spark.sql(f"CALL {CATALOG_NAME}.system.expire_snapshots(table => '{SCHEMA_NAME}.{TABLE_NAME1}',older_than => TIMESTAMP '{latest_snapshot_committed_at}',retain_last => 1)").show()
    spark.sql("SELECT committed_at, snapshot_id, operation FROM {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}.snapshots").show()
    # Removing Orphan data files
    spark.sql(f"CALL {CATALOG_NAME}.system.remove_orphan_files(table => '{SCHEMA_NAME}.{TABLE_NAME1}')").show(truncate=False)
    # Rewriting Manifest Files
    spark.sql(f"CALL {CATALOG_NAME}.system.rewrite_manifests('{SCHEMA_NAME}.{TABLE_NAME1}')").show()

def evolve_schema(spark):
    # demonstration: Schema evolution
    # Add column fare_per_mile to the table
    spark.sql('ALTER TABLE {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1} ADD COLUMN(fare_per_mile double)')
    # describe the table
    spark.sql('describe table {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1}').show(25)

def clean_database(spark):
    # clean-up the demo database
    spark.sql('drop table if exists {CATALOG_NAME}.{SCHEMA_NAME}.testTable purge')
    spark.sql('drop table if exists {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME2} purge')
    spark.sql('drop table if exists {CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME1} purge')
    spark.sql('drop database if exists {CATALOG_NAME}.{SCHEMA_NAME} cascade')

def main():
    try:
        spark = init_spark()
        spark_conf(spark)
        print("===================================")
        create_schema(spark)
        list_schemas(spark)
        basic_iceberg_table_operations(spark)
        # demonstration: Ingest parquet and csv data into a wastonx.data Iceberg table
        create_table_from_parquet_data(spark)
        ingest_from_csv_temp_table(spark)
        # load data for the month of Feburary to June into the table {TABLE_NAME1} created above
        ingest_monthly_data(spark)
        # demonstration: Table maintenance
        perform_table_maintenance_operations(spark)
        # demonstration: Schema evolution
        evolve_schema(spark)
    finally:
        # clean-up the demo database
        #clean_database(spark)
        spark.stop()

if __name__ == '__main__':
  main()