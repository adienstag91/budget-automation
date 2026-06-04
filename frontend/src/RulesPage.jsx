import React, { useEffect, useState, useCallback, useMemo } from "react";
import {
  fetchRules,
  fetchTaxonomy,
  createRule,
  updateRule,
  deleteRule,
} from "./api.js";

const MATCH_TYPES = ["exact", "contains", "startswith", "regex"];

const EMPTY_DRAFT = {
  match_type: "exact",
  match_value: "",
  match_detail: "",
  category: "",
  subcategory: "",
  priority: 50,
  notes: "",
};

// Settings → Rules. View / edit / enable-disable / delete the merchant_rules
// that auto-categorize transactions. This is where you fix the *cause* of
// mis-categorizations (e.g. an over-broad "large CHECK → Rent" rule), instead
// of cleaning up symptoms one transaction at a time on the Transactions page.
// All rules load once; filter/sort/search happen client-side (~200 rules).
export default function RulesPage() {
  const [rules, setRules] = useState([]);
  const [taxonomy, setTaxonomy] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const [filters, setFilters] = useState({
    search: "",
    pack: "",
    matchType: "",
    category: "",
    active: "", // "", "active", "inactive"
  });
  const [sort, setSort] = useState({ by: "priority", dir: "asc" });

  const [expandedId, setExpandedId] = useState(null); // rule_id being edited
  const [draft, setDraft] = useState(EMPTY_DRAFT); // edit OR add draft
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchRules()
      .then((data) => setRules(data.rules || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    fetchTaxonomy()
      .then((data) => setTaxonomy(data || {}))
      .catch(() => setTaxonomy({}));
  }, []);

  // Wrap a mutation: set busy, run, re-fetch, surface errors inline.
  const run = useCallback(
    async (fn) => {
      setBusy(true);
      setError(null);
      try {
        await fn();
        const data = await fetchRules();
        setRules(data.rules || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setBusy(false);
      }
    },
    []
  );

  const catNames = Object.keys(taxonomy || {});
  const draftSubs = taxonomy?.[draft.category] || [];

  function setFilter(key, value) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  function clearFilters() {
    setFilters({ search: "", pack: "", matchType: "", category: "", active: "" });
  }

  function toggleSort(col) {
    setSort((s) =>
      s.by === col
        ? { by: col, dir: s.dir === "asc" ? "desc" : "asc" }
        : { by: col, dir: "asc" }
    );
  }

  const sortArrow = (col) =>
    sort.by === col ? (sort.dir === "asc" ? " ▲" : " ▼") : "";

  // Distinct rule packs for the filter dropdown.
  const packs = useMemo(
    () => Array.from(new Set(rules.map((r) => r.rule_pack))).sort(),
    [rules]
  );

  const filtered = useMemo(() => {
    const q = filters.search.trim().toLowerCase();
    let out = rules.filter((r) => {
      if (filters.pack && r.rule_pack !== filters.pack) return false;
      if (filters.matchType && r.match_type !== filters.matchType) return false;
      if (filters.category && r.category !== filters.category) return false;
      if (filters.active === "active" && !r.is_active) return false;
      if (filters.active === "inactive" && r.is_active) return false;
      if (q) {
        const hay = `${r.match_value || ""} ${r.match_detail || ""} ${
          r.notes || ""
        }`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const dir = sort.dir === "asc" ? 1 : -1;
    out = [...out].sort((a, b) => {
      let av = a[sort.by];
      let bv = b[sort.by];
      if (typeof av === "string") av = av.toLowerCase();
      if (typeof bv === "string") bv = bv.toLowerCase();
      if (av == null) av = "";
      if (bv == null) bv = "";
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return (a.rule_id - b.rule_id) * dir;
    });
    return out;
  }, [rules, filters, sort]);

  function startEdit(rule) {
    setAdding(false);
    setExpandedId(rule.rule_id);
    setDraft({
      match_type: rule.match_type || "exact",
      match_value: rule.match_value || "",
      match_detail: rule.match_detail || "",
      category: rule.category || "",
      subcategory: rule.subcategory || "",
      priority: rule.priority ?? 50,
      notes: rule.notes || "",
    });
  }

  function cancelEdit() {
    setExpandedId(null);
    setAdding(false);
    setDraft(EMPTY_DRAFT);
  }

  function startAdd() {
    setExpandedId(null);
    setAdding(true);
    setDraft(EMPTY_DRAFT);
  }

  function toggleActive(rule) {
    run(() => updateRule(rule.rule_id, { is_active: !rule.is_active }));
  }

  function saveEdit(ruleId) {
    const patch = {
      match_type: draft.match_type,
      match_value: draft.match_value.trim(),
      match_detail: draft.match_detail.trim() || null,
      category: draft.category,
      subcategory: draft.subcategory || null,
      priority: Number(draft.priority),
      notes: draft.notes.trim() || null,
    };
    run(() => updateRule(ruleId, patch)).then(() => cancelEdit());
  }

  function saveAdd() {
    run(() =>
      createRule({
        merchantNorm: draft.match_value.trim(),
        category: draft.category,
        subcategory: draft.subcategory,
        matchDetail: draft.match_detail.trim() || undefined,
        matchType: draft.match_type,
        priority: draft.priority,
      })
    ).then(() => cancelEdit());
  }

  function remove(rule) {
    if (
      !window.confirm(
        `Delete rule #${rule.rule_id} (${rule.match_value}${
          rule.match_detail ? " · " + rule.match_detail : ""
        } → ${rule.category}/${rule.subcategory})?`
      )
    )
      return;
    run(() => deleteRule(rule.rule_id));
  }

  // The shared edit/add form (rendered in an expanded row or the add row).
  function draftForm({ onSave, saveLabel }) {
    const valid = draft.match_value.trim() && draft.category;
    return (
      <div className="rule-edit">
        <div className="rule-edit-grid">
          <label>
            Match type
            <select
              value={draft.match_type}
              disabled={busy}
              onChange={(e) => setDraft((d) => ({ ...d, match_type: e.target.value }))}
            >
              {MATCH_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Match value
            <input
              value={draft.match_value}
              disabled={busy}
              placeholder="e.g. AMAZON"
              onChange={(e) =>
                setDraft((d) => ({ ...d, match_value: e.target.value }))
              }
            />
          </label>
          <label>
            Detail (optional)
            <input
              value={draft.match_detail}
              disabled={busy}
              placeholder="e.g. BREADS BAKERY"
              onChange={(e) =>
                setDraft((d) => ({ ...d, match_detail: e.target.value }))
              }
            />
          </label>
          <label>
            Priority
            <input
              type="number"
              className="rule-priority"
              value={draft.priority}
              disabled={busy}
              onChange={(e) =>
                setDraft((d) => ({ ...d, priority: e.target.value }))
              }
            />
          </label>
          <label>
            Category
            <select
              value={draft.category}
              disabled={busy}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  category: e.target.value,
                  subcategory: "",
                }))
              }
            >
              <option value="">—category—</option>
              {catNames.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            Subcategory
            <select
              value={draft.subcategory}
              disabled={busy || !draft.category}
              onChange={(e) =>
                setDraft((d) => ({ ...d, subcategory: e.target.value }))
              }
            >
              <option value="">—subcategory—</option>
              {draftSubs.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="rule-notes">
            Notes
            <input
              value={draft.notes}
              disabled={busy}
              placeholder="Why this rule exists"
              onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
            />
          </label>
        </div>
        <div className="rule-edit-actions">
          <button
            className="bulk-apply"
            onClick={onSave}
            disabled={busy || !valid}
          >
            {saveLabel}
          </button>
          <button className="bulk-clear" onClick={cancelEdit} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="toolbar txn-toolbar">
        <h1>Rules</h1>
        <input
          className="txn-search"
          value={filters.search}
          placeholder="Search match value / detail / notes…"
          onChange={(e) => setFilter("search", e.target.value)}
        />
        <label>
          Pack
          <select
            value={filters.pack}
            onChange={(e) => setFilter("pack", e.target.value)}
          >
            <option value="">All</option>
            {packs.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label>
          Type
          <select
            value={filters.matchType}
            onChange={(e) => setFilter("matchType", e.target.value)}
          >
            <option value="">All</option>
            {MATCH_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Category
          <select
            value={filters.category}
            onChange={(e) => setFilter("category", e.target.value)}
          >
            <option value="">All</option>
            {catNames.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          Active
          <select
            value={filters.active}
            onChange={(e) => setFilter("active", e.target.value)}
          >
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <button className="txn-clear" onClick={clearFilters}>
          Clear
        </button>
        <button className="bulk-apply" onClick={startAdd} disabled={busy}>
          + Add rule
        </button>
        <div className="spacer" />
        <div className="stat">
          <b>{filtered.length}</b> of {rules.length} rules
        </div>
      </div>

      <div className="content txn-page-content">
        <div className="grid-wrap">
          {loading && <div className="loading">Loading rules…</div>}
          {error && <div className="error">{error}</div>}

          {adding && (
            <div className="rule-add-panel">
              <div className="rule-add-title">New rule</div>
              {draftForm({ onSave: saveAdd, saveLabel: "Create rule" })}
            </div>
          )}

          {!loading && !error && (
            <table className="import-table rule-table">
              <thead>
                <tr>
                  <th className="col-check">On</th>
                  <th
                    className="col-sortable num"
                    onClick={() => toggleSort("priority")}
                  >
                    Prio{sortArrow("priority")}
                  </th>
                  <th>Type</th>
                  <th
                    className="col-sortable"
                    onClick={() => toggleSort("match_value")}
                  >
                    Match value{sortArrow("match_value")}
                  </th>
                  <th>Detail</th>
                  <th
                    className="col-sortable"
                    onClick={() => toggleSort("category")}
                  >
                    → Category / Subcategory{sortArrow("category")}
                  </th>
                  <th
                    className="col-sortable num"
                    onClick={() => toggleSort("match_count")}
                    title="Approximate: transactions categorized by any rule into this category/subcategory"
                  >
                    ≈ matches{sortArrow("match_count")}
                  </th>
                  <th>Pack</th>
                  <th className="col-actions">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={9} className="empty">
                      No rules match these filters.
                    </td>
                  </tr>
                )}
                {filtered.map((r) => (
                  <React.Fragment key={r.rule_id}>
                    <tr className={"rule-row" + (r.is_active ? "" : " inactive")}>
                      <td className="col-check">
                        <input
                          type="checkbox"
                          checked={r.is_active}
                          disabled={busy}
                          onChange={() => toggleActive(r)}
                          title={r.is_active ? "Active" : "Inactive"}
                        />
                      </td>
                      <td className="num">{r.priority}</td>
                      <td>
                        <span className="rule-type">{r.match_type}</span>
                      </td>
                      <td className="rule-mval">{r.match_value}</td>
                      <td className="detail">{r.match_detail || "—"}</td>
                      <td>
                        {r.category}
                        {r.subcategory ? (
                          <span className="detail"> / {r.subcategory}</span>
                        ) : (
                          ""
                        )}
                      </td>
                      <td className="num">
                        <span className="match-badge">≈ {r.match_count}</span>
                      </td>
                      <td>
                        <span className="src-badge">{r.rule_pack}</span>
                      </td>
                      <td className="col-actions">
                        <button
                          className="row-edit-toggle"
                          onClick={() =>
                            expandedId === r.rule_id ? cancelEdit() : startEdit(r)
                          }
                          disabled={busy}
                        >
                          {expandedId === r.rule_id ? "Close" : "Edit"}
                        </button>
                        <button
                          className="row-edit-toggle danger"
                          onClick={() => remove(r)}
                          disabled={busy}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                    {expandedId === r.rule_id && (
                      <tr className="txn-edit-row">
                        <td colSpan={9}>
                          {draftForm({
                            onSave: () => saveEdit(r.rule_id),
                            saveLabel: "Save changes",
                          })}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
