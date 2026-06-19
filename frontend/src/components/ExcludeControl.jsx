import React, { useState } from "react";
import { updateTransaction } from "../api.js";

// A checkbox to manually exclude a single transaction from the budget — the
// escape hatch for genuine double-counts (a duplicate, a transfer the rules
// missed) that categorization can't express. This is the same flag the
// Venmo/Amazon enrichments set when they supersede a row, so excluded txns
// drop out of pivot/dashboard/stats totals.
//
// NOTE: For whole classes of money-movement (credit-card payments, transfers),
// prefer categorizing to a transfer category instead — that rides the
// category's is_transfer flag and scales without per-row toggling.
//
// Toggling is an immediate save (not tied to the Save button): it's an
// occasional, deliberate action, so it lives in the Edit area rather than the
// always-visible row.
export default function ExcludeControl({ txn, onSaved }) {
  const [excluded, setExcluded] = useState(!!txn.exclude_from_budget);
  const [saving, setSaving] = useState(false);

  async function toggle(next) {
    setExcluded(next); // optimistic
    setSaving(true);
    try {
      await updateTransaction(txn.txn_id, { excludeFromBudget: next });
      onSaved && onSaved();
    } catch (err) {
      setExcluded(!next); // revert on failure
      alert("Could not update budget exclusion: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <label
      className="exclude-check"
      title="Exclude this transaction from budget totals (pivot, dashboard, stats). Use for genuine double-counts; for transfers/payments, categorize to a transfer category instead."
    >
      <input
        type="checkbox"
        checked={excluded}
        disabled={saving}
        onChange={(e) => toggle(e.target.checked)}
      />
      exclude from budget
    </label>
  );
}
