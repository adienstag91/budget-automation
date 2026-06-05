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

function StatCard({ label, value, tone, onClick }) {
  return (
    <div
      className={
        "dash-card" +
        (tone ? ` ${tone}` : "") +
        (onClick ? " clickable" : "")
      }
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
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchStats(),
      fetchPivot({ monthsLimit: TREND_MONTHS, view: "expense" }),
      fetchTransactions({
        limit: RECENT_LIMIT,
        sortBy: "txn_date",
        sortDir: "desc",
      }),
      importLastDates().catch(() => null), // non-critical
    ])
      .then(([stats, pivot, txns, imports]) => {
        setData({
          stats,
          pivot,
          recent: txns.transactions || [],
          imports,
        });
      })
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Dashboard</h1>
        <div className="spacer" />
        <button className="dash-refresh" onClick={load} disabled={loading}>
          ↻ Refresh
        </button>
      </div>

      <div className="content">
        <div className="dash-body">
          {loading && <div className="loading">Loading dashboard…</div>}
          {error && <div className="error">{error}</div>}
          {!loading && !error && data && (
            <DashboardContent data={data} navigate={navigate} />
          )}
        </div>
      </div>
    </div>
  );
}

function DashboardContent({ data, navigate }) {
  const { stats, pivot, recent, imports } = data;

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
          label="Income (all time)"
          value={fmtCurrency(stats.total_income || 0)}
          tone="pos"
        />
        <StatCard
          label="Expenses (all time)"
          value={fmtCurrency(stats.total_expenses || 0)}
          tone="neg"
        />
        <StatCard
          label="Net (all time)"
          value={fmtCurrency(net)}
          tone={net >= 0 ? "pos" : "neg"}
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
