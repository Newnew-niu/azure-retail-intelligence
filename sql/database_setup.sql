/*
    Schemas = logical data layers. Runs unchanged on LocalDB and Azure SQL Database.
    (The database itself is created by scripts/deploy_sql.py locally and by the
    Azure deployment scripts in the cloud, because Azure SQL does not support USE.)

    raw   - source data as delivered: text columns plus load metadata
    stg   - typed, cleaned, de-duplicated data, one table per source entity
    dw    - dimensional model (facts and dimensions)
    mart  - business-facing views consumed by Power BI
    ops   - pipeline run log, step log, rejected rows, data quality results
*/
IF SCHEMA_ID(N'raw')  IS NULL EXEC (N'CREATE SCHEMA raw');
IF SCHEMA_ID(N'stg')  IS NULL EXEC (N'CREATE SCHEMA stg');
IF SCHEMA_ID(N'dw')   IS NULL EXEC (N'CREATE SCHEMA dw');
IF SCHEMA_ID(N'mart') IS NULL EXEC (N'CREATE SCHEMA mart');
IF SCHEMA_ID(N'ops')  IS NULL EXEC (N'CREATE SCHEMA ops');
