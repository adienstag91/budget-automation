import React, { useEffect, useState, useCallback } from "react";
import {
  fetchTransactions,
  fetchTaxonomy,
  fmtCurrency,
  recategorizeReviewQueue,
} from "./api.js";
import RecategorizeControl from "./components/RecategorizeControl.jsx";
import TagEditor from "./components/TagEditor.jsx";

// The needs-review worklist. Lists every transaction flagged needs_review
// (both income and expense), and lets you recategorize each one inline.
// Saving marks the txn reviewed, so it drops out of the list and the count
// shrinks -- this is the core feedback loop.
export default function ReviewQueuePage({ onCountChange }) {
  const [txns, setTxns] = useState([]);
  const [taxonomy, setTaxonomy] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [rerunning, setRerunning] = useState(false);
  const [rerunMsg, setRerunMsg] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchTransactions({ needsReview: true, limit: 1000 })
      .then((data) => {
        const rows = data.transactions || [];
        setTxns(rows);
        onCountChange && onCountChange(rows.length);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [onCountChange]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    fetchTaxonomy()
      .then((data) => setTaxonomy(data))
      .catch(() => setTaxonomy({}));
  }, []);

  // Re-run the whole queue through rules + LLM. High-confidence results clear
  // out of the queue; the rest get a suggestion filled in but stay flagged.
  async function handleRerun() {
    setRerunning(true);
    setRerunMsg(null);
    setError(null);
    try {
      const r = await recategorizeReviewQueue();
      setRerunMsg(
        `Re-ran ${r.scanned}: ${r.cleared} cleared, ` +
          `${r.still_flagged} still need confirmation, ` +
          `${r.unresolved} still unplaced ` +
          `(${r.rule_matched} rule, ${r.llm_matched} LLM).`
      );
      load(); // refresh the list + badge
    } catch (err) {
      setError(err.message);
    } finally {
      setRerunning(false);
    }
  }

  // Drop a row locally after it's been categorized (it's now reviewed).
  function removeRow(txnId) {
    setTxns((prev) => {
      const next = prev.filter((t) => t.txn_id !== txnId);
      onCountChange && onCountChange(next.length);
      return next;
    });
  }

  const total = txns.reduce((s, t) => s + t.amount, 0);

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Review Queue</h1>
        <button
          className="stat"
          onClick={handleRerun}
          disabled={rerunning || loading || txns.length === 0}
          title="Re-categorize every queued transaction through rules + the LLM"
          style={{
            cursor: rerunning || txns.length === 0 ? "default" : "pointer",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "5px 10px",
            background: "#fff",
          }}
        >
          {rerunning ? "Re-running…" : "↻ Re-run through LLM"}
        </button>
        <div className="spacer" />
        <div className="stat">
          <b>{txns.length}</b> to clear · {fmtCurrency(total)}
        </div>
      </div>

      {rerunMsg && (
        <div
          className="stat"
          style={{ margin: "0 16px 8px", color: "var(--muted)" }}
        >
          {rerunMsg}
        </div>
      )}

      <div className="content">
        <div className="review-wrap">
          {loading && <div className="loading">Loading review queue…</div>}
          {error && <div className="error">{error}</div>}
          {!loading && !error && txns.length === 0 && (
            <div className="empty">All caught up — nothing to review. 🎉</div>
          )}
          {!loading &&
            !error &&
            txns.map((t) => (
              <div className="review-row" key={t.txn_id}>
                <div className="txn-top">
                  <span className="merchant">
                    {t.merchant_norm}
                    {t.merchant_detail ? ` · ${t.merchant_detail}` : ""}
                    <span
                      className={
                        "dir-badge " +
                        (t.direction === "credit"
                          ? "badge-income"
                          : "badge-expense")
                      }
                    >
                      {t.direction === "credit" ? "income" : "expense"}
                    </span>
                  </span>
                  <span className="amount">{fmtCurrency(t.amount)}</span>
                </div>
                <div className="meta">
                  {t.txn_date}
                  {t.description_raw ? ` · ${t.description_raw}` : ""}
                </div>
                <RecategorizeControl
                  txn={t}
                  taxonomy={taxonomy}
                  allowRule
                  onSaved={() => removeRow(t.txn_id)}
                />
                <TagEditor txn={t} />
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
