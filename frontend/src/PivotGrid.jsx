import React, { useMemo, useState, useCallback } from "react";
import { fmtMonthLabel, fmtCurrency } from "./api.js";

// A self-contained pivot table with manual expand/collapse.
// Deliberately does NOT use AG Grid tree/row-grouping (those are Enterprise
// or otherwise unreliable in the Community build). This is a plain table we
// fully control: category rows toggle their subcategory rows open/closed.

function Amount({ value }) {
  const zero = !value;
  return (
    <td className={"cell-amount" + (zero ? " zero" : "")}>
      {zero ? "" : fmtCurrency(Number(value))}
    </td>
  );
}

// A clickable month amount cell on a subcategory row.
// Clicking drills into that specific month so it sums to this cell.
function ClickableAmount({ value, onClick }) {
  const zero = !value;
  return (
    <td
      className={"cell-amount clickable" + (zero ? " zero" : "")}
      onClick={zero ? undefined : onClick}
      title={zero ? "" : "View this month's charges"}
    >
      {zero ? "" : fmtCurrency(Number(value))}
    </td>
  );
}

export default function PivotGrid({ pivot, onDrilldown, selectedKey }) {
  const months = pivot.months;

  // Track which categories are expanded. Default: all collapsed.
  const [expanded, setExpanded] = useState(() => new Set());

  const toggle = useCallback((category) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }, []);

  const allExpanded = expanded.size === pivot.categories.length;

  const toggleAll = useCallback(() => {
    setExpanded((prev) =>
      prev.size === pivot.categories.length
        ? new Set()
        : new Set(pivot.categories.map((c) => c.category))
    );
  }, [pivot.categories]);

  const grandTotal = useMemo(
    () => Object.values(pivot.grand_totals).reduce((s, n) => s + n, 0),
    [pivot.grand_totals]
  );

  return (
    <div className="pivot-scroll">
      <table className="pivot-table">
        <thead>
          <tr>
            <th className="col-label sticky-left">
              <button className="expand-all" onClick={toggleAll}>
                {allExpanded ? "Collapse all" : "Expand all"}
              </button>
            </th>
            {months.map((m) => (
              <th key={m} className="col-amount">
                {fmtMonthLabel(m)}
              </th>
            ))}
            <th className="col-amount col-total">Total</th>
          </tr>
        </thead>
        <tbody>
          {pivot.categories.map((cat) => {
            const isOpen = expanded.has(cat.category);
            return (
              <React.Fragment key={cat.category}>
                {/* Category row */}
                <tr
                  className="row-category"
                  onClick={() => toggle(cat.category)}
                >
                  <td className="col-label sticky-left">
                    <span className="caret">{isOpen ? "▼" : "▶"}</span>
                    {cat.category}
                  </td>
                  {months.map((m) => (
                    <Amount key={m} value={cat.monthly_data[m]} />
                  ))}
                  <td className="cell-amount col-total">
                    {fmtCurrency(cat.total)}
                  </td>
                </tr>

                {/* Subcategory rows (only when expanded). Hide subcategories
                    with no charges in the selected timeframe to reduce noise. */}
                {isOpen &&
                  (cat.subcategories || [])
                    .filter((sub) => sub.total !== 0)
                    .map((sub) => {
                      const key = `${cat.category}|${sub.subcategory}`;
                      const selected = selectedKey === key;
                      return (
                        <tr
                          key={key}
                          className={
                            "row-subcategory" + (selected ? " selected" : "")
                          }
                        >
                          {/* Label click = all charges across the timeframe */}
                          <td
                            className="col-label sticky-left sub clickable"
                            title="View all charges in this timeframe"
                            onClick={() =>
                              onDrilldown({
                                category: cat.category,
                                subcategory: sub.subcategory,
                              })
                            }
                          >
                            {sub.subcategory}
                          </td>
                          {/* Month cell click = just that month's charges */}
                          {months.map((m) => (
                            <ClickableAmount
                              key={m}
                              value={sub.monthly_data[m]}
                              onClick={() =>
                                onDrilldown({
                                  category: cat.category,
                                  subcategory: sub.subcategory,
                                  month: m,
                                })
                              }
                            />
                          ))}
                          <td
                            className="cell-amount col-total clickable"
                            title="View all charges in this timeframe"
                            onClick={() =>
                              onDrilldown({
                                category: cat.category,
                                subcategory: sub.subcategory,
                              })
                            }
                          >
                            {fmtCurrency(sub.total)}
                          </td>
                        </tr>
                      );
                    })}
              </React.Fragment>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="row-grandtotal">
            <td className="col-label sticky-left">GRAND TOTAL</td>
            {months.map((m) => (
              <td key={m} className="cell-amount">
                {fmtCurrency(pivot.grand_totals[m] || 0)}
              </td>
            ))}
            <td className="cell-amount col-total">{fmtCurrency(grandTotal)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
