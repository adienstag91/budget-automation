import React, { useEffect, useState, useCallback } from "react";
import PivotGrid from "./PivotGrid.jsx";
import Drilldown from "./Drilldown.jsx";
import { fetchPivot, fetchTaxonomy, fmtCurrency } from "./api.js";

// Resolve a range selection into { monthsLimit, startDate, endDate }
// that the pivot API understands.
function resolveRange(range, custom) {
  const today = new Date();
  const iso = (d) => d.toISOString().slice(0, 10);
  const year = today.getFullYear();

  if (range === "ytd") {
    return {
      monthsLimit: 12,
      startDate: `${year}-01-01`,
      endDate: iso(today),
    };
  }
  if (range === "lastyear") {
    return {
      monthsLimit: 12,
      startDate: `${year - 1}-01-01`,
      endDate: `${year - 1}-12-31`,
    };
  }
  if (range === "custom") {
    return {
      monthsLimit: 240, // effectively no truncation; dates do the filtering
      startDate: custom.start || undefined,
      endDate: custom.end || undefined,
    };
  }
  // "last3" / "last6" / "last12" / "last24"
  const n = Number(range.replace("last", "")) || 6;
  return { monthsLimit: n, startDate: undefined, endDate: undefined };
}

export default function PivotPage() {
  const [range, setRange] = useState("last6");
  const [custom, setCustom] = useState({ start: "", end: "" });
  const [pivot, setPivot] = useState(null);
  const [taxonomy, setTaxonomy] = useState({});
  const [selection, setSelection] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadPivot = useCallback(() => {
    setLoading(true);
    setError(null);
    const { monthsLimit, startDate, endDate } = resolveRange(range, custom);
    fetchPivot({ monthsLimit, startDate, endDate })
      .then((data) => setPivot(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [range, custom]);

  useEffect(() => {
    loadPivot();
  }, [loadPivot]);

  useEffect(() => {
    fetchTaxonomy()
      .then((data) => setTaxonomy(data))
      .catch(() => setTaxonomy({}));
  }, []);

  const grandTotal = pivot
    ? Object.values(pivot.grand_totals).reduce((s, n) => s + n, 0)
    : 0;

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Budget Pivot</h1>
        <label>
          Range
          <select value={range} onChange={(e) => setRange(e.target.value)}>
            <option value="last3">Last 3 months</option>
            <option value="last6">Last 6 months</option>
            <option value="last12">Last 12 months</option>
            <option value="last24">Last 24 months</option>
            <option value="ytd">YTD</option>
            <option value="lastyear">Last Year</option>
            <option value="custom">Custom range</option>
          </select>
        </label>
        {range === "custom" && (
          <>
            <label>
              From
              <input
                type="date"
                value={custom.start}
                onChange={(e) =>
                  setCustom((c) => ({ ...c, start: e.target.value }))
                }
              />
            </label>
            <label>
              To
              <input
                type="date"
                value={custom.end}
                onChange={(e) =>
                  setCustom((c) => ({ ...c, end: e.target.value }))
                }
              />
            </label>
          </>
        )}
        <button
          className="stat"
          onClick={loadPivot}
          style={{ cursor: "pointer", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 10px", background: "#fff" }}
        >
          ↻ Refresh
        </button>
        <div className="spacer" />
        {pivot && (
          <div className="stat">
            Spending shown: <b>{fmtCurrency(grandTotal)}</b> across{" "}
            <b>{pivot.categories.length}</b> categories
          </div>
        )}
      </div>

      <div className="content">
        <div className="grid-wrap">
          {loading && <div className="loading">Loading pivot…</div>}
          {error && (
            <div className="error">
              {error}
              <div style={{ marginTop: 8, color: "var(--muted)" }}>
                Is the API running? Start it with:{" "}
                <code>uvicorn api:app --reload --port 8000</code>
              </div>
            </div>
          )}
          {!loading && !error && pivot && (
            <PivotGrid
              pivot={pivot}
              onDrilldown={setSelection}
              selectedKey={
                selection
                  ? `${selection.category}|${selection.subcategory}`
                  : null
              }
            />
          )}
        </div>

        {selection && (
          <Drilldown
            selection={selection}
            taxonomy={taxonomy}
            onClose={() => setSelection(null)}
            onChanged={loadPivot}
          />
        )}
      </div>
    </div>
  );
}
