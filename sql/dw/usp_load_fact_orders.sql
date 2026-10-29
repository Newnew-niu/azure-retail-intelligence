/*
    dw.usp_load_fact_orders : stg.orders + per-order aggregates of items, payments, reviews
                              -> dw.fact_orders                          (grain: one row per order)

    Incremental pattern shared by the three fact procedures:
      1. Read the high-water mark for this fact from ops.watermark (default 1900-01-01).
      2. New mark = latest change time (COALESCE(updated_at_utc, inserted_at_utc)) in the
         staging tables this fact is built from.
      3. Affected orders = orders with any staging change in (old mark, new mark], plus orders
         whose fact row still points at the Unknown (-1) member, so a late-arriving
         dimension row is picked up on the next run.
      4. In ONE transaction: delete the affected orders' fact rows, rebuild them from the
         current staging state, and move the mark. A failure leaves the mark unchanged, so the
         next run retries the same changes; a rerun with no new changes writes 0 rows.
    Rebuilding by order (not by row) keeps every order's rows consistent with each other.

    Aggregation without fan-out: items, payments and reviews are each aggregated to one row
    per order on their own, and only then joined to the order - never joined to each other.
*/
CREATE OR ALTER PROCEDURE dw.usp_load_fact_orders
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @rows_read INT, @rows_written INT, @old_mark DATETIME2(3), @new_mark DATETIME2(3);
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'dw.usp_load_fact_orders',
                            @target_object = N'dw.fact_orders', @step_id = @step_id OUTPUT;
    BEGIN TRY
        SET @old_mark = ISNULL((SELECT last_change_utc FROM ops.watermark WHERE target_object = N'dw.fact_orders'),
                               '19000101');
        SELECT @new_mark = MAX(changed_at)
          FROM (SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.orders
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.order_items
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.order_payments
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.order_reviews
                UNION ALL SELECT MAX(COALESCE(updated_at_utc, inserted_at_utc)) FROM stg.customers) AS m(changed_at);
        SET @new_mark = ISNULL(@new_mark, @old_mark);

        SELECT order_id INTO #affected FROM (
            SELECT order_id FROM stg.orders         WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM stg.order_items    WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM stg.order_payments WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM stg.order_reviews  WHERE COALESCE(updated_at_utc, inserted_at_utc) > @old_mark AND COALESCE(updated_at_utc, inserted_at_utc) <= @new_mark
            UNION SELECT o.order_id FROM stg.customers AS c JOIN stg.orders AS o ON o.customer_id = c.customer_id
                   WHERE COALESCE(c.updated_at_utc, c.inserted_at_utc) > @old_mark AND COALESCE(c.updated_at_utc, c.inserted_at_utc) <= @new_mark
            UNION SELECT order_id FROM dw.fact_orders WHERE customer_key = -1
        ) AS a;
        CREATE UNIQUE CLUSTERED INDEX ix_affected ON #affected (order_id);
        SET @rows_read = (SELECT COUNT(*) FROM #affected);  -- for facts, rows_read = affected orders

        WITH items AS (
            SELECT i.order_id, COUNT(*) AS item_count, SUM(i.price) AS items_price, SUM(i.freight_value) AS items_freight
              FROM stg.order_items AS i JOIN #affected AS a ON a.order_id = i.order_id
             GROUP BY i.order_id
        ),
        payments AS (
            SELECT p.order_id, COUNT(*) AS payment_count, SUM(p.payment_value) AS payment_value
              FROM stg.order_payments AS p JOIN #affected AS a ON a.order_id = p.order_id
             GROUP BY p.order_id
        ),
        reviews AS (
            SELECT r.order_id, COUNT(*) AS review_count, AVG(CAST(r.review_score AS DECIMAL(5,2))) AS review_score_avg
              FROM stg.order_reviews AS r JOIN #affected AS a ON a.order_id = r.order_id
             GROUP BY r.order_id
        )
        SELECT o.order_id,
               ISNULL(c.customer_key, -1)                                             AS customer_key,
               CONVERT(INT, CONVERT(CHAR(8), o.purchased_at, 112))                    AS purchase_date_key,
               CONVERT(INT, CONVERT(CHAR(8), o.approved_at, 112))                     AS approved_date_key,
               CONVERT(INT, CONVERT(CHAR(8), o.delivered_carrier_at, 112))            AS delivered_carrier_date_key,
               CONVERT(INT, CONVERT(CHAR(8), o.delivered_customer_at, 112))           AS delivered_customer_date_key,
               CONVERT(INT, CONVERT(CHAR(8), o.estimated_delivery_date, 112))         AS estimated_delivery_date_key,
               CONVERT(NVARCHAR(20), o.order_status)                                  AS order_status,
               o.purchased_at, o.delivered_customer_at, o.estimated_delivery_date,
               ISNULL(i.item_count, 0)    AS item_count,
               ISNULL(i.items_price, 0)   AS items_price,
               ISNULL(i.items_freight, 0) AS items_freight,
               ISNULL(p.payment_count, 0) AS payment_count,
               ISNULL(p.payment_value, 0) AS payment_value,
               ISNULL(r.review_count, 0)  AS review_count,
               CONVERT(DECIMAL(3,2), r.review_score_avg) AS review_score_avg,
               d.is_delivered
          INTO #fact
          FROM stg.orders AS o
          JOIN #affected AS a ON a.order_id = o.order_id
          LEFT JOIN dw.dim_customer AS c ON c.customer_id = o.customer_id
          LEFT JOIN items    AS i ON i.order_id = o.order_id
          LEFT JOIN payments AS p ON p.order_id = o.order_id
          LEFT JOIN reviews  AS r ON r.order_id = o.order_id
         -- Delivered = status 'delivered' AND a delivery timestamp (8 'delivered' orders have no
         -- timestamp; 6 other orders have a timestamp but a non-delivered status).
         CROSS APPLY (SELECT CASE WHEN o.order_status = N'delivered' AND o.delivered_customer_at IS NOT NULL
                                  THEN 1 ELSE 0 END AS is_delivered) AS d;

        BEGIN TRANSACTION;

        DELETE f FROM dw.fact_orders AS f JOIN #affected AS a ON a.order_id = f.order_id;

        INSERT dw.fact_orders (order_id, customer_key, purchase_date_key, approved_date_key, delivered_carrier_date_key,
                               delivered_customer_date_key, estimated_delivery_date_key, order_status, purchased_at,
                               delivered_customer_at, estimated_delivery_date, item_count, items_price, items_freight,
                               payment_count, payment_value, review_count, review_score_avg, delivery_days,
                               estimated_delivery_days, delivery_vs_estimate_days, is_delivered, is_late,
                               delivery_status, run_id)
        SELECT order_id, customer_key, purchase_date_key, approved_date_key, delivered_carrier_date_key,
               delivered_customer_date_key, estimated_delivery_date_key, order_status, purchased_at,
               delivered_customer_at, estimated_delivery_date, item_count, items_price, items_freight,
               payment_count, payment_value, review_count, review_score_avg,
               CASE WHEN is_delivered = 1
                    THEN CONVERT(DECIMAL(7,2), DATEDIFF(MINUTE, purchased_at, delivered_customer_at) / 1440.0) END,
               DATEDIFF(DAY, CAST(purchased_at AS DATE), estimated_delivery_date),
               CASE WHEN is_delivered = 1
                    THEN DATEDIFF(DAY, estimated_delivery_date, CAST(delivered_customer_at AS DATE)) END,
               is_delivered,
               CASE WHEN is_delivered = 1
                    THEN CASE WHEN CAST(delivered_customer_at AS DATE) > estimated_delivery_date THEN 1 ELSE 0 END END,
               CASE WHEN is_delivered = 0 THEN N'Not delivered'
                    WHEN CAST(delivered_customer_at AS DATE) > estimated_delivery_date THEN N'Late'
                    ELSE N'On time' END,
               @run_id
          FROM #fact;
        SET @rows_written = @@ROWCOUNT;

        MERGE ops.watermark AS w
        USING (SELECT N'dw.fact_orders' AS target_object) AS s ON w.target_object = s.target_object
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
