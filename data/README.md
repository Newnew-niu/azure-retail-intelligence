# Source data

**Dataset:** [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
**Publisher:** Olist  **License:** CC BY-NC-SA 4.0 (attribution, non-commercial, share-alike)

The CSV files are **not committed** to this repository. To reproduce them:

```bash
python scripts/download_data.py          # downloads and extracts into data/raw/
python -m ingestion.validate_files       # checks the files against config/source_schema.yml
```

Archive SHA-256 used for this project (downloaded 2026-10-28):
`967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784`

## Files (as profiled on 2026-10-28)

| Entity | File | Rows | Natural key |
|---|---|---:|---|
| customers | olist_customers_dataset.csv | 99,441 | `customer_id` (one per order; the person is `customer_unique_id`) |
| geolocation | olist_geolocation_dataset.csv | 1,000,163 | none: many rows per zip prefix, 261,831 exact duplicates |
| orders | olist_orders_dataset.csv | 99,441 | `order_id` |
| order_items | olist_order_items_dataset.csv | 112,650 | `order_id`, `order_item_id` |
| order_payments | olist_order_payments_dataset.csv | 103,886 | `order_id`, `payment_sequential` |
| order_reviews | olist_order_reviews_dataset.csv | 99,224 | `review_id`, `order_id` (`review_id` alone is **not** unique) |
| products | olist_products_dataset.csv | 32,951 | `product_id` |
| sellers | olist_sellers_dataset.csv | 3,095 | `seller_id` |
| product_category_translation | product_category_name_translation.csv | 71 | `product_category_name` |

Orders are purchased between 2016-09-04 and 2018-10-17. Timestamps carry no
time zone; the project assumes they are Brazilian local time and does not convert them.

## Folders

- `raw/` – the original files, unmodified (git-ignored).
- `batches/` – simulated incremental batches generated from `raw/` (git-ignored, Stage 4).
