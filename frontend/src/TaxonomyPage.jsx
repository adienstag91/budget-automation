import React, { useEffect, useState, useCallback } from "react";
import {
  fetchTaxonomyTree,
  createCategory,
  updateCategory,
  mergeCategory,
  deleteCategory,
  createSubcategory,
  updateSubcategory,
  mergeSubcategory,
  deleteSubcategory,
} from "./api.js";
import TaxonomyNodeActions from "./components/TaxonomyNodeActions.jsx";

// Settings → Taxonomy. Manage the category tree (add / rename / move / merge /
// delete) without SQL. Every structural edit cascades to transactions and
// merchant_rules server-side; here we just re-fetch the tree after each change.
export default function TaxonomyPage() {
  const [categories, setCategories] = useState([]);
  const [expanded, setExpanded] = useState({}); // category -> bool
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Inline "add" inputs.
  const [newCat, setNewCat] = useState("");
  const [addSubFor, setAddSubFor] = useState(null); // category name or null
  const [newSub, setNewSub] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchTaxonomyTree()
      .then((data) => setCategories(data.categories || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Wrap a mutation: set busy, run, re-fetch, surface errors inline.
  const run = useCallback(
    async (fn) => {
      setBusy(true);
      setError(null);
      try {
        await fn();
        const data = await fetchTaxonomyTree();
        setCategories(data.categories || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setBusy(false);
      }
    },
    []
  );

  const catNames = categories.map((c) => c.category);

  function toggle(cat) {
    setExpanded((e) => ({ ...e, [cat]: !e[cat] }));
  }

  function addCategory() {
    const v = newCat.trim();
    if (!v) return;
    run(() => createCategory({ category: v })).then(() => setNewCat(""));
  }

  function addSubcategory(cat) {
    const v = newSub.trim();
    if (!v) return;
    run(() => createSubcategory({ category: cat, subcategory: v })).then(() => {
      setNewSub("");
      setAddSubFor(null);
    });
  }

  return (
    <div className="page">
      <div className="toolbar">
        <h1>Taxonomy</h1>
        <div className="spacer" />
        <label>
          New category
          <input
            value={newCat}
            disabled={busy}
            placeholder="Category name"
            onChange={(e) => setNewCat(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCategory()}
          />
        </label>
        <button
          className="expand-all"
          onClick={addCategory}
          disabled={busy || !newCat.trim()}
        >
          + Add category
        </button>
      </div>

      <div className="content">
        <div className="review-wrap">
          {loading && <div className="loading">Loading taxonomy…</div>}
          {error && <div className="error">{error}</div>}
          {!loading && (
            <div className="tax-tree">
              {categories.map((cat) => {
                const isOpen = !!expanded[cat.category];
                const subNames = cat.subcategories.map((s) => s.subcategory);
                return (
                  <div key={cat.category} className="tax-cat">
                    <div className="tax-cat-row">
                      <button
                        className="caret-btn"
                        onClick={() => toggle(cat.category)}
                        title={isOpen ? "Collapse" : "Expand"}
                      >
                        {isOpen ? "▾" : "▸"}
                      </button>
                      <span className="tax-name">{cat.category}</span>
                      <span className="tax-count">{cat.txn_count} txns</span>
                      {cat.rule_count > 0 && (
                        <span className="tax-count">{cat.rule_count} rules</span>
                      )}
                      {cat.is_income && <span className="tax-flag">income</span>}
                      {cat.is_transfer && <span className="tax-flag">transfer</span>}
                      <div className="spacer" />
                      <TaxonomyNodeActions
                        node={cat}
                        isCategory
                        siblings={catNames}
                        categories={catNames}
                        busy={busy}
                        onRename={(newName) =>
                          run(() =>
                            updateCategory(cat.category, { newCategory: newName })
                          )
                        }
                        onMerge={(into) =>
                          run(() => mergeCategory(cat.category, into))
                        }
                        onDelete={() => run(() => deleteCategory(cat.category))}
                      />
                    </div>

                    {isOpen && (
                      <div className="tax-subs">
                        {cat.subcategories.map((sub) => (
                          <div key={sub.subcategory} className="tax-sub-row">
                            <span className="tax-name sub">{sub.subcategory}</span>
                            <span className="tax-count">{sub.txn_count} txns</span>
                            {sub.rule_count > 0 && (
                              <span className="tax-count">
                                {sub.rule_count} rules
                              </span>
                            )}
                            <div className="spacer" />
                            <TaxonomyNodeActions
                              node={sub}
                              isCategory={false}
                              siblings={subNames}
                              categories={catNames}
                              busy={busy}
                              onRename={(newName) =>
                                run(() =>
                                  updateSubcategory({
                                    category: cat.category,
                                    subcategory: sub.subcategory,
                                    newSubcategory: newName,
                                  })
                                )
                              }
                              onMove={(newCategory) =>
                                run(() =>
                                  updateSubcategory({
                                    category: cat.category,
                                    subcategory: sub.subcategory,
                                    newCategory,
                                  })
                                )
                              }
                              onMerge={(intoSub) =>
                                run(() =>
                                  mergeSubcategory({
                                    category: cat.category,
                                    subcategory: sub.subcategory,
                                    intoSubcategory: intoSub,
                                  })
                                )
                              }
                              onDelete={() =>
                                run(() =>
                                  deleteSubcategory({
                                    category: cat.category,
                                    subcategory: sub.subcategory,
                                  })
                                )
                              }
                            />
                          </div>
                        ))}

                        {addSubFor === cat.category ? (
                          <div className="tax-sub-row">
                            <input
                              className="tag-input"
                              style={{ width: 180 }}
                              autoFocus
                              value={newSub}
                              disabled={busy}
                              placeholder="Subcategory name"
                              onChange={(e) => setNewSub(e.target.value)}
                              onKeyDown={(e) =>
                                e.key === "Enter" && addSubcategory(cat.category)
                              }
                            />
                            <button
                              onClick={() => addSubcategory(cat.category)}
                              disabled={busy || !newSub.trim()}
                            >
                              Add
                            </button>
                            <button
                              className="ghost"
                              onClick={() => {
                                setAddSubFor(null);
                                setNewSub("");
                              }}
                              disabled={busy}
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            className="expand-all add-sub"
                            onClick={() => {
                              setAddSubFor(cat.category);
                              setNewSub("");
                            }}
                            disabled={busy}
                          >
                            + Add subcategory
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
