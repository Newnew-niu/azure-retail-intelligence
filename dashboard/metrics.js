// KPI calculations for the web dashboard. Pure functions shared by the page (app.js) and the
// tests (tests/dashboard_metrics.mjs), so the numbers shown are the numbers tested.
// Definitions mirror the DAX measures in scripts/build_powerbi_model.py.

const F = {}; // cell field name -> column index, filled by index()

export function index(data) {
  data.cellFields.forEach((name, i) => { F[name] = i; });
  return data;
}

function inFilter(m, s, f) {
  return m >= f.m0 && m <= f.m1 && (f.state === null || s === f.state);
}

const div = (a, b) => (b ? a / b : null);

export function compute(data, f) {
  const nM = data.months.length, nS = data.states.length;
  const zeros = (n) => new Array(n).fill(0);
  const t = Object.fromEntries(data.cellFields.slice(2).map((k) => [k, 0]));
  const byMonth = { sales: zeros(nM), delivered: zeros(nM), late: zeros(nM) };
  const byState = { salesOrders: zeros(nS), delivered: zeros(nS), deliveryDaysX100: zeros(nS) };

  for (const c of data.cells) {
    const m = c[F.m], s = c[F.s];
    if (!inFilter(m, s, f)) continue;
    for (const k of Object.keys(t)) t[k] += c[F[k]];
    byMonth.sales[m] += c[F.salesCents];
    byMonth.delivered[m] += c[F.delivered];
    byMonth.late[m] += c[F.late];
    byState.salesOrders[s] += c[F.salesOrders];
    byState.delivered[s] += c[F.delivered];
    byState.deliveryDaysX100[s] += c[F.deliveryDaysX100];
  }

  // Distinct people and repeat rate: counted per person across the filtered sales orders
  const ordersPerPerson = new Map();
  const peopleByState = Array.from({ length: nS }, () => new Set());
  const P = data.people;
  for (let i = 0; i < P.p.length; i++) {
    if (!inFilter(P.m[i], P.s[i], f)) continue;
    ordersPerPerson.set(P.p[i], (ordersPerPerson.get(P.p[i]) || 0) + 1);
    peopleByState[P.s[i]].add(P.p[i]);
  }
  let repeat = 0;
  for (const n of ordersPerPerson.values()) if (n > 1) repeat++;

  const review = data.deliveryStatuses.map(() => ({ x: 0, n: 0 }));
  for (const [m, s, k, x, n] of data.review) {
    if (inFilter(m, s, f)) { review[k].x += x; review[k].n += n; }
  }

  const cat = data.categories.map(() => ({ items: 0, cents: 0, x: 0, n: 0 }));
  for (const [m, s, k, items, cents, x, n] of data.categories_cells) {
    if (!inFilter(m, s, f)) continue;
    const c = cat[k]; c.items += items; c.cents += cents; c.x += x; c.n += n;
  }

  const pay = data.paymentTypes.map(() => 0);
  for (const [m, s, k, v] of data.payments) if (inFilter(m, s, f)) pay[k] += v;

  const months = data.months.slice(f.m0, f.m1 + 1);
  const pick = (arr) => arr.slice(f.m0, f.m1 + 1);
  const states = data.states.map((name, i) => ({
    name,
    salesOrders: byState.salesOrders[i],
    customers: peopleByState[i].size,
    avgDeliveryDays: div(byState.deliveryDaysX100[i] / 100, byState.delivered[i]),
  }));

  return {
    kpi: {
      productSales: t.salesCents / 100,
      salesOrders: t.salesOrders,
      averageOrderValue: div((t.salesCents + t.freightCents) / 100, t.salesOrdersWithItems),
      customers: ordersPerPerson.size,
      deliveredOrders: t.delivered,
      avgDeliveryDays: div(t.deliveryDaysX100 / 100, t.delivered),
      lateDeliveryRate: div(t.late, t.delivered),
      avgReviewScore: div(t.reviewX100 / 100, t.reviewed),
      repeatCustomerRate: div(repeat, ordersPerPerson.size),
      itemsSold: t.items,
      avgItemPrice: div(t.salesCents / 100, t.items),
      orderReviewScoreAllCategories: div(t.itemOrdersReviewX100 / 100, t.itemOrdersReviewed),
      paymentValue: pay.reduce((a, b) => a + b, 0) / 100,
    },
    salesByMonth: { months, values: pick(byMonth.sales).map((v) => v / 100) },
    deliveryByMonth: {
      months,
      delivered: pick(byMonth.delivered),
      lateRate: pick(byMonth.late).map((v, i) => div(v, pick(byMonth.delivered)[i])),
    },
    states,
    reviewByStatus: data.deliveryStatuses.map((name, i) => ({ name, avg: div(review[i].x / 100, review[i].n), n: review[i].n })),
    categories: data.categories
      .map((name, i) => ({
        name,
        itemsSold: cat[i].items,
        productSales: cat[i].cents / 100,
        avgItemPrice: div(cat[i].cents / 100, cat[i].items),
        orderReviewScore: div(cat[i].x / 100, cat[i].n),
      }))
      .filter((c) => c.itemsSold > 0)
      .sort((a, b) => b.productSales - a.productSales),
    payments: data.paymentTypes.map((name, i) => ({ name, value: pay[i] / 100 })).filter((p) => p.value > 0),
  };
}
