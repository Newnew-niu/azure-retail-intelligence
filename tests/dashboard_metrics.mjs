// Helper for tests/test_dashboard.py: print dashboard/metrics.js results for one filter as JSON.
// usage: node tests/dashboard_metrics.mjs <data.json> <firstMonth> <lastMonth> <state|ALL>
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const [dataPath, first, last, state] = process.argv.slice(2);
const { index, compute } = await import(pathToFileURL(resolve("dashboard/metrics.js")).href);
const data = index(JSON.parse(readFileSync(dataPath, "utf8")));
const filter = {
  m0: data.months.indexOf(first),
  m1: data.months.indexOf(last),
  state: state === "ALL" ? null : data.states.indexOf(state),
};
console.log(JSON.stringify(compute(data, filter)));
