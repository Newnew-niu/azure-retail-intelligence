/*
    ops.usp_run_dq_checks : data quality checks on the staging and DW layers, results in ops.dq_result.

    Severity policy
      ERROR - the reported numbers would be wrong, or the pipeline itself has a defect
              (reconciliation breaks, double counting, invalid values in KPIs, broken keys).
              Any ERROR check that finds rows FAILS the step, so a bad load stops the pipeline
              before anyone reports on it. Results are written first, so the failure is explained.
      WARN  - known anomalies in the source data that are documented and handled in the model
              (e.g. 775 orders without items). Counted every run so a change is visible, but
              they do not block the load.
    failed_rows = number of rows (or orders) violating the check; 0 = PASS.
*/
CREATE OR ALTER PROCEDURE ops.usp_run_dq_checks
    @run_id   NVARCHAR(100),
    @batch_id NVARCHAR(50) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @step_id INT, @checks INT, @errors INT, @warnings INT, @failed_list NVARCHAR(4000);
    EXEC ops.usp_step_start @run_id = @run_id, @step_name = N'ops.usp_run_dq_checks',
                            @target_object = N'ops.dq_result', @step_id = @step_id OUTPUT;
    BEGIN TRY
        CREATE TABLE #r (
            check_name     NVARCHAR(100) NOT NULL,
            check_category NVARCHAR(30)  NOT NULL,
            target_object  NVARCHAR(200) NOT NULL,
            severity       NVARCHAR(10)  NOT NULL,
            failed_rows    BIGINT        NOT NULL,
            description    NVARCHAR(400) NOT NULL
        );

        -- Per-order sums from staging, computed once for the reconciliation checks
        SELECT o.order_id,
               (SELECT SUM(i.price) FROM stg.order_items AS i WHERE i.order_id = o.order_id)            AS items_price,
               (SELECT SUM(p.payment_value) FROM stg.order_payments AS p WHERE p.order_id = o.order_id) AS payment_value
          INTO #stg_order
          FROM stg.orders AS o;

        /* ---------------- ERROR: reconciliation stg -> dw ---------------- */
        INSERT #r SELECT N'fact_orders_row_count', N'reconciliation', N'dw.fact_orders', N'ERROR',
               ABS((SELECT COUNT_BIG(*) FROM dw.fact_orders) - (SELECT COUNT_BIG(*) FROM stg.orders)),
               N'fact_orders must have exactly one row per staged order';
        INSERT #r SELECT N'fact_order_items_row_count', N'reconciliation', N'dw.fact_order_items', N'ERROR',
               ABS((SELECT COUNT_BIG(*) FROM dw.fact_order_items) - (SELECT COUNT_BIG(*) FROM stg.order_items)),
               N'fact_order_items must have exactly one row per staged order item';
        INSERT #r SELECT N'fact_payments_row_count', N'reconciliation', N'dw.fact_payments', N'ERROR',
               ABS((SELECT COUNT_BIG(*) FROM dw.fact_payments) - (SELECT COUNT_BIG(*) FROM stg.order_payments)),
               N'fact_payments must have exactly one row per staged payment record';
        INSERT #r SELECT N'fact_orders_items_price_matches_stg', N'reconciliation', N'dw.fact_orders', N'ERROR',
               COUNT_BIG(*), N'Orders whose items_price differs from the sum of their staged item prices (fan-out or lost rows)'
          FROM dw.fact_orders AS f JOIN #stg_order AS s ON s.order_id = f.order_id
         WHERE f.items_price <> ISNULL(s.items_price, 0);
        INSERT #r SELECT N'fact_orders_payment_value_matches_stg', N'reconciliation', N'dw.fact_orders', N'ERROR',
               COUNT_BIG(*), N'Orders whose payment_value differs from the sum of their staged payments'
          FROM dw.fact_orders AS f JOIN #stg_order AS s ON s.order_id = f.order_id
         WHERE f.payment_value <> ISNULL(s.payment_value, 0);
        INSERT #r SELECT N'fact_order_items_price_total', N'reconciliation', N'dw.fact_order_items', N'ERROR',
               CASE WHEN (SELECT SUM(price) FROM dw.fact_order_items) = (SELECT SUM(price) FROM stg.order_items)
                    THEN 0 ELSE 1 END,
               N'Total item price in the fact equals staging (1 = totals differ)';
        INSERT #r SELECT N'fact_payments_value_total', N'reconciliation', N'dw.fact_payments', N'ERROR',
               CASE WHEN (SELECT SUM(payment_value) FROM dw.fact_payments) = (SELECT SUM(payment_value) FROM stg.order_payments)
                    THEN 0 ELSE 1 END,
               N'Total payment value in the fact equals staging (1 = totals differ)';

        /* ---------------- ERROR: keys and validity ---------------- */
        INSERT #r SELECT N'fact_date_keys_in_dim_date', N'referential', N'dw.fact_*', N'ERROR', COUNT_BIG(*),
               N'Fact date keys with no row in dw.dim_date'
          FROM (SELECT purchase_date_key AS k FROM dw.fact_orders
                UNION ALL SELECT approved_date_key FROM dw.fact_orders
                UNION ALL SELECT delivered_carrier_date_key FROM dw.fact_orders
                UNION ALL SELECT delivered_customer_date_key FROM dw.fact_orders
                UNION ALL SELECT estimated_delivery_date_key FROM dw.fact_orders
                UNION ALL SELECT purchase_date_key FROM dw.fact_order_items
                UNION ALL SELECT shipping_limit_date_key FROM dw.fact_order_items
                UNION ALL SELECT purchase_date_key FROM dw.fact_payments) AS k
         WHERE k.k IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dw.dim_date AS d WHERE d.date_key = k.k);
        INSERT #r SELECT N'review_score_between_1_and_5', N'validity', N'stg.order_reviews', N'ERROR', COUNT_BIG(*),
               N'Review scores outside 1-5 would distort the average score KPI'
          FROM stg.order_reviews WHERE review_score NOT BETWEEN 1 AND 5;
        INSERT #r SELECT N'item_price_positive', N'validity', N'stg.order_items', N'ERROR', COUNT_BIG(*),
               N'Item prices must be > 0 and freight >= 0'
          FROM stg.order_items WHERE price <= 0 OR freight_value < 0;
        INSERT #r SELECT N'payment_value_not_negative', N'validity', N'stg.order_payments', N'ERROR', COUNT_BIG(*),
               N'Payment values must be >= 0'
          FROM stg.order_payments WHERE payment_value < 0;
        INSERT #r SELECT N'dim_customer_unique_id_consistent', N'consistency', N'dw.dim_customer', N'ERROR', COUNT_BIG(*),
               N'Rows whose customer_unique_id differs from staging (the person key drives customer counts)'
          FROM dw.dim_customer AS d JOIN stg.customers AS c ON c.customer_id = d.customer_id
         WHERE d.customer_unique_id <> c.customer_unique_id;

        /* ---------------- WARN: known source anomalies (documented, handled) ---------------- */
        INSERT #r SELECT N'orders_without_items', N'completeness', N'dw.fact_orders', N'WARN', COUNT_BIG(*),
               N'Orders with no items (mostly unavailable/canceled); kept with item_count = 0'
          FROM dw.fact_orders WHERE item_count = 0;
        INSERT #r SELECT N'orders_without_payments', N'completeness', N'dw.fact_orders', N'WARN', COUNT_BIG(*),
               N'Orders with no payment record; kept with payment_value = 0'
          FROM dw.fact_orders WHERE payment_count = 0;
        INSERT #r SELECT N'orders_without_reviews', N'completeness', N'dw.fact_orders', N'WARN', COUNT_BIG(*),
               N'Orders with no review; review_score_avg is NULL and excluded from averages'
          FROM dw.fact_orders WHERE review_count = 0;
        INSERT #r SELECT N'orders_with_multiple_reviews', N'consistency', N'dw.fact_orders', N'WARN', COUNT_BIG(*),
               N'Orders with more than one review; review_score_avg is their mean'
          FROM dw.fact_orders WHERE review_count > 1;
        INSERT #r SELECT N'payment_differs_from_price_plus_freight', N'consistency', N'dw.fact_orders', N'WARN', COUNT_BIG(*),
               N'Orders (with items and payments) where payments differ from item price + freight by more than 0.01'
          FROM dw.fact_orders
         WHERE item_count > 0 AND payment_count > 0 AND ABS(payment_value - items_price - items_freight) > 0.01;
        INSERT #r SELECT N'delivered_status_without_delivery_date', N'consistency', N'stg.orders', N'WARN', COUNT_BIG(*),
               N'Status delivered but no customer delivery timestamp; treated as not delivered'
          FROM stg.orders WHERE order_status = N'delivered' AND delivered_customer_at IS NULL;
        INSERT #r SELECT N'delivery_date_on_undelivered_order', N'consistency', N'stg.orders', N'WARN', COUNT_BIG(*),
               N'Delivery timestamp on an order whose status is not delivered; treated as not delivered'
          FROM stg.orders WHERE order_status <> N'delivered' AND delivered_customer_at IS NOT NULL;
        INSERT #r SELECT N'carrier_pickup_before_approval', N'consistency', N'stg.orders', N'WARN', COUNT_BIG(*),
               N'Handed to the carrier before payment approval'
          FROM stg.orders WHERE delivered_carrier_at < approved_at;
        INSERT #r SELECT N'delivered_before_purchase', N'consistency', N'stg.orders', N'WARN', COUNT_BIG(*),
               N'Customer delivery timestamp earlier than the purchase timestamp'
          FROM stg.orders WHERE delivered_customer_at < purchased_at;
        INSERT #r SELECT N'payment_type_not_defined', N'validity', N'stg.order_payments', N'WARN', COUNT_BIG(*),
               N'Payment type ''not_defined'''
          FROM stg.order_payments WHERE payment_type = N'not_defined';
        INSERT #r SELECT N'products_without_category', N'completeness', N'dw.dim_product', N'WARN', COUNT_BIG(*),
               N'Products with no category in the source; shown as uncategorised'
          FROM dw.dim_product WHERE category_name_pt = N'sem_categoria';
        INSERT #r SELECT N'products_category_not_translated', N'completeness', N'dw.dim_product', N'WARN', COUNT_BIG(*),
               N'Products whose category has no English translation; Portuguese name used'
          FROM dw.dim_product WHERE is_category_translated = 0 AND product_key <> -1;
        INSERT #r SELECT N'customers_without_geolocation', N'referential', N'dw.dim_customer', N'WARN', COUNT_BIG(*),
               N'Customer zip prefixes with no geolocation (no map coordinates)'
          FROM dw.dim_customer WHERE latitude IS NULL AND customer_key <> -1;
        INSERT #r SELECT N'sellers_without_geolocation', N'referential', N'dw.dim_seller', N'WARN', COUNT_BIG(*),
               N'Seller zip prefixes with no geolocation (no map coordinates)'
          FROM dw.dim_seller WHERE latitude IS NULL AND seller_key <> -1;
        INSERT #r SELECT N'facts_with_unknown_dimension', N'referential', N'dw.fact_*', N'WARN', COUNT_BIG(*),
               N'Fact rows pointing at an Unknown (-1) member because the dimension row is missing'
          FROM (SELECT 1 AS x FROM dw.fact_order_items WHERE product_key = -1 OR seller_key = -1 OR customer_key = -1
                UNION ALL SELECT 1 FROM dw.fact_orders WHERE customer_key = -1
                UNION ALL SELECT 1 FROM dw.fact_payments WHERE customer_key = -1) AS u;
        INSERT #r SELECT N'order_items_without_order', N'referential', N'stg.order_items', N'WARN', COUNT_BIG(*),
               N'Items whose order is not in staging (orphans)'
          FROM stg.order_items AS i WHERE NOT EXISTS (SELECT 1 FROM stg.orders AS o WHERE o.order_id = i.order_id);

        INSERT ops.dq_result (run_id, check_name, check_category, target_object, severity, failed_rows, status, description)
        SELECT @run_id, check_name, check_category, target_object, severity, failed_rows,
               CASE WHEN failed_rows = 0 THEN N'PASS' WHEN severity = N'ERROR' THEN N'FAIL' ELSE N'WARN' END,
               description
          FROM #r;

        SELECT @checks = COUNT(*),
               @errors = SUM(CASE WHEN severity = N'ERROR' AND failed_rows > 0 THEN 1 ELSE 0 END),
               @warnings = SUM(CASE WHEN severity = N'WARN' AND failed_rows > 0 THEN 1 ELSE 0 END)
          FROM #r;

        IF @errors > 0
        BEGIN
            SELECT @failed_list = STRING_AGG(CONVERT(NVARCHAR(4000), check_name + N' (' + CONVERT(NVARCHAR(20), failed_rows) + N')'), N', ')
              FROM #r WHERE severity = N'ERROR' AND failed_rows > 0;
            DECLARE @message NVARCHAR(2048) = LEFT(CONCAT(N'Data quality: ', @errors, N' ERROR check(s) failed: ', @failed_list), 2048);
            THROW 50010, @message, 1;
        END;

        -- rows_written = checks recorded; rows_rejected = checks with findings (warnings)
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'SUCCEEDED', @rows_read = @checks,
                              @rows_written = @checks, @rows_rejected = @warnings;
    END TRY
    BEGIN CATCH
        DECLARE @error NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC ops.usp_step_end @step_id = @step_id, @status = N'FAILED', @error_message = @error;
        THROW;
    END CATCH;
END;
GO
