import React, { useState } from "react";
import { updateTransaction } from "../api.js";

// Add/remove multiple manual tags on a transaction. Tag edits are independent
// of categorization (they don't mark the txn reviewed). Used by the drilldown
// and the review queue.
export default function TagEditor({ txn, onSaved }) {
  const [tags, setTags] = useState(txn.tags || []);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);

  async function commit(next) {
    setSaving(true);
    try {
      const res = await updateTransaction(txn.txn_id, { tags: next });
      setTags(res.tags || next);
      onSaved && onSaved();
    } catch (err) {
      alert("Could not save tags: " + err.message);
    } finally {
      setSaving(false);
    }
  }

  function addTag() {
    const t = input.trim();
    if (!t || tags.includes(t)) {
      setInput("");
      return;
    }
    const next = [...tags, t];
    setInput("");
    commit(next);
  }

  function removeTag(t) {
    commit(tags.filter((x) => x !== t));
  }

  return (
    <div className="tags">
      {tags.map((t) => (
        <span className="tag-chip" key={t}>
          {t}
          <button
            className="tag-remove"
            disabled={saving}
            onClick={() => removeTag(t)}
            title="Remove tag"
          >
            ×
          </button>
        </span>
      ))}
      <input
        className="tag-input"
        value={input}
        placeholder="+ tag"
        disabled={saving}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") addTag();
        }}
        onBlur={addTag}
      />
    </div>
  );
}
