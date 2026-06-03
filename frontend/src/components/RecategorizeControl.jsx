import React, { useState } from "react";
import { updateTransaction, createRule } from "../api.js";

// Category + subcategory dropdowns with a Save button. Saving recategorizes the
// transaction (marks it reviewed, stamps category_source='manual').
//
// Props:
//   txn        - the transaction being edited
//   taxonomy   - { category: [subcategory, ...] }
//   onSaved    - called after a successful save
//   allowRule  - when true, show an "also create a rule" checkbox. If checked,
//                a successful save also POSTs a merchant rule so the same
//                merchant auto-categorizes on the next import.
export default function RecategorizeControl({ txn, taxonomy, onSaved, allowRule }) {
  const [category, setCategory] = useState(txn.category || "");
  const [subcategory, setSubcategory] = useState(txn.subcategory || "");
  const [makeRule, setMakeRule] = useState(false);
  const [saving, setSaving] = useState(false);

  const categories = Object.keys(taxonomy || {});
  const subs = taxonomy?.[category] || [];

  const changed =
    category !== (txn.category || "") ||
    subcategory !== (txn.subcategory || "");

  async function save() {
    setSaving(true);
    try {
      await updateTransaction(txn.txn_id, { category, subcategory });
      if (allowRule && makeRule && txn.merchant_norm) {
        await createRule({
          merchantNorm: txn.merchant_norm,
          category,
          subcategory,
          matchDetail: txn.merchant_detail || undefined,
        });
      }
      onSaved && onSaved();
    } catch (err) {
      alert("Could not save: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="recat">
      <select
        value={category}
        onChange={(e) => {
          setCategory(e.target.value);
          setSubcategory("");
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
        value={subcategory}
        onChange={(e) => setSubcategory(e.target.value)}
      >
        <option value="">— subcategory —</option>
        {subs.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <button
        disabled={!changed || !category || !subcategory || saving}
        onClick={save}
      >
        {saving ? "..." : "Save"}
      </button>
      {allowRule && (
        <label className="rule-check" title="Also create a rule so this merchant auto-categorizes next time">
          <input
            type="checkbox"
            checked={makeRule}
            disabled={saving}
            onChange={(e) => setMakeRule(e.target.checked)}
          />
          rule
        </label>
      )}
    </div>
  );
}
