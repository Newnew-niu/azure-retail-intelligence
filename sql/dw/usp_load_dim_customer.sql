/*
    dw.usp_load_dim_customer : stg.customers (+ stg.geolocation) -> dw.dim_customer   (SCD type 1)

    Dimensions are small, so every run compares ALL staging rows with the dimension and
    writes only what changed (MERGE with NULL-safe EXCEPT change detection, as in staging).
    A rerun writes 0 rows; existing surrogate keys never change. Latitude/longitude come from
    the zip-prefix centroid, so a geolocation rebuild that moves a centroid updates the row.
*/
CREATE OR ALTER PROCEDURE dw.usp_load_dim_customer
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'dw.usp_load_dim_customer',
                            @target_object = N'dw.dim_customer', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SELECT c.customer_id, c.customer_unique_id, c.zip_code_prefix, c.city, c.state, g.latitude, g.longitude
          INTO #src
          FROM stg.customers AS c
          LEFT JOIN stg.geolocation AS g ON g.zip_code_prefix = c.zip_code_prefix;
        SET @rows_read = @@ROWCOUNT;

        MERGE dw.dim_customer WITH (HOLDLOCK) AS tgt
        USING #src AS src
           ON tgt.customer_id = src.customer_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.customer_unique_id, src.zip_code_prefix, src.city, src.state, src.latitude, src.longitude
                  EXCEPT
                  SELECT tgt.customer_unique_id, tgt.zip_code_prefix, tgt.city, tgt.state, tgt.latitude, tgt.longitude)
              THEN UPDATE SET customer_unique_id = src.customer_unique_id, zip_code_prefix = src.zip_code_prefix,
                              city = src.city, state = src.state, latitude = src.latitude, longitude = src.longitude,
                              run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (customer_id, customer_unique_id, zip_code_prefix, city, state, latitude, longitude, run_id)
                   VALUES (src.customer_id, src.customer_unique_id, src.zip_code_prefix, src.city, src.state,
                           src.latitude, src.longitude, @run_id);
        SET @rows_written = @@ROWCOUNT;

        EXEC ops.usp_step_end @step_id = @step_id, @status = N'SUCCEEDED', @rows_read = @rows_read,
                              @rows_written = @rows_written, @rows_rejected = 0;
    END TRY
    BEGIN CATCH
        DECLARE @error NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'FAILED', @error_message = @error;
        THROW;
    END CATCH;
END;
GO
