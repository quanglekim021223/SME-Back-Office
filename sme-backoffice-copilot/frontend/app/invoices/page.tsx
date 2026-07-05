"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../_components/status-states";
import {
  formatApiError,
  listInvoices,
  type InvoiceListResponse,
} from "../_lib/api-client";

type InvoiceItem = InvoiceListResponse["items"][number];
type LoadState = "idle" | "loading" | "loaded" | "error";

const STATUS_OPTIONS = [
  { label: "Active (exclude superseded)", value: "active" },
  { label: "Extracted", value: "extracted" },
  { label: "Pending review", value: "pending_review" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
  { label: "All (include superseded)", value: "all" },
];

function formatMoney(amount: string | null, currency: string | null) {
  if (!amount) return "—";
  const formatted = parseFloat(amount).toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${currency} ${formatted}` : formatted;
}

function formatDate(dateStr: string | null) {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function statusPillClass(status: string) {
  switch (status) {
    case "approved":
      return "status-pill status-pill-success";
    case "extracted":
      return "status-pill status-pill-info";
    case "pending_review":
      return "status-pill status-pill-warning";
    case "rejected":
      return "status-pill status-pill-error";
    case "superseded":
      return "status-pill status-pill-muted";
    default:
      return "status-pill status-pill-muted";
  }
}

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<InvoiceItem[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("active");

  async function refreshInvoices() {
    setLoadState("loading");
    setErrorMessage(null);

    try {
      const excludeSuperseded = statusFilter !== "all";
      const status =
        statusFilter === "active" || statusFilter === "all"
          ? undefined
          : statusFilter;

      const response = await listInvoices({ excludeSuperseded, status });
      setInvoices(response.items);
      setLoadState("loaded");
    } catch (error) {
      setErrorMessage(formatApiError(error));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void refreshInvoices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const stats = useMemo(() => {
    return [
      {
        label: "Total shown",
        value: String(invoices.length),
      },
      {
        label: "With totals",
        value: String(invoices.filter((inv) => inv.total_amount !== null).length),
      },
      {
        label: "Extracted",
        value: String(invoices.filter((inv) => inv.status === "extracted").length),
      },
    ];
  }, [invoices]);

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Finance records</p>
          <h2>Extracted invoices</h2>
          <p>
            Invoices extracted by AI and validated through human review. Each
            entry represents the latest version of the structured invoice data.
          </p>
        </div>
        <button
          className="button button-secondary"
          disabled={loadState === "loading"}
          onClick={() => void refreshInvoices()}
          type="button"
        >
          Refresh
        </button>
      </section>

      <section className="metric-grid compact-metric-grid">
        {stats.map((stat) => (
          <article className="metric-card metric-card-compact" key={stat.label}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </article>
        ))}
      </section>

      <section className="panel-card">
        <div className="card-header">
          <div>
            <p className="eyebrow">Filter</p>
            <h3>Invoice status</h3>
          </div>
        </div>
        <div className="queue-toolbar" aria-label="Invoice status filters">
          {STATUS_OPTIONS.map((opt) => (
            <button
              className={`toolbar-chip ${statusFilter === opt.value ? "toolbar-chip-active" : ""}`}
              key={opt.value}
              onClick={() => setStatusFilter(opt.value)}
              type="button"
            >
              {opt.label}
            </button>
          ))}
        </div>
      </section>

      {loadState === "loading" && invoices.length === 0 ? (
        <LoadingState
          title="Loading invoices"
          message="Fetching extracted invoices from the backend..."
        />
      ) : null}

      {loadState === "error" ? (
        <ErrorState
          message={errorMessage ?? "Could not load invoices."}
          title="Invoices could not be loaded"
          action={
            <button
              className="button button-primary"
              onClick={() => void refreshInvoices()}
              type="button"
            >
              Try again
            </button>
          }
        />
      ) : null}

      {loadState === "loaded" && invoices.length === 0 ? (
        <EmptyState
          title="No invoices found"
          message="Upload a document and process it through the review queue to see extracted invoices here."
          action={
            <Link className="button button-primary" href="/upload">
              Upload a document
            </Link>
          }
        />
      ) : null}

      {invoices.length > 0 ? (
        <section className="panel-card">
          <div className="card-header">
            <div>
              <p className="eyebrow">Results</p>
              <h3>Invoice records</h3>
            </div>
            <span className="status-pill status-pill-muted">
              {invoices.length} invoices
            </span>
          </div>

          <div className="line-items-table-wrap">
            <table className="compact-data-table">
              <thead>
                <tr>
                  <th>Invoice #</th>
                  <th>Supplier</th>
                  <th>Customer</th>
                  <th>Issue date</th>
                  <th>Due date</th>
                  <th>Total</th>
                  <th>Status</th>
                  <th>Ver.</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice) => (
                  <tr key={invoice.id}>
                    <td>
                      <strong>{invoice.invoice_number ?? "—"}</strong>
                    </td>
                    <td>{invoice.supplier_name ?? "—"}</td>
                    <td>{invoice.customer_name ?? "—"}</td>
                    <td>{formatDate(invoice.issue_date)}</td>
                    <td>{formatDate(invoice.due_date)}</td>
                    <td>
                      <strong>
                        {formatMoney(invoice.total_amount, invoice.currency)}
                      </strong>
                    </td>
                    <td>
                      <span className={statusPillClass(invoice.status)}>
                        {invoice.status.replace("_", " ")}
                      </span>
                    </td>
                    <td>v{invoice.version}</td>
                    <td>
                      <Link
                        className="button button-ghost"
                        href={`/invoices/${invoice.id}`}
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
