"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../_components/status-states";
import {
  formatApiError,
  listBankTransactions,
  type BankTransactionDirection,
  type BankTransactionMatchStatus,
  type BankTransactionResponse,
} from "../_lib/api-client";

type DirectionFilter = "all" | BankTransactionDirection;
type MatchFilter = "all" | BankTransactionMatchStatus;
type LoadState = "idle" | "loading" | "loaded" | "error";

const DIRECTION_OPTIONS: { label: string; value: DirectionFilter }[] = [
  { label: "All movement", value: "all" },
  { label: "Inflow", value: "inflow" },
  { label: "Outflow", value: "outflow" },
  { label: "Unknown", value: "unknown" },
];

const MATCH_OPTIONS: { label: string; value: MatchFilter }[] = [
  { label: "All matches", value: "all" },
  { label: "Matched", value: "matched" },
  { label: "Needs review", value: "review" },
  { label: "Unmatched", value: "unmatched" },
];

export default function BankingPage() {
  return (
    <Suspense
      fallback={
        <LoadingState
          title="Loading bank transactions"
          message="Preparing the banking workspace..."
        />
      }
    >
      <BankingPageContent />
    </Suspense>
  );
}

function BankingPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [transactions, setTransactions] = useState<BankTransactionResponse[]>(
    [],
  );
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const direction = normalizeDirection(searchParams.get("direction"));
  const matchStatus = normalizeMatchStatus(searchParams.get("match"));

  async function refreshTransactions() {
    setLoadState("loading");
    setErrorMessage(null);

    try {
      const response = await listBankTransactions({
        direction: direction === "all" ? undefined : direction,
        reconciliationStatus: matchStatus === "all" ? undefined : matchStatus,
      });
      setTransactions(response.items);
      setLoadState("loaded");
    } catch (error) {
      setErrorMessage(formatApiError(error));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void refreshTransactions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [direction, matchStatus]);

  const visibleTransactions = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return transactions;

    return transactions.filter((transaction) =>
      [
        transaction.counterparty_name,
        transaction.description,
        transaction.reference,
        transaction.bank_account_name,
        transaction.institution_name,
        transaction.source_filename,
      ].some((value) => value?.toLowerCase().includes(query)),
    );
  }, [search, transactions]);

  const stats = useMemo(() => {
    const inflow = visibleTransactions.filter(
      (transaction) => transaction.direction === "inflow",
    );
    const outflow = visibleTransactions.filter(
      (transaction) => transaction.direction === "outflow",
    );
    const needsAttention = visibleTransactions.filter(
      (transaction) => transaction.reconciliation_status !== "matched",
    ).length;

    return [
      {
        label: "Transactions shown",
        value: String(visibleTransactions.length),
      },
      { label: "Inflow", value: formatAggregateAmount(inflow) },
      { label: "Outflow", value: formatAggregateAmount(outflow) },
      { label: "Needs attention", value: String(needsAttention) },
    ];
  }, [visibleTransactions]);

  function updateFilters({
    nextDirection = direction,
    nextMatch = matchStatus,
  }: {
    nextDirection?: DirectionFilter;
    nextMatch?: MatchFilter;
  }) {
    const params = new URLSearchParams(searchParams.toString());
    setOrDelete(params, "direction", nextDirection, "all");
    setOrDelete(params, "match", nextMatch, "all");
    const query = params.toString();
    router.replace(query ? `/banking?${query}` : "/banking");
  }

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Bank activity</p>
          <h2>Cash movement and matching</h2>
          <p>
            Inspect imported bank transactions, separate receipts from payments,
            and see which movements are linked to an invoice or still need human
            attention.
          </p>
        </div>
        <button
          className="button button-secondary"
          disabled={loadState === "loading"}
          onClick={() => void refreshTransactions()}
          type="button"
        >
          Refresh
        </button>
      </section>

      <section className="metric-grid banking-metric-grid">
        {stats.map((stat) => (
          <article className="metric-card metric-card-compact" key={stat.label}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </article>
        ))}
      </section>

      <section className="panel-card banking-filter-panel">
        <div className="banking-filter-row">
          <div>
            <p className="eyebrow">Direction</p>
            <div className="queue-toolbar" aria-label="Cash direction filters">
              {DIRECTION_OPTIONS.map((option) => (
                <button
                  className={`toolbar-chip ${direction === option.value ? "toolbar-chip-active" : ""}`}
                  key={option.value}
                  onClick={() => updateFilters({ nextDirection: option.value })}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="eyebrow">Invoice match</p>
            <div className="queue-toolbar" aria-label="Invoice match filters">
              {MATCH_OPTIONS.map((option) => (
                <button
                  className={`toolbar-chip ${matchStatus === option.value ? "toolbar-chip-active" : ""}`}
                  key={option.value}
                  onClick={() => updateFilters({ nextMatch: option.value })}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <label className="banking-search-field">
            <span>Search current results</span>
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Counterparty, reference, account..."
              type="search"
              value={search}
            />
          </label>
        </div>
      </section>

      {loadState === "loading" && transactions.length === 0 ? (
        <LoadingState
          title="Loading bank transactions"
          message="Reading imported statement activity and invoice matches..."
        />
      ) : null}

      {loadState === "error" ? (
        <ErrorState
          message={errorMessage ?? "Could not load bank transactions."}
          title="Bank transactions could not be loaded"
          action={
            <button
              className="button button-primary"
              onClick={() => void refreshTransactions()}
              type="button"
            >
              Try again
            </button>
          }
        />
      ) : null}

      {loadState === "loaded" && transactions.length === 0 ? (
        <EmptyState
          title="No bank transactions found"
          message="Upload a bank statement CSV or change the filters to inspect another part of the cashflow."
          action={
            <Link className="button button-primary" href="/upload">
              Upload bank statement
            </Link>
          }
        />
      ) : null}

      {transactions.length > 0 && visibleTransactions.length === 0 ? (
        <EmptyState
          title="No results match this search"
          message="Clear the search field to return to the filtered transaction list."
        />
      ) : null}

      {visibleTransactions.length > 0 ? (
        <section className="panel-card">
          <div className="card-header">
            <div>
              <p className="eyebrow">Bank ledger</p>
              <h3>Imported transactions</h3>
            </div>
            <span className="status-pill status-pill-muted">
              {visibleTransactions.length} shown
            </span>
          </div>

          <div className="line-items-table-wrap">
            <table className="compact-data-table banking-data-table">
              <thead>
                <tr>
                  <th>Posted</th>
                  <th>Transaction</th>
                  <th>Account</th>
                  <th>Direction</th>
                  <th>Amount</th>
                  <th>Invoice match</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {visibleTransactions.map((transaction) => (
                  <TransactionRow
                    key={transaction.id}
                    transaction={transaction}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function TransactionRow({
  transaction,
}: {
  transaction: BankTransactionResponse;
}) {
  const primaryMatch = transaction.invoice_matches[0];

  return (
    <tr>
      <td>{formatDate(transaction.posted_at)}</td>
      <td>
        <div className="transaction-primary">
          <strong>
            {transaction.counterparty_name ??
              transaction.description ??
              "Unlabelled transaction"}
          </strong>
          {transaction.counterparty_name && transaction.description ? (
            <span>{transaction.description}</span>
          ) : null}
          {transaction.reference ? (
            <small>Ref {transaction.reference}</small>
          ) : null}
        </div>
      </td>
      <td>
        <div className="transaction-primary">
          <strong>
            {transaction.bank_account_name ?? transaction.institution_name}
          </strong>
          <span>
            {[transaction.institution_name, transaction.masked_account_number]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
      </td>
      <td>
        <span
          className={`direction-label direction-label-${transaction.direction}`}
        >
          {transaction.direction}
        </span>
      </td>
      <td>
        <strong
          className={
            transaction.direction === "inflow"
              ? "transaction-amount transaction-amount-positive"
              : transaction.direction === "outflow"
                ? "transaction-amount transaction-amount-negative"
                : "transaction-amount"
          }
        >
          {formatMoney(transaction.amount, transaction.currency)}
        </strong>
      </td>
      <td>
        <div className="transaction-primary">
          <span className={matchStatusClass(transaction.reconciliation_status)}>
            {matchStatusLabel(transaction.reconciliation_status)}
          </span>
          {primaryMatch ? (
            <Link
              className="text-link"
              href={`/invoices/${primaryMatch.invoice_id}`}
            >
              {primaryMatch.invoice_number ?? "View invoice"}
            </Link>
          ) : transaction.reconciliation_status === "review" ? (
            <Link className="text-link" href="/review">
              Open review queue
            </Link>
          ) : (
            <small>No invoice linked</small>
          )}
        </div>
      </td>
      <td>
        <span className="transaction-source">
          {transaction.source_filename ?? "Imported statement"}
        </span>
      </td>
    </tr>
  );
}

function normalizeDirection(value: string | null): DirectionFilter {
  return value === "inflow" || value === "outflow" || value === "unknown"
    ? value
    : "all";
}

function normalizeMatchStatus(value: string | null): MatchFilter {
  return value === "matched" || value === "review" || value === "unmatched"
    ? value
    : "all";
}

function setOrDelete(
  params: URLSearchParams,
  key: string,
  value: string,
  emptyValue: string,
) {
  if (value === emptyValue) {
    params.delete(key);
  } else {
    params.set(key, value);
  }
}

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function formatMoney(amount: string, currency: string | null) {
  const value = Number(amount);
  if (!Number.isFinite(value) || !currency || currency === "UNK") return amount;

  return new Intl.NumberFormat("en-US", {
    currency,
    minimumFractionDigits: 2,
    style: "currency",
  }).format(value);
}

function formatAggregateAmount(transactions: BankTransactionResponse[]) {
  if (transactions.length === 0) return "—";
  const currencies = new Set(
    transactions.map((transaction) => transaction.currency).filter(Boolean),
  );
  if (currencies.size !== 1) return "Multi-currency";

  const total = transactions.reduce(
    (sum, transaction) => sum + Math.abs(Number(transaction.amount) || 0),
    0,
  );
  return formatMoney(String(total), [...currencies][0] ?? null);
}

function matchStatusClass(status: BankTransactionMatchStatus) {
  if (status === "matched") return "status-pill status-pill-success";
  if (status === "review") return "status-pill status-pill-warning";
  return "status-pill status-pill-muted";
}

function matchStatusLabel(status: BankTransactionMatchStatus) {
  if (status === "matched") return "Matched";
  if (status === "review") return "Needs review";
  return "Unmatched";
}
