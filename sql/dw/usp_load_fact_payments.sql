/*
    dw.usp_load_fact_payments : stg.order_payments (+ order status/date, customer key)
                                -> dw.fact_payments        (grain: one row per payment record)

    Same incremental pattern as dw.usp_load_fact_orders.
*/
CREATE OR ALTER PROCEDURE dw.usp_load_fact_payments
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_written INT, @old_mark DATETIME2(3), @new_mark DATETIME2(3);
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'dw.usp_load_fact_payments',
                            @target_object = N'dw.fact_payments', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SET @old_mark = ISNULL((SELECT last_change_utc FROM ops.watermark WHERE target_object = N'dw.fact_payments'),
                               '19000101');
        SELECT @new_mark = MAX(changed_at)
          FROM (SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.order_payments
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.orders
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.customers) AS m(changed_at);
        SET @new_mark = ISNULL(@new_mark, @old_mark);

        SELECT order_id INTO #affected FROM (
            SELECT order_id FROM stg.order_payments WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM stg.orders WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT o.order_id FROM stg.customers AS c JOIN stg.orders AS o ON o.customer_id = c.customer_id
                   WHERE COALESCE(c.updated_at_utc, c.inserted_at_utc) > @old_mark AND COALESCE(c.updated_at_utc, c.inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM dw.fact_payments WHERE customer_key = -1
        ) AS a;
        CREATE UNIQUE CLUSTERED INDEX ix_affected ON #affected (order_id);
        SET @rows_read = (SELECT COUNT(*) FROM #affected);  -- for facts, rows_read = affected orders

        BEGIN TRANSACTION;

        DELETE f FROM dw.fact_payments AS f JOIN #affected AS a ON a.order_id = f.order_id;

        INSERT dw.fact_payments (order_id, payment_sequential, customer_key, purchase_date_key, order_status,
                                 payment_type, payment_installments, payment_value, run_id)
        SELECT p.order_id, p.payment_sequential, ISNULL(c.customer_key, -1),
               CONVERT(INT, CONVERT(CHAR(8), o.purchased_at, 112)),
               CONVERT(NVARCHAR(20), o.order_status),
               CONVERT(NVARCHAR(20), p.payment_type), p.payment_installments, p.payment_value, @run_id
          FROM stg.order_payments AS p
          JOIN #affected AS a ON a.order_id = p.order_id
          LEFT JOIN stg.orders      AS o ON o.order_id = p.order_id
          LEFT JOIN dw.dim_customer AS c ON c.customer_id = o.customer_id;
        SET @rows_written = @@ROWCOUNT;

        MERGE ops.watermark AS w
        USING (SELECT N'dw.fact_payments' AS target_object) AS s ON w.target_object = s.target_object
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
