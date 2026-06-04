import React, { useEffect, useState, useCallback } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  Navigate,
} from "react-router-dom";
import PivotPage from "./PivotPage.jsx";
import ReviewQueuePage from "./ReviewQueuePage.jsx";
import TransactionsPage from "./TransactionsPage.jsx";
import TaxonomyPage from "./TaxonomyPage.jsx";
import ImportPage from "./ImportPage.jsx";
import { fetchStats } from "./api.js";

// Simple placeholder for pages not built yet.
function Placeholder({ name }) {
  return (
    <div className="page">
      <div className="placeholder">
        <h1>{name}</h1>
        <p>Coming soon.</p>
      </div>
    </div>
  );
}

function Sidebar({ reviewCount, onReviewCountChange }) {
  // Refresh the badge whenever the route is the review queue, and on mount.
  const refresh = useCallback(() => {
    fetchStats()
      .then((s) => onReviewCountChange(s.needs_review))
      .catch(() => {});
  }, [onReviewCountChange]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const link = ({ isActive }) => "nav-link" + (isActive ? " active" : "");

  return (
    <nav className="sidebar">
      <div className="sidebar-brand">Budget</div>
      <NavLink to="/dashboard" className={link}>
        Dashboard
      </NavLink>
      <NavLink to="/pivot" className={link}>
        Pivot
      </NavLink>
      <NavLink to="/transactions" className={link}>
        Transactions
      </NavLink>
      <NavLink to="/review" className={link}>
        Review Queue
        {reviewCount > 0 && <span className="nav-badge">{reviewCount}</span>}
      </NavLink>
      <NavLink to="/import" className={link}>
        Import
      </NavLink>

      <div className="sidebar-section">Settings</div>
      <NavLink to="/settings/taxonomy" className={link}>
        Taxonomy
      </NavLink>
    </nav>
  );
}

export default function AppShell() {
  const [reviewCount, setReviewCount] = useState(0);

  // Editing a transaction can clear its needs_review flag, so refresh the badge.
  const refreshReviewCount = useCallback(() => {
    fetchStats()
      .then((s) => setReviewCount(s.needs_review))
      .catch(() => {});
  }, []);

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar
          reviewCount={reviewCount}
          onReviewCountChange={setReviewCount}
        />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/pivot" replace />} />
            <Route path="/pivot" element={<PivotPage />} />
            <Route
              path="/review"
              element={<ReviewQueuePage onCountChange={setReviewCount} />}
            />
            <Route
              path="/dashboard"
              element={<Placeholder name="Dashboard" />}
            />
            <Route
              path="/transactions"
              element={
                <TransactionsPage onReviewMaybeChanged={refreshReviewCount} />
              }
            />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/settings/taxonomy" element={<TaxonomyPage />} />
            <Route path="*" element={<Navigate to="/pivot" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
