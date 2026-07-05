"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { OrganizationSelector } from "./organization-selector";

type NavigationItem = {
  href: string;
  label: string;
  description: string;
  icon: string;
};

const navigationItems: NavigationItem[] = [
  {
    href: "/",
    label: "Dashboard",
    description: "Cashflow and business insight overview",
    icon: "DB",
  },
  {
    href: "/upload",
    label: "Upload",
    description: "Invoice and bank statement intake",
    icon: "UP",
  },
  {
    href: "/invoices",
    label: "Invoices",
    description: "Extracted and validated invoices",
    icon: "IV",
  },
  {
    href: "/review",
    label: "Review",
    description: "Human review queue",
    icon: "RV",
  },
];


export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="app-shell">
        <aside className="app-sidebar" aria-label="Primary navigation">
          <div className="brand-block">
            <div className="brand-mark" aria-hidden="true">
              SME
            </div>
            <div>
              <p className="eyebrow">Back-office Copilot</p>
              <h1>SME Workspace</h1>
            </div>
          </div>

          <OrganizationSelector />

          <nav className="nav-list">
            {navigationItems.map((item) => {
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);

              return (
                <Link
                  aria-current={isActive ? "page" : undefined}
                  className={isActive ? "nav-item nav-item-active" : "nav-item"}
                  href={item.href}
                  key={item.href}
                >
                  <span className="nav-icon" aria-hidden="true">
                    {item.icon}
                  </span>
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                </Link>
              );
            })}
          </nav>

          <section
            className="sidebar-summary"
            aria-label="Local workflow status"
          >
            <p className="eyebrow">Workflow health</p>
            <div className="sidebar-summary-row">
              <span>Mock AI</span>
              <strong>Ready</strong>
            </div>
            <div className="sidebar-summary-row">
              <span>Human review</span>
              <strong>Enabled</strong>
            </div>
          </section>
        </aside>

        <div className="app-main">
          <header className="topbar">
            <div>
              <p className="eyebrow">Local finance workspace</p>
              <strong>Human-in-the-loop financial operations</strong>
            </div>
            <div className="topbar-actions">
              <div className="topbar-search" aria-label="Search placeholder">
                Search documents, review tasks, insights
              </div>
              <div className="status-pill">Dev auth placeholder</div>
            </div>
          </header>

          <main className="page-container" id="main-content">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
