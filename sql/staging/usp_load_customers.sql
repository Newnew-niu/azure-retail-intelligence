/*
    stg.usp_load_customers : raw.customers -> stg.customers        (key: customer_id)
    Same pattern as stg.usp_load_orders (see that file for the step-by-step description).
    Note: customer_id identifies a customer *per order*; customer_unique_id identifies the person.
*/
CREATE OR ALTER PROCEDURE stg.usp_load_customers
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_customers',
                            @target_object = N'stg.customers', @step_id = @step_id OUTPUT;
    BEGIN TRY
        WITH latest AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (PARTITION BY r.customer_id ORDER BY r.loaded_at_utc DESC, r.batch_id DESC) AS version_rank
              FROM raw.customers AS r
             WHERE @batch_id IS NULL OR r.batch_id = @batch_id
        )
        SELECT l.customer_id AS record_key,
               l.batch_id,
               t.*,
               CASE
                   WHEN stg.fn_is_hex32(l.customer_id) = 0        THEN N'customer_id is not a 32-character hex id'
                   WHEN stg.fn_is_hex32(l.customer_unique_id) = 0 THEN N'customer_unique_id is not a 32-character hex id'
                   WHEN stg.fn_is_zip5(l.customer_zip_code_prefix) = 0 THEN N'customer_zip_code_prefix is not 5 digits'
                   WHEN t.city IS NULL                            THEN N'customer_city is empty'
                   WHEN t.state IS NULL OR t.state LIKE N'%[^A-Z]%' OR LEN(t.state) <> 2
                                                                  THEN N'customer_state is not a 2-letter code'
               END AS reject_reason
          INTO #src
          FROM latest AS l
         CROSS APPLY (SELECT
                CONVERT(CHAR(32), l.customer_id)        AS customer_id,
                CONVERT(CHAR(32), l.customer_unique_id) AS customer_unique_id,
                CONVERT(CHAR(5), l.customer_zip_code_prefix) AS zip_code_prefix,
                NULLIF(TRIM(l.customer_city), N'')      AS city,
                UPPER(TRIM(l.customer_state))           AS state
         ) AS t
         WHERE l.version_rank = 1
            OR l.customer_id IS NULL;

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.customers', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        MERGE stg.customers WITH (HOLDLOCK) AS tgt
        USING (SELECT * FROM #src WHERE reject_reason IS NULL) AS src
           ON tgt.customer_id = src.customer_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.customer_unique_id, src.zip_code_prefix, src.city, src.state
                  EXCEPT
                  SELECT tgt.customer_unique_id, tgt.zip_code_prefix, tgt.city, tgt.state)
              THEN UPDATE SET
                   customer_unique_id = src.customer_unique_id, zip_code_prefix = src.zip_code_prefix,
                   city = src.city, state = src.state,
                   batch_id = src.batch_id, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (customer_id, customer_unique_id, zip_code_prefix, city, state, batch_id, run_id)
                   VALUES (src.customer_id, src.customer_unique_id, src.zip_code_prefix, src.city, src.state,
                           src.batch_id, @run_id);
        SET @rows_written = @@ROWCOUNT;

        COMMIT TRANSACTION;

        EXEC ops.usp_step_end @step_id = @step_id, @status = N'SUCCEEDED', @rows_read = @rows_read,
                              @rows_written = @rows_written, @rows_rejected = @rows_rejected;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        DECLARE @error NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'FAILED', @error_message = @error;
        THROW;
    END CATCH;
END;
GO
