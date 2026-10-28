/*
    stg.usp_load_order_items : raw.order_items -> stg.order_items     (key: order_id, order_item_id)
    Same pattern as stg.usp_load_orders (see that file for the step-by-step description).
    Grain: one row per item line in an order. price and freight_value are per item.
*/
CREATE OR ALTER PROCEDURE stg.usp_load_order_items
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_rejected INT, @rows_written INT;
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'stg.usp_load_order_items',
                            @target_object = N'stg.order_items', @step_id = @step_id OUTPUT;
    BEGIN TRY
        WITH latest AS (
            SELECT r.*,
                   ROW_NUMBER() OVER (PARTITION BY r.order_id, r.order_item_id
                                      ORDER BY r.loaded_at_utc DESC, r.batch_id DESC) AS version_rank
              FROM raw.order_items AS r
             WHERE @batch_id IS NULL OR r.batch_id = @batch_id
        )
        SELECT CONCAT(l.order_id, N'|', l.order_item_id) AS record_key,
               l.batch_id,
               t.*,
               CASE
                   WHEN stg.fn_is_hex32(l.order_id) = 0   THEN N'order_id is not a 32-character hex id'
                   WHEN t.order_item_id IS NULL           THEN N'order_item_id is empty or not an integer'
                   WHEN stg.fn_is_hex32(l.product_id) = 0 THEN N'product_id is not a 32-character hex id'
                   WHEN stg.fn_is_hex32(l.seller_id) = 0  THEN N'seller_id is not a 32-character hex id'
                   WHEN t.shipping_limit_at IS NULL       THEN N'shipping_limit_date is empty or not a timestamp'
                   WHEN t.price IS NULL                   THEN N'price is empty or not a decimal(10,2)'
                   WHEN t.freight_value IS NULL           THEN N'freight_value is empty or not a decimal(10,2)'
               END AS reject_reason
          INTO #src
          FROM latest AS l
         CROSS APPLY (SELECT
                CONVERT(CHAR(32), l.order_id)                         AS order_id,
                TRY_CONVERT(INT, l.order_item_id)                     AS order_item_id,
                CONVERT(CHAR(32), l.product_id)                       AS product_id,
                CONVERT(CHAR(32), l.seller_id)                        AS seller_id,
                TRY_CONVERT(DATETIME2(0), l.shipping_limit_date, 120) AS shipping_limit_at,
                TRY_CONVERT(DECIMAL(10,2), l.price)                   AS price,
                TRY_CONVERT(DECIMAL(10,2), l.freight_value)           AS freight_value
         ) AS t
         WHERE l.version_rank = 1
            OR l.order_id IS NULL OR l.order_item_id IS NULL;

        SELECT @rows_read = COUNT(*), @rows_rejected = COUNT(reject_reason) FROM #src;

        BEGIN TRANSACTION;

        INSERT ops.rejected_row (run_id, step_id, source_table, batch_id, record_key, reason)
        SELECT @run_id, @step_id, N'raw.order_items', batch_id, LEFT(record_key, 400), reject_reason
          FROM #src
         WHERE reject_reason IS NOT NULL;

        MERGE stg.order_items WITH (HOLDLOCK) AS tgt
        USING (SELECT * FROM #src WHERE reject_reason IS NULL) AS src
           ON tgt.order_id = src.order_id AND tgt.order_item_id = src.order_item_id
         WHEN MATCHED AND EXISTS (
                  SELECT src.product_id, src.seller_id, src.shipping_limit_at, src.price, src.freight_value
                  EXCEPT
                  SELECT tgt.product_id, tgt.seller_id, tgt.shipping_limit_at, tgt.price, tgt.freight_value)
              THEN UPDATE SET
                   product_id = src.product_id, seller_id = src.seller_id, shipping_limit_at = src.shipping_limit_at,
                   price = src.price, freight_value = src.freight_value,
                   batch_id = src.batch_id, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED BY TARGET
              THEN INSERT (order_id, order_item_id, product_id, seller_id, shipping_limit_at, price, freight_value,
                           batch_id, run_id)
                   VALUES (src.order_id, src.order_item_id, src.product_id, src.seller_id, src.shipping_limit_at,
                           src.price, src.freight_value, src.batch_id, @run_id);
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
