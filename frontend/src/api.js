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
export function fetchPivot({ monthsLimit = 12, startDate, endDate } = {}) {
  const params = new URLSearchParams({
    include_subcategories: "true",
    months_limit: String(monthsLimit),
  });
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  return getJSON(`/api/pivot?${params.toString()}`);
}

// Individual transactions. Used by the drilldown panel and the review queue.
// direction: "debit" | "credit" | undefined (both). needsReview: filter the queue.
export function fetchTransactions({
  category,
  subcategory,
  month,
  direction,
  needsReview,
  limit = 200,
} = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (category) params.set("category", category);
  if (subcategory) params.set("subcategory", subcategory);
  if (month) params.set("month", month);
  if (direction) params.set("direction", direction);
  if (needsReview != null) params.set("needs_review", String(needsReview));
  params.set("sort_by", "txn_date");
  params.set("sort_dir", "desc");
  return getJSON(`/api/transactions?${params.toString()}`);
}

// Full taxonomy: { category: [subcategory, ...] }
export function fetchTaxonomy() {
  return getJSON(`/api/subcategories`);
}

// Dashboard/queue stats: { needs_review, categorized, total_transactions, ... }
export function fetchStats() {
  return getJSON(`/api/stats`);
}

// Update a single transaction's category/subcategory/notes and/or tags.
// category/subcategory/notes go as query params; tags (an array) goes as the
// JSON body. Sending tags alone updates only tags (no recategorization).
export async function updateTransaction(
  txnId,
  { category, subcategory, notes, tags } = {}
) {
  const params = new URLSearchParams();
  if (category != null) params.set("category", category);
  if (subcategory != null) params.set("subcategory", subcategory);
  if (notes != null) params.set("notes", notes);

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
