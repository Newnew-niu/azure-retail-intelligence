// Web dashboard: loads data.json, applies the month/state filters, renders KPIs, charts and the table.
// All numbers come from metrics.js (tested against SQL in tests/test_dashboard.py).
import { index, compute } from "./metrics.js";

const $ = (id) => document.getElementById(id);
const fmtInt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const fmt2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt1 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const pct = (v) => (v == null ? "–" : `${fmt1.format(v * 100)}%`);
const num = (f) => (v) => (v == null ? "–" : f.format(v));
const compact = (v) => (Math.abs(v) >= 1e6 ? `${fmt1.format(v / 1e6)}M` : Math.abs(v) >= 1e3 ? `${fmtInt.format(v / 1e3)}K` : fmtInt.format(v));

let data, page = "sales";
const charts = {};

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function theme() {
  return {
    series: css("--series-1"), text: css("--text-secondary"), muted: css("--text-muted"),
    grid: css("--grid"), surface: css("--surface-1"), primary: css("--text-primary"), border: css("--border"),
  };
}

function chart(id) {
  if (!charts[id]) charts[id] = echarts.init($(id), null, { renderer: "svg" });
  return charts[id];
}

function base(t) {
  return {
    animationDuration: 300,
    textStyle: { fontFamily: getComputedStyle(document.body).fontFamily, color: t.text },
    tooltip: {
      backgroundColor: t.surface, borderColor: t.border, textStyle: { color: t.primary, fontSize: 13 },
      confine: true,
    },
  };
}

const axisLabel = (t, extra = {}) => ({ color: t.text, fontSize: 12, ...extra });
const valueAxis = (t, formatter) => ({
  type: "value", axisLabel: axisLabel(t, { formatter }), splitLine: { lineStyle: { color: t.grid } },
  axisLine: { show: false }, axisTick: { show: false },
});
const catAxis = (t, values, extra = {}) => ({
  type: "category", data: values, axisLabel: axisLabel(t), axisTick: { show: false },
  axisLine: { lineStyle: { color: t.grid } }, ...extra,
});

function lineChart(id, labels, values, t, valueFmt, axisFmt) {
  chart(id).setOption({
    ...base(t),
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: { ...base(t).tooltip, trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.muted } },
      valueFormatter: valueFmt },
    xAxis: catAxis(t, labels, { boundaryGap: false, axisLabel: axisLabel(t, { hideOverlap: true }) }),
    yAxis: valueAxis(t, axisFmt),
    series: [{ type: "line", data: values, smooth: false, symbol: "circle", symbolSize: 8, showSymbol: values.length <= 1,
      lineStyle: { width: 2, color: t.series }, itemStyle: { color: t.series } }],
  }, true);
}

function columnChart(id, labels, values, t, valueFmt, axisFmt) {
  chart(id).setOption({
    ...base(t),
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: { ...base(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: valueFmt },
    xAxis: catAxis(t, labels, { axisLabel: axisLabel(t, { hideOverlap: true }) }),
    yAxis: valueAxis(t, axisFmt),
    series: [{ type: "bar", data: values, barMaxWidth: 36, itemStyle: { color: t.series, borderRadius: [4, 4, 0, 0] } }],
  }, true);
}

// Horizontal bars, largest at the top, value printed at the bar end
function barChart(id, labels, values, t, valueFmt, axisFmt, max) {
  chart(id).setOption({
    ...base(t),
    grid: { left: 8, right: 56, top: 8, bottom: 8, containLabel: true },
    tooltip: { ...base(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: valueFmt },
    xAxis: { ...valueAxis(t, axisFmt), max },
    yAxis: catAxis(t, [...labels].reverse()),
    series: [{ type: "bar", data: [...values].reverse(), barMaxWidth: 22,
      itemStyle: { color: t.series, borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: t.text, fontSize: 12, formatter: (p) => valueFmt(p.value) } }],
  }, true);
}

function setKpi(id, text) { $(id).textContent = text; }

function render() {
  const f = { m0: +$("m0").value, m1: +$("m1").value, state: $("state").value === "" ? null : +$("state").value };
  if (f.m0 > f.m1) { [f.m0, f.m1] = [f.m1, f.m0]; $("m0").value = f.m0; $("m1").value = f.m1; }
  const r = compute(data, f);
  const k = r.kpi, t = theme();

  setKpi("k-productSales", num(fmtInt)(k.productSales));
  setKpi("k-salesOrders", num(fmtInt)(k.salesOrders));
  setKpi("k-averageOrderValue", num(fmt2)(k.averageOrderValue));
  setKpi("k-customers", num(fmtInt)(k.customers));
  setKpi("k-customers2", num(fmtInt)(k.customers));
  setKpi("k-deliveredOrders", num(fmtInt)(k.deliveredOrders));
  setKpi("k-avgDeliveryDays", num(fmt1)(k.avgDeliveryDays));
  setKpi("k-lateDeliveryRate", pct(k.lateDeliveryRate));
  setKpi("k-avgReviewScore", num(fmt2)(k.avgReviewScore));
  setKpi("k-repeatCustomerRate", pct(k.repeatCustomerRate));
  setKpi("k-itemsSold", num(fmtInt)(k.itemsSold));
  setKpi("k-avgItemPrice", num(fmt2)(k.avgItemPrice));

  const states = r.states;
  const top = (key, n, dir = -1) => states.filter((s) => s[key] != null && (key !== "salesOrders" || s[key] > 0))
    .sort((a, b) => dir * (a[key] - b[key])).slice(0, n);

  if (page === "sales") {
    lineChart("c-salesMonth", r.salesByMonth.months, r.salesByMonth.values, t, num(fmtInt), compact);
    const os = top("salesOrders", 12);
    columnChart("c-ordersState", os.map((s) => s.name), os.map((s) => s.salesOrders), t, num(fmtInt), compact);
    const cats = r.categories.slice(0, 15);
    barChart("c-salesCategory", cats.map((c) => c.name), cats.map((c) => c.productSales), t, num(fmtInt), compact);
  } else if (page === "delivery") {
    columnChart("c-deliveredMonth", r.deliveryByMonth.months, r.deliveryByMonth.delivered, t, num(fmtInt), compact);
    lineChart("c-lateMonth", r.deliveryByMonth.months, r.deliveryByMonth.lateRate, t, pct, (v) => `${Math.round(v * 100)}%`);
    const slow = top("avgDeliveryDays", 12);
    barChart("c-daysState", slow.map((s) => s.name), slow.map((s) => s.avgDeliveryDays), t, num(fmt1), (v) => v);
    const rv = r.reviewByStatus.filter((x) => x.n > 0);
    columnChart("c-reviewStatus", rv.map((x) => x.name), rv.map((x) => x.avg), t, num(fmt2), (v) => v);
    chart("c-reviewStatus").setOption({ yAxis: { min: 0, max: 5 } });
  } else {
    const totalPay = r.payments.reduce((a, p) => a + p.value, 0);
    const pays = [...r.payments].sort((a, b) => b.value - a.value);
    barChart("c-payments", pays.map((p) => p.name), pays.map((p) => p.value / totalPay), t, pct, (v) => `${Math.round(v * 100)}%`);
    const cs = top("customers", 12);
    barChart("c-customersState", cs.map((s) => s.name), cs.map((s) => s.customers), t, num(fmtInt), compact);
    renderTable(r);
  }
}

const TOP_CATEGORIES = 20;
let showAllCategories = false;

function renderTable(r) {
  const shown = showAllCategories ? r.categories : r.categories.slice(0, TOP_CATEGORIES);
  const rows = shown.map((c) => `<tr><td>${c.name}</td><td>${fmtInt.format(c.itemsSold)}</td>
    <td>${fmtInt.format(c.productSales)}</td><td>${num(fmt2)(c.avgItemPrice)}</td><td>${num(fmt2)(c.orderReviewScore)}</td></tr>`);
  document.querySelector("#t-categories tbody").innerHTML = rows.join("");
  const more = $("more");
  more.hidden = r.categories.length <= TOP_CATEGORIES;
  more.textContent = showAllCategories ? `Show top ${TOP_CATEGORIES}` : `Show all ${r.categories.length} categories`;
  const k = r.kpi;
  document.querySelector("#t-categories tfoot").innerHTML = `<tr><td>Total</td><td>${fmtInt.format(k.itemsSold)}</td>
    <td>${fmtInt.format(k.productSales)}</td><td>${num(fmt2)(k.avgItemPrice)}</td><td>${num(fmt2)(k.orderReviewScoreAllCategories)}</td></tr>`;
}

function showPage(name) {
  page = name;
  document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll("[data-page]").forEach((s) => { s.hidden = s.dataset.page !== name; });
  render();
  Object.values(charts).forEach((c) => c.resize());
}

function fillFilters() {
  const opt = (v, label) => `<option value="${v}">${label}</option>`;
  $("m0").innerHTML = data.months.map((m, i) => opt(i, m)).join("");
  $("m1").innerHTML = $("m0").innerHTML;
  $("state").innerHTML = opt("", "All states") + data.states.map((s, i) => opt(i, s)).join("");
  reset();
}

function reset() {
  $("m0").value = 0; $("m1").value = data.months.length - 1; $("state").value = "";
}

async function main() {
  data = index(await (await fetch("data.json")).json());
  $("generated").textContent = data.meta.generated_at_utc;
  fillFilters();
  ["m0", "m1", "state"].forEach((id) => $(id).addEventListener("change", render));
  $("reset").addEventListener("click", () => { reset(); render(); });
  $("more").addEventListener("click", () => { showAllCategories = !showAllCategories; render(); });
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => showPage(b.dataset.tab)));
  window.addEventListener("resize", () => Object.values(charts).forEach((c) => c.resize()));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  showPage("sales");
}

main().catch((e) => {
  document.querySelector("main").innerHTML = `<p>Could not load the data: ${e.message}</p>`;
});
