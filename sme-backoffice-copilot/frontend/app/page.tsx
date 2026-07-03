"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  formatApiError,
  listReviewTasks,
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
};

const cashPosition = {
  label: "Cash position",
  value: "$42.6k",
  trend: "Placeholder",
  tone: "neutral" as const,
  caption:
    "Available balance across connected accounts once banking sync exists.",
  source: "Mock aggregate",
};

const inflowOutflow = [
  {
    label: "Inflow",
    value: "$18.4k",
    trend: "Placeholder",
    tone: "positive" as const,
    caption: "Customer receipts detected this week after statement parsing.",
    source: "Mock statement data",
  },
  {
    label: "Outflow",
    value: "$9.7k",
    trend: "Placeholder",
    tone: "warning" as const,
    caption: "Vendor payments and operating expenses after categorization.",
    source: "Mock statement data",
  },
];

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
    body: "Once statement parsing is connected, this card will compare weekly inflow and outflow using traceable source transactions.",
    evidence: "Waiting for parsed bank statements",
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
  const [isLoadingReviews, setIsLoadingReviews] = useState(true);

  useEffect(() => {
    async function loadReviewSummary() {
      setIsLoadingReviews(true);
      setReviewError(null);

      try {
        const response = await listReviewTasks({ limit: 100 });
        setReviewTasks(response.items);
      } catch (error) {
        setReviewError(formatApiError(error));
      } finally {
        setIsLoadingReviews(false);
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

  const metrics: DashboardMetric[] = [
    cashPosition,
    ...inflowOutflow,
    {
      label: "Unresolved items",
      value: isLoadingReviews ? "…" : String(unresolvedCount),
      trend:
        reviewError !== null
          ? "Review API issue"
          : urgentCount > 0
            ? `${urgentCount} urgent`
            : "Live count",
      tone: urgentCount > 0 || reviewError !== null ? "warning" : "neutral",
      caption:
        reviewError !== null
          ? "Could not load review task count from the backend."
          : "Open or in-progress review tasks waiting for human decision.",
      source: reviewError ?? "Live review API",
    },
  ];

  const operatingSignals = [
    { label: "Dashboard mode", value: "Local MVP" },
    { label: "Financial data", value: "Placeholder" },
    {
      label: "Review API",
      value: reviewError ? "Needs attention" : "Connected",
    },
    { label: "Workflow", value: "Skeleton ready" },
  ];

  return (
    <div className="page-stack">
      <section className="dashboard-hero dashboard-hero-compact">
        <div className="hero-copy">
          <span className="status-pill status-pill-inverted">
            Local dashboard placeholder
          </span>
          <h2>Cashflow, review work, and grounded signals in one place.</h2>
          <p>
            This dashboard gives the SME operator a calm daily snapshot. Cash
            metrics are placeholder aggregates for now; unresolved review count
            is wired to the backend review API.
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

        <aside
          className="dashboard-readiness-card"
          aria-label="Dashboard data readiness"
        >
          <p className="eyebrow">Data readiness</p>
          <div className="readiness-list">
            <DashboardReadinessItem label="Upload API" value="Live" />
            <DashboardReadinessItem label="Review count" value="Live" />
            <DashboardReadinessItem label="Cash position" value="Placeholder" />
            <DashboardReadinessItem label="Insights" value="Placeholder" />
          </div>
        </aside>
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
        {metrics.map((metric) => (
          <article className="metric-card" key={metric.label}>
            <div className="card-header">
              <span>{metric.label}</span>
              <em className={`metric-trend metric-trend-${metric.tone}`}>
                {metric.trend}
              </em>
            </div>
            <strong>{metric.value}</strong>
            <p>{metric.caption}</p>
            <small>{metric.source}</small>
          </article>
        ))}
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

function DashboardReadinessItem({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
