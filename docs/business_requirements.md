# Business requirements

## Context

Olist is a Brazilian marketplace that connects small sellers to large online stores. The public
dataset covers ~99k orders placed between September 2016 and October 2018. The audience for the
report is a commercial / operations manager who wants a monthly view of sales, delivery service and
customers, built on numbers that reconcile to the source.

## Questions and where they are answered

| # | Question | Report page | Measures |
|---|---|---|---|
| 1 | How are sales and order volumes trending month by month? | Sales Performance | Product Sales, Sales Orders |
| 2 | What is the average order value? | Sales Performance | Average Order Value |
| 3 | Which product categories and customer states drive sales? | Sales Performance | Product Sales by category, Sales Orders by state |
| 4 | How long does delivery take, against the promised date? | Delivery and Operations | Avg Delivery Days, Avg Estimated Delivery Days |
| 5 | How often are deliveries late, and where? | Delivery and Operations | Late Delivery Rate, Avg Delivery Days by state |
| 6 | How do review scores differ between on-time and late orders? | Delivery and Operations | Avg Review Score by delivery outcome |
| 7 | How many customers buy more than once? | Customer and Product Insights | Customers, Repeat Customer Rate |
| 8 | What do categories sell, at what price, and how are their orders reviewed? | Customer and Product Insights | Items Sold, Product Sales, Avg Item Price, Avg Review Score of Item Orders |
| 9 | How do customers pay? | Customer and Product Insights | Payment Value by payment type |

## KPI definitions

These definitions are implemented once in SQL ([sql/mart/01_views.sql](../sql/mart/01_views.sql)) and
once in DAX ([scripts/build_powerbi_model.py](../scripts/build_powerbi_model.py)), and the two were
checked against each other (see [testing strategy](testing_strategy.md)).

| KPI | Definition | Grain it is computed at |
|---|---|---|
| Sales order | An order whose status is not `canceled` or `unavailable` | order |
| Product Sales | Sum of item `price` of sales orders; excludes freight. Currency BRL | order item |
| Freight | Sum of item `freight_value` of sales orders, BRL | order item |
| Average Order Value | (Product Sales + Freight) / sales orders that have at least one item | order |
| Customers | Distinct `customer_unique_id` with at least one sales order. (`customer_id` is issued per order in Olist and would count orders, not people) | person |
| Repeat Customer Rate | Customers with more than one sales order in the selected period / Customers | person |
| Delivered order | Status `delivered` **and** a customer delivery timestamp | order |
| Avg Delivery Days | Mean of (delivered timestamp − purchase timestamp) in days, delivered orders | order |
| Late Delivery Rate | Delivered orders whose delivery date is after the estimated delivery date / delivered orders | order |
| Avg Review Score | Mean of each order's average review score (1–5); orders without a review are excluded | order |
| Payment Value | Sum of payment records of sales orders, BRL. Not always equal to price + freight (303 orders differ in the source) | payment record |

**Reporting window.** The report filters to January 2017 – August 2018. September–December 2016 and
September–October 2018 together contain only 349 of the 99,441 orders (the export starts and ends
mid-stream), and including them would show misleading drops at both ends of every trend. The SQL
marts and the dw tables keep all months.

## Explicitly out of scope

- **Profit, margin, inventory turnover, stock levels** – the dataset has no cost or stock data.
- **Causal claims** – e.g. "late deliveries cause bad reviews". The report shows the association and
  says so on the page; product, seller and region are not controlled for.
- **Currency conversion** – amounts stay in BRL; converting would need an exchange-rate assumption.
- **Customer lifetime value / churn prediction** – two years of data with a 3 % repeat rate is too thin.

## Expected values (reporting window, used to verify the report)

Computed in SQL from `dw` and compared with the Power BI cards after a refresh from Azure SQL:

| Measure | Value |
|---|---:|
| Sales Orders | 97,910 |
| Product Sales (BRL) | 13,449,529.68 |
| Average Order Value (BRL) | 160.19 |
| Customers | 94,707 |
| Repeat Customer Rate | 3.0 % |
| Delivered Orders | 96,203 |
| Avg Delivery Days | 12.5 |
| Late Delivery Rate | 6.8 % |
| Avg Review Score | 4.09 |
| Items Sold | 111,752 |
| Avg Item Price (BRL) | 120.35 |
