import React, { useState } from "react";
import { updateTransaction } from "../api.js";

// Click-to-edit the date of a single transaction. A date edit is NOT a
// recategorization (it doesn't mark the txn reviewed). Used to fix recurring
// bills that posted a day early/late around a month boundary so they land in
// the right month. Renders the date as text until clicked, then a date input
// with Save / Cancel.
export default function DateEditControl({ txn, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(txn.txn_date);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (value === txn.txn_date) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await updateTransaction(txn.txn_id, { txnDate: value });
      setEditing(false);
      onSaved && onSaved();
    } catch (err) {
      alert("Could not change date: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setValue(txn.txn_date);
    setEditing(false);
  }

  if (!editing) {
    return (
      <button
        className="date-edit-trigger"
        title="Click to change the date"
        onClick={() => setEditing(true)}
      >
        {txn.txn_date}
      </button>
    );
  }

  return (
    <span className="date-edit">
      <input
        type="date"
        autoFocus
        value={value}
        disabled={saving}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") cancel();
        }}
      />
      <button onClick={save} disabled={saving}>
        {saving ? "..." : "Save"}
      </button>
      <button className="ghost" onClick={cancel} disabled={saving}>
        Cancel
      </button>
    </span>
  );
}
