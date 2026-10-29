/*
    dw.usp_load_fact_order_items : stg.order_items (+ order status/date, dimension keys)
                                   -> dw.fact_order_items          (grain: one row per order item)

    Same incremental pattern as dw.usp_load_fact_orders (watermark, rebuild affected orders in
    one transaction). Changes to product or seller attributes need no fact rewrite (SCD 1,
    stable keys); a product or seller that arrives late is picked up through the -1 retry.
*/
CREATE OR ALTER PROCEDURE dw.usp_load_fact_order_items
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_written INT, @old_mark DATETIME2(3), @new_mark DATETIME2(3);
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'dw.usp_load_fact_order_items',
                            @target_object = N'dw.fact_order_items', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SET @old_mark = ISNULL((SELECT last_change_utc FROM ops.watermark WHERE target_object = N'dw.fact_order_items'),
                               '19000101');
        SELECT @new_mark = MAX(changed_at)
          FROM (SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.order_items
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.orders
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.customers) AS m(changed_at);
        SET @new_mark = ISNULL(@new_mark, @old_mark);

        SELECT order_id INTO #affected FROM (
            SELECT order_id FROM stg.order_items WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM stg.orders WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT o.order_id FROM stg.customers AS c JOIN stg.orders AS o ON o.customer_id = c.customer_id
                   WHERE COALESCE(c.updated_at_utc, c.inserted_at_utc) > @old_mark AND COALESCE(c.updated_at_utc, c.inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM dw.fact_order_items WHERE product_key = -1 OR seller_key = -1 OR customer_key = -1
        ) AS a;
        CREATE UNIQUE CLUSTERED INDEX ix_affected ON #affected (order_id);
        SET @rows_read = (SELECT COUNT(*) FROM #affected);  -- for facts, rows_read = affected orders

        BEGIN TRANSACTION;

        DELETE f FROM dw.fact_order_items AS f JOIN #affected AS a ON a.order_id = f.order_id;

        INSERT dw.fact_order_items (order_id, order_item_id, product_key, seller_key, customer_key, purchase_date_key,
                                    shipping_limit_date_key, order_status, price, freight_value, run_id)
        SELECT i.order_id, i.order_item_id,
               ISNULL(p.product_key, -1), ISNULL(s.seller_key, -1), ISNULL(c.customer_key, -1),
               CONVERT(INT, CONVERT(CHAR(8), o.purchased_at, 112)),
               CONVERT(INT, CONVERT(CHAR(8), i.shipping_limit_at, 112)),
               CONVERT(NVARCHAR(20), o.order_status),
               i.price, i.freight_value, @run_id
          FROM stg.order_items AS i
          JOIN #affected AS a ON a.order_id = i.order_id
          LEFT JOIN stg.orders       AS o ON o.order_id = i.order_id
          LEFT JOIN dw.dim_customer  AS c ON c.customer_id = o.customer_id
          LEFT JOIN dw.dim_product   AS p ON p.product_id = i.product_id
          LEFT JOIN dw.dim_seller    AS s ON s.seller_id = i.seller_id;
        SET @rows_written = @@ROWCOUNT;

        MERGE ops.watermark AS w
        USING (SELECT N'dw.fact_order_items' AS target_object) AS s ON w.target_object = s.target_object
         WHEN MATCHED THEN UPDATE SET last_change_utc = @new_mark, run_id = @run_id, updated_at_utc = SYSUTCDATETIME()
         WHEN NOT MATCHED THEN INSERT (target_object, last_change_utc, run_id) VALUES (s.target_object, @new_mark, @run_id);

        COMMIT TRANSACTION;

        EXEC ops.usp_step_end @step_id = @step_id, @status = N'SUCCEEDED', @rows_read = @rows_read,
                              @rows_written = @rows_written, @rows_rejected = 0;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        DECLARE @error NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'FAILED', @error_message = @error;
        THROW;
    END CATCH;
END;
GO
