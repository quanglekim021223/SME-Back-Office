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
  listReviewTasks,
  type ReviewTaskStatus,
  type ReviewTaskSummaryResponse,
  type ReviewTaskType,
} from "../_lib/api-client";

const TASK_FILTERS: Array<{ label: string; value: "all" | ReviewTaskType }> = [
  { label: "All tasks", value: "all" },
  { label: "Extraction", value: "extraction" },
  { label: "Classification", value: "classification" },
  { label: "Reconciliation", value: "reconciliation" },
  { label: "Policy", value: "policy" },
  { label: "Insight", value: "insight" },
];

const STATUS_FILTERS: Array<{
  label: string;
  value: "all" | ReviewTaskStatus;
}> = [
  { label: "All status", value: "all" },
  { label: "Open", value: "open" },
  { label: "In progress", value: "in_progress" },
  { label: "Resolved", value: "resolved" },
];

type LoadState = "idle" | "loading" | "loaded" | "error";

export default function ReviewPage() {
  const [tasks, setTasks] = useState<ReviewTaskSummaryResponse[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [taskFilter, setTaskFilter] = useState<"all" | ReviewTaskType>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | ReviewTaskStatus>(
    "all",
  );

  async function refreshReviewTasks() {
    setLoadState("loading");
    setErrorMessage(null);

    try {
      const response = await listReviewTasks();
      setTasks(response.items);
      setLoadState("loaded");
    } catch (error) {
      setErrorMessage(formatApiError(error));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void refreshReviewTasks();
  }, []);

  const visibleTasks = useMemo(() => {
    return tasks.filter((task) => {
      const matchesType = taskFilter === "all" || task.task_type === taskFilter;
      const matchesStatus =
        statusFilter === "all" || task.status === statusFilter;

      return matchesType && matchesStatus;
    });
  }, [statusFilter, taskFilter, tasks]);

  const stats = useMemo(() => {
    return [
      {
        label: "Open",
        value: String(tasks.filter((task) => task.status === "open").length),
      },
      {
        label: "Urgent",
        value: String(
          tasks.filter((task) => task.priority === "urgent").length,
        ),
      },
      {
        label: "Resolved",
        value: String(
          tasks.filter((task) => task.status === "resolved").length,
        ),
      },
    ];
  }, [tasks]);

  const highlightedTask = visibleTasks[0] ?? tasks[0] ?? null;

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Human review</p>
          <h2>Keep uncertain AI outputs accountable.</h2>
          <p>
            Approve, correct, or reject extraction, classification, and
            reconciliation proposals before they affect reports.
          </p>
        </div>
        <button
          className="button button-secondary"
          disabled={loadState === "loading"}
          onClick={() => void refreshReviewTasks()}
          type="button"
        >
          Refresh queue
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

      {loadState === "loading" && tasks.length === 0 ? (
        <LoadingState
          title="Loading review queue"
          message="Fetching tenant-scoped tasks from the review API..."
        />
      ) : null}

      {loadState === "error" ? (
        <ErrorState
          message={errorMessage ?? "Could not load review tasks."}
          title="Review queue needs attention"
          action={
            <button
              className="button button-primary"
              onClick={() => void refreshReviewTasks()}
              type="button"
            >
              Try again
            </button>
          }
        />
      ) : null}

      {loadState === "loaded" && tasks.length === 0 ? (
        <EmptyState
          title="No review tasks yet"
          message="When extraction, classification, reconciliation, or policy checks need a human decision, tasks will appear here."
          action={
            <Link className="button button-primary" href="/upload">
              Upload a document
            </Link>
          }
        />
      ) : null}

      {tasks.length > 0 ? (
        <section className="review-layout">
          <article className="panel-card panel-card-large">
            <div className="card-header">
              <div>
                <p className="eyebrow">Live queue</p>
                <h3>Review tasks</h3>
              </div>
              <span className="status-pill status-pill-muted">
                {visibleTasks.length} shown / {tasks.length} total
              </span>
            </div>

            <div className="queue-filter-stack">
              <div
                className="queue-toolbar"
                aria-label="Review task type filters"
              >
                {TASK_FILTERS.map((filter) => (
                  <button
                    className={`toolbar-chip ${
                      taskFilter === filter.value ? "toolbar-chip-active" : ""
                    }`}
                    key={filter.value}
                    onClick={() => setTaskFilter(filter.value)}
                    type="button"
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
              <div className="queue-toolbar" aria-label="Review status filters">
                {STATUS_FILTERS.map((filter) => (
                  <button
                    className={`toolbar-chip ${
                      statusFilter === filter.value ? "toolbar-chip-active" : ""
                    }`}
                    key={filter.value}
                    onClick={() => setStatusFilter(filter.value)}
                    type="button"
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
            </div>

            {visibleTasks.length > 0 ? (
              <div className="table-shell">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Task</th>
                      <th>Type</th>
                      <th>Priority</th>
                      <th>Status</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleTasks.map((task) => (
                      <tr key={task.id}>
                        <td>
                          <Link
                            className="table-primary-link"
                            href={`/review/${task.id}`}
                          >
                            {task.title}
                          </Link>
                          <span>{task.reason_code ?? task.target_type}</span>
                        </td>
                        <td>{formatTaskType(task.task_type)}</td>
                        <td>
                          <em
                            className={`priority priority-${priorityTone(
                              task.priority,
                            )}`}
                          >
                            {formatPriority(task.priority)}
                          </em>
                        </td>
                        <td>
                          <span className="status-pill status-pill-muted">
                            {formatStatus(task.status)}
                          </span>
                        </td>
                        <td>{formatDate(task.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                title="No tasks match this filter"
                message="Try a broader task type or status filter to see more review work."
              />
            )}
          </article>

          <aside className="panel-card evidence-card">
            <p className="eyebrow">Source evidence</p>
            <h3>{highlightedTask?.title ?? "Evidence placeholder"}</h3>
            <div className="evidence-preview">
              <span>{highlightedTask?.target_type ?? "source"}</span>
              <strong>
                {highlightedTask
                  ? formatTaskType(highlightedTask.task_type)
                  : "Waiting for a review task"}
              </strong>
              <p>
                Source document preview, OCR snippets, field coordinates, and
                validation notes will be shown here once task evidence is wired.
              </p>
            </div>

            {highlightedTask ? (
              <Link
                className="button button-primary"
                href={`/review/${highlightedTask.id}`}
              >
                Inspect task
              </Link>
            ) : (
              <Link className="button button-secondary" href="/upload">
                Create review input
              </Link>
            )}
            <small>
              This is intentionally a placeholder: it reserves the UX space for
              source evidence before OCR/PDF rendering is connected.
            </small>
          </aside>
        </section>
      ) : null}
    </div>
  );
}

function formatTaskType(taskType: ReviewTaskType) {
  return taskType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatStatus(status: ReviewTaskStatus) {
  return status
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatPriority(priority: ReviewTaskSummaryResponse["priority"]) {
  return priority.charAt(0).toUpperCase() + priority.slice(1);
}

function priorityTone(priority: ReviewTaskSummaryResponse["priority"]) {
  if (priority === "urgent") {
    return "danger";
  }

  if (priority === "high") {
    return "warning";
  }

  return "neutral";
}

function formatDate(value: string | null) {
  if (!value) {
    return "—";
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
