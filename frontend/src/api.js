// Thin API client for the FastAPI backend (api.py).
// All calls go through the Vite proxy (/api -> localhost:8000),
// so no backend URL is hardcoded here.

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Request failed (${res.status}): ${text || url}`);
  }
  return res.json();
}

// Pivot table data: categories -> subcategories -> { month: amount }
// view: "expense" (default, drops transfers) | "income" | "all" (raw, no flag filter)
export function fetchPivot({ monthsLimit = 12, startDate, endDate, view = "expense" } = {}) {
  const params = new URLSearchParams({
    include_subcategories: "true",
    months_limit: String(monthsLimit),
    view,
  });
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  return getJSON(`/api/pivot?${params.toString()}`);
}

// Individual transactions. Used by the drilldown panel, the review queue, and
// the Transactions cleanup page.
// direction: "debit" | "credit" | undefined (both). needsReview: filter the queue.
// search: free text (merchant/description/notes). tag: exact tag match.
// dateFrom/dateTo: "YYYY-MM-DD". amountMin/amountMax: filter the (positive)
// dollar magnitude. sortBy/sortDir/offset: paging + ordering.
// Returns { transactions, total_count, count, limit, offset }.
export function fetchTransactions({
  category,
  subcategory,
  month,
  direction,
  needsReview,
  search,
  tag,
  categorySource,
  dateFrom,
  dateTo,
  amountMin,
  amountMax,
  sortBy = "txn_date",
  sortDir = "desc",
  limit = 200,
  offset = 0,
} = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (category) params.set("category", category);
  if (subcategory) params.set("subcategory", subcategory);
  if (month) params.set("month", month);
  if (direction) params.set("direction", direction);
  if (needsReview != null) params.set("needs_review", String(needsReview));
  if (search) params.set("merchant_search", search);
  if (tag) params.set("tag", tag);
  if (categorySource) params.set("category_source", categorySource);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (amountMin != null && amountMin !== "")
    params.set("amount_min", String(amountMin));
  if (amountMax != null && amountMax !== "")
    params.set("amount_max", String(amountMax));
  if (offset) params.set("offset", String(offset));
  params.set("sort_by", sortBy);
  params.set("sort_dir", sortDir);
  return getJSON(`/api/transactions?${params.toString()}`);
}

// Recategorize many transactions at once (Transactions cleanup page).
// Returns { updated }.
export function bulkRecategorize(txnIds, { category, subcategory }) {
  return sendJSON(`/api/transactions/bulk-recategorize`, "POST", {
    txn_ids: txnIds,
    category,
    subcategory: subcategory || null,
  });
}

// Full taxonomy: { category: [subcategory, ...] }
export function fetchTaxonomy() {
  return getJSON(`/api/subcategories`);
}

// Dashboard/queue stats: { needs_review, categorized, total_transactions, ... }
export function fetchStats() {
  return getJSON(`/api/stats`);
}

// Update a single transaction's category/subcategory/notes/date and/or tags.
// category/subcategory/notes/txnDate go as query params; tags (an array) goes as
// the JSON body. Sending tags or txnDate alone does NOT recategorize the txn.
export async function updateTransaction(
  txnId,
  { category, subcategory, notes, txnDate, tags } = {}
) {
  const params = new URLSearchParams();
  if (category != null) params.set("category", category);
  if (subcategory != null) params.set("subcategory", subcategory);
  if (notes != null) params.set("notes", notes);
  if (txnDate != null) params.set("txn_date", txnDate);

  const opts = { method: "PUT" };
  if (tags != null) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(tags);
  }

  const res = await fetch(`/api/transactions/${txnId}?${params.toString()}`, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Update failed (${res.status}): ${text}`);
  }
  return res.json();
}

// Re-run the whole needs-review queue through rules + LLM. Returns
// { scanned, rule_matched, llm_matched, cleared, still_flagged, unresolved }.
export function recategorizeReviewQueue() {
  return sendJSON(`/api/transactions/recategorize-review`, "POST", {});
}

// Create a categorization rule (writes to merchant_rules).
export async function createRule({
  merchantNorm,
  category,
  subcategory,
  matchDetail,
}) {
  const params = new URLSearchParams({
    merchant_norm: merchantNorm,
    category,
    subcategory,
  });
  if (matchDetail) params.set("match_detail", matchDetail);
  const res = await fetch(`/api/rules?${params.toString()}`, {
    method: "POST",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Create rule failed (${res.status}): ${text}`);
  }
  return res.json();
}

// ===== Import (Chase CSV) + Amazon enrichment =====
// Uploads use FormData, not the JSON helpers above.

async function postForm(url, formData) {
  const res = await fetch(url, { method: "POST", body: formData });
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

// Parse + categorize a Chase CSV and return a preview (writes nothing).
export function importPreview(file, { accountId, useLlm = false } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  if (accountId != null) fd.append("account_id", String(accountId));
  fd.append("use_llm", String(useLlm));
  return postForm(`/api/import/preview`, fd);
}

// Commit the kept rows from a preview (no re-LLM; re-validated server-side).
export function importCommit(rows) {
  return sendJSON(`/api/import/commit`, "POST", { rows });
}

// Stage an Amazon order-history CSV into amazon_orders_raw.
export function amazonImport(file) {
  const fd = new FormData();
  fd.append("file", file);
  return postForm(`/api/amazon/import`, fd);
}

// Latest transaction/order date we already hold, per import type.
// { chase: [{account_id, account_name, account_type, last_txn_date, txn_count}],
//   amazon: {last_order_date, order_count} }
export function importLastDates() {
  return getJSON(`/api/import/last-dates`);
}

// Read-only enrichment plan (matches, line items, txns to supersede).
export function amazonEnrichPreview({ startDate, useLlm = false } = {}) {
  const params = new URLSearchParams({ use_llm: String(useLlm) });
  if (startDate) params.set("start_date", startDate);
  return getJSON(`/api/amazon/enrichment/preview?${params.toString()}`);
}

// Commit enrichment for approved order ids (soft-supersedes matched txns).
export function amazonEnrichCommit(orderIds, { useLlm = false, startDate } = {}) {
  const body = { order_ids: orderIds, use_llm: useLlm };
  if (startDate) body.start_date = startDate;
  return sendJSON(`/api/amazon/enrichment/commit`, "POST", body);
}

// ===== Taxonomy management =====
// Shared helper for the mutating taxonomy endpoints (JSON body in, JSON out,
// API error text surfaced). GET goes through getJSON above.
async function sendJSON(url, method, body) {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

// Full category tree with per-node txn/rule usage counts.
export function fetchTaxonomyTree() {
  return getJSON(`/api/taxonomy/tree`);
}

export function createCategory({ category, isIncome = false, isTransfer = false }) {
  return sendJSON(`/api/taxonomy/categories`, "POST", {
    category,
    is_income: isIncome,
    is_transfer: isTransfer,
  });
}

// Rename and/or set flags/order. Pass newCategory to rename.
export function updateCategory(category, { newCategory, isIncome, isTransfer, displayOrder } = {}) {
  const body = {};
  if (newCategory != null) body.new_category = newCategory;
  if (isIncome != null) body.is_income = isIncome;
  if (isTransfer != null) body.is_transfer = isTransfer;
  if (displayOrder != null) body.display_order = displayOrder;
  return sendJSON(`/api/taxonomy/categories/${encodeURIComponent(category)}`, "PUT", body);
}

export function mergeCategory(category, into) {
  return sendJSON(
    `/api/taxonomy/categories/${encodeURIComponent(category)}/merge`,
    "POST",
    { into }
  );
}

export function deleteCategory(category) {
  return sendJSON(`/api/taxonomy/categories/${encodeURIComponent(category)}`, "DELETE");
}

export function createSubcategory({ category, subcategory }) {
  return sendJSON(`/api/taxonomy/subcategories`, "POST", { category, subcategory });
}

// Rename (same parent) and/or move (new parent).
export function updateSubcategory({ category, subcategory, newCategory, newSubcategory }) {
  const body = { category, subcategory };
  if (newCategory != null) body.new_category = newCategory;
  if (newSubcategory != null) body.new_subcategory = newSubcategory;
  return sendJSON(`/api/taxonomy/subcategories`, "PUT", body);
}

export function mergeSubcategory({ category, subcategory, intoSubcategory, intoCategory }) {
  const body = { category, subcategory, into_subcategory: intoSubcategory };
  if (intoCategory != null) body.into_category = intoCategory;
  return sendJSON(`/api/taxonomy/subcategories/merge`, "POST", body);
}

export function deleteSubcategory({ category, subcategory }) {
  return sendJSON(`/api/taxonomy/subcategories`, "DELETE", { category, subcategory });
}

export function fmtMonthLabel(ym) {
  // "2025-11" -> "Nov 2025"
  const [y, m] = ym.split("-");
  const date = new Date(Number(y), Number(m) - 1, 1);
  return date.toLocaleString("en-US", { month: "short", year: "numeric" });
}

export function fmtCurrency(n) {
  if (n == null) return "";
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
