import React, { useEffect, useState } from "react";
import {
  fetchTransactions,
  fmtCurrency,
  fmtMonthLabel,
  pivotTxnSign,
  isPivotInflow,
} from "./api.js";
import RecategorizeControl from "./components/RecategorizeControl.jsx";
import TagEditor from "./components/TagEditor.jsx";
import DateEditControl from "./components/DateEditControl.jsx";
import ExcludeControl from "./components/ExcludeControl.jsx";

export default function Drilldown({ selection, view, taxonomy, onClose, onChanged }) {
  const [txns, setTxns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    // No direction filter: pivot cells are NET (both directions), so the
    // drilldown must include credits/inflows (refunds, income) too — otherwise
    // positive cash flows are invisible and the total won't match the cell.
    fetchTransactions({
      category: selection.category,
      subcategory: selection.subcategory,
      month: selection.month, // when set, scope to that month only
    })
      .then((data) => setTxns(data.transactions || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection.category, selection.subcategory, selection.month]);

  // Net total, signed to match the pivot cell that was clicked (so this total
  // equals the number in the grid). Inflows render green.
  const total = txns.reduce(
    (s, t) => s + pivotTxnSign(view, t.direction) * t.amount,
    0
  );
  const totalInflow = isPivotInflow(view, total);

  return (
    <div className="drilldown">
      <div className="drilldown-header">
        <button className="close" onClick={onClose}>
          ×
        </button>
        <div className="title">{selection.subcategory}</div>
        <div className="subtitle">
          {selection.category}
          {" · "}
          {selection.month ? fmtMonthLabel(selection.month) : "All in range"}
          {" · "}
          {txns.length} charges ·{" "}
          <span className={totalInflow ? "inflow" : undefined}>
            {fmtCurrency(totalInflow ? Math.abs(total) : total)}
          </span>
        </div>
      </div>
      <div className="drilldown-list">
        {loading && <div className="loading">Loading transactions…</div>}
        {error && <div className="error">{error}</div>}
        {!loading && !error && txns.length === 0 && (
          <div className="empty">No transactions found.</div>
        )}
        {!loading &&
          !error &&
          txns.map((t) => (
            <div className="txn" key={t.txn_id}>
              <div className="txn-top">
                <span className="merchant">
                  {t.merchant_norm}
                  {t.merchant_detail ? ` · ${t.merchant_detail}` : ""}
                </span>
                <span
                  className={
                    "amount" + (t.direction === "credit" ? " inflow" : "")
                  }
                  title={t.direction === "credit" ? "Money in" : "Money out"}
                >
                  {fmtCurrency(t.amount)}
                </span>
              </div>
              <div className="meta">
                <DateEditControl
                  txn={t}
                  onSaved={() => {
                    load();
                    onChanged && onChanged();
                  }}
                />
                {t.notes ? ` · ${t.notes}` : ""}
              </div>
              <RecategorizeControl
                txn={t}
                taxonomy={taxonomy}
                onSaved={() => {
                  load();
                  onChanged && onChanged();
                }}
              />
              <TagEditor txn={t} onSaved={load} />
              <ExcludeControl
                txn={t}
                onSaved={() => {
                  load();
                  onChanged && onChanged();
                }}
              />
            </div>
          ))}
      </div>
    </div>
  );
}
