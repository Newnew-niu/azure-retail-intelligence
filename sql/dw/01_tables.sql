/*
    DW layer: star schema for analysis and Power BI.

    Grain (one row per ...)
      dim_date            calendar day                       key: date_key (yyyymmdd)
      dim_customer        customer_id = one customer per ORDER in Olist; the person is
                          customer_unique_id, so "customers" = DISTINCTCOUNT(customer_unique_id)
      dim_product         product_id
      dim_seller          seller_id
      fact_order_items    order item  (order_id, order_item_id)  - product/seller/category analysis
      fact_orders         order       (order_id)                 - order counts, delivery, reviews
      fact_payments       payment record (order_id, payment_sequential) - payment mix

    Why three facts: items, payments and reviews each have their own grain. Joining them in
    one table would multiply rows (an order with 3 items and 2 payments would give 6 rows and
    inflate both sales and payment totals). fact_orders holds per-order aggregates that were
    computed from each source table SEPARATELY, then joined 1:1 on order_id.

    Dimensions are SCD type 1 (overwritten in place): the source has no history of changes.
    Surrogate keys are stable across reloads, so facts never need rewriting when an attribute
    changes. Key -1 is the "Unknown" member used when a fact references a missing dimension row.
*/

IF OBJECT_ID(N'dw.dim_date') IS NULL
CREATE TABLE dw.dim_date (
    date_key        INT          NOT NULL CONSTRAINT pk_dim_date PRIMARY KEY,  -- yyyymmdd
    [date]          DATE         NOT NULL CONSTRAINT uq_dim_date_date UNIQUE,
    [year]          SMALLINT     NOT NULL,
    quarter         TINYINT      NOT NULL,
    month           TINYINT      NOT NULL,
    month_name      NVARCHAR(10) NOT NULL,
    year_month      CHAR(7)      NOT NULL,  -- '2018-01', sorts correctly as text
    month_start     DATE         NOT NULL,
    day_of_month    TINYINT      NOT NULL,
    day_of_week     TINYINT      NOT NULL,  -- 1 = Monday ... 7 = Sunday (independent of DATEFIRST)
    day_name        NVARCHAR(10) NOT NULL,
    is_weekend      BIT          NOT NULL
);
GO

IF OBJECT_ID(N'dw.dim_customer') IS NULL
CREATE TABLE dw.dim_customer (
    customer_key       INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_dim_customer PRIMARY KEY,
    customer_id        CHAR(32)      NOT NULL CONSTRAINT uq_dim_customer_id UNIQUE,
    customer_unique_id CHAR(32)      NOT NULL,
    zip_code_prefix    CHAR(5)       NOT NULL,
    city               NVARCHAR(255) NOT NULL,
    state              CHAR(2)       NOT NULL,
    latitude           DECIMAL(9,6)  NULL,  -- zip-prefix centroid; NULL if the prefix has no geolocation
    longitude          DECIMAL(9,6)  NULL,
    run_id             NVARCHAR(100) NOT NULL,
    updated_at_utc     DATETIME2(3)  NOT NULL CONSTRAINT df_dim_customer_upd DEFAULT SYSUTCDATETIME()
);
GO
IF INDEXPROPERTY(OBJECT_ID(N'dw.dim_customer'), N'ix_dim_customer_unique', N'IndexID') IS NULL
    CREATE INDEX ix_dim_customer_unique ON dw.dim_customer (customer_unique_id);
GO

IF OBJECT_ID(N'dw.dim_product') IS NULL
CREATE TABLE dw.dim_product (
    product_key          INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_dim_product PRIMARY KEY,
    product_id           CHAR(32)      NOT NULL CONSTRAINT uq_dim_product_id UNIQUE,
    category_name_pt     NVARCHAR(255) NOT NULL,  -- 'sem_categoria' when the source has none
    category_name_en     NVARCHAR(255) NOT NULL,  -- English; falls back to the Portuguese name
    is_category_translated BIT         NOT NULL,  -- 0 for the fallback above
    name_length          INT           NULL,
    description_length   INT           NULL,
    photos_qty           INT           NULL,
    weight_g             INT           NULL,
    length_cm            INT           NULL,
    height_cm            INT           NULL,
    width_cm             INT           NULL,
    run_id               NVARCHAR(100) NOT NULL,
    updated_at_utc       DATETIME2(3)  NOT NULL CONSTRAINT df_dim_product_upd DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'dw.dim_seller') IS NULL
CREATE TABLE dw.dim_seller (
    seller_key      INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_dim_seller PRIMARY KEY,
    seller_id       CHAR(32)      NOT NULL CONSTRAINT uq_dim_seller_id UNIQUE,
    zip_code_prefix CHAR(5)       NOT NULL,
    city            NVARCHAR(255) NOT NULL,
    state           CHAR(2)       NOT NULL,
    latitude        DECIMAL(9,6)  NULL,
    longitude       DECIMAL(9,6)  NULL,
    run_id          NVARCHAR(100) NOT NULL,
    updated_at_utc  DATETIME2(3)  NOT NULL CONSTRAINT df_dim_seller_upd DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'dw.fact_orders') IS NULL
CREATE TABLE dw.fact_orders (
    order_id                    CHAR(32)      NOT NULL CONSTRAINT pk_fact_orders PRIMARY KEY,
    customer_key                INT           NOT NULL,
    purchase_date_key           INT           NOT NULL,
    approved_date_key           INT           NULL,
    delivered_carrier_date_key  INT           NULL,
    delivered_customer_date_key INT           NULL,
    estimated_delivery_date_key INT           NOT NULL,
    order_status                NVARCHAR(20)  NOT NULL,
    purchased_at                DATETIME2(0)  NOT NULL,
    delivered_customer_at       DATETIME2(0)  NULL,
    estimated_delivery_date     DATE          NOT NULL,
    -- aggregated from stg.order_items (0 when the order has no items: 775 orders)
    item_count                  INT           NOT NULL,
    items_price                 DECIMAL(12,2) NOT NULL,
    items_freight               DECIMAL(12,2) NOT NULL,
    -- aggregated from stg.order_payments (does NOT always equal price + freight: see data dictionary)
    payment_count               INT           NOT NULL,
    payment_value               DECIMAL(12,2) NOT NULL,
    -- aggregated from stg.order_reviews (NULL when no review; some orders have several)
    review_count                INT           NOT NULL,
    review_score_avg            DECIMAL(3,2)  NULL,
    -- delivery measures; NULL unless the order has a customer delivery timestamp
    delivery_days               DECIMAL(7,2)  NULL,  -- purchase -> delivered to customer, in days
    estimated_delivery_days     INT           NOT NULL, -- purchase date -> estimated date, in days
    delivery_vs_estimate_days   INT           NULL,  -- delivered date - estimated date (> 0 = late)
    is_delivered                BIT           NOT NULL,
    is_late                     BIT           NULL,  -- NULL when not delivered
    delivery_status             NVARCHAR(20)  NOT NULL, -- On time | Late | Not delivered
    run_id                      NVARCHAR(100) NOT NULL,
    loaded_at_utc               DATETIME2(3)  NOT NULL CONSTRAINT df_fact_orders_loaded DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID(N'dw.fact_order_items') IS NULL
CREATE TABLE dw.fact_order_items (
    order_id                CHAR(32)      NOT NULL,
    order_item_id           INT           NOT NULL,
    product_key             INT           NOT NULL,
    seller_key              INT           NOT NULL,
    customer_key            INT           NOT NULL,
    purchase_date_key       INT           NULL,      -- NULL only if the order itself is missing
    shipping_limit_date_key INT           NOT NULL,
    order_status            NVARCHAR(20)  NULL,      -- copied from the order, for filtering
    price                   DECIMAL(10,2) NOT NULL,
    freight_value           DECIMAL(10,2) NOT NULL,
    run_id                  NVARCHAR(100) NOT NULL,
    loaded_at_utc           DATETIME2(3)  NOT NULL CONSTRAINT df_fact_order_items_loaded DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_fact_order_items PRIMARY KEY (order_id, order_item_id)
);
GO

IF OBJECT_ID(N'dw.fact_payments') IS NULL
CREATE TABLE dw.fact_payments (
    order_id             CHAR(32)      NOT NULL,
    payment_sequential   INT           NOT NULL,
    customer_key         INT           NOT NULL,
    purchase_date_key    INT           NULL,
    order_status         NVARCHAR(20)  NULL,
    payment_type         NVARCHAR(20)  NOT NULL,
    payment_installments INT           NOT NULL,
    payment_value        DECIMAL(10,2) NOT NULL,
    run_id               NVARCHAR(100) NOT NULL,
    loaded_at_utc        DATETIME2(3)  NOT NULL CONSTRAINT df_fact_payments_loaded DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_fact_payments PRIMARY KEY (order_id, payment_sequential)
);
GO

-- "Unknown" members (key -1), referenced by facts whose dimension row is missing.
IF NOT EXISTS (SELECT 1 FROM dw.dim_customer WHERE customer_key = -1)
BEGIN
    SET IDENTITY_INSERT dw.dim_customer ON;
    INSERT dw.dim_customer (customer_key, customer_id, customer_unique_id, zip_code_prefix, city, state, run_id)
    VALUES (-1, REPLICATE('?', 32), REPLICATE('?', 32), '?', N'Unknown', '?', N'seed');
    SET IDENTITY_INSERT dw.dim_customer OFF;
END;
IF NOT EXISTS (SELECT 1 FROM dw.dim_product WHERE product_key = -1)
BEGIN
    SET IDENTITY_INSERT dw.dim_product ON;
    INSERT dw.dim_product (product_key, product_id, category_name_pt, category_name_en, is_category_translated, run_id)
    VALUES (-1, REPLICATE('?', 32), N'Unknown', N'Unknown', 0, N'seed');
    SET IDENTITY_INSERT dw.dim_product OFF;
END;
IF NOT EXISTS (SELECT 1 FROM dw.dim_seller WHERE seller_key = -1)
BEGIN
    SET IDENTITY_INSERT dw.dim_seller ON;
    INSERT dw.dim_seller (seller_key, seller_id, zip_code_prefix, city, state, run_id)
    VALUES (-1, REPLICATE('?', 32), '?', N'Unknown', '?', N'seed');
    SET IDENTITY_INSERT dw.dim_seller OFF;
END;
GO
