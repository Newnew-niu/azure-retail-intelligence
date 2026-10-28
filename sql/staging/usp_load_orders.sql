/*
    stg.usp_load_orders : raw.orders -> stg.orders        (key: order_id)

    Reference implementation of the staging pattern used by every stg.usp_load_* procedure:
      1. Take the latest raw version of each key in scope (@batch_id, or all batches if NULL).
      2. Convert to target types with TRY_CONVERT and give each unstorable row a reject_reason.
      3. Log rejected rows to ops.rejected_row - they are reported, never silently dropped.
      4. MERGE valid rows: insert new keys; update existing keys only if a value changed,
         so rerunning the same batch writes 0 rows (idempotent).
      5. Log row counts to ops.step_log; on error roll back, log the message and re-throw.

    Staging rejects only values that cannot be stored (bad keys, unparseable timestamps).
    Business rules (e.g. delivered before purchase) are tested in sql/quality/, not here.
*/
CREATE OR ALTER PROCEDURE stg.usp_load_orders
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_orders',
                            @target_object = N'stg.orders', @step_id = @step_id OUTPUT;
    BEGIN TRY
        WITH latest AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (PARTITION BY r.order_id ORDER BY r.loaded_at_utc DESC, r.batch_id DESC) AS version_rank
              FROM raw.orders AS r
             WHERE @batch_id IS NULL OR r.batch_id = @batch_id
        )
        SELECT l.order_id AS record_key,
               l.batch_id,
               t.*,
               CASE
                   WHEN stg.fn_is_hex32(l.order_id) = 0    THEN N'order_id is not a 32-character hex id'
                   WHEN stg.fn_is_hex32(l.customer_id) = 0 THEN N'customer_id is not a 32-character hex id'
                   WHEN t.order_status IS NULL             THEN N'order_status is empty'
                   WHEN t.purchased_at IS NULL             THEN N'order_purchase_timestamp is empty or not a timestamp'
                   WHEN l.order_approved_at IS NOT NULL AND t.approved_at IS NULL
                                                           THEN N'order_approved_at is not a timestamp'
                   WHEN l.order_delivered_carrier_date IS NOT NULL AND t.delivered_carrier_at IS NULL
                                                           THEN N'order_delivered_carrier_date is not a timestamp'
                   WHEN l.order_delivered_customer_date IS NOT NULL AND t.delivered_customer_at IS NULL
                                                           THEN N'order_delivered_customer_date is not a timestamp'
                   WHEN t.estimated_delivery_at IS NULL    THEN N'order_estimated_delivery_date is empty or not a timestamp'
                   WHEN CAST(t.estimated_delivery_at AS TIME) <> '00:00:00'
                                                           THEN N'order_estimated_delivery_date has a time part; DATE would lose it'
               END AS reject_reason
          INTO #src
          FROM latest AS l
         CROSS APPLY (SELECT
                CONVERT(CHAR(32), l.order_id)                                   AS order_id,
                CONVERT(CHAR(32), l.customer_id)                                AS customer_id,
                NULLIF(LOWER(TRIM(l.order_status)), N'')                        AS order_status,
                TRY_CONVERT(DATETIME2(0), l.order_purchase_timestamp, 120)      AS purchased_at,
                TRY_CONVERT(DATETIME2(0), l.order_approved_at, 120)             AS approved_at,
                TRY_CONVERT(DATETIME2(0), l.order_delivered_carrier_date, 120)  AS delivered_carrier_at,
                TRY_CONVERT(DATETIME2(0), l.order_delivered_customer_date, 120) AS delivered_customer_at,
                TRY_CONVERT(DATETIME2(0), l.order_estimated_delivery_date, 120) AS estimated_delivery_at
         ) AS t
         WHERE l.version_rank = 1
            OR l.order_id IS NULL;  -- every keyless row is kept so it is counted as a reject

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.orders', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        MERGE stg.orders WITH (HOLDLOCK) AS tgt
        USING (SELECT order_id, customer_id, order_status, purchased_at, approved_at, delivered_carrier_at,
                      delivered_customer_at, CONVERT(DATE, estimated_delivery_at) AS estimated_delivery_date, batch_id
                 FROM #src
                WHERE reject_reason IS NULL) AS src
           ON tgt.order_id = src.order_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.customer_id, src.order_status, src.purchased_at, src.approved_at, src.delivered_carrier_at,
                         src.delivered_customer_at, src.estimated_delivery_date
                  EXCEPT
                  SELECT tgt.customer_id, tgt.order_status, tgt.purchased_at, tgt.approved_at, tgt.delivered_carrier_at,
                         tgt.delivered_customer_at, tgt.estimated_delivery_date)
              THEN UPDATE SET
                   customer_id = src.customer_id, order_status = src.order_status, purchased_at = src.purchased_at,
                   approved_at = src.approved_at, delivered_carrier_at = src.delivered_carrier_at,
                   delivered_customer_at = src.delivered_customer_at, estimated_delivery_date = src.estimated_delivery_date,
                   batch_id = src.batch_id, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (order_id, customer_id, order_status, purchased_at, approved_at, delivered_carrier_at,
                           delivered_customer_at, estimated_delivery_date, batch_id, run_id)
                   VALUES (src.order_id, src.customer_id, src.order_status, src.purchased_at, src.approved_at,
                           src.delivered_carrier_at, src.delivered_customer_at, src.estimated_delivery_date,
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
