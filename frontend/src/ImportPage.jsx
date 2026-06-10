import React, { useState, useCallback, useEffect } from "react";
import {
  importPreview,
  importCommit,
  amazonImport,
  amazonEnrichPreview,
  amazonEnrichCommit,
  venmoImport,
  venmoEnrichPreview,
  venmoEnrichCommit,
  importLastDates,
  fmtCurrency,
} from "./api.js";

// "2026-02-27" or "2026-01-05T16:09:00" -> "Feb 27, 2026"
function fmtDate(s) {
  if (!s) return null;
  const d = new Date(s.slice(0, 10) + "T00:00:00");
  if (isNaN(d)) return s.slice(0, 10);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// Two-step import + Amazon enrichment under /import.
// Nothing is written to the DB until the user confirms a parsed preview.
export default function ImportPage() {
  const [tab, setTab] = useState("chase");
  const [lastDates, setLastDates] = useState(null);

  const refreshLastDates = useCallback(() => {
    importLastDates()
      .then(setLastDates)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshLastDates();
  }, [refreshLastDates]);

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Import</h1>
        <div className="import-tabs">
          <button
            className={"import-tab" + (tab === "chase" ? " active" : "")}
            onClick={() => setTab("chase")}
          >
            Chase CSV
          </button>
          <button
            className={"import-tab" + (tab === "amazon" ? " active" : "")}
            onClick={() => setTab("amazon")}
          >
            Amazon
          </button>
          <button
            className={"import-tab" + (tab === "venmo" ? " active" : "")}
            onClick={() => setTab("venmo")}
          >
            Venmo
          </button>
        </div>
      </div>
      <div className="content">
        <div className="import-wrap">
          {tab === "chase" && (
            <ChaseImport
              lastDates={lastDates}
              onImported={refreshLastDates}
            />
          )}
          {tab === "amazon" && <AmazonImport lastDates={lastDates} />}
          {tab === "venmo" && (
            <VenmoImport lastDates={lastDates} onImported={refreshLastDates} />
          )}
        </div>
      </div>
    </div>
  );
}

// Latest transaction/order date we already hold, so the user knows where to
// resume uploading. Shows the date of the data itself, not when it was uploaded.
function ChaseLastDates({ lastDates }) {
  if (!lastDates) return null;
  return (
    <div className="import-lastdates">
      <span className="import-lastdates-label">Last imported:</span>
      {lastDates.chase.map((a) => (
        <span key={a.account_id} className="import-lastdates-item">
          {a.account_name}{" "}
          <b>{fmtDate(a.last_txn_date) || "—"}</b>
        </span>
      ))}
    </div>
  );
}

function AmazonLastDates({ lastDates }) {
  if (!lastDates) return null;
  const amz = lastDates.amazon;
  return (
    <div className="import-lastdates">
      <span className="import-lastdates-label">Last order:</span>
      <span className="import-lastdates-item">
        <b>{fmtDate(amz.last_order_date) || "—"}</b>
        {amz.order_count ? ` · ${amz.order_count} orders staged` : ""}
      </span>
    </div>
  );
}

function VenmoLastDates({ lastDates }) {
  if (!lastDates || !lastDates.venmo) return null;
  const vmo = lastDates.venmo;
  return (
    <div className="import-lastdates">
      <span className="import-lastdates-label">Last transaction:</span>
      <span className="import-lastdates-item">
        <b>{fmtDate(vmo.last_txn_date) || "—"}</b>
        {vmo.txn_count ? ` · ${vmo.txn_count} staged` : ""}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chase CSV: upload -> preview (rows + dup flags) -> exclude rows -> commit
// ---------------------------------------------------------------------------
function ChaseImport({ lastDates, onImported }) {
  const [file, setFile] = useState(null);
  const [useLlm, setUseLlm] = useState(false);
  const [preview, setPreview] = useState(null);
  const [excluded, setExcluded] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const runPreview = useCallback(() => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setPreview(null);
    importPreview(file, { useLlm })
      .then((data) => {
        setPreview(data);
        // Default: exclude rows already in the DB (duplicates).
        const dupIdx = new Set(
          data.rows
            .map((r, i) => (r.is_duplicate ? i : -1))
            .filter((i) => i >= 0)
        );
        setExcluded(dupIdx);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [file, useLlm]);

  const toggleRow = (i) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  const runCommit = useCallback(() => {
    if (!preview) return;
    const rows = preview.rows.filter((_, i) => !excluded.has(i));
    if (rows.length === 0) return;
    setBusy(true);
    setError(null);
    importCommit(rows)
      .then((res) => {
        setResult(res);
        setPreview(null);
        onImported && onImported();
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [preview, excluded, onImported]);

  const keptCount = preview ? preview.rows.length - excluded.size : 0;

  return (
    <div>
      <ChaseLastDates lastDates={lastDates} />
      <div className="import-controls">
        <input
          type="file"
          accept=".csv,.CSV"
          onChange={(e) => {
            setFile(e.target.files[0] || null);
            setPreview(null);
            setResult(null);
          }}
        />
        <label className="import-toggle">
          <input
            type="checkbox"
            checked={useLlm}
            onChange={(e) => setUseLlm(e.target.checked)}
          />
          Use LLM for unmatched (costs API credits)
        </label>
        <button className="import-btn" disabled={!file || busy} onClick={runPreview}>
          {busy && !result ? "Working…" : "Preview"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <div className="import-result">
          Imported <b>{result.inserted}</b> · skipped {result.duplicates}{" "}
          duplicates
          {result.errors > 0 ? ` · ${result.errors} errors` : ""}.{" "}
          <a href="/review">Go to Review Queue →</a>
        </div>
      )}

      {preview && (
        <>
          <div className="import-summary">
            <span className="stat">
              {preview.csv_type} · acct {preview.account_id}
            </span>
            <span className="stat">
              parsed <b>{preview.totals.parsed}</b>
            </span>
            <span className="stat">
              new <b>{preview.totals.new}</b>
            </span>
            <span className="stat">
              dup <b>{preview.totals.duplicates}</b>
            </span>
            <span className="stat">
              rules <b>{preview.totals.rule_matched}</b>
            </span>
            <span className="stat">
              llm <b>{preview.totals.llm_matched}</b>
            </span>
            <span className="stat">
              review <b>{preview.totals.needs_review}</b>
            </span>
            <div className="spacer" />
            <button
              className="import-btn"
              disabled={busy || keptCount === 0}
              onClick={runCommit}
            >
              Import {keptCount} transaction{keptCount === 1 ? "" : "s"}
            </button>
          </div>

          <table className="import-table">
            <thead>
              <tr>
                <th>Keep</th>
                <th>Date</th>
                <th>Description</th>
                <th>Category</th>
                <th>Source</th>
                <th className="num">Amount</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((r, i) => (
                <tr
                  key={r.source_row_hash + i}
                  className={excluded.has(i) ? "excluded" : ""}
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={!excluded.has(i)}
                      onChange={() => toggleRow(i)}
                    />
                  </td>
                  <td>{r.txn_date}</td>
                  <td className="desc">{r.description_raw}</td>
                  <td>
                    {r.category}
                    {r.subcategory ? ` / ${r.subcategory}` : ""}
                  </td>
                  <td>
                    <span className={"src-badge src-" + r.category_source}>
                      {r.category_source}
                    </span>
                  </td>
                  <td className="num">{fmtCurrency(r.amount)}</td>
                  <td>
                    {r.is_duplicate ? (
                      <span className="dup-badge">duplicate</span>
                    ) : r.needs_review ? (
                      <span className="review-badge">review</span>
                    ) : (
                      <span className="new-badge">new</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Amazon: upload order CSV -> stage -> preview enrichment -> commit
// ---------------------------------------------------------------------------
function AmazonImport({ lastDates }) {
  const [file, setFile] = useState(null);
  const [useLlm, setUseLlm] = useState(false);
  const [stageResult, setStageResult] = useState(null);
  const [plan, setPlan] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [commitResult, setCommitResult] = useState(null);

  const runStage = useCallback(() => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setStageResult(null);
    amazonImport(file)
      .then((res) => setStageResult(res))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [file]);

  const runPreview = useCallback(() => {
    setBusy(true);
    setError(null);
    setPlan(null);
    setCommitResult(null);
    amazonEnrichPreview({ useLlm })
      .then((data) => {
        setPlan(data);
        // Default: select all matched orders (the safe, expected action).
        setSelected(
          new Set(
            data.orders
              .filter((o) => o.payment_source === "credit_card")
              .map((o) => o.order_id)
          )
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [useLlm]);

  const toggleOrder = (oid) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(oid)) next.delete(oid);
      else next.add(oid);
      return next;
    });
  };

  const runCommit = useCallback(() => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    setBusy(true);
    setError(null);
    amazonEnrichCommit(ids, { useLlm })
      .then((res) => {
        setCommitResult(res);
        setPlan(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [selected, useLlm]);

  return (
    <div>
      <AmazonLastDates lastDates={lastDates} />
      <div className="import-controls">
        <input
          type="file"
          accept=".csv,.CSV"
          onChange={(e) => {
            setFile(e.target.files[0] || null);
            setStageResult(null);
          }}
        />
        <button className="import-btn" disabled={!file || busy} onClick={runStage}>
          Stage orders
        </button>
        <label className="import-toggle">
          <input
            type="checkbox"
            checked={useLlm}
            onChange={(e) => setUseLlm(e.target.checked)}
          />
          Use LLM for product categories
        </label>
        <button className="import-btn" disabled={busy} onClick={runPreview}>
          Preview enrichment
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {stageResult && (
        <div className="import-result">
          Staged <b>{stageResult.inserted}</b> new order items ·{" "}
          {stageResult.already_imported} already imported.
        </div>
      )}

      {commitResult && (
        <div className="import-result">
          Enriched <b>{commitResult.enriched_orders}</b> orders into{" "}
          {commitResult.line_items} line items ·{" "}
          {commitResult.superseded_txns} card txns superseded.
        </div>
      )}

      {plan && (
        <>
          <div className="import-summary">
            <span className="stat">
              orders <b>{plan.totals.orders}</b>
            </span>
            <span className="stat">
              matched <b>{plan.totals.matched}</b>
            </span>
            <span className="stat">
              unmatched <b>{plan.totals.unmatched}</b>
            </span>
            <span className="stat">
              line items <b>{plan.totals.line_items}</b>
            </span>
            <div className="spacer" />
            <button
              className="import-btn"
              disabled={busy || selected.size === 0}
              onClick={runCommit}
            >
              Enrich {selected.size} order{selected.size === 1 ? "" : "s"}
            </button>
          </div>

          <table className="import-table">
            <thead>
              <tr>
                <th>Enrich</th>
                <th>Date</th>
                <th>Order</th>
                <th>Items</th>
                <th className="num">Total</th>
                <th>Match</th>
              </tr>
            </thead>
            <tbody>
              {plan.orders.map((o) => (
                <tr key={o.order_id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(o.order_id)}
                      onChange={() => toggleOrder(o.order_id)}
                    />
                  </td>
                  <td>{(o.order_date || "").slice(0, 10)}</td>
                  <td className="desc">
                    {o.order_id}
                    <div className="order-items">
                      {o.items.map((it, j) => (
                        <div key={j}>
                          {it.product_name.slice(0, 50)} →{" "}
                          {it.category}/{it.subcategory}
                        </div>
                      ))}
                    </div>
                  </td>
                  <td>{o.items.length}</td>
                  <td className="num">{fmtCurrency(o.total)}</td>
                  <td>
                    {o.matched_txn ? (
                      <span className="new-badge">
                        txn {o.matched_txn.txn_id}
                      </span>
                    ) : (
                      <span className="dup-badge">no match</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Venmo: upload statement CSV -> stage -> preview enrichment -> commit
//   - "expand" rows: a generic Chase VENMO CASHOUT credit is soft-superseded and
//     split into detailed VENMO FROM rows (one per matched income payment).
//   - "enrich" rows: a generic Chase VENMO OUTGOING debit is relabeled VENMO TO
//     with the payee + note (in place).
// ---------------------------------------------------------------------------
function VenmoImport({ lastDates, onImported }) {
  const [file, setFile] = useState(null);
  const [stageResult, setStageResult] = useState(null);
  const [plan, setPlan] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [commitResult, setCommitResult] = useState(null);

  const runStage = useCallback(() => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setStageResult(null);
    venmoImport(file)
      .then((res) => {
        setStageResult(res);
        onImported && onImported();
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [file, onImported]);

  const runPreview = useCallback(() => {
    setBusy(true);
    setError(null);
    setPlan(null);
    setCommitResult(null);
    venmoEnrichPreview()
      .then((data) => {
        setPlan(data);
        // Default: select every proposed enrichment.
        setSelected(new Set(data.rows.map((r) => r.key)));
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, []);

  const toggleRow = (key) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const runCommit = useCallback(() => {
    const keys = Array.from(selected);
    if (keys.length === 0) return;
    setBusy(true);
    setError(null);
    venmoEnrichCommit(keys)
      .then((res) => {
        setCommitResult(res);
        setPlan(null);
        onImported && onImported();
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [selected, onImported]);

  return (
    <div>
      <VenmoLastDates lastDates={lastDates} />
      <div className="import-controls">
        <input
          type="file"
          accept=".csv,.CSV"
          onChange={(e) => {
            setFile(e.target.files[0] || null);
            setStageResult(null);
          }}
        />
        <button className="import-btn" disabled={!file || busy} onClick={runStage}>
          Stage transactions
        </button>
        <button className="import-btn" disabled={busy} onClick={runPreview}>
          Preview enrichment
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {stageResult && (
        <div className="import-result">
          Staged <b>{stageResult.inserted}</b> new transaction
          {stageResult.inserted === 1 ? "" : "s"} ·{" "}
          {stageResult.already_imported} already imported
          {stageResult.account_owner ? ` · @${stageResult.account_owner}` : ""}.
        </div>
      )}

      {commitResult && (
        <div className="import-result">
          Expanded <b>{commitResult.expanded_cashouts}</b> cashouts into{" "}
          {commitResult.new_rows} VENMO FROM rows ·{" "}
          {commitResult.enriched_outgoing} outgoing relabeled ·{" "}
          {commitResult.superseded_txns} cashouts superseded.{" "}
          <a href="/review">Go to Review Queue →</a>
        </div>
      )}

      {plan && (
        <>
          <div className="import-summary">
            <span className="stat">
              expansions <b>{plan.totals.expansions}</b>
            </span>
            <span className="stat">
              outgoing <b>{plan.totals.enrich}</b>
            </span>
            <span className="stat">
              new rows <b>{plan.totals.new_rows}</b>
            </span>
            <div className="spacer" />
            <button
              className="import-btn"
              disabled={busy || selected.size === 0}
              onClick={runCommit}
            >
              Apply {selected.size} enrichment{selected.size === 1 ? "" : "s"}
            </button>
          </div>

          {plan.rows.length === 0 ? (
            <div className="empty">
              No unenriched Venmo matches found. Stage a statement CSV first, or
              everything is already enriched.
            </div>
          ) : (
            <table className="import-table">
              <thead>
                <tr>
                  <th>Apply</th>
                  <th>Date</th>
                  <th>Type</th>
                  <th>Detail</th>
                  <th className="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                {plan.rows.map((r) => (
                  <tr key={r.key}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.has(r.key)}
                        onChange={() => toggleRow(r.key)}
                      />
                    </td>
                    <td>{(r.date || "").slice(0, 10)}</td>
                    <td>
                      {r.kind === "expand" ? (
                        <span className="new-badge">cashout → from</span>
                      ) : (
                        <span className="src-badge src-rule">outgoing → to</span>
                      )}
                    </td>
                    <td className="desc">
                      {r.kind === "expand" ? (
                        <>
                          Expand cashout (@{r.venmo_account}) into{" "}
                          {r.income.length} VENMO FROM
                          <div className="order-items">
                            {r.income.map((inc, j) => (
                              <div key={j}>
                                {fmtCurrency(inc.amount)} from {inc.from_name}
                                {inc.note ? ` — ${inc.note.slice(0, 40)}` : ""}
                              </div>
                            ))}
                          </div>
                        </>
                      ) : (
                        <>
                          VENMO TO {r.to_name} (@{r.venmo_account})
                          {r.note ? ` — ${r.note.slice(0, 50)}` : ""}
                        </>
                      )}
                    </td>
                    <td className="num">{fmtCurrency(r.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
