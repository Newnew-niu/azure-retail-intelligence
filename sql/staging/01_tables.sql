/*
    STAGING layer: one typed, de-duplicated table per source entity.

    Design rules
      * Primary keys enforce the natural key of each entity (uniqueness is guaranteed here).
      * No foreign keys: an orphan (e.g. an item whose product is missing) is a data quality
        finding to REPORT, not a reason to block the load. Referential integrity is tested
        in sql/quality/.
      * Columns are renamed to readable names (source typos fixed) and typed.
      * Text columns keep the raw width, so no value can be silently truncated.
      * Timestamps are DATETIME2(0) in Brazilian local time, exactly as delivered (no
        time-zone conversion; the source has no offset information).
      * Metadata: batch_id / run_id that last changed the row, insert and update times.
*/

IF OBJECT_ID(N'stg.customers') IS NULL
CREATE TABLE stg.customers (
    customer_id        CHAR(32)      NOT NULL CONSTRAINT pk_stg_customers PRIMARY KEY,  -- one per order
    customer_unique_id CHAR(32)      NOT NULL,                                          -- the actual person
    zip_code_prefix    CHAR(5)       NOT NULL,
    city               NVARCHAR(255) NOT NULL,
    state              CHAR(2)       NOT NULL,
    batch_id           NVARCHAR(50)  NOT NULL,
    run_id             NVARCHAR(100) NOT NULL,
    inserted_at_utc    DATETIME2(3)  NOT NULL CONSTRAINT df_stg_customers_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc     DATETIME2(3)  NULL
);
GO

IF OBJECT_ID(N'stg.sellers') IS NULL
CREATE TABLE stg.sellers (
    seller_id       CHAR(32)      NOT NULL CONSTRAINT pk_stg_sellers PRIMARY KEY,
    zip_code_prefix CHAR(5)       NOT NULL,
    city            NVARCHAR(255) NOT NULL,
    state           CHAR(2)       NOT NULL,
    batch_id        NVARCHAR(50)  NOT NULL,
    run_id          NVARCHAR(100) NOT NULL,
    inserted_at_utc DATETIME2(3)  NOT NULL CONSTRAINT df_stg_sellers_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc  DATETIME2(3)  NULL
);
GO

IF OBJECT_ID(N'stg.product_category_translation') IS NULL
CREATE TABLE stg.product_category_translation (
    category_name_pt NVARCHAR(255) NOT NULL CONSTRAINT pk_stg_product_category_translation PRIMARY KEY,
    category_name_en NVARCHAR(255) NOT NULL,
    batch_id         NVARCHAR(50)  NOT NULL,
    run_id           NVARCHAR(100) NOT NULL,
    inserted_at_utc  DATETIME2(3)  NOT NULL CONSTRAINT df_stg_product_category_translation_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc   DATETIME2(3)  NULL
);
GO

IF OBJECT_ID(N'stg.products') IS NULL
CREATE TABLE stg.products (
    product_id         CHAR(32)      NOT NULL CONSTRAINT pk_stg_products PRIMARY KEY,
    category_name_pt   NVARCHAR(255) NULL,   -- NULL for 610 products in the source
    name_length        INT           NULL,   -- source: product_name_lenght
    description_length INT           NULL,   -- source: product_description_lenght
    photos_qty         INT           NULL,
    weight_g           INT           NULL,
    length_cm          INT           NULL,
    height_cm          INT           NULL,
    width_cm           INT           NULL,
    batch_id           NVARCHAR(50)  NOT NULL,
    run_id             NVARCHAR(100) NOT NULL,
    inserted_at_utc    DATETIME2(3)  NOT NULL CONSTRAINT df_stg_products_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc     DATETIME2(3)  NULL
);
GO

IF OBJECT_ID(N'stg.orders') IS NULL
CREATE TABLE stg.orders (
    order_id                CHAR(32)      NOT NULL CONSTRAINT pk_stg_orders PRIMARY KEY,
    customer_id             CHAR(32)      NOT NULL,
    order_status            NVARCHAR(255) NOT NULL,
    purchased_at            DATETIME2(0)  NOT NULL,
    approved_at             DATETIME2(0)  NULL,
    delivered_carrier_at    DATETIME2(0)  NULL,
    delivered_customer_at   DATETIME2(0)  NULL,
    estimated_delivery_date DATE          NOT NULL,  -- always midnight in the source, so DATE loses nothing
    batch_id                NVARCHAR(50)  NOT NULL,
    run_id                  NVARCHAR(100) NOT NULL,
    inserted_at_utc         DATETIME2(3)  NOT NULL CONSTRAINT df_stg_orders_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc          DATETIME2(3)  NULL
);
GO

IF OBJECT_ID(N'stg.order_items') IS NULL
CREATE TABLE stg.order_items (
    order_id          CHAR(32)      NOT NULL,
    order_item_id     INT           NOT NULL,   -- 1..n sequence within the order
    product_id        CHAR(32)      NOT NULL,
    seller_id         CHAR(32)      NOT NULL,
    shipping_limit_at DATETIME2(0)  NOT NULL,
    price             DECIMAL(10,2) NOT NULL,
    freight_value     DECIMAL(10,2) NOT NULL,
    batch_id          NVARCHAR(50)  NOT NULL,
    run_id            NVARCHAR(100) NOT NULL,
    inserted_at_utc   DATETIME2(3)  NOT NULL CONSTRAINT df_stg_order_items_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc    DATETIME2(3)  NULL,
    CONSTRAINT pk_stg_order_items PRIMARY KEY (order_id, order_item_id)
);
GO

IF OBJECT_ID(N'stg.order_payments') IS NULL
CREATE TABLE stg.order_payments (
    order_id             CHAR(32)      NOT NULL,
    payment_sequential   INT           NOT NULL,
    payment_type         NVARCHAR(255) NOT NULL,
    payment_installments INT           NOT NULL,
    payment_value        DECIMAL(10,2) NOT NULL,
    batch_id             NVARCHAR(50)  NOT NULL,
    run_id               NVARCHAR(100) NOT NULL,
    inserted_at_utc      DATETIME2(3)  NOT NULL CONSTRAINT df_stg_order_payments_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc       DATETIME2(3)  NULL,
    CONSTRAINT pk_stg_order_payments PRIMARY KEY (order_id, payment_sequential)
);
GO

IF OBJECT_ID(N'stg.order_reviews') IS NULL
CREATE TABLE stg.order_reviews (
    review_id       CHAR(32)       NOT NULL,   -- NOT unique on its own in the source
    order_id        CHAR(32)       NOT NULL,
    review_score    INT            NOT NULL,
    comment_title   NVARCHAR(4000) NULL,
    comment_message NVARCHAR(4000) NULL,
    created_at      DATETIME2(0)   NOT NULL,   -- usually midnight, but not always
    answered_at     DATETIME2(0)   NOT NULL,
    batch_id        NVARCHAR(50)   NOT NULL,
    run_id          NVARCHAR(100)  NOT NULL,
    inserted_at_utc DATETIME2(3)   NOT NULL CONSTRAINT df_stg_order_reviews_ins DEFAULT SYSUTCDATETIME(),
    updated_at_utc  DATETIME2(3)   NULL,
    CONSTRAINT pk_stg_order_reviews PRIMARY KEY (review_id, order_id)
);
GO

-- Geolocation is reduced to ONE row per zip prefix (the source has ~53 rows per prefix,
-- many exact duplicates). Joining the raw table to customers would multiply rows.
IF OBJECT_ID(N'stg.geolocation') IS NULL
CREATE TABLE stg.geolocation (
    zip_code_prefix   CHAR(5)       NOT NULL CONSTRAINT pk_stg_geolocation PRIMARY KEY,
    latitude          DECIMAL(9,6)  NULL,   -- mean of the points inside Brazil's bounding box
    longitude         DECIMAL(9,6)  NULL,
    state             CHAR(2)       NOT NULL, -- most frequent state for the prefix
    source_rows       INT           NOT NULL, -- raw rows summarised
    excluded_points   INT           NOT NULL, -- raw rows outside Brazil, ignored for lat/lng
    run_id            NVARCHAR(100) NOT NULL,
    inserted_at_utc   DATETIME2(3)  NOT NULL CONSTRAINT df_stg_geolocation_ins DEFAULT SYSUTCDATETIME()
);
GO
