import React, { useState, useCallback } from "react";

// Read-only SQL transparency disclosure.
//
// Each page passes a `load` function that re-fetches that page's data WITH
// `includeSql:true`, mirroring its current filters/sort. Nothing is fetched
// until the user expands, and we only ever DISPLAY the SQL the backend already
// ran (via cursor.mogrify) -- no SQL is executed from here.
//
// The backend returns `sql` as a string (most views) or an array of strings
// (the Rules view runs two queries); both are handled.
export default function SqlPeek({ load, label = "Show SQL" }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sql, setSql] = useState(null); // string | string[]
  const [copied, setCopied] = useState(null); // index of just-copied block

  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    load()
      .then((data) => setSql(data && data.sql != null ? data.sql : null))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [load]);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (sql == null && !loading) run();
  }

  function copy(text, idx) {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(idx);
        setTimeout(() => setCopied((c) => (c === idx ? null : c)), 1200);
      })
      .catch(() => {});
  }

  const blocks = sql == null ? [] : Array.isArray(sql) ? sql : [sql];

  return (
    <div className="sql-peek">
      <button className="sql-peek-toggle ghost" onClick={toggle}>
        {open ? "▾" : "▸"} {label}
      </button>

      {open && (
        <div className="sql-peek-body">
          {loading && <div className="loading">Loading SQL…</div>}
          {error && <div className="error">{error}</div>}
          {!loading && !error && (
            <>
              <div className="sql-peek-actions">
                <button className="ghost" onClick={run} disabled={loading}>
                  ↻ Refresh
                </button>
                <span className="sql-peek-note">
                  Read-only echo of the query that produced this view (parameters
                  inlined). Nothing is executed from here.
                </span>
              </div>
              {blocks.length === 0 && (
                <div className="sql-peek-note">No SQL returned.</div>
              )}
              {blocks.map((block, idx) => (
                <div key={idx} className="sql-block-wrap">
                  <button
                    className="sql-copy ghost"
                    onClick={() => copy(block, idx)}
                  >
                    {copied === idx ? "Copied" : "Copy"}
                  </button>
                  <pre className="sql-block">{block}</pre>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
