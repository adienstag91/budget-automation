import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchStats,
  fetchPivot,
  fetchTransactions,
  importLastDates,
  fmtCurrency,
  fmtMonthLabel,
} from "./api.js";

const TREND_MONTHS = 6; // trailing months for the trend bars + spike baseline
const TOP_CATEGORIES = 6;
const MAJOR_PURCHASES = 6;
const PERIOD_MONTHS = 240; // effectively "all" for period-scoped pivot (bounds drive it)

// Spike/dip thresholds (single-month view): a category must move at least this
// much in BOTH percent and dollars vs its trailing baseline to be flagged.
const MOVE_MIN_PCT = 0.25;
const MOVE_MIN_DOLLARS = 50;
const MOVERS_LIMIT = 4;
const BASELINE_MONTHS = 3;

// Period options for the money cards + insight panels. Counts stay all-time.
// Default "Last month" is always a complete, populated period (the current
// month is often empty until transactions are imported). isMonth picks the
// insight lens: single month => Spikes & Dips; multi-month => Category trends.
const PERIODS = [
  { key: "last_month", label: "Last month", isMonth: true },
  { key: "this_month", label: "This month", isMonth: true },
  { key: "ytd", label: "Year to date", isMonth: false },
  { key: "all", label: "All time", isMonth: false },
];
const DEFAULT_PERIOD = "last_month";

const pad = (n) => String(n).padStart(2, "0");
const isoLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

// Resolve a period key to {startDate, endDate, label, isMonth}. Local-time safe
// (no UTC shift). "all" returns undefined bounds (all-time).
function periodRange(key) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const def = PERIODS.find((p) => p.key === key) || PERIODS[0];
  const base = { label: def.label, isMonth: def.isMonth };
  if (key === "this_month")
    return { ...base, startDate: isoLocal(new Date(y, m, 1)), endDate: isoLocal(new Date(y, m + 1, 0)) };
  if (key === "last_month")
    return { ...base, startDate: isoLocal(new Date(y, m - 1, 1)), endDate: isoLocal(new Date(y, m, 0)) };
  if (key === "ytd")
    return { ...base, startDate: isoLocal(new Date(y, 0, 1)), endDate: isoLocal(new Date(y, 11, 31)) };
  return { ...base, startDate: undefined, endDate: undefined };
}

// --- Insight computations (pure, derived from pivot data) -------------------

// Median of a numeric array (0 if empty). Used for the spike/dip baseline: a
// lumpy recurring category (e.g. rent that double-posts in one month due to a
// month-boundary shift) skews the mean but barely moves the median, so the
// median gives a more representative "typical month".
function median(arr) {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

// Spikes & dips for one target month vs the typical (median) of up to
// BASELINE_MONTHS months before it. Returns null if the target month has no
// data in the pivot.
function computeMovers(pivot, targetMonth) {
  const months = pivot.months || [];
  const idx = months.indexOf(targetMonth);
  if (idx < 0) return null;
  const baselineMonths = months.slice(Math.max(0, idx - BASELINE_MONTHS), idx);

  const movers = (pivot.categories || []).map((c) => {
    const current = c.monthly_data?.[targetMonth] || 0;
    const baseVals = baselineMonths.map((m) => c.monthly_data?.[m] || 0);
    const baseline = median(baseVals);
    const delta = current - baseline;
    const pct = baseline > 0 ? delta / baseline : current > 0 ? Infinity : 0;
    return { category: c.category, current, baseline, delta, pct };
  });

  const spikes = movers
    .filter((m) => m.delta >= MOVE_MIN_DOLLARS && (!isFinite(m.pct) || m.pct >= MOVE_MIN_PCT))
    .sort((a, b) => b.delta - a.delta)
    .slice(0, MOVERS_LIMIT);
  const dips = movers
    .filter((m) => m.delta <= -MOVE_MIN_DOLLARS && m.pct <= -MOVE_MIN_PCT)
    .sort((a, b) => a.delta - b.delta)
    .slice(0, MOVERS_LIMIT);
  return { spikes, dips, baselineMonths };
}

// Per-category trend over a multi-month window: total, avg/month, and direction
// (2nd-half avg vs 1st-half avg). Sorted by total desc.
function computeTrends(pivot) {
  const months = pivot.months || [];
  const n = months.length || 1;
  const half = Math.floor(months.length / 2);
  const firstHalf = months.slice(0, half);
  const secondHalf = months.slice(months.length - half);
  const avgOver = (c, ms) =>
    ms.length ? ms.reduce((s, m) => s + (c.monthly_data?.[m] || 0), 0) / ms.length : 0;

  return (pivot.categories || [])
    .map((c) => {
      const total = c.total ?? Object.values(c.monthly_data || {}).reduce((a, b) => a + b, 0);
      let direction = "flat";
      if (half >= 1) {
        const fa = avgOver(c, firstHalf);
        const sa = avgOver(c, secondHalf);
        if (sa > fa * 1.15) direction = "up";
        else if (sa < fa * 0.85) direction = "down";
      }
      return { category: c.category, total, avg: total / n, direction };
    })
    .filter((c) => Math.abs(c.total) > 0.005)
    .sort((a, b) => b.total - a.total)
    .slice(0, TOP_CATEGORIES);
}

function topCategoriesForPeriod(pivot) {
  return (pivot.categories || [])
    .map((c) => ({
      category: c.category,
      amount: c.total ?? Object.values(c.monthly_data || {}).reduce((a, b) => a + b, 0),
    }))
    .filter((c) => Math.abs(c.amount) > 0.005)
    .sort((a, b) => b.amount - a.amount)
    .slice(0, TOP_CATEGORIES);
}

// --- Small presentational pieces --------------------------------------------

function BarRow({ label, value, max }) {
  const pct = max > 0 ? Math.round((Math.abs(value) / max) * 100) : 0;
  return (
    <div className="dash-bar-row">
      <div className="dash-bar-label">{label}</div>
      <div className="dash-bar-track">
        <div className="dash-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="dash-bar-value">{fmtCurrency(value)}</div>
    </div>
  );
}

function StatCard({ label, value, sub, tone, onClick, dim }) {
  return (
    <div
      className={"dash-card" + (tone ? ` ${tone}` : "") + (onClick ? " clickable" : "")}
      style={dim ? { opacity: 0.5 } : undefined}
      onClick={onClick}
      role={onClick ? "button" : undefined}
    >
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub != null && <div className="dash-card-sub">{sub}</div>}
    </div>
  );
}

function MoverRow({ m, kind }) {
  const up = kind === "up";
  const pctText = !isFinite(m.pct)
    ? "new"
    : `${m.delta >= 0 ? "+" : "−"}${Math.round(Math.abs(m.pct) * 100)}%`;
  return (
    <div className="dash-mover-row">
      <span className="dash-mover-cat">
        <span className={"dash-delta " + (up ? "up" : "down")}>{up ? "↑" : "↓"}</span>{" "}
        {m.category}
      </span>
      <span className="dash-mover-base">vs {fmtCurrency(m.baseline)}/mo</span>
      <span className={"dash-delta " + (up ? "up" : "down")}>
        {m.delta >= 0 ? "+" : "−"}
        {fmtCurrency(Math.abs(m.delta))} ({pctText})
      </span>
    </div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null); // { pivotTrend, imports } — period-independent
  const [periodData, setPeriodData] = useState(null); // { stats, pivotPeriod, majorPurchases }
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [loading, setLoading] = useState(true);
  const [periodLoading, setPeriodLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchPivot({ monthsLimit: TREND_MONTHS, view: "expense" }),
      importLastDates().catch(() => null),
    ])
      .then(([pivotTrend, imports]) => setData({ pivotTrend, imports }))
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }, []);

  const loadPeriod = useCallback(() => {
    setPeriodLoading(true);
    const { startDate, endDate } = periodRange(period);
    Promise.all([
      fetchStats({ startDate, endDate }),
      fetchPivot({ startDate, endDate, view: "expense", monthsLimit: PERIOD_MONTHS }),
      fetchTransactions({
        dateFrom: startDate,
        dateTo: endDate,
        direction: "debit",
        spendingOnly: true,
        sortBy: "amount",
        sortDir: "desc",
        limit: MAJOR_PURCHASES,
      }),
    ])
      .then(([stats, pivotPeriod, txns]) =>
        setPeriodData({ stats, pivotPeriod, majorPurchases: txns.transactions || [] })
      )
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setPeriodLoading(false));
  }, [period]);

  useEffect(() => {
    loadData();
  }, [loadData]);
  useEffect(() => {
    loadPeriod();
  }, [loadPeriod]);

  const refresh = () => {
    loadData();
    loadPeriod();
  };

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Dashboard</h1>
        <label>
          Period
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            {PERIODS.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <div className="spacer" />
        <button
          className="dash-refresh"
          onClick={refresh}
          disabled={loading || periodLoading}
        >
          ↻ Refresh
        </button>
      </div>

      <div className="content">
        <div className="dash-body">
          {loading && !data && <div className="loading">Loading dashboard…</div>}
          {error && <div className="error">{error}</div>}
          {!error && data && periodData && (
            <DashboardContent
              data={data}
              periodData={periodData}
              period={period}
              periodLoading={periodLoading}
              navigate={navigate}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function DashboardContent({ data, periodData, period, periodLoading, navigate }) {
  const { pivotTrend, imports } = data;
  const { stats, pivotPeriod, majorPurchases } = periodData;
  const { label: periodLabel, isMonth, startDate } = periodRange(period);

  const net = (stats.total_income || 0) - (stats.total_expenses || 0);
  const saved = stats.total_savings || 0;
  const savingsRate =
    stats.total_income > 0 && saved > 0
      ? `${Math.round((saved / stats.total_income) * 100)}% of income`
      : undefined;

  // Spending-trend bars (trailing 6 months, period-independent).
  const months = pivotTrend.months || [];
  const trend = months.map((m) => ({ month: m, amount: pivotTrend.grand_totals?.[m] || 0 }));
  const trendMax = Math.max(0, ...trend.map((t) => Math.abs(t.amount)));

  // Adaptive insight panel inputs.
  const targetMonth = startDate ? startDate.slice(0, 7) : null;
  const movers = isMonth ? computeMovers(pivotTrend, targetMonth) : null;
  const trends = !isMonth ? computeTrends(pivotPeriod) : [];

  // Top categories + biggest purchases for the selected period.
  const topCats = topCategoriesForPeriod(pivotPeriod);
  const topMax = Math.max(0, ...topCats.map((c) => Math.abs(c.amount)));

  return (
    <>
      <div className="dash-cards">
        <StatCard label="Transactions" value={(stats.total_transactions || 0).toLocaleString()} />
        <StatCard label="Categorized" value={`${Math.round(stats.categorization_rate || 0)}%`} />
        <StatCard
          label="Needs review"
          value={(stats.needs_review || 0).toLocaleString()}
          tone={stats.needs_review > 0 ? "warn" : undefined}
          onClick={() => navigate("/review")}
        />
        <StatCard
          label={`Income · ${periodLabel}`}
          value={fmtCurrency(stats.total_income || 0)}
          tone="pos"
          dim={periodLoading}
        />
        <StatCard
          label={`Expenses · ${periodLabel}`}
          value={fmtCurrency(stats.total_expenses || 0)}
          tone="neg"
          dim={periodLoading}
        />
        <StatCard
          label={`Saved · ${periodLabel}`}
          value={fmtCurrency(saved)}
          sub={savingsRate}
          tone={saved >= 0 ? "pos" : "neg"}
          dim={periodLoading}
        />
        <StatCard
          label={`Net · ${periodLabel}`}
          value={fmtCurrency(net)}
          tone={net >= 0 ? "pos" : "neg"}
          dim={periodLoading}
        />
      </div>

      <div className="dash-grid">
        <section className="dash-section">
          <h2>Spending trend</h2>
          {trend.length === 0 ? (
            <div className="empty">No spending data yet.</div>
          ) : (
            <div className="dash-bars">
              {trend.map((t) => (
                <BarRow key={t.month} label={fmtMonthLabel(t.month)} value={t.amount} max={trendMax} />
              ))}
            </div>
          )}
        </section>

        {isMonth ? (
          <section className="dash-section">
            <h2>
              Spikes &amp; dips
              {targetMonth && <span className="dash-sub"> · {fmtMonthLabel(targetMonth)} vs typical month</span>}
            </h2>
            {movers === null ? (
              <div className="empty">No data for this month yet.</div>
            ) : movers.spikes.length === 0 && movers.dips.length === 0 ? (
              <div className="empty">Nothing notable — spending was in line with your recent average.</div>
            ) : (
              <div className="dash-movers">
                {movers.spikes.length > 0 && (
                  <div className="dash-mover-group">
                    <div className="dash-mover-head up">Spending up — worth a look</div>
                    {movers.spikes.map((m) => (
                      <MoverRow key={m.category} m={m} kind="up" />
                    ))}
                  </div>
                )}
                {movers.dips.length > 0 && (
                  <div className="dash-mover-group">
                    <div className="dash-mover-head down">Spending down</div>
                    {movers.dips.map((m) => (
                      <MoverRow key={m.category} m={m} kind="down" />
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        ) : (
          <section className="dash-section">
            <h2>
              Category trends<span className="dash-sub"> · {periodLabel}</span>
            </h2>
            {trends.length === 0 ? (
              <div className="empty">No spending in this range.</div>
            ) : (
              <div className="dash-trends">
                {trends.map((c) => (
                  <div className="dash-trend-row" key={c.category}>
                    <span className="dash-trend-cat">{c.category}</span>
                    <span className="dash-trend-avg">{fmtCurrency(c.avg)}/mo</span>
                    <span className={"dash-trend-arrow " + c.direction}>
                      {c.direction === "up" ? "↑" : c.direction === "down" ? "↓" : "→"}
                    </span>
                    <span className="dash-trend-total">{fmtCurrency(c.total)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      <div className="dash-grid">
        <section className="dash-section">
          <h2>
            Top categories<span className="dash-sub"> · {periodLabel}</span>
          </h2>
          {topCats.length === 0 ? (
            <div className="empty">No spending in this range.</div>
          ) : (
            <div className="dash-bars">
              {topCats.map((c) => (
                <BarRow key={c.category} label={c.category} value={c.amount} max={topMax} />
              ))}
            </div>
          )}
        </section>

        <section className="dash-section">
          <h2>
            Major purchases<span className="dash-sub"> · {periodLabel}</span>
          </h2>
          {majorPurchases.length === 0 ? (
            <div className="empty">No purchases in this range.</div>
          ) : (
            <div className="dash-recent">
              {majorPurchases.map((t) => (
                <div className="dash-recent-row" key={t.txn_id}>
                  <span className="dash-recent-date">{t.txn_date}</span>
                  <span className="dash-recent-merchant">
                    {t.merchant_norm}
                    {t.merchant_detail ? (
                      <span className="dash-recent-detail"> · {t.merchant_detail}</span>
                    ) : null}
                  </span>
                  <span className="dash-recent-cat">{t.category || <em>uncategorized</em>}</span>
                  <span className="dash-recent-amt">−{fmtCurrency(t.amount)}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {imports && (
        <div className="dash-footnote">
          {imports.chase && imports.chase.length > 0 && (
            <span>
              Last Chase import:{" "}
              <b>
                {imports.chase
                  .map((a) => a.last_txn_date)
                  .filter(Boolean)
                  .sort()
                  .slice(-1)[0] || "—"}
              </b>
            </span>
          )}
          {imports.amazon && imports.amazon.last_order_date && (
            <span>
              {" · "}Last Amazon order: <b>{String(imports.amazon.last_order_date).slice(0, 10)}</b>
            </span>
          )}
        </div>
      )}
    </>
  );
}
