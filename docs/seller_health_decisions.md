# Seller Health: design decisions

Seller Health lets an analyst browse the marketplace's sellers and assess one seller's
performance: sales, order value, dispatch punctuality and reviews, month by month, with three
simple health signals. It is read from the same warehouse as the rest of the project, through
the serving layer.

Each record follows the same form: context, decision, alternatives considered, trade-offs.
Numbers quoted here were measured on the DuckDB export of the full Olist data
(`data/serving.duckdb`), unless stated otherwise.

---

## ADR-001: Metric definitions at the seller-order grain

**Context.** Olist orders can contain items from several sellers, and the order-level facts
(delivery dates, review score) belong to the whole order. A seller KPI has to choose a grain.

**Decision.** One *seller-order* is one order counted for one seller. All KPIs use sales orders
(status not `canceled` or `unavailable`) purchased inside the catalog's reporting window,
2017-01-01 to 2018-08-31, the same window as the README.

| KPI | Definition |
|---|---|
| `orders` | Seller-orders |
| `items_sold` | Order items of the seller |
| `product_sales` | Sum of the seller's item prices, excluding freight |
| `average_order_value` | The seller's (price + freight) per seller-order |
| `late_rate` | Dispatched seller-orders handed to the carrier after the seller's shipping deadline, divided by dispatched seller-orders |
| `review_score` | Mean order review score over seller-orders that have a review |

**Alternatives.** Reuse `mart.vw_seller_performance`: it covers all dates rather than the
reporting window, weights averages by item and has no monthly breakdown. Count an order's review
or delivery against only one "main" seller: arbitrary for multi-seller orders.

**Trade-offs.** An order shared by two sellers counts once for each, so seller orders do not add
up to marketplace orders. The review score belongs to the whole order, so a seller in a shared
order inherits a review that may be about the other seller.

## ADR-002: Late dispatch instead of late delivery

**Context.** The warehouse has two lateness measures. `is_late` compares delivery to the
customer with the promised date, which also measures the carrier. The seller's own obligation is
the shipping deadline (`shipping_limit_date_key`) for handing the order to the carrier.

**Decision.** `late_rate` is late dispatch: the carrier hand-over date is after the seller's
shipping deadline. Dates are compared, not times. A seller-order that has not been handed to the
carrier is not in the denominator.

**Alternatives.** Late delivery to the customer (`is_late`): available and already used by the
dashboard, but it mixes seller and carrier performance.

**Trade-offs.** The carrier date is recorded per order, so in a shared order both sellers get
the same hand-over date. Comparing whole dates ignores a hand-over a few hours late on the
deadline day. Within one seller-order the deadline was identical for every item (0 of 99,245
seller-orders differ), so taking the maximum or the minimum gives the same result.

## ADR-003: Fixed, parameterised queries, not the guarded SQL path

**Context.** The serving layer already runs caller SQL safely through `sql_guard`. Seller pages
need only a few known query shapes.

**Decision.** `serving/core/sellers.py` holds fixed SQL text. Callers choose values, never SQL:
filters are bound parameters, the sort column comes from a fixed mapping, and the page size and
offset are integers validated by the API and checked again in the service. Values are therefore
data, not code, and the API rejects malformed ones with 422 before any query runs. The SQL is
DuckDB dialect and the azuresql backend translates it, like every other query.

LIMIT and OFFSET are written as integers, not placeholders: sqlglot translates
`LIMIT ? OFFSET ?` to `OFFSET ? ROWS FETCH FIRST ? ROWS ONLY`, which reverses the order of the
two placeholders, so bound values would be swapped on Azure SQL. A test documents this.

**Alternatives.** Send these queries through `run_query`: the guard is designed for untrusted
SQL, and building SQL strings from user input to feed it would be the very pattern the guard
exists to stop. An ORM or a query builder: one more dependency for three queries.

**Trade-offs.** The seller-order logic exists as SQL text in one module rather than as a
warehouse view, so Power BI and the MCP server do not see it. A `mart` view would need a
deployment to Azure SQL, which is out of scope here.

## ADR-004: Public read-only seller endpoints; `/query` keeps its key

**Context.** A browser application cannot keep an API key secret: anything shipped to the
browser can be read. The seller endpoints run only fixed queries over data that the public web
dashboard already summarises.

**Decision.** `GET /sellers` and `GET /sellers/{seller_id}` need no key. They are protected by
their shape instead: fixed queries, validated parameters, at most 100 rows per page, page numbers
up to 10,000, the query timeout, and the audit log, which records every seller query by name with
its parameters. CORS is off unless `SERVING_CORS_ORIGINS` lists origins; then only `GET` is
allowed and no custom request headers, so a browser page can never send `X-API-Key`.
`/datasets`, `/query` and `/runs/latest` keep the API key exactly as before.

**Alternatives.** Require the API key on seller endpoints too: the key would have to be built
into the front end, where it is public anyway. A backend-for-frontend with user sign-in (OAuth):
the right choice for non-public data, but heavy for public, aggregated data.

**Trade-offs.** Anyone can call the seller endpoints, so there is no per-user identity. There is
no rate limiting in the application; a hosted deployment should add it at the platform edge.
CORS limits browsers only; it is not access control for other clients.

## ADR-005: Health signals are three transparent rules

**Context.** The page should help an analyst see where to look, without pretending to be a
credit model. Rules must be simple enough to check by hand.

**Decision.** Three signals over the last six months of the window (2018-03 to 2018-08), each
returning a status (`positive`, `neutral`, `attention`, `insufficient_data`), the value, the rule
and a sentence with the numbers behind it. Every response carries a disclaimer that this is not
a credit score.

| Signal | Positive | Attention | Minimum data |
|---|---|---|---|
| Sales trend: last 3 months vs the 3 before | +10 % or more | −20 % or less | 10 orders |
| Late dispatch rate | 5 % or less | above 10 % | 10 dispatched orders |
| Mean review score | 4.0 or more | below 3.5 | 5 reviewed orders |

How the thresholds relate to the data, measured on the export:
- Across the marketplace, product sales from 2018-06 to 2018-08 were 12.7 % lower than from
  2018-03 to 2018-05, so the attention threshold for the trend is set below that (−20 %) to
  avoid flagging the market-wide dip.
- Late dispatch over all seller-orders in the window is 5.6 %. Among sellers with at least 10
  dispatched orders in the last six months, the median is 0 % and the 90th percentile 10.9 %.
- Among sellers with at least 5 reviewed orders in the last six months, the median review score
  is 4.22 and the 10th percentile 3.62.

Status counts over all 3,029 sellers with sales in the window:

| Signal | Positive | Neutral | Attention | Insufficient data |
|---|--:|--:|--:|--:|
| Sales trend | 239 | 105 | 382 | 2,303 |
| Late dispatch | 556 | 143 | 86 | 2,244 |
| Review score | 897 | 242 | 79 | 1,811 |

**Alternatives.** A weighted composite score: hides which input drove the result. Percentile
ranks against peers: fairer across categories but harder to explain and unstable for small
sellers. A statistical or learned model: needs outcomes (for example repayments) that this data
does not have.

**Trade-offs.** Fixed thresholds ignore category and seasonality, and most sellers are too small
for any verdict (`insufficient_data`), which is shown rather than guessed. Signals are computed in
Python from the monthly rows, so the front end only displays them and every client sees the
same result.

## ADR-006: Testing approach for the seller endpoints

**Context.** The CI runs without real data, and the seller numbers must be right, not just
well-formed.

**Decision.** Three layers.
1. A separate synthetic database (`serving/tests/seller_data.py`) where every expected number is
   worked out by hand: sorting with empty values, shared orders, excluded statuses, paging,
   filters, 404 and 422. It is separate from the existing fixture database, so the existing
   tests keep their data.
2. Golden numbers on the real export: KPIs of a sample of sellers from independently written SQL
   (a different query shape) must equal the API's list and detail responses. Skipped on CI.
3. The same requests on the azuresql backend against LocalDB must return the same pages, KPIs
   and signal statuses as DuckDB, which proves the translated T-SQL. Skipped without LocalDB.

The tests were checked by changing the seller SQL on purpose: treating a dispatch on the deadline
day as late failed three tests. Counting `unavailable` orders as sales was first missed, because
all seven unavailable items are from 2016, outside the window; a synthetic unavailable order now
catches it.

**Alternatives.** Snapshot the API responses: catches change, not error.

**Trade-offs.** The golden tests and the SQL Server comparison run only on a machine that has the
export and LocalDB; CI runs the synthetic layer.

## ADR-007: Front-end stack

**Context.** The web app needs routing, data fetching with loading and error states, one chart
type, and types that follow the API.

**Decision.** Vite, React and TypeScript in strict mode (`strict`, `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`), React Router, TanStack Query and Recharts. No UI kit and no
state-management library: the URL holds the list state and TanStack Query holds server data.
TypeScript is pinned to 5.9, because typescript-eslint supports versions below 6.1 and
openapi-typescript declares TypeScript 5 as its peer.

Recharts rather than ECharts: its charts are React components, so they follow React's state
without imperative set-up and clean-up, and it draws SVG that Testing Library can render.
ECharts, used by the existing dashboard, offers more chart types, which this page does not need.
The detail page, which holds the chart, is loaded on demand; the list page does not download the
chart library.

**Alternatives.** Next.js: server rendering is not needed for an analyst tool behind a static
host. Redux or Zustand: no client state that the URL and the query cache do not already hold.

**Trade-offs.** Recharts adds most of the bundle weight of the detail page. Pinning TypeScript
below the newest major version keeps the lint rules that need type information.

## ADR-008: The OpenAPI schema is the contract between the API and the web app

**Context.** Field names and nullability must match on both sides; a renamed field should fail a
build, not a page.

**Decision.** `scripts/export_openapi.py` writes `web/openapi.json` from the FastAPI app, and
`npm run gen:api` turns it into `web/src/api/schema.d.ts` with openapi-typescript. Two checks
keep them in step: a pytest test fails when `openapi.json` differs from the live schema, and the
web CI fails when the generated types differ from `openapi.json`. Test data in the web app is
typed with the generated types, so a contract change also breaks the tests at compile time.

**Alternatives.** Hand-written types: drift silently. Generating a full client (openapi-fetch,
Orval): more code and a dependency for two GET endpoints; a thin `fetch` wrapper is enough.

**Trade-offs.** Changing an endpoint takes two commands. Nullable fields from Pydantic
(`float | None`) become `number | null`, so every formatter handles `null`, which the pages show
as a dash: no basis is not the same as zero.

## ADR-009: State in the URL, hash routing

**Context.** An analyst should be able to share a filtered, sorted page of the seller list, and
the app is served from a sub-path of a static host.

**Decision.** Search, state, sort, order and page live in the query string and are parsed
forgivingly: a hand-edited or outdated link falls back to defaults instead of failing. Routes use
the URL hash (`#/sellers/<id>?...`), and builds use relative asset paths, so the same files work
at `/` in Docker and under `/<repository>/seller-health/` on GitHub Pages without server rewrites.

**Alternatives.** Path-based routing with a `404.html` redirect on GitHub Pages: cleaner URLs, but
GitHub Pages serves one 404 page for the whole site, which here also hosts the dashboard.

**Trade-offs.** Hash URLs look less tidy, and the server never sees the route.

## ADR-010: Hosting the API on Azure Container Apps

**Context.** GitHub Pages serves static files only, so the web app needs the API hosted somewhere
to show data. The project already runs on Azure.

**Decision.** Azure Container Apps on the Consumption plan, in its own resource group, created by
`infra/seller_api.sh`.
- One container, 0.25 vCPU and 0.5 GiB, scaling between 0 and 1 replica. Scale to zero means no
  compute is billed while nobody uses it; one replica at most caps the cost of misuse. The first
  request after a quiet period waits for a cold start, and the web app explains that wait.
- The image holds code only and is published to GitHub Container Registry by
  `.github/workflows/api-image.yml` after the serving tests pass. The DuckDB export is mounted
  read-only from an Azure Files share, as in `docker-compose.yml`.
- The `/query` key is generated by the script and stored as a Container Apps secret; it is not
  printed or committed. CORS allows the GitHub Pages origin only.
- Deployment runs from a machine with `az login`; GitHub holds no Azure credential.
- No Log Analytics workspace, to avoid ingestion cost.

**Alternatives.** Render: a free instance sleeps after 15 minutes and takes about a minute to wake;
the always-on instance is paid, and the data would have to be built into the image. A static
JSON snapshot of all sellers on GitHub Pages: no back end at all, but the full detail data is
about 15 MB uncompressed, and the page would no longer exercise the API.

**Trade-offs.** The Azure Files mount over SMB needs the storage account key (stored only as a
Container Apps environment secret), unlike the pipeline's storage account, which has shared-key
access turned off. The audit log is written inside the container and is lost when the replica
stops. There is no application-level rate limiting; the replica cap and the query timeout bound
the load.
