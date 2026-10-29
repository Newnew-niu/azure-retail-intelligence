/*
    MART layer: business-ready views on the star schema, one per reporting question.
    Views (not tables), so they are always consistent with dw and cost nothing to refresh.
    Power BI imports the dw star schema directly and uses the same definitions in DAX;
    these views make the definitions testable in SQL and usable by any other SQL client.

    KPI definitions (used everywhere in the project)
      Sales orders   orders whose status is not 'canceled' or 'unavailable'
      Product sales  SUM(item price) of sales orders - excludes freight; "GMV" in reports
      Freight        SUM(item freight) of sales orders
      AOV            (product sales + freight) / number of sales orders that have items
      Customers      DISTINCT customer_unique_id (customer_id is one per order in Olist)
      Delivery days  purchase -> customer delivery, delivered orders only
      Late rate      delivered orders delivered after the estimated date / delivered orders
      Review score   mean of the per-order average score, orders with a review only
    Not calculated: profit, margin, inventory (the dataset has no cost or stock data).
*/

CREATE OR ALTER VIEW mart.vw_sales_monthly AS
SELECT d.year_month,
       d.month_start,
       COUNT(*)                                                  AS sales_orders,
       COUNT(DISTINCT c.customer_unique_id)                      AS customers,
       SUM(f.item_count)                                         AS items_sold,
       SUM(f.items_price)                                        AS product_sales,
       SUM(f.items_freight)                                      AS freight,
       CAST(SUM(f.items_price + f.items_freight) / NULLIF(SUM(CASE WHEN f.item_count > 0 THEN 1 END), 0)
            AS DECIMAL(12,2))                                    AS average_order_value
  FROM dw.fact_orders AS f
  JOIN dw.dim_date AS d     ON d.date_key = f.purchase_date_key
  JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key
 WHERE f.order_status NOT IN (N'canceled', N'unavailable')
 GROUP BY d.year_month, d.month_start;
GO

CREATE OR ALTER VIEW mart.vw_delivery_by_state AS
SELECT c.state                                                           AS customer_state,
       COUNT(*)                                                          AS delivered_orders,
       CAST(AVG(f.delivery_days) AS DECIMAL(7,2))                        AS avg_delivery_days,
       CAST(AVG(CAST(f.estimated_delivery_days AS DECIMAL(7,2))) AS DECIMAL(7,2)) AS avg_estimated_days,
       CAST(AVG(CAST(f.is_late AS DECIMAL(5,4))) AS DECIMAL(5,4))        AS late_rate,
       CAST(AVG(f.review_score_avg) AS DECIMAL(3,2))                     AS avg_review_score
  FROM dw.fact_orders AS f
  JOIN dw.dim_customer AS c ON c.customer_key = f.customer_key
 WHERE f.is_delivered = 1
 GROUP BY c.state;
GO

-- Review score by delivery outcome. Descriptive only: late orders get lower scores, but this
-- view does not show that lateness CAUSES the lower score (other factors are not controlled).
CREATE OR ALTER VIEW mart.vw_review_by_delivery_status AS
SELECT f.delivery_status,
       COUNT(*)                                             AS orders,
       SUM(CASE WHEN f.review_count > 0 THEN 1 ELSE 0 END)  AS reviewed_orders,
       CAST(AVG(f.review_score_avg) AS DECIMAL(3,2))        AS avg_review_score
  FROM dw.fact_orders AS f
 WHERE f.order_status NOT IN (N'canceled', N'unavailable')
 GROUP BY f.delivery_status;
GO

-- Category performance at ITEM grain (an order can contain several categories, so order
-- counts per category would not add up to the total and are not shown here).
CREATE OR ALTER VIEW mart.vw_category_sales AS
SELECT p.category_name_en,
       p.is_category_translated,
       COUNT(*)                                  AS items_sold,
       COUNT(DISTINCT i.product_key)             AS products,
       SUM(i.price)                              AS product_sales,
       CAST(AVG(i.price) AS DECIMAL(10,2))       AS avg_item_price,
       SUM(i.freight_value)                      AS freight
  FROM dw.fact_order_items AS i
  JOIN dw.dim_product AS p ON p.product_key = i.product_key
 WHERE i.order_status NOT IN (N'canceled', N'unavailable')
 GROUP BY p.category_name_en, p.is_category_translated;
GO

CREATE OR ALTER VIEW mart.vw_seller_performance AS
SELECT s.seller_id,
       s.state                                   AS seller_state,
       COUNT(*)                                  AS items_sold,
       COUNT(DISTINCT i.order_id)                AS orders,
       SUM(i.price)                              AS product_sales,
       CAST(AVG(o.delivery_days) AS DECIMAL(7,2)) AS avg_delivery_days,  -- per item of delivered orders
       CAST(AVG(o.review_score_avg) AS DECIMAL(3,2)) AS avg_review_score
  FROM dw.fact_order_items AS i
  JOIN dw.dim_seller AS s ON s.seller_key = i.seller_key
  JOIN dw.fact_orders AS o ON o.order_id = i.order_id
 WHERE i.order_status NOT IN (N'canceled', N'unavailable')
 GROUP BY s.seller_id, s.state;
GO

CREATE OR ALTER VIEW mart.vw_payment_mix AS
SELECT f.payment_type,
       COUNT(*)                                          AS payment_records,
       COUNT(DISTINCT f.order_id)                        AS orders,
       SUM(f.payment_value)                              AS payment_value,
       CAST(AVG(CAST(f.payment_installments AS DECIMAL(5,2))) AS DECIMAL(5,2)) AS avg_installments
  FROM dw.fact_payments AS f
 WHERE f.order_status NOT IN (N'canceled', N'unavailable')
 GROUP BY f.payment_type;
GO
