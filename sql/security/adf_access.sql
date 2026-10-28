/*
    Database access for the Data Factory managed identity (Azure SQL only; not in the manifest).
    Run by scripts/deploy_sql.py when AZURE_DATA_FACTORY is set; the ? parameter is the factory name,
    which is also the display name of its system-assigned managed identity in Microsoft Entra ID.

    Least privilege - the factory can only:
      * replace a batch in the raw layer (Copy activity pre-copy DELETE + bulk INSERT)
      * run the staging and ops procedures (ownership chaining covers the tables they touch)
    It cannot read or change stg/dw/mart tables directly, and has no DDL rights.
    Re-runnable: the user is created once; GRANT is idempotent.
*/
DECLARE @adf_name SYSNAME = ?;
DECLARE @user NVARCHAR(300) = QUOTENAME(@adf_name);

IF DATABASE_PRINCIPAL_ID(@adf_name) IS NULL
    EXEC (N'CREATE USER ' + @user + N' FROM EXTERNAL PROVIDER');

EXEC (N'GRANT SELECT, INSERT, DELETE ON SCHEMA::raw TO ' + @user);
EXEC (N'GRANT EXECUTE ON SCHEMA::stg TO ' + @user);
EXEC (N'GRANT EXECUTE ON SCHEMA::ops TO ' + @user);
