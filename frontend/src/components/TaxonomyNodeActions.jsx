import React, { useState } from "react";

// Per-row action controls + inline confirm dialogs for a taxonomy node
// (a category or a subcategory). Keeps TaxonomyPage lean.
//
// Props:
//   node       - { category, subcategory?, txn_count, rule_count }
//   isCategory - true for a category row, false for a subcategory row
//   siblings   - array of sibling names to merge into (category names, or
//                subcategory names within the same parent)
//   categories - all category names (subcategory "move" target list)
//   onRename(newName)
//   onMove(newCategory)            (subcategory only)
//   onMerge(intoName)
//   onDelete()
//   busy       - disables controls while a mutation is in flight
function affectsLabel(node) {
  return `affects ${node.txn_count} transaction${node.txn_count === 1 ? "" : "s"}, ` +
    `${node.rule_count} rule${node.rule_count === 1 ? "" : "s"}`;
}

export default function TaxonomyNodeActions({
  node,
  isCategory,
  siblings = [],
  categories = [],
  onRename,
  onMove,
  onMerge,
  onDelete,
  busy,
}) {
  // mode: null | "rename" | "move" | "merge" | "delete"
  const [mode, setMode] = useState(null);
  const [text, setText] = useState("");
  const [target, setTarget] = useState("");

  const name = isCategory ? node.category : node.subcategory;
  const hasData = node.txn_count > 0 || node.rule_count > 0;
  const close = () => {
    setMode(null);
    setText("");
    setTarget("");
  };

  function openRename() {
    setText(name);
    setMode("rename");
  }

  function confirmRename() {
    const v = text.trim();
    if (v && v !== name) onRename(v);
    close();
  }

  function confirmMove() {
    if (target && target !== node.category) onMove(target);
    close();
  }

  function confirmMerge() {
    if (target) onMerge(target);
    close();
  }

  function confirmDelete() {
    onDelete();
    close();
  }

  if (mode === "rename") {
    return (
      <div className="confirm">
        <input
          className="tag-input"
          style={{ width: 160 }}
          autoFocus
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && confirmRename()}
        />
        <button onClick={confirmRename} disabled={busy}>Save</button>
        <button className="ghost" onClick={close} disabled={busy}>Cancel</button>
      </div>
    );
  }

  if (mode === "move") {
    const opts = categories.filter((c) => c !== node.category);
    return (
      <div className="confirm">
        <span className="confirm-text">Move to</span>
        <select value={target} disabled={busy} onChange={(e) => setTarget(e.target.value)}>
          <option value="">— parent —</option>
          {opts.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <button onClick={confirmMove} disabled={busy || !target}>Move</button>
        <button className="ghost" onClick={close} disabled={busy}>Cancel</button>
      </div>
    );
  }

  if (mode === "merge") {
    const opts = siblings.filter((s) => s !== name);
    return (
      <div className="confirm">
        <span className="confirm-text">Merge {affectsLabel(node)} into</span>
        <select value={target} disabled={busy} onChange={(e) => setTarget(e.target.value)}>
          <option value="">— target —</option>
          {opts.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <button onClick={confirmMerge} disabled={busy || !target}>Merge</button>
        <button className="ghost" onClick={close} disabled={busy}>Cancel</button>
      </div>
    );
  }

  if (mode === "delete") {
    return (
      <div className="confirm">
        <span className="confirm-text">
          Delete {isCategory ? "category" : "subcategory"} “{name}”?
        </span>
        <button onClick={confirmDelete} disabled={busy}>Delete</button>
        <button className="ghost" onClick={close} disabled={busy}>Cancel</button>
      </div>
    );
  }

  // Default: the action button group.
  return (
    <div className="tax-actions">
      <button className="ghost" onClick={openRename} disabled={busy}>Rename</button>
      {!isCategory && (
        <button className="ghost" onClick={() => setMode("move")} disabled={busy}>
          Move
        </button>
      )}
      <button
        className="ghost"
        onClick={() => setMode("merge")}
        disabled={busy || siblings.filter((s) => s !== name).length === 0}
      >
        Merge
      </button>
      <button
        className="ghost danger"
        onClick={() => setMode("delete")}
        disabled={busy || hasData}
        title={hasData ? `Has data (${affectsLabel(node)}) — merge instead` : "Delete"}
      >
        Delete
      </button>
    </div>
  );
}
