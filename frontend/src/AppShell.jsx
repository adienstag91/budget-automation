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
import RulesPage from "./RulesPage.jsx";
import ImportPage from "./ImportPage.jsx";
import DashboardPage from "./DashboardPage.jsx";
import { fetchStats, fetchConfig } from "./api.js";

// Shown only when the backend reports APP_MODE=demo, so the public showcase
// instance is unmistakably fake data (real data lives behind auth elsewhere).
function DemoBanner() {
  return (
    <div
      style={{
        background: "#92400e",
        color: "#fff",
        padding: "6px 16px",
        fontSize: 13,
        fontWeight: 600,
        textAlign: "center",
        letterSpacing: 0.2,
      }}
    >
      Demo — synthetic data. Not real finances.
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
      <NavLink to="/settings/rules" className={link}>
        Rules
      </NavLink>
    </nav>
  );
}

export default function AppShell() {
  const [reviewCount, setReviewCount] = useState(0);
  const [isDemo, setIsDemo] = useState(false);

  // Editing a transaction can clear its needs_review flag, so refresh the badge.
  const refreshReviewCount = useCallback(() => {
    fetchStats()
      .then((s) => setReviewCount(s.needs_review))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchConfig()
      .then((c) => setIsDemo(Boolean(c.demo)))
      .catch(() => {});
  }, []);

  return (
    <BrowserRouter>
      {isDemo && <DemoBanner />}
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
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route
              path="/transactions"
              element={
                <TransactionsPage onReviewMaybeChanged={refreshReviewCount} />
              }
            />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/settings/taxonomy" element={<TaxonomyPage />} />
            <Route path="/settings/rules" element={<RulesPage />} />
            <Route path="*" element={<Navigate to="/pivot" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
