const reviewTasks = [
  {
    title: "Low confidence classification",
    type: "Classification",
    source: "transaction: stripe payout",
    status: "Open",
    priority: "High",
    priorityTone: "warning",
  },
  {
    title: "Invoice total mismatch",
    type: "Extraction",
    source: "invoice-acme-1042.pdf",
    status: "In progress",
    priority: "Urgent",
    priorityTone: "danger",
  },
  {
    title: "Possible split payment",
    type: "Reconciliation",
    source: "statement-june.csv",
    status: "Open",
    priority: "Normal",
    priorityTone: "neutral",
  },
];

const reviewStats = [
  { label: "Open", value: "7" },
  { label: "Urgent", value: "3" },
  { label: "Resolved today", value: "12" },
];

export default function ReviewPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Human review</p>
          <h2>Keep uncertain AI outputs accountable.</h2>
          <p>
            Approve, correct, or reject extraction, classification, and
            reconciliation proposals before they affect reporting.
          </p>
        </div>
        <span className="status-pill">Phase 6 APIs ready</span>
      </section>

      <section className="metric-grid compact-metric-grid">
        {reviewStats.map((stat) => (
          <article className="metric-card metric-card-compact" key={stat.label}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </article>
        ))}
      </section>

      <section className="review-layout">
        <article className="panel-card panel-card-large">
          <div className="card-header">
            <div>
              <p className="eyebrow">Queue preview</p>
              <h3>Review tasks</h3>
            </div>
            <span className="status-pill status-pill-muted">Mock data</span>
          </div>

          <div className="queue-toolbar" aria-label="Review queue filters">
            <span className="toolbar-chip toolbar-chip-active">All tasks</span>
            <span className="toolbar-chip">Extraction</span>
            <span className="toolbar-chip">Classification</span>
            <span className="toolbar-chip">Reconciliation</span>
          </div>

          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Type</th>
                  <th>Priority</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {reviewTasks.map((task) => (
                  <tr key={task.title}>
                    <td>
                      <strong>{task.title}</strong>
                      <span>{task.source}</span>
                    </td>
                    <td>{task.type}</td>
                    <td>
                      <em className={`priority priority-${task.priorityTone}`}>
                        {task.priority}
                      </em>
                    </td>
                    <td>
                      <span className="status-pill status-pill-muted">
                        {task.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <aside className="panel-card evidence-card">
          <p className="eyebrow">Source evidence</p>
          <h3>Invoice total mismatch</h3>
          <div className="evidence-preview">
            <span>PDF</span>
            <strong>Total amount: $1,240.00</strong>
            <p>Validator expected $1,204.00 based on line items and tax.</p>
          </div>
          <div className="action-row">
            <button className="button button-primary" type="button">
              Approve
            </button>
            <button className="button button-secondary" type="button">
              Correct
            </button>
            <button className="button button-ghost" type="button">
              Reject
            </button>
          </div>
          <small>
            Buttons are visual placeholders until the action UI is wired.
          </small>
        </aside>
      </section>
    </div>
  );
}
