/*
    stg.usp_load_order_payments : raw.order_payments -> stg.order_payments  (key: order_id, payment_sequential)
    Same pattern as stg.usp_load_orders (see that file for the step-by-step description).
    Grain: one row per payment record; an order can be paid with several (e.g. voucher + card).
*/
CREATE OR ALTER PROCEDURE stg.usp_load_order_payments
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_order_payments',
                            @target_object = N'stg.order_payments', @step_id = @step_id OUTPUT;
    BEGIN TRY
        WITH latest AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (PARTITION BY r.order_id, r.payment_sequential
                                      ORDER BY r.loaded_at_utc DESC, r.batch_id DESC) AS version_rank
              FROM raw.order_payments AS r
             WHERE @batch_id IS NULL OR r.batch_id = @batch_id
        )
        SELECT CONCAT(l.order_id, N'|', l.payment_sequential) AS record_key,
               l.batch_id,
               t.*,
               CASE
                   WHEN stg.fn_is_hex32(l.order_id) = 0 THEN N'order_id is not a 32-character hex id'
                   WHEN t.payment_sequential IS NULL    THEN N'payment_sequential is empty or not an integer'
                   WHEN t.payment_type IS NULL          THEN N'payment_type is empty'
                   WHEN t.payment_installments IS NULL  THEN N'payment_installments is empty or not an integer'
                   WHEN t.payment_value IS NULL         THEN N'payment_value is empty or not a decimal(10,2)'
               END AS reject_reason
          INTO #src
          FROM latest AS l
         CROSS APPLY (SELECT
                CONVERT(CHAR(32), l.order_id)               AS order_id,
                TRY_CONVERT(INT, l.payment_sequential)      AS payment_sequential,
                NULLIF(LOWER(TRIM(l.payment_type)), N'')    AS payment_type,
                TRY_CONVERT(INT, l.payment_installments)    AS payment_installments,
                TRY_CONVERT(DECIMAL(10,2), l.payment_value) AS payment_value
         ) AS t
         WHERE l.version_rank = 1
            OR l.order_id IS NULL OR l.payment_sequential IS NULL;

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.order_payments', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        MERGE stg.order_payments WITH (HOLDLOCK) AS tgt
        USING (SELECT * FROM #src WHERE reject_reason IS NULL) AS src
           ON tgt.order_id = src.order_id AND tgt.payment_sequential = src.payment_sequential
         WHEN MATCHED AND EXISTS (
                  SELECT src.payment_type, src.payment_installments, src.payment_value
                  EXCEPT
                  SELECT tgt.payment_type, tgt.payment_installments, tgt.payment_value)
              THEN UPDATE SET
                   payment_type = src.payment_type, payment_installments = src.payment_installments,
                   payment_value = src.payment_value,
                   batch_id = src.batch_id, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (order_id, payment_sequential, payment_type, payment_installments, payment_value, batch_id, run_id)
                   VALUES (src.order_id, src.payment_sequential, src.payment_type, src.payment_installments,
                           src.payment_value, src.batch_id, @run_id);
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
