/*
    RAW layer: one table per source file, columns named exactly as in the source.

    Design rules
      * Every source column is text (NVARCHAR). Raw never rejects a value because of
        its type; conversion and rejection happen in staging, where they are logged.
      * Empty source fields arrive as NULL (local loader and ADF "treat empty as null").
      * Four metadata columns record lineage:
          batch_id       - which delivery the row came from (reruns replace a whole batch)
          source_file    - file path the row was read from
          run_id         - pipeline run that loaded it (ops.pipeline_run)
          loaded_at_utc  - load time
      * Rows are only ever inserted or deleted per batch_id, which makes reloads idempotent.
*/

IF OBJECT_ID(N'raw.customers') IS NULL
CREATE TABLE raw.customers (
    customer_id              NVARCHAR(255) NULL,
    customer_unique_id       NVARCHAR(255) NULL,
    customer_zip_code_prefix NVARCHAR(255) NULL,
    customer_city            NVARCHAR(255) NULL,
    customer_state           NVARCHAR(255) NULL,
    batch_id                 NVARCHAR(50)  NOT NULL,
    source_file              NVARCHAR(400) NOT NULL,
    run_id                   NVARCHAR(100) NOT NULL,
    loaded_at_utc            DATETIME2(3)  NOT NULL CONSTRAINT df_raw_customers_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.geolocation') IS NULL
CREATE TABLE raw.geolocation (
    geolocation_zip_code_prefix NVARCHAR(255) NULL,
    geolocation_lat             NVARCHAR(255) NULL,
    geolocation_lng             NVARCHAR(255) NULL,
    geolocation_city            NVARCHAR(255) NULL,
    geolocation_state           NVARCHAR(255) NULL,
    batch_id                    NVARCHAR(50)  NOT NULL,
    source_file                 NVARCHAR(400) NOT NULL,
    run_id                      NVARCHAR(100) NOT NULL,
    loaded_at_utc               DATETIME2(3)  NOT NULL CONSTRAINT df_raw_geolocation_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.orders') IS NULL
CREATE TABLE raw.orders (
    order_id                      NVARCHAR(255) NULL,
    customer_id                   NVARCHAR(255) NULL,
    order_status                  NVARCHAR(255) NULL,
    order_purchase_timestamp      NVARCHAR(255) NULL,
    order_approved_at             NVARCHAR(255) NULL,
    order_delivered_carrier_date  NVARCHAR(255) NULL,
    order_delivered_customer_date NVARCHAR(255) NULL,
    order_estimated_delivery_date NVARCHAR(255) NULL,
    batch_id                      NVARCHAR(50)  NOT NULL,
    source_file                   NVARCHAR(400) NOT NULL,
    run_id                        NVARCHAR(100) NOT NULL,
    loaded_at_utc                 DATETIME2(3)  NOT NULL CONSTRAINT df_raw_orders_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.order_items') IS NULL
CREATE TABLE raw.order_items (
    order_id            NVARCHAR(255) NULL,
    order_item_id       NVARCHAR(255) NULL,
    product_id          NVARCHAR(255) NULL,
    seller_id           NVARCHAR(255) NULL,
    shipping_limit_date NVARCHAR(255) NULL,
    price               NVARCHAR(255) NULL,
    freight_value       NVARCHAR(255) NULL,
    batch_id            NVARCHAR(50)  NOT NULL,
    source_file         NVARCHAR(400) NOT NULL,
    run_id              NVARCHAR(100) NOT NULL,
    loaded_at_utc       DATETIME2(3)  NOT NULL CONSTRAINT df_raw_order_items_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.order_payments') IS NULL
CREATE TABLE raw.order_payments (
    order_id             NVARCHAR(255) NULL,
    payment_sequential   NVARCHAR(255) NULL,
    payment_type         NVARCHAR(255) NULL,
    payment_installments NVARCHAR(255) NULL,
    payment_value        NVARCHAR(255) NULL,
    batch_id             NVARCHAR(50)  NOT NULL,
    source_file          NVARCHAR(400) NOT NULL,
    run_id               NVARCHAR(100) NOT NULL,
    loaded_at_utc        DATETIME2(3)  NOT NULL CONSTRAINT df_raw_order_payments_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.order_reviews') IS NULL
CREATE TABLE raw.order_reviews (
    review_id               NVARCHAR(255)  NULL,
    order_id                NVARCHAR(255)  NULL,
    review_score            NVARCHAR(255)  NULL,
    review_comment_title    NVARCHAR(4000) NULL,  -- free text
    review_comment_message  NVARCHAR(4000) NULL,  -- free text, may contain line breaks
    review_creation_date    NVARCHAR(255)  NULL,
    review_answer_timestamp NVARCHAR(255)  NULL,
    batch_id                NVARCHAR(50)   NOT NULL,
    source_file             NVARCHAR(400)  NOT NULL,
    run_id                  NVARCHAR(100)  NOT NULL,
    loaded_at_utc           DATETIME2(3)   NOT NULL CONSTRAINT df_raw_order_reviews_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.products') IS NULL
CREATE TABLE raw.products (
    product_id                 NVARCHAR(255) NULL,
    product_category_name      NVARCHAR(255) NULL,
    product_name_lenght        NVARCHAR(255) NULL,  -- source spelling, fixed in staging
    product_description_lenght NVARCHAR(255) NULL,  -- source spelling, fixed in staging
    product_photos_qty         NVARCHAR(255) NULL,
    product_weight_g           NVARCHAR(255) NULL,
    product_length_cm          NVARCHAR(255) NULL,
    product_height_cm          NVARCHAR(255) NULL,
    product_width_cm           NVARCHAR(255) NULL,
    batch_id                   NVARCHAR(50)  NOT NULL,
    source_file                NVARCHAR(400) NOT NULL,
    run_id                     NVARCHAR(100) NOT NULL,
    loaded_at_utc              DATETIME2(3)  NOT NULL CONSTRAINT df_raw_products_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.sellers') IS NULL
CREATE TABLE raw.sellers (
    seller_id              NVARCHAR(255) NULL,
    seller_zip_code_prefix NVARCHAR(255) NULL,
    seller_city            NVARCHAR(255) NULL,
    seller_state           NVARCHAR(255) NULL,
    batch_id               NVARCHAR(50)  NOT NULL,
    source_file            NVARCHAR(400) NOT NULL,
    run_id                 NVARCHAR(100) NOT NULL,
    loaded_at_utc          DATETIME2(3)  NOT NULL CONSTRAINT df_raw_sellers_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'raw.product_category_translation') IS NULL
CREATE TABLE raw.product_category_translation (
    product_category_name         NVARCHAR(255) NULL,
    product_category_name_english NVARCHAR(255) NULL,
    batch_id                      NVARCHAR(50)  NOT NULL,
    source_file                   NVARCHAR(400) NOT NULL,
    run_id                        NVARCHAR(100) NOT NULL,
    loaded_at_utc                 DATETIME2(3)  NOT NULL CONSTRAINT df_raw_product_category_translation_loaded DEFAULT SYSUTCDATETIME()
);
GO

-- Reloads delete by batch_id, so every raw table gets an index on it.
DECLARE @sql NVARCHAR(MAX) = N'';
SELECT @sql += N'CREATE INDEX ix_raw_' + t.name + N'_batch ON raw.' + QUOTENAME(t.name) + N' (batch_id);' + CHAR(10)
  FROM sys.tables AS t
 WHERE t.schema_id = SCHEMA_ID(N'raw')
   AND NOT EXISTS (SELECT 1 FROM sys.indexes AS i WHERE i.object_id = t.object_id AND i.name = N'ix_raw_' + t.name + N'_batch');
EXEC sys.sp_executesql @sql;
GO
