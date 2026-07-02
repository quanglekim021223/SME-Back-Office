import Link from "next/link";

const metrics = [
  {
    label: "Cash position",
    value: "$42,638",
    trend: "+12.4%",
    tone: "positive",
    caption: "Available balance across connected accounts",
  },
  {
    label: "Cash in",
    value: "$18,420",
    trend: "+8.1%",
    tone: "positive",
    caption: "Customer receipts detected this week",
  },
  {
    label: "Cash out",
    value: "$9,780",
    trend: "-3.6%",
    tone: "neutral",
    caption: "Vendor payments and operating expenses",
  },
  {
    label: "Review tasks",
    value: "7",
    trend: "3 urgent",
    tone: "warning",
    caption: "Items waiting for accountant approval",
  },
];

const operatingSignals = [
  { label: "Runway", value: "7.8 months" },
  { label: "Unmatched cash", value: "$3,284" },
  { label: "Low-confidence fields", value: "5" },
  { label: "Duplicate documents", value: "2" },
];

const pipeline = [
  { label: "Uploaded", value: "18 docs", progressClass: "progress-92" },
  { label: "Extracted", value: "15 docs", progressClass: "progress-76" },
  { label: "Matched", value: "11 docs", progressClass: "progress-58" },
  { label: "Reviewed", value: "8 docs", progressClass: "progress-42" },
];

const chartBars = [
  "chart-bar-42",
  "chart-bar-58",
  "chart-bar-36",
  "chart-bar-72",
  "chart-bar-64",
  "chart-bar-88",
];

const insights = [
  "Ad spend increased 18% while payment collection stayed flat.",
  "Two invoices likely match one bank transaction and need review.",
  "Office utilities are trending above the 90-day baseline.",
];

const heroSignals = [
  { label: "Review queue", value: "7 open" },
  { label: "Auto matches", value: "11 proposed" },
  { label: "Data quality", value: "92% complete" },
];

export default function HomePage() {
  return (
    <div className="page-stack">
      <section className="dashboard-hero">
        <div className="hero-copy">
          <span className="status-pill status-pill-inverted">
            Week ending Jul 2
          </span>
          <h2>Finance operations ready for review.</h2>
          <p>
            Track cash, review uncertain AI proposals, and keep invoice-to-bank
            reconciliation traceable.
          </p>
          <div className="hero-actions">
            <Link className="button button-primary" href="/upload">
              Upload documents
            </Link>
            <Link className="button button-secondary" href="/review">
              Open review queue
            </Link>
          </div>
          <div className="hero-status-list" aria-label="Current operations">
            {heroSignals.map((signal) => (
              <div key={signal.label}>
                <span>{signal.label}</span>
                <strong>{signal.value}</strong>
              </div>
            ))}
          </div>
        </div>

        <div
          className="hero-balance-card"
          aria-label="Cash snapshot placeholder"
        >
          <div className="cash-card-header">
            <p>Net cash movement</p>
            <span>Last 7 days</span>
          </div>
          <strong>+$8,640</strong>
          <span>Projected runway: 7.8 months</span>
          <div className="mini-chart" aria-hidden="true">
            {chartBars.map((chartBar) => (
              <i className={chartBar} key={chartBar} />
            ))}
          </div>
        </div>
      </section>

      <section className="ops-strip" aria-label="Operating signals">
        {operatingSignals.map((signal) => (
          <article key={signal.label}>
            <span>{signal.label}</span>
            <strong>{signal.value}</strong>
          </article>
        ))}
      </section>

      <section className="metric-grid" aria-label="Business metrics">
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
          </article>
        ))}
      </section>

      <section className="content-grid">
        <article className="panel-card panel-card-large">
          <div className="card-header">
            <div>
              <p className="eyebrow">Agent workflow</p>
              <h3>Document processing pipeline</h3>
            </div>
            <span className="status-pill">Local mock data</span>
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
          <div>
            <p className="eyebrow">Grounded insights</p>
            <h3>Latest business signals</h3>
          </div>
          <div className="insight-list">
            {insights.map((insight) => (
              <div className="insight-item" key={insight}>
                <span className="signal-marker" aria-hidden="true" />
                <p>{insight}</p>
              </div>
            ))}
          </div>
        </article>
      </section>
    </div>
  );
}
