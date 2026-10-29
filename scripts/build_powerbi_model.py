"""Generate the Power BI semantic model (TMDL) from one reviewable definition.

    python scripts/build_powerbi_model.py [--model-dir powerbi/RetailIntelligence.SemanticModel]

Writes definition/{database,model,expressions,relationships}.tmdl and definition/tables/*.tmdl.
Power BI Desktop must be CLOSED while this runs; reopen the .pbip afterwards and refresh.

Model design
  * Import mode from the dw star schema. The committed Server parameter is a placeholder (no
    real hostname in a public repository): set it in Power BI Desktop (Transform data -> Edit
    parameters) to your Azure SQL server or (localdb)\\MSSQLLocalDB, or pass --server here and
    do not commit the result. Load/run metadata columns are not imported.
  * Single-direction one-to-many relationships from dimensions to facts. The three facts
    are NOT related to each other: each measure lives on the fact of its own grain, so a
    category filter (product grain) can never silently multiply an order-level number.
    The one cross-grain measure uses TREATAS explicitly.
  * Measures follow the KPI definitions in sql/mart/01_views.sql (sales orders exclude
    'canceled' and 'unavailable'; customers = distinct customer_unique_id).
  * dim_date[In Reporting Window] = Jan 2017 - Aug 2018, the months with complete data
    (Sep-Dec 2016 and Sep-Oct 2018 have only a handful of orders); used as a report filter.
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR = PROJECT_ROOT / "powerbi" / "RetailIntelligence.SemanticModel"
DEFAULT_SERVER = "your-server.database.windows.net"  # placeholder; see the module docstring
DEFAULT_DATABASE = "retail_intelligence"
NOT_SALES = '{"canceled", "unavailable"}'

# (column, TMDL dataType, properties). Properties: hidden, format, sort_by, key, summarize
COLUMNS: dict[str, list[tuple]] = {
    "dim_date": [
        ("date_key", "int64", {"hidden": True}),
        ("date", "dateTime", {"format": "yyyy-mm-dd", "key": True}),
        ("year", "int64", {}),
        ("quarter", "int64", {}),
        ("month", "int64", {"hidden": True}),
        ("month_name", "string", {"sort_by": "month"}),
        ("year_month", "string", {}),
        ("month_start", "dateTime", {"format": "mmm yyyy"}),
        ("day_of_month", "int64", {}),
        ("day_of_week", "int64", {"hidden": True}),
        ("day_name", "string", {"sort_by": "day_of_week"}),
        ("is_weekend", "boolean", {}),
    ],
    "dim_customer": [
        ("customer_key", "int64", {"hidden": True}),
        ("customer_id", "string", {"hidden": True}),
        ("customer_unique_id", "string", {}),
        ("zip_code_prefix", "string", {}),
        ("city", "string", {}),
        ("state", "string", {}),
        ("latitude", "double", {"category": "Latitude"}),
        ("longitude", "double", {"category": "Longitude"}),
    ],
    "dim_product": [
        ("product_key", "int64", {"hidden": True}),
        ("product_id", "string", {}),
        ("category_name_pt", "string", {}),
        ("category_name_en", "string", {}),
        ("is_category_translated", "boolean", {}),
        ("photos_qty", "int64", {}),
        ("weight_g", "int64", {}),
    ],
    "dim_seller": [
        ("seller_key", "int64", {"hidden": True}),
        ("seller_id", "string", {}),
        ("city", "string", {}),
        ("state", "string", {}),
        ("latitude", "double", {"category": "Latitude"}),
        ("longitude", "double", {"category": "Longitude"}),
    ],
    "fact_orders": [
        ("order_id", "string", {}),
        ("customer_key", "int64", {"hidden": True}),
        ("purchase_date_key", "int64", {"hidden": True}),
        ("order_status", "string", {}),
        ("purchased_at", "dateTime", {"format": "yyyy-mm-dd hh:nn"}),
        ("delivered_customer_at", "dateTime", {"format": "yyyy-mm-dd hh:nn"}),
        ("estimated_delivery_date", "dateTime", {"format": "yyyy-mm-dd"}),
        ("item_count", "int64", {"summarize": "sum"}),
        ("items_price", "decimal", {"hidden": True}),
        ("items_freight", "decimal", {"hidden": True}),
        ("payment_count", "int64", {"hidden": True}),
        ("payment_value", "decimal", {"hidden": True}),
        ("review_count", "int64", {"hidden": True}),
        ("review_score_avg", "decimal", {"hidden": True}),
        ("delivery_days", "decimal", {"hidden": True}),
        ("estimated_delivery_days", "int64", {"hidden": True}),
        ("delivery_vs_estimate_days", "int64", {}),
        ("is_delivered", "boolean", {}),
        ("is_late", "boolean", {}),
        ("delivery_status", "string", {}),
    ],
    "fact_order_items": [
        ("order_id", "string", {}),
        ("order_item_id", "int64", {}),
        ("product_key", "int64", {"hidden": True}),
        ("seller_key", "int64", {"hidden": True}),
        ("customer_key", "int64", {"hidden": True}),
        ("purchase_date_key", "int64", {"hidden": True}),
        ("order_status", "string", {}),
        ("price", "decimal", {"hidden": True}),
        ("freight_value", "decimal", {"hidden": True}),
    ],
    "fact_payments": [
        ("order_id", "string", {}),
        ("payment_sequential", "int64", {}),
        ("customer_key", "int64", {"hidden": True}),
        ("purchase_date_key", "int64", {"hidden": True}),
        ("order_status", "string", {}),
        ("payment_type", "string", {}),
        ("payment_installments", "int64", {"hidden": True}),
        ("payment_value", "decimal", {"hidden": True}),
    ],
}

CALCULATED_COLUMNS = {
    "dim_date": [("In Reporting Window", "boolean",
                  "dim_date[date] >= DATE(2017, 1, 1) && dim_date[date] <= DATE(2018, 8, 31)")],
}

def sales_filter(table: str) -> str:
    """Filter argument restricting a fact to sales orders (keeps any status filter the user set)."""
    return f"KEEPFILTERS(NOT {table}[order_status] IN {NOT_SALES})"

# (table, name, DAX, format, display folder, description)
MEASURES = [
    # --- order grain ---
    ("fact_orders", "All Orders", "COUNTROWS(fact_orders)", "#,##0", "Orders",
     "Every order, whatever its status"),
    ("fact_orders", "Sales Orders", f"CALCULATE(COUNTROWS(fact_orders), {sales_filter('fact_orders')})",
     "#,##0", "Orders", "Orders whose status is not canceled or unavailable"),
    ("fact_orders", "Canceled or Unavailable Rate",
     f"DIVIDE(CALCULATE(COUNTROWS(fact_orders), KEEPFILTERS(fact_orders[order_status] IN {NOT_SALES})), [All Orders])",
     "0.0%", "Orders", "Share of orders that were canceled or unavailable"),
    ("fact_orders", "Customers",
     f"COUNTROWS(SUMMARIZE(CALCULATETABLE(fact_orders, {sales_filter('fact_orders')}), dim_customer[customer_unique_id]))",
     "#,##0", "Customers", "Distinct people (customer_unique_id) with at least one sales order"),
    ("fact_orders", "Repeat Customer Rate",
     "VAR people =\n    ADDCOLUMNS(\n        SUMMARIZE(CALCULATETABLE(fact_orders, "
     f"{sales_filter('fact_orders')}), dim_customer[customer_unique_id]),\n"
     '        "@orders", [Sales Orders])\nRETURN\n    DIVIDE(COUNTROWS(FILTER(people, [@orders] > 1)), COUNTROWS(people))',
     "0.0%", "Customers", "Customers with more than one sales order in the selected period / customers"),
    ("fact_orders", "Average Order Value",
     "DIVIDE([Product Sales] + [Freight], CALCULATE([Sales Orders], KEEPFILTERS(fact_orders[item_count] > 0)))",
     "#,##0.00", "Sales", "(product sales + freight) / sales orders that have items, BRL"),
    ("fact_orders", "Delivered Orders",
     "CALCULATE(COUNTROWS(fact_orders), KEEPFILTERS(fact_orders[is_delivered] = TRUE()))",
     "#,##0", "Delivery", "Status delivered and a customer delivery timestamp"),
    ("fact_orders", "Avg Delivery Days",
     "CALCULATE(AVERAGE(fact_orders[delivery_days]), KEEPFILTERS(fact_orders[is_delivered] = TRUE()))",
     "0.0", "Delivery", "Purchase to customer delivery, delivered orders only"),
    ("fact_orders", "Avg Estimated Delivery Days",
     "CALCULATE(AVERAGE(fact_orders[estimated_delivery_days]), KEEPFILTERS(fact_orders[is_delivered] = TRUE()))",
     "0.0", "Delivery", "Purchase date to promised date, delivered orders only"),
    ("fact_orders", "Late Deliveries",
     "CALCULATE(COUNTROWS(fact_orders), KEEPFILTERS(fact_orders[is_late] = TRUE()))",
     "#,##0", "Delivery", "Delivered after the estimated delivery date"),
    ("fact_orders", "Late Delivery Rate", "DIVIDE([Late Deliveries], [Delivered Orders])",
     "0.0%", "Delivery", "Late deliveries / delivered orders"),
    ("fact_orders", "Avg Review Score", "AVERAGE(fact_orders[review_score_avg])",
     "0.00", "Reviews", "Mean of the per-order average score (1-5), reviewed orders only"),
    ("fact_orders", "Reviewed Orders", "CALCULATE(COUNTROWS(fact_orders), KEEPFILTERS(fact_orders[review_count] > 0))",
     "#,##0", "Reviews", "Orders with at least one review"),
    # --- item grain ---
    ("fact_order_items", "Product Sales",
     f"CALCULATE(SUM(fact_order_items[price]), {sales_filter('fact_order_items')})",
     "#,##0", "Sales", "Sum of item prices of sales orders, excluding freight, BRL"),
    ("fact_order_items", "Freight",
     f"CALCULATE(SUM(fact_order_items[freight_value]), {sales_filter('fact_order_items')})",
     "#,##0", "Sales", "Sum of item freight of sales orders, BRL"),
    ("fact_order_items", "Items Sold",
     f"CALCULATE(COUNTROWS(fact_order_items), {sales_filter('fact_order_items')})",
     "#,##0", "Sales", "Order items of sales orders"),
    ("fact_order_items", "Avg Item Price", "DIVIDE([Product Sales], [Items Sold])",
     "#,##0.00", "Sales", "Product sales / items sold, BRL"),
    ("fact_order_items", "Order Review Score",
     "CALCULATE([Avg Review Score], TREATAS(VALUES(fact_order_items[order_id]), fact_orders[order_id]))",
     "0.00", "Reviews",
     "Average review score of the orders containing the items in context (e.g. a category). "
     "A review is per order, so an order with several categories counts for each of them."),
    # --- payment grain ---
    ("fact_payments", "Payment Value",
     f"CALCULATE(SUM(fact_payments[payment_value]), {sales_filter('fact_payments')})",
     "#,##0", "Payments", "Sum of payment records of sales orders, BRL (can differ from price + freight)"),
    ("fact_payments", "Payment Value Share",
     "DIVIDE([Payment Value], CALCULATE([Payment Value], REMOVEFILTERS(fact_payments[payment_type])))",
     "0.0%", "Payments", "Share of payment value by payment type"),
    ("fact_payments", "Avg Installments",
     f"CALCULATE(AVERAGE(fact_payments[payment_installments]), {sales_filter('fact_payments')})",
     "0.0", "Payments", "Average number of instalments per payment record"),
]

# (from table, from column, to table, to column) - many-to-one, single direction
RELATIONSHIPS = [
    ("fact_orders", "customer_key", "dim_customer", "customer_key"),
    ("fact_orders", "purchase_date_key", "dim_date", "date_key"),
    ("fact_order_items", "product_key", "dim_product", "product_key"),
    ("fact_order_items", "seller_key", "dim_seller", "seller_key"),
    ("fact_order_items", "customer_key", "dim_customer", "customer_key"),
    ("fact_order_items", "purchase_date_key", "dim_date", "date_key"),
    ("fact_payments", "customer_key", "dim_customer", "customer_key"),
    ("fact_payments", "purchase_date_key", "dim_date", "date_key"),
]

TABLE_DESCRIPTIONS = {
    "dim_date": "Calendar, one row per day (date_key = yyyymmdd)",
    "dim_customer": "One row per customer_id (= per order in Olist); the person is customer_unique_id",
    "dim_product": "One row per product, with English category (Portuguese fallback)",
    "dim_seller": "One row per seller",
    "fact_orders": "One row per order, with item/payment/review aggregates and delivery measures",
    "fact_order_items": "One row per order item",
    "fact_payments": "One row per payment record",
}


def tag(*parts: str) -> str:
    """Stable lineage tag, so regenerating the model does not look like a new model to Power BI."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "retail-intelligence/" + "/".join(parts)))


def name(identifier: str) -> str:
    return identifier if identifier.replace("_", "").isalnum() else f"'{identifier}'"


def indent(text: str, tabs: int) -> str:
    return "\n".join("\t" * tabs + line for line in text.splitlines())


def table_tmdl(table: str) -> str:
    lines = [f"/// {TABLE_DESCRIPTIONS[table]}", f"table {table}", f"\tlineageTag: {tag(table)}"]
    if table == "dim_date":
        lines.append("\tdataCategory: Time")
    lines.append("")
    for t, measure, dax, fmt, folder, description in MEASURES:
        if t != table:
            continue
        lines.append(f"\t/// {description}")
        if "\n" in dax:
            lines += [f"\tmeasure {name(measure)} =", indent(dax, 3)]
        else:
            lines.append(f"\tmeasure {name(measure)} = {dax}")
        lines += [f"\t\tformatString: {fmt}", f"\t\tdisplayFolder: {folder}",
                  f"\t\tlineageTag: {tag(table, 'measure', measure)}", ""]
    for column, data_type, props in COLUMNS[table]:
        lines += [f"\tcolumn {name(column)}", f"\t\tdataType: {data_type}"]
        if props.get("hidden"):
            lines.append("\t\tisHidden")
        if props.get("key"):
            lines.append("\t\tisKey")
        if "format" in props:
            lines.append(f"\t\tformatString: {props['format']}")
        if "category" in props:
            lines.append(f"\t\tdataCategory: {props['category']}")
        if "sort_by" in props:
            lines.append(f"\t\tsortByColumn: {props['sort_by']}")
        lines += [f"\t\tlineageTag: {tag(table, column)}",
                  f"\t\tsummarizeBy: {props.get('summarize', 'none')}",
                  f"\t\tsourceColumn: {column}", ""]
    for column, data_type, dax in CALCULATED_COLUMNS.get(table, []):
        lines += [f"\tcolumn {name(column)} = {dax}", f"\t\tdataType: {data_type}",
                  f"\t\tlineageTag: {tag(table, column)}", "\t\tsummarizeBy: none", ""]
    selected = ", ".join(f'"{c}"' for c, _, _ in COLUMNS[table])
    m = (f'let\n    Source = Sql.Database(Server, Database),\n'
         f'    Data = Source{{[Schema = "dw", Item = "{table}"]}}[Data],\n'
         f'    Selected = Table.SelectColumns(Data, {{{selected}}})\nin\n    Selected')
    lines += [f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource =", indent(m, 4), ""]
    return "\n".join(lines)


def build(model_dir: Path, server: str, database: str) -> None:
    definition = model_dir / "definition"
    (definition / "tables").mkdir(parents=True, exist_ok=True)
    for old in (definition / "tables").glob("*.tmdl"):
        old.unlink()

    # Compatibility level, culture file and annotations match what Power BI Desktop 2.159 writes
    (definition / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1606\n", encoding="utf-8", newline="\n")
    (definition / "cultures").mkdir(exist_ok=True)
    (definition / "cultures" / "en-GB.tmdl").write_text("cultureInfo en-GB\n", encoding="utf-8", newline="\n")
    model = ["model Model", "\tculture: en-GB", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tsourceQueryCulture: en-GB", "\tvalueFilterBehavior: independent", "\tdataAccessOptions",
             "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
             # dim_date is the calendar: no hidden auto date/time tables per date column
             "annotation __PBI_TimeIntelligenceEnabled = 0", "",
             'annotation PBI_ProTooling = ["DevMode"]', ""]
    model += [f"ref table {t}" for t in COLUMNS] + ["", "ref cultureInfo en-GB", ""]
    (definition / "model.tmdl").write_text("\n".join(model), encoding="utf-8", newline="\n")

    expressions = []
    for param, value, description in [("Server", server, "SQL server: <name>.database.windows.net (Azure SQL) or (localdb)\\MSSQLLocalDB"),
                                      ("Database", database, "Database name")]:
        expressions += [f"/// {description}",
                        f'expression {param} = "{value}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
                        f"\tlineageTag: {tag('parameter', param)}", "", "\tannotation PBI_ResultType = Text", ""]
    (definition / "expressions.tmdl").write_text("\n".join(expressions), encoding="utf-8", newline="\n")

    relationships = []
    for from_table, from_col, to_table, to_col in RELATIONSHIPS:
        relationships += [f"relationship {tag('rel', from_table, from_col, to_table)}",
                          f"\tfromColumn: {from_table}.{from_col}", f"\ttoColumn: {to_table}.{to_col}", ""]
    (definition / "relationships.tmdl").write_text("\n".join(relationships), encoding="utf-8", newline="\n")

    for table in COLUMNS:
        (definition / "tables" / f"{table}.tmdl").write_text(table_tmdl(table), encoding="utf-8", newline="\n")
    print(f"Wrote {len(COLUMNS)} tables, {len(MEASURES)} measures, {len(RELATIONSHIPS)} relationships to {definition}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    args = parser.parse_args()
    build(args.model_dir, args.server, args.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
