# Data dictionary

Authoritative definitions are the DDL files; this page summarises them for readers.
Money is BRL, `DECIMAL(10,2)` per row and `DECIMAL(12,2)` for per-order sums. Timestamps are
`DATETIME2(0)` in Brazilian local time as delivered (no time zone in the source).

## raw ([sql/raw/01_tables.sql](../sql/raw/01_tables.sql))

One table per source file (`raw.customers`, `raw.geolocation`, `raw.orders`, `raw.order_items`,
`raw.order_payments`, `raw.order_reviews`, `raw.products`, `raw.sellers`,
`raw.product_category_translation`) with the **source column names unchanged**, all `NVARCHAR(255)`
(review texts `NVARCHAR(4000)`), plus:

| Column | Meaning |
|---|---|
| `batch_id` | Batch the row arrived in (`full_load`, `sim_01_2017-12`, …) |
| `source_file` | File name the row came from |
| `run_id` | Pipeline run that loaded it (ADF run ID or `local_<timestamp>_<hex>`) |
| `loaded_at_utc` | Load time |

Source columns and formats: [config/source_schema.yml](../config/source_schema.yml).

## stg ([sql/staging/01_tables.sql](../sql/staging/01_tables.sql))

Typed, one row per natural key, columns renamed (source typos `product_name_lenght` /
`product_description_lenght` fixed). Every table carries `batch_id` / `run_id` of the last change and
`inserted_at_utc` / `updated_at_utc`, which drive the incremental DW loads.

| Table | Key | Notable rules |
|---|---|---|
| `stg.customers` | `customer_id` | `customer_unique_id` identifies the person |
| `stg.sellers` | `seller_id` | |
| `stg.products` | `product_id` | `category_name_pt` NULL for 610 products |
| `stg.product_category_translation` | `category_name_pt` | 71 categories; BOM in the source file handled |
| `stg.orders` | `order_id` | `estimated_delivery_date` stored as `DATE` (always midnight; a time part would be rejected) |
| `stg.order_items` | `order_id`, `order_item_id` | |
| `stg.order_payments` | `order_id`, `payment_sequential` | |
| `stg.order_reviews` | `review_id`, `order_id` | `review_id` alone is not unique in the source (814 repeats) |
| `stg.geolocation` | `zip_code_prefix` | 1,000,163 raw rows summarised to 19,015: mean lat/lng of points inside Brazil's bounding box, most frequent state; `source_rows`, `excluded_points` kept |

Rows that cannot be stored (bad id, unparseable timestamp, …) go to `ops.rejected_row` with a reason.

## dw ([sql/dw/01_tables.sql](../sql/dw/01_tables.sql))

### dim_date
| Column | Type | Description |
|---|---|---|
| `date_key` | INT | yyyymmdd, primary key |
| `date` | DATE | Calendar date |
| `year`, `quarter`, `month`, `day_of_month` | numbers | |
| `month_name`, `day_name` | NVARCHAR | English, independent of session language |
| `year_month` | CHAR(7) | `2018-01`; sorts correctly as text |
| `month_start` | DATE | First day of the month |
| `day_of_week` | TINYINT | 1 = Monday … 7 = Sunday |
| `is_weekend` | BIT | Saturday or Sunday |

### dim_customer
| Column | Type | Description |
|---|---|---|
| `customer_key` | INT | Surrogate key; `-1` = Unknown |
| `customer_id` | CHAR(32) | Source key, one per order |
| `customer_unique_id` | CHAR(32) | The person; count this for "customers" |
| `zip_code_prefix`, `city`, `state` | | Delivery address of that order |
| `latitude`, `longitude` | DECIMAL(9,6) | Zip-prefix centroid; NULL for 279 customers whose prefix has no geolocation |

### dim_product
| Column | Type | Description |
|---|---|---|
| `product_key` | INT | Surrogate key; `-1` = Unknown |
| `product_id` | CHAR(32) | Source key |
| `category_name_pt` | NVARCHAR | Portuguese category; `sem_categoria` when missing |
| `category_name_en` | NVARCHAR | English category; `uncategorised` when missing; Portuguese name when no translation exists |
| `is_category_translated` | BIT | 0 for the 13 products in `pc_gamer` and `portateis_cozinha_e_preparadores_de_alimentos` |
| `name_length`, `description_length`, `photos_qty`, `weight_g`, `length_cm`, `height_cm`, `width_cm` | INT | As in the source |

### dim_seller
| Column | Type | Description |
|---|---|---|
| `seller_key` | INT | Surrogate key; `-1` = Unknown |
| `seller_id` | CHAR(32) | Source key |
| `zip_code_prefix`, `city`, `state`, `latitude`, `longitude` | | As for customers; 7 sellers without geolocation |

### fact_orders (one row per order)
| Column | Type | Description |
|---|---|---|
| `order_id` | CHAR(32) | Primary key |
| `customer_key` | INT | → dim_customer |
| `purchase_date_key`, `approved_date_key`, `delivered_carrier_date_key`, `delivered_customer_date_key`, `estimated_delivery_date_key` | INT | → dim_date (NULL when the event has not happened) |
| `order_status` | NVARCHAR(20) | delivered, shipped, canceled, unavailable, invoiced, processing, created, approved |
| `purchased_at`, `delivered_customer_at` | DATETIME2 | |
| `estimated_delivery_date` | DATE | Promised date |
| `item_count`, `items_price`, `items_freight` | | From `stg.order_items` grouped by order; 0 for the 775 orders without items |
| `payment_count`, `payment_value` | | From `stg.order_payments` grouped by order; 0 for the 1 order without payment |
| `review_count`, `review_score_avg` | | From `stg.order_reviews`; NULL score for the 768 orders without a review |
| `is_delivered` | BIT | Status `delivered` and a delivery timestamp |
| `delivery_days` | DECIMAL(7,2) | Purchase → delivered, in days (delivered orders only) |
| `estimated_delivery_days` | INT | Purchase date → promised date |
| `delivery_vs_estimate_days` | INT | Delivered date − promised date; > 0 means late |
| `is_late` | BIT | NULL when not delivered |
| `delivery_status` | NVARCHAR(20) | `On time`, `Late`, `Not delivered` |

### fact_order_items (one row per order item)
`order_id`, `order_item_id` (key), `product_key`, `seller_key`, `customer_key`, `purchase_date_key`,
`shipping_limit_date_key`, `order_status` (copied from the order for filtering), `price`, `freight_value`.

### fact_payments (one row per payment record)
`order_id`, `payment_sequential` (key), `customer_key`, `purchase_date_key`, `order_status`,
`payment_type` (credit_card, boleto, voucher, debit_card, not_defined), `payment_installments`, `payment_value`.

All dw tables carry `run_id` and `updated_at_utc` / `loaded_at_utc` for lineage.

## mart ([sql/mart/01_views.sql](../sql/mart/01_views.sql))

Sales orders only (status not canceled / unavailable) unless stated.

| View | Grain | Columns |
|---|---|---|
| `vw_sales_monthly` | month | `year_month`, `month_start`, `sales_orders`, `customers`, `items_sold`, `product_sales`, `freight`, `average_order_value` |
| `vw_delivery_by_state` | customer state, delivered orders | `delivered_orders`, `avg_delivery_days`, `avg_estimated_days`, `late_rate`, `avg_review_score` |
| `vw_review_by_delivery_status` | delivery status | `orders`, `reviewed_orders`, `avg_review_score` (descriptive, not causal) |
| `vw_category_sales` | English category | `items_sold`, `products`, `product_sales`, `avg_item_price`, `freight` |
| `vw_seller_performance` | seller | `seller_state`, `items_sold`, `orders`, `product_sales`, `avg_delivery_days`, `avg_review_score` (item-weighted) |
| `vw_payment_mix` | payment type | `payment_records`, `orders`, `payment_value`, `avg_installments` |

## ops ([sql/ops/01_tables.sql](../sql/ops/01_tables.sql))

| Table | Purpose |
|---|---|
| `pipeline_run` | One row per run: `run_id`, pipeline, batch, `trigger_source` (local / adf), status, times, error |
| `step_log` | One row per step: procedure or copy, target, status, rows read / written / rejected, error |
| `rejected_row` | Rows staging could not store, with key and reason |
| `watermark` | Last staging change applied to each fact |
| `dq_result` | One row per check per run: category, severity (ERROR / WARN), failed rows, status (PASS / FAIL / WARN) |
