"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { use } from "react";

import {
  ErrorState,
  LoadingState,
} from "../../_components/status-states";
import {
  formatApiError,
  getInvoice,
  type InvoiceResponse,
} from "../../_lib/api-client";

type LoadState = "idle" | "loading" | "loaded" | "error";

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

function DetailField({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string | null | undefined;
  emphasis?: boolean;
}) {
  return (
    <div className={emphasis ? "proposal-field proposal-field-emphasis" : "proposal-field"}>
      <span>{label}</span>
      <strong>{value || "—"}</strong>
    </div>
  );
}

export default function InvoiceDetailPage({
  params,
}: {
  params: Promise<{ invoiceId: string }>;
}) {
  const { invoiceId } = use(params);
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function loadInvoice() {
    setLoadState("loading");
    setErrorMessage(null);

    try {
      const response = await getInvoice(invoiceId);
      setInvoice(response);
      setLoadState("loaded");
    } catch (error) {
      setErrorMessage(formatApiError(error));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void loadInvoice();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId]);

  if (loadState === "loading" && !invoice) {
    return (
      <LoadingState
        title="Loading invoice"
        message="Fetching invoice details and line items..."
      />
    );
  }

  if (loadState === "error") {
    return (
      <ErrorState
        title="Invoice could not be loaded"
        message={errorMessage ?? "The invoice API returned an error."}
        action={
          <div className="action-row">
            <button
              className="button button-primary"
              onClick={() => void loadInvoice()}
              type="button"
            >
              Try again
            </button>
            <Link className="button button-ghost" href="/invoices">
              Back to invoices
            </Link>
          </div>
        }
      />
    );
  }

  if (!invoice) return null;

  return (
    <div className="page-stack">
      <section className="review-detail-layout">
        <article className="panel-card panel-card-large">
          <div className="card-header">
            <div>
              <p className="eyebrow">Invoice detail</p>
              <h2>{invoice.invoice_number ?? "Unnamed invoice"}</h2>
              <p>
                Structured invoice data extracted from the source document.
                Version {invoice.version} of this invoice record.
              </p>
            </div>
            <div className="action-row">
              <span className={statusPillClass(invoice.status)}>
                {invoice.status.replace("_", " ")}
              </span>
              <Link className="button button-ghost" href="/invoices">
                Back to invoices
              </Link>
            </div>
          </div>

          {/* Header fields */}
          <div className="proposal-summary-grid">
            <DetailField label="Invoice #" value={invoice.invoice_number} />
            <DetailField label="Supplier" value={invoice.supplier_name} />
            <DetailField label="Supplier Tax ID" value={invoice.supplier_tax_id} />
            <DetailField label="Customer" value={invoice.customer_name} />
            <DetailField label="Customer Tax ID" value={invoice.customer_tax_id} />
            <DetailField label="Direction" value={invoice.direction} />
            <DetailField label="Issue date" value={formatDate(invoice.issue_date)} />
            <DetailField label="Due date" value={formatDate(invoice.due_date)} />
            <DetailField label="Currency" value={invoice.currency} />
            <DetailField
              label="Subtotal"
              value={formatMoney(invoice.subtotal_amount, invoice.currency)}
            />
            <DetailField
              label="Tax"
              value={formatMoney(invoice.tax_amount, invoice.currency)}
            />
            <DetailField
              label="Total"
              value={formatMoney(invoice.total_amount, invoice.currency)}
              emphasis
            />
          </div>

          {invoice.notes ? (
            <div className="proposal-section">
              <p className="eyebrow">Notes</p>
              <p>{invoice.notes}</p>
            </div>
          ) : null}

          {/* Line items */}
          <div className="proposal-section">
            <div className="card-header card-header-compact">
              <div>
                <p className="eyebrow">Line items</p>
                <h4>Extracted table rows</h4>
              </div>
              <span className="status-pill status-pill-muted">
                {invoice.line_items.length} rows
              </span>
            </div>
            {invoice.line_items.length > 0 ? (
              <div className="line-items-table-wrap">
                <table className="compact-data-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Description</th>
                      <th>Product code</th>
                      <th>Qty</th>
                      <th>Unit</th>
                      <th>Unit price</th>
                      <th>Net</th>
                      <th>Tax</th>
                      <th>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoice.line_items.map((item) => (
                      <tr key={item.id}>
                        <td>{item.line_number}</td>
                        <td>{item.description ?? "—"}</td>
                        <td>{item.product_code ?? "—"}</td>
                        <td>{item.quantity ?? "—"}</td>
                        <td>{item.unit_of_measure ?? "—"}</td>
                        <td>{formatMoney(item.unit_price_amount, item.currency)}</td>
                        <td>{formatMoney(item.net_amount, item.currency)}</td>
                        <td>{item.tax_rate ? `${item.tax_rate}%` : "—"}</td>
                        <td>
                          <strong>
                            {formatMoney(item.total_amount, item.currency)}
                          </strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted-copy">
                No line items were extracted for this invoice version.
              </p>
            )}
          </div>

          {/* Traceability */}
          <div className="proposal-section">
            <p className="eyebrow">Traceability</p>
            <div className="evidence-ref-list">
              {invoice.document_id ? (
                <code>document:{invoice.document_id}</code>
              ) : null}
              {invoice.supersedes_invoice_id ? (
                <code>supersedes:{invoice.supersedes_invoice_id}</code>
              ) : null}
              {invoice.source_processing_run_id ? (
                <code>run:{invoice.source_processing_run_id}</code>
              ) : null}
              <code>version:{invoice.version}</code>
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}
