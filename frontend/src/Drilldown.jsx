import React, { useEffect, useState } from "react";
import { fetchTransactions, fmtCurrency, fmtMonthLabel } from "./api.js";
import RecategorizeControl from "./components/RecategorizeControl.jsx";
import TagEditor from "./components/TagEditor.jsx";

export default function Drilldown({ selection, taxonomy, onClose, onChanged }) {
  const [txns, setTxns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    fetchTransactions({
      category: selection.category,
      subcategory: selection.subcategory,
      month: selection.month, // when set, scope to that month only
      direction: "debit", // pivot is debit-only; preserve prior behavior
    })
      .then((data) => setTxns(data.transactions || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection.category, selection.subcategory, selection.month]);

  const total = txns.reduce((s, t) => s + t.amount, 0);

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
          {txns.length} charges · {fmtCurrency(total)}
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
                <span className="amount">{fmtCurrency(t.amount)}</span>
              </div>
              <div className="meta">
                {t.txn_date}
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
            </div>
          ))}
      </div>
    </div>
  );
}
