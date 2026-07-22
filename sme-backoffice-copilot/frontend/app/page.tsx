"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  formatApiError,
  getDashboardFinancialSummary,
  getLocalMetrics,
  listReviewTasks,
  type DashboardFinancialSummaryResponse,
  type FinancialMetricResponse,
  type LocalMetricsResponse,
  type ReviewTaskSummaryResponse,
} from "./_lib/api-client";

type MetricTone = "positive" | "neutral" | "warning";

type DashboardMetric = {
  label: string;
  value: string;
  trend: string;
  tone: MetricTone;
  caption: string;
  source: string;
  href?: string;
};

const pipeline = [
  {
    label: "Uploaded",
    value: "Local files accepted",
    progressClass: "progress-92",
  },
  {
    label: "Extracted",
    value: "Mock OCR/LLM pending",
    progressClass: "progress-58",
  },
  {
    label: "Validated",
    value: "Deterministic checks ready",
    progressClass: "progress-76",
  },
  {
    label: "Reviewed",
    value: "Human queue wired",
    progressClass: "progress-42",
  },
];

const latestInsights = [
  {
    title: "Cash movement summary",
    body: "Imported bank transactions now drive the cashflow cards; future insight cards will explain movement changes with evidence refs.",
    evidence: "Live bank transaction aggregates",
  },
  {
    title: "Unresolved finance work",
    body: "Review tasks will surface extraction, classification, reconciliation, and policy items that need human approval.",
    evidence: "Live review queue count",
  },
  {
    title: "Expense drift watch",
    body: "Future grounded insights will flag category-level changes such as SaaS, ads, utilities, rent, and payroll movement.",
    evidence: "Mock insight placeholder",
  },
];

export default function HomePage() {
  const [reviewTasks, setReviewTasks] = useState<ReviewTaskSummaryResponse[]>(
    [],
  );
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [opsMetrics, setOpsMetrics] = useState<LocalMetricsResponse | null>(
    null,
  );
  const [financialSummary, setFinancialSummary] =
    useState<DashboardFinancialSummaryResponse | null>(null);
  const [opsError, setOpsError] = useState<string | null>(null);
  const [financialError, setFinancialError] = useState<string | null>(null);
  const [isLoadingReviews, setIsLoadingReviews] = useState(true);
  const [isLoadingOps, setIsLoadingOps] = useState(true);
  const [isLoadingFinancial, setIsLoadingFinancial] = useState(true);

  useEffect(() => {
    async function loadReviewSummary() {
      setIsLoadingReviews(true);
      setIsLoadingOps(true);
      setIsLoadingFinancial(true);
      setReviewError(null);
      setOpsError(null);
      setFinancialError(null);

      try {
        const response = await listReviewTasks({ limit: 100 });
        setReviewTasks(response.items);
      } catch (error) {
        setReviewError(formatApiError(error));
      } finally {
        setIsLoadingReviews(false);
      }

      try {
        const response = await getLocalMetrics();
        setOpsMetrics(response);
      } catch (error) {
        setOpsError(formatApiError(error));
      } finally {
        setIsLoadingOps(false);
      }

      try {
        const response = await getDashboardFinancialSummary();
        setFinancialSummary(response);
      } catch (error) {
        setFinancialError(formatApiError(error));
      } finally {
        setIsLoadingFinancial(false);
      }
    }

    void loadReviewSummary();
  }, []);

  const unresolvedCount = useMemo(() => {
    return reviewTasks.filter(
      (task) => task.status === "open" || task.status === "in_progress",
    ).length;
  }, [reviewTasks]);

  const urgentCount = useMemo(() => {
    return reviewTasks.filter((task) => task.priority === "urgent").length;
  }, [reviewTasks]);

  const observedQueueSize = useMemo(() => {
    return findOpenReviewQueueSize(opsMetrics) ?? unresolvedCount;
  }, [opsMetrics, unresolvedCount]);

  const correctionRate = opsMetrics?.correction_rate ?? null;
  const correctionActionCount = correctionRate?.review_action_count ?? 0;
  const correctionTone =
    correctionRate && correctionRate.rate >= 0.25 ? "warning" : "positive";

  const financialMetricCards = buildFinancialMetricCards({
    summary: financialSummary,
    isLoading: isLoadingFinancial,
    error: financialError,
  });

  const metrics: DashboardMetric[] = [
    ...financialMetricCards,
    {
      label: "Review queue",
      value: isLoadingReviews || isLoadingOps ? "…" : String(observedQueueSize),
      trend:
        reviewError !== null || opsError !== null
          ? "Metrics issue"
          : urgentCount > 0
            ? `${urgentCount} urgent`
            : "Live ops metric",
      tone:
        urgentCount > 0 || reviewError !== null || opsError !== null
          ? "warning"
          : "neutral",
      caption:
        reviewError !== null || opsError !== null
          ? "Could not load the complete human review queue metric."
          : "Open or in-progress review tasks waiting for human decision.",
      source: reviewError ?? opsError ?? "Live ops metrics",
    },
    {
      label: "Correction rate",
      value: isLoadingOps
        ? "…"
        : correctionActionCount > 0 && correctionRate
          ? formatPercent(correctionRate.rate)
          : "0%",
      trend:
        opsError !== null
          ? "Metrics issue"
          : correctionActionCount > 0
            ? `${correctionRate?.correction_count ?? 0}/${correctionActionCount} corrected`
            : "No decisions yet",
      tone: opsError !== null ? "warning" : correctionTone,
      caption:
        "Share of human review actions that required corrected data instead of approve/reject.",
      source: opsError ?? "Live ops metrics",
    },
  ];

  const hasFinancialData =
    financialSummary?.inflow.available ||
    financialSummary?.outflow.available ||
    financialSummary?.cash_position.available ||
    false;

  const operatingSignals = [
    { label: "Dashboard mode", value: "Local MVP" },
    {
      label: "Financial data",
      value:
        financialError !== null
          ? "Needs attention"
          : isLoadingFinancial
            ? "Loading"
            : hasFinancialData
              ? "Live"
              : "Awaiting bank data",
    },
    {
      label: "Review API",
      value: reviewError ? "Needs attention" : "Connected",
    },
    {
      label: "Ops metrics",
      value: opsError ? "Needs attention" : "Connected",
    },
  ];

  return (
    <div className="page-stack">
      <section className="dashboard-hero dashboard-hero-compact">
        <div className="hero-copy">
          <span className="status-pill status-pill-inverted">
            Local dashboard
          </span>
          <h2>Cashflow, review work, and grounded signals in one place.</h2>
          <p>
            This dashboard gives the SME operator a calm daily snapshot. Cash
            metrics now read uploaded bank transactions when available; review
            and correction signals are wired to live ops metrics.
          </p>
          <div className="hero-actions">
            <Link className="button button-primary" href="/upload">
              Upload documents
            </Link>
            <Link className="button button-secondary" href="/review">
              Review unresolved work
            </Link>
          </div>
        </div>

        <NetCashMovementCard
          error={financialError}
          isLoading={isLoadingFinancial}
          summary={financialSummary}
        />
      </section>

      <section className="ops-strip" aria-label="Dashboard operating signals">
        {operatingSignals.map((signal) => (
          <article key={signal.label}>
            <span>{signal.label}</span>
            <strong>{signal.value}</strong>
          </article>
        ))}
      </section>

      <section className="metric-grid" aria-label="Dashboard metrics">
        {metrics.map((metric) => {
          const content = (
            <>
              <div className="card-header">
                <span>{metric.label}</span>
                <em className={`metric-trend metric-trend-${metric.tone}`}>
                  {metric.trend}
                </em>
              </div>
              <strong>{metric.value}</strong>
              <p>{metric.caption}</p>
              <small>{metric.source}</small>
              {metric.href ? (
                <span className="metric-card-cta">View transactions</span>
              ) : null}
            </>
          );

          return metric.href ? (
            <Link
              aria-label={`View ${metric.label.toLowerCase()} transactions`}
              className="metric-card metric-card-link"
              href={metric.href}
              key={metric.label}
            >
              {content}
            </Link>
          ) : (
            <article className="metric-card" key={metric.label}>
              {content}
            </article>
          );
        })}
      </section>

      <section className="content-grid">
        <article className="panel-card panel-card-large">
          <div className="card-header">
            <div>
              <p className="eyebrow">Processing overview</p>
              <h3>Document workflow placeholder</h3>
            </div>
            <span className="status-pill status-pill-muted">MVP skeleton</span>
          </div>
          <div className="pipeline-list">
            {pipeline.map((item) => (
              <div className="pipeline-row" key={item.label}>
                <div>
                  <strong>{item.label}</strong>
                  <span>{item.value}</span>
                </div>
                <div className="progress-track">
                  <i className={item.progressClass} />
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="panel-card">
          <div className="card-header">
            <div>
              <p className="eyebrow">Latest insights</p>
              <h3>Grounded insight placeholders</h3>
            </div>
            <span className="status-pill status-pill-muted">Mock</span>
          </div>
          <div className="insight-list">
            {latestInsights.map((insight) => (
              <div
                className="insight-item insight-item-stacked"
                key={insight.title}
              >
                <span className="signal-marker" aria-hidden="true" />
                <div>
                  <strong>{insight.title}</strong>
                  <p>{insight.body}</p>
                  <small>{insight.evidence}</small>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </div>
  );
}

function NetCashMovementCard({
  summary,
  isLoading,
  error,
}: {
  summary: DashboardFinancialSummaryResponse | null;
  isLoading: boolean;
  error: string | null;
}) {
  const inflowAmount = Number(summary?.inflow.amount ?? 0);
  const outflowAmount = Number(summary?.outflow.amount ?? 0);
  const netAmount = inflowAmount - outflowAmount;
  const currency =
    summary?.inflow.currency ??
    summary?.outflow.currency ??
    summary?.cash_position.currency ??
    "USD";
  const hasCashMovement =
    Boolean(summary?.inflow.available) || Boolean(summary?.outflow.available);
  const periodLabel = formatPeriodLabel(summary);
  const bars = buildNetMovementBars(inflowAmount, outflowAmount);

  let value = "No data";
  let note = "Upload a bank statement CSV to start tracking cash movement.";
  if (isLoading) {
    value = "…";
    note = "Reading bank transaction aggregates.";
  } else if (error !== null) {
    value = "Unavailable";
    note = "Financial summary API needs attention.";
  } else if (hasCashMovement) {
    value = formatSignedMoney(netAmount, currency);
    note = `Cash in ${formatMoney(String(inflowAmount), currency)} minus cash out ${formatMoney(
      String(outflowAmount),
      currency,
    )}.`;
  }

  return (
    <aside className="hero-balance-card" aria-label="Net cash movement">
      <div className="cash-card-header">
        <span>Net cash movement</span>
        <span>{periodLabel}</span>
      </div>
      <strong>{value}</strong>
      <p>{note}</p>
      <div className="mini-chart" aria-hidden="true">
        {bars.map((height, index) => (
          <i key={index} style={{ height: `${height}%` }} />
        ))}
      </div>
    </aside>
  );
}

function findOpenReviewQueueSize(metrics: LocalMetricsResponse | null) {
  if (!metrics) {
    return null;
  }

  const entry = Object.entries(metrics.review_queue_size).find(([key]) =>
    key.includes(":status:open:type:all"),
  );
  return entry?.[1] ?? null;
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function buildFinancialMetricCards({
  summary,
  isLoading,
  error,
}: {
  summary: DashboardFinancialSummaryResponse | null;
  isLoading: boolean;
  error: string | null;
}): DashboardMetric[] {
  return [
    financialMetricToCard({
      label: "Cash position",
      metric: summary?.cash_position ?? null,
      isLoading,
      error,
      positiveLabel: "Live balance",
      emptyTrend: "Needs balance",
      emptyCaption:
        "Upload a bank statement CSV with a balance column to show available cash.",
      liveCaption: "Latest known balance across imported bank accounts.",
      tone: "neutral",
    }),
    financialMetricToCard({
      label: "Inflow",
      href: "/banking?direction=inflow",
      metric: summary?.inflow ?? null,
      isLoading,
      error,
      positiveLabel: "Live transactions",
      emptyTrend: "Awaiting bank data",
      emptyCaption: "Upload a bank statement CSV to calculate receipts.",
      liveCaption: "Incoming transactions from parsed bank statements.",
      tone: "positive",
    }),
    financialMetricToCard({
      label: "Outflow",
      href: "/banking?direction=outflow",
      metric: summary?.outflow ?? null,
      isLoading,
      error,
      positiveLabel: "Live transactions",
      emptyTrend: "Awaiting bank data",
      emptyCaption: "Upload a bank statement CSV to calculate payments.",
      liveCaption: "Outgoing transactions from parsed bank statements.",
      tone: "warning",
    }),
  ];
}

function financialMetricToCard({
  label,
  metric,
  isLoading,
  error,
  positiveLabel,
  emptyTrend,
  emptyCaption,
  href,
  liveCaption,
  tone,
}: {
  label: string;
  metric: FinancialMetricResponse | null;
  isLoading: boolean;
  error: string | null;
  positiveLabel: string;
  emptyTrend: string;
  emptyCaption: string;
  href?: string;
  liveCaption: string;
  tone: MetricTone;
}): DashboardMetric {
  if (isLoading) {
    return {
      label,
      href,
      value: "…",
      trend: "Loading",
      tone: "neutral",
      caption: "Reading persisted bank transaction aggregates.",
      source: "Live bank data",
    };
  }

  if (error !== null) {
    return {
      label,
      href,
      value: "Unavailable",
      trend: "Metrics issue",
      tone: "warning",
      caption: "Could not load the financial summary API.",
      source: error,
    };
  }

  if (!metric || !metric.available) {
    return {
      label,
      href,
      value: "No data",
      trend: emptyTrend,
      tone: "neutral",
      caption: emptyCaption,
      source: metric?.source ?? "No parsed bank transactions yet",
    };
  }

  return {
    label,
    href,
    value: formatFinancialAmount(metric),
    trend: metricTrend(metric, positiveLabel),
    tone,
    caption: appendPeriod(liveCaption, metric),
    source: metric.source,
  };
}

function formatFinancialAmount(metric: FinancialMetricResponse) {
  if (metric.amount !== null && metric.currency !== null) {
    return formatMoney(metric.amount, metric.currency);
  }

  const currencies = Object.keys(metric.by_currency);
  if (currencies.length > 1) {
    return "Multi-currency";
  }

  return "No data";
}

function formatMoney(amount: string, currency: string) {
  const numericAmount = Number(amount);
  if (!Number.isFinite(numericAmount) || currency === "UNK") {
    return amount;
  }

  return new Intl.NumberFormat("en-US", {
    currency,
    maximumFractionDigits: Math.abs(numericAmount) >= 1000 ? 1 : 2,
    notation: Math.abs(numericAmount) >= 1000 ? "compact" : "standard",
    style: "currency",
  }).format(numericAmount);
}

function metricTrend(metric: FinancialMetricResponse, fallback: string) {
  if (metric.account_count > 0) {
    return `${metric.account_count} account${metric.account_count === 1 ? "" : "s"}`;
  }

  if (metric.transaction_count > 0) {
    return `${metric.transaction_count} transaction${
      metric.transaction_count === 1 ? "" : "s"
    }`;
  }

  return fallback;
}

function appendPeriod(caption: string, metric: FinancialMetricResponse) {
  const period = formatDateRangeLabel({
    emptyLabel: null,
    end: metric.period_end,
    start: metric.period_start,
  });

  if (period === null) {
    return caption;
  }

  return `${caption} ${period}.`;
}

function formatPeriodLabel(summary: DashboardFinancialSummaryResponse | null) {
  const start =
    summary?.inflow.period_start ??
    summary?.outflow.period_start ??
    summary?.cash_position.period_start;
  const end =
    summary?.inflow.period_end ??
    summary?.outflow.period_end ??
    summary?.cash_position.period_end;

  return formatDateRangeLabel({
    emptyLabel: "Awaiting data",
    end,
    start,
  });
}

function formatDateRangeLabel({
  emptyLabel,
  end,
  start,
}: {
  emptyLabel: string | null;
  end: string | null | undefined;
  start: string | null | undefined;
}) {
  if (!start && !end) {
    return emptyLabel;
  }

  if (start && end && start !== end) {
    return `Period: ${start} to ${end}`;
  }

  if (start && end && start === end) {
    return `As of ${end}`;
  }

  if (end) {
    return `As of ${end}`;
  }

  return `From ${start}`;
}

function formatSignedMoney(amount: number, currency: string) {
  const sign = amount > 0 ? "+" : amount < 0 ? "-" : "";
  return `${sign}${formatMoney(String(Math.abs(amount)), currency)}`;
}

function buildNetMovementBars(inflowAmount: number, outflowAmount: number) {
  const base = Math.max(Math.abs(inflowAmount), Math.abs(outflowAmount), 1);
  const net = inflowAmount - outflowAmount;
  const normalizedNet = Math.min(Math.abs(net) / base, 1);
  const normalizedIn = Math.min(Math.abs(inflowAmount) / base, 1);
  const normalizedOut = Math.min(Math.abs(outflowAmount) / base, 1);

  return [
    24 + normalizedOut * 28,
    28 + normalizedIn * 34,
    22 + normalizedNet * 22,
    34 + normalizedIn * 38,
    30 + normalizedOut * 30,
    38 + normalizedNet * 42,
  ].map((height) => Math.round(Math.min(Math.max(height, 18), 86)));
}
