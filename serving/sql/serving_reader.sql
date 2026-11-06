/*
    Least-privilege identity for the azuresql backend. NOT run by any script and NOT tested on
    Azure: review it, replace the placeholder, and run it as the Entra admin of the database.

    SQL Server has no read-only connection flag like DuckDB's, so this file is what stops a
    write if the SQL guard ever misses one. The identity can read the catalog datasets and the
    columns get_pipeline_status() selects. It cannot read other schemas or ops.*.error_message.
    serving/tests/test_catalog.py checks that this list matches serving/catalog.yml.
*/

CREATE USER [<SERVING_IDENTITY>] FROM EXTERNAL PROVIDER;
GO

GRANT SELECT ON mart.vw_sales_monthly            TO [<SERVING_IDENTITY>];
GRANT SELECT ON mart.vw_delivery_by_state        TO [<SERVING_IDENTITY>];
GRANT SELECT ON mart.vw_review_by_delivery_status TO [<SERVING_IDENTITY>];
GRANT SELECT ON mart.vw_category_sales           TO [<SERVING_IDENTITY>];
GRANT SELECT ON mart.vw_seller_performance       TO [<SERVING_IDENTITY>];
GRANT SELECT ON mart.vw_payment_mix              TO [<SERVING_IDENTITY>];
GRANT SELECT ON dw.fact_orders                   TO [<SERVING_IDENTITY>];
GRANT SELECT ON dw.fact_order_items              TO [<SERVING_IDENTITY>];
GRANT SELECT ON dw.fact_payments                 TO [<SERVING_IDENTITY>];
GRANT SELECT ON dw.dim_customer                  TO [<SERVING_IDENTITY>];
GRANT SELECT ON dw.dim_product                   TO [<SERVING_IDENTITY>];
GRANT SELECT ON dw.dim_seller                    TO [<SERVING_IDENTITY>];
GRANT SELECT ON dw.dim_date                      TO [<SERVING_IDENTITY>];

GRANT SELECT ON ops.pipeline_run (run_id, pipeline_name, batch_id, trigger_source, status,
                                  started_at_utc, ended_at_utc) TO [<SERVING_IDENTITY>];
GRANT SELECT ON ops.dq_result (run_id, check_name, check_category, target_object, severity,
                               failed_rows, status, description) TO [<SERVING_IDENTITY>];
GO
