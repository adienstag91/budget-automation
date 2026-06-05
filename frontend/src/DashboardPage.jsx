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

const TREND_MONTHS = 6;
const TOP_CATEGORIES = 6;
const RECENT_LIMIT = 8;

// Period options for the Income/Expenses/Net cards (counts stay all-time).
// Default is "Last month" — always a complete, populated period (the current
// month is often empty until transactions are imported).
const PERIODS = [
  { key: "last_month", label: "Last month" },
  { key: "this_month", label: "This month" },
  { key: "ytd", label: "Year to date" },
  { key: "all", label: "All time" },
];
const DEFAULT_PERIOD = "last_month";

const pad = (n) => String(n).padStart(2, "0");
const isoLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

// Resolve a period key to {startDate, endDate, label}. Local-time safe (no UTC
// shift). "all" returns undefined bounds (all-time).
function periodRange(key) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const label = (PERIODS.find((p) => p.key === key) || PERIODS[0]).label;
  if (key === "this_month")
    return { startDate: isoLocal(new Date(y, m, 1)), endDate: isoLocal(new Date(y, m + 1, 0)), label };
  if (key === "last_month")
    return { startDate: isoLocal(new Date(y, m - 1, 1)), endDate: isoLocal(new Date(y, m, 0)), label };
  if (key === "ytd")
    return { startDate: isoLocal(new Date(y, 0, 1)), endDate: isoLocal(new Date(y, 11, 31)), label };
  return { startDate: undefined, endDate: undefined, label };
}

// A simple horizontal bar row (label · track · value). Used for the spending
// trend and top-categories sections — no chart library needed.
function BarRow({ label, value, max, onClick }) {
  const pct = max > 0 ? Math.round((Math.abs(value) / max) * 100) : 0;
  return (
    <div
      className={"dash-bar-row" + (onClick ? " clickable" : "")}
      onClick={onClick}
      role={onClick ? "button" : undefined}
    >
      <div className="dash-bar-label">{label}</div>
      <div className="dash-bar-track">
        <div className="dash-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="dash-bar-value">{fmtCurrency(value)}</div>
    </div>
  );
}

function StatCard({ label, value, tone, onClick, dim }) {
  return (
    <div
      className={
        "dash-card" +
        (tone ? ` ${tone}` : "") +
        (onClick ? " clickable" : "")
      }
      style={dim ? { opacity: 0.5 } : undefined}
      onClick={onClick}
      role={onClick ? "button" : undefined}
    >
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null); // period-independent (pivot/recent/imports)
  const [stats, setStats] = useState(null); // all-time counts + period-scoped money
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchPivot({ monthsLimit: TREND_MONTHS, view: "expense" }),
      fetchTransactions({ limit: RECENT_LIMIT, sortBy: "txn_date", sortDir: "desc" }),
      importLastDates().catch(() => null), // non-critical
    ])
      .then(([pivot, txns, imports]) => {
        setData({ pivot, recent: txns.transactions || [], imports });
      })
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }, []);

  const loadStats = useCallback(() => {
    setStatsLoading(true);
    const { startDate, endDate } = periodRange(period);
    fetchStats({ startDate, endDate })
      .then(setStats)
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setStatsLoading(false));
  }, [period]);

  useEffect(() => {
    loadData();
  }, [loadData]);
  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const refresh = () => {
    loadData();
    loadStats();
  };
  const periodLabel = periodRange(period).label;

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
          disabled={loading || statsLoading}
        >
          ↻ Refresh
        </button>
      </div>

      <div className="content">
        <div className="dash-body">
          {loading && !data && <div className="loading">Loading dashboard…</div>}
          {error && <div className="error">{error}</div>}
          {!error && data && stats && (
            <DashboardContent
              data={data}
              stats={stats}
              periodLabel={periodLabel}
              statsLoading={statsLoading}
              navigate={navigate}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function DashboardContent({ data, stats, periodLabel, statsLoading, navigate }) {
  const { pivot, recent, imports } = data;

  const net = (stats.total_income || 0) - (stats.total_expenses || 0);

  // --- Spending trend (last N months from grand_totals) ---
  const months = pivot.months || [];
  const trend = months.map((m) => ({
    month: m,
    amount: pivot.grand_totals?.[m] || 0,
  }));
  const trendMax = Math.max(0, ...trend.map((t) => Math.abs(t.amount)));

  // --- Top categories for the latest month (categories already sorted) ---
  const latestMonth = months[months.length - 1];
  const topCats = (pivot.categories || [])
    .map((c) => ({
      category: c.category,
      amount: latestMonth ? c.monthly_data?.[latestMonth] || 0 : 0,
    }))
    .filter((c) => Math.abs(c.amount) > 0.005)
    .slice(0, TOP_CATEGORIES);
  const topMax = Math.max(0, ...topCats.map((c) => Math.abs(c.amount)));

  return (
    <>
      <div className="dash-cards">
        <StatCard
          label="Transactions"
          value={(stats.total_transactions || 0).toLocaleString()}
        />
        <StatCard
          label="Categorized"
          value={`${Math.round(stats.categorization_rate || 0)}%`}
        />
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
          dim={statsLoading}
        />
        <StatCard
          label={`Expenses · ${periodLabel}`}
          value={fmtCurrency(stats.total_expenses || 0)}
          tone="neg"
          dim={statsLoading}
        />
        <StatCard
          label={`Net · ${periodLabel}`}
          value={fmtCurrency(net)}
          tone={net >= 0 ? "pos" : "neg"}
          dim={statsLoading}
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
                <BarRow
                  key={t.month}
                  label={fmtMonthLabel(t.month)}
                  value={t.amount}
                  max={trendMax}
                />
              ))}
            </div>
          )}
        </section>

        <section className="dash-section">
          <h2>
            Top categories
            {latestMonth && (
              <span className="dash-sub"> · {fmtMonthLabel(latestMonth)}</span>
            )}
          </h2>
          {topCats.length === 0 ? (
            <div className="empty">No spending this month.</div>
          ) : (
            <div className="dash-bars">
              {topCats.map((c) => (
                <BarRow
                  key={c.category}
                  label={c.category}
                  value={c.amount}
                  max={topMax}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="dash-section">
        <h2>Recent transactions</h2>
        {recent.length === 0 ? (
          <div className="empty">No transactions yet.</div>
        ) : (
          <div className="dash-recent">
            {recent.map((t) => (
              <div className="dash-recent-row" key={t.txn_id}>
                <span className="dash-recent-date">{t.txn_date}</span>
                <span className="dash-recent-merchant">
                  {t.merchant_norm}
                  {t.merchant_detail ? (
                    <span className="dash-recent-detail">
                      {" "}
                      · {t.merchant_detail}
                    </span>
                  ) : null}
                </span>
                <span className="dash-recent-cat">
                  {t.category || <em>uncategorized</em>}
                </span>
                <span
                  className={
                    "dash-recent-amt" +
                    (t.direction === "credit" ? " credit" : "")
                  }
                >
                  {t.direction === "credit" ? "+" : "−"}
                  {fmtCurrency(t.amount)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

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
              {" · "}Last Amazon order:{" "}
              <b>{String(imports.amazon.last_order_date).slice(0, 10)}</b>
            </span>
          )}
        </div>
      )}
    </>
  );
}
