import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  fetchTransactions,
  fetchTaxonomy,
  bulkRecategorize,
  fmtCurrency,
} from "./api.js";
import RecategorizeControl from "./components/RecategorizeControl.jsx";
import TagEditor from "./components/TagEditor.jsx";
import DateEditControl from "./components/DateEditControl.jsx";
import SqlPeek from "./components/SqlPeek.jsx";

const PAGE_SIZE = 100;

const EMPTY_FILTERS = {
  search: "",
  category: "",
  subcategory: "",
  tag: "",
  direction: "",
  dateFrom: "",
  dateTo: "",
  amountMin: "",
  amountMax: "",
};

// The Transactions cleanup page. Filter / search / sort across every
// transaction, then fix categorization inline (per row) or in bulk (select many
// rows -> apply one category). This is the workhorse for post-import cleanup,
// e.g. a big daycare check a rule mis-filed as Rent.
export default function TransactionsPage({ onReviewMaybeChanged }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [sort, setSort] = useState({ by: "txn_date", dir: "desc" });
  const [offset, setOffset] = useState(0);

  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [taxonomy, setTaxonomy] = useState({});
  const [selected, setSelected] = useState(() => new Set());
  const [expanded, setExpanded] = useState(() => new Set());

  // Bulk action target category/subcategory.
  const [bulkCat, setBulkCat] = useState("");
  const [bulkSub, setBulkSub] = useState("");
  const [applying, setApplying] = useState(false);

  // Debounce the free-text search so we don't fire on every keystroke.
  const [searchInput, setSearchInput] = useState("");
  const debounceRef = useRef(null);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setFilters((f) => ({ ...f, search: searchInput }));
      setOffset(0);
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [searchInput]);

  // Debounce the min/max $ amount inputs the same way (typed values).
  const [amountMinInput, setAmountMinInput] = useState("");
  const [amountMaxInput, setAmountMaxInput] = useState("");
  const amtDebounceRef = useRef(null);
  useEffect(() => {
    if (amtDebounceRef.current) clearTimeout(amtDebounceRef.current);
    amtDebounceRef.current = setTimeout(() => {
      setFilters((f) => ({
        ...f,
        amountMin: amountMinInput,
        amountMax: amountMaxInput,
      }));
      setOffset(0);
    }, 400);
    return () => clearTimeout(amtDebounceRef.current);
  }, [amountMinInput, amountMaxInput]);

  // The exact params behind the current view — reused by the data fetch and by
  // the "Show SQL" peek (with includeSql) so the echoed SQL matches the table.
  const queryParams = useCallback(
    (extra = {}) => ({
      search: filters.search || undefined,
      category: filters.category || undefined,
      subcategory: filters.subcategory || undefined,
      tag: filters.tag || undefined,
      direction: filters.direction || undefined,
      dateFrom: filters.dateFrom || undefined,
      dateTo: filters.dateTo || undefined,
      amountMin: filters.amountMin || undefined,
      amountMax: filters.amountMax || undefined,
      sortBy: sort.by,
      sortDir: sort.dir,
      limit: PAGE_SIZE,
      offset,
      ...extra,
    }),
    [filters, sort, offset]
  );

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchTransactions(queryParams())
      .then((data) => {
        setRows(data.transactions || []);
        setTotal(data.total_count || 0);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [queryParams]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    fetchTaxonomy()
      .then((data) => setTaxonomy(data))
      .catch(() => setTaxonomy({}));
  }, []);

  const categories = Object.keys(taxonomy || {});

  // --- filter helpers ---
  function setFilter(key, value) {
    setFilters((f) => ({ ...f, [key]: value }));
    setOffset(0);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setSearchInput("");
    setAmountMinInput("");
    setAmountMaxInput("");
    setOffset(0);
  }

  function toggleSort(col) {
    setSort((s) =>
      s.by === col
        ? { by: col, dir: s.dir === "asc" ? "desc" : "asc" }
        : { by: col, dir: "asc" }
    );
    setOffset(0);
  }

  function sortCaret(col) {
    if (sort.by !== col) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  // --- selection ---
  function toggleRow(txnId) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(txnId)) next.delete(txnId);
      else next.add(txnId);
      return next;
    });
  }

  const allOnPageSelected =
    rows.length > 0 && rows.every((r) => selected.has(r.txn_id));

  function toggleSelectAll() {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) rows.forEach((r) => next.delete(r.txn_id));
      else rows.forEach((r) => next.add(r.txn_id));
      return next;
    });
  }

  function toggleExpand(txnId) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(txnId)) next.delete(txnId);
      else next.add(txnId);
      return next;
    });
  }

  // --- bulk apply ---
  async function applyBulk() {
    if (!bulkCat || selected.size === 0) return;
    setApplying(true);
    try {
      const ids = Array.from(selected);
      const res = await bulkRecategorize(ids, {
        category: bulkCat,
        subcategory: bulkSub || null,
      });
      setSelected(new Set());
      setBulkCat("");
      setBulkSub("");
      onReviewMaybeChanged && onReviewMaybeChanged();
      load();
      alert(`Updated ${res.updated} transaction(s).`);
    } catch (err) {
      alert("Bulk update failed: " + err.message);
    } finally {
      setApplying(false);
    }
  }

  // After an inline edit, refresh the page and the review badge.
  function afterRowEdit() {
    onReviewMaybeChanged && onReviewMaybeChanged();
    load();
  }

  const pageTotal = rows.reduce((s, t) => s + t.amount, 0);
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + rows.length, total);
  const subOptions = filters.category ? taxonomy[filters.category] || [] : [];
  const bulkSubOptions = bulkCat ? taxonomy[bulkCat] || [] : [];

  return (
    <div className="page">
      <div className="toolbar txn-toolbar">
        <h1>Transactions</h1>
        <input
          className="txn-search"
          type="search"
          placeholder="Search merchant, description, notes… (e.g. venmo, check)"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <label>
          Category
          <select
            value={filters.category}
            onChange={(e) => {
              setFilters((f) => ({
                ...f,
                category: e.target.value,
                subcategory: "",
              }));
              setOffset(0);
            }}
          >
            <option value="">All</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          Subcategory
          <select
            value={filters.subcategory}
            disabled={!filters.category}
            onChange={(e) => setFilter("subcategory", e.target.value)}
          >
            <option value="">All</option>
            {subOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tag
          <input
            type="text"
            placeholder="exact tag"
            value={filters.tag}
            onChange={(e) => setFilter("tag", e.target.value)}
          />
        </label>
        <label>
          Type
          <select
            value={filters.direction}
            onChange={(e) => setFilter("direction", e.target.value)}
          >
            <option value="">All</option>
            <option value="debit">Expense</option>
            <option value="credit">Income</option>
          </select>
        </label>
        <label>
          From
          <input
            type="date"
            value={filters.dateFrom}
            onChange={(e) => setFilter("dateFrom", e.target.value)}
          />
        </label>
        <label>
          To
          <input
            type="date"
            value={filters.dateTo}
            onChange={(e) => setFilter("dateTo", e.target.value)}
          />
        </label>
        <label>
          Min $
          <input
            className="txn-amount"
            type="number"
            min="0"
            step="0.01"
            inputMode="decimal"
            placeholder="0"
            value={amountMinInput}
            onChange={(e) => setAmountMinInput(e.target.value)}
          />
        </label>
        <label>
          Max $
          <input
            className="txn-amount"
            type="number"
            min="0"
            step="0.01"
            inputMode="decimal"
            placeholder="∞"
            value={amountMaxInput}
            onChange={(e) => setAmountMaxInput(e.target.value)}
          />
        </label>
        <button className="txn-clear" onClick={clearFilters}>
          Clear
        </button>
        <div className="spacer" />
        <div className="stat">
          <b>{total.toLocaleString()}</b> match · {fmtCurrency(pageTotal)} on page
        </div>
      </div>

      {selected.size > 0 && (
        <div className="bulk-bar">
          <span className="bulk-count">
            <b>{selected.size}</b> selected
          </span>
          <select
            value={bulkCat}
            onChange={(e) => {
              setBulkCat(e.target.value);
              setBulkSub("");
            }}
          >
            <option value="">— category —</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            value={bulkSub}
            onChange={(e) => setBulkSub(e.target.value)}
            disabled={!bulkCat}
          >
            <option value="">— subcategory —</option>
            {bulkSubOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            className="bulk-apply"
            disabled={!bulkCat || applying}
            onClick={applyBulk}
          >
            {applying ? "Applying…" : `Apply to ${selected.size}`}
          </button>
          <button className="bulk-clear" onClick={() => setSelected(new Set())}>
            Deselect all
          </button>
        </div>
      )}

      <div className="content txn-page-content">
        <div className="grid-wrap">
          {loading && <div className="loading">Loading transactions…</div>}
          {error && <div className="error">{error}</div>}
          {!loading && !error && rows.length === 0 && (
            <div className="empty">No transactions match these filters.</div>
          )}
          {!loading && !error && rows.length > 0 && (
            <table className="txn-table">
              <thead>
                <tr>
                  <th className="col-check">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={toggleSelectAll}
                      title="Select all on this page"
                    />
                  </th>
                  <th
                    className="col-sortable"
                    onClick={() => toggleSort("txn_date")}
                  >
                    Date{sortCaret("txn_date")}
                  </th>
                  <th
                    className="col-sortable"
                    onClick={() => toggleSort("merchant_norm")}
                  >
                    Merchant{sortCaret("merchant_norm")}
                  </th>
                  <th>Description</th>
                  <th
                    className="col-sortable"
                    onClick={() => toggleSort("category")}
                  >
                    Category{sortCaret("category")}
                  </th>
                  <th>Subcategory</th>
                  <th>Tags</th>
                  <th
                    className="col-sortable col-amount"
                    onClick={() => toggleSort("amount")}
                  >
                    Amount{sortCaret("amount")}
                  </th>
                  <th className="col-edit"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => {
                  const isSelected = selected.has(t.txn_id);
                  const isOpen = expanded.has(t.txn_id);
                  return (
                    <React.Fragment key={t.txn_id}>
                      <tr className={isSelected ? "txn-row selected" : "txn-row"}>
                        <td className="col-check">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleRow(t.txn_id)}
                          />
                        </td>
                        <td className="col-date">{t.txn_date}</td>
                        <td className="col-merchant">
                          {t.merchant_norm}
                          {t.merchant_detail ? (
                            <span className="detail"> · {t.merchant_detail}</span>
                          ) : null}
                          {t.needs_review ? (
                            <span className="review-flag" title="Needs review">
                              ⚑
                            </span>
                          ) : null}
                        </td>
                        <td className="col-desc" title={t.description_raw || ""}>
                          {t.description_raw}
                        </td>
                        <td className="col-cat">{t.category}</td>
                        <td className="col-sub">{t.subcategory}</td>
                        <td className="col-tags">
                          {(t.tags || []).map((tg) => (
                            <span className="tag-chip mini" key={tg}>
                              {tg}
                            </span>
                          ))}
                        </td>
                        <td
                          className={
                            "col-amount " +
                            (t.direction === "credit" ? "credit" : "")
                          }
                        >
                          {fmtCurrency(t.amount)}
                        </td>
                        <td className="col-edit">
                          <button
                            className="row-edit-toggle"
                            onClick={() => toggleExpand(t.txn_id)}
                          >
                            {isOpen ? "Close" : "Edit"}
                          </button>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="txn-edit-row">
                          <td colSpan={9}>
                            <div className="txn-edit">
                              <RecategorizeControl
                                txn={t}
                                taxonomy={taxonomy}
                                allowRule
                                onSaved={afterRowEdit}
                              />
                              <div className="txn-edit-meta">
                                <DateEditControl
                                  txn={t}
                                  onSaved={afterRowEdit}
                                />
                                <TagEditor txn={t} onSaved={load} />
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          )}

          {!loading && !error && (
            <SqlPeek
              load={() => fetchTransactions(queryParams({ includeSql: true }))}
            />
          )}
        </div>

        {!error && total > 0 && (
          <div className="txn-pager">
            <button
              disabled={offset === 0 || loading}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              ← Prev
            </button>
            <span className="txn-pager-info">
              {from.toLocaleString()}–{to.toLocaleString()} of{" "}
              {total.toLocaleString()}
            </span>
            <button
              disabled={offset + PAGE_SIZE >= total || loading}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
