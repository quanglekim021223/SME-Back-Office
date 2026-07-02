import type { ReactNode } from "react";

type LoadingStateProps = {
  title?: string;
  message?: string;
};

type ErrorStateProps = {
  title?: string;
  message: string;
  action?: ReactNode;
};

type EmptyStateProps = {
  title: string;
  message: string;
  action?: ReactNode;
};

export function LoadingState({
  title = "Loading workspace",
  message = "Preparing the latest financial operations state...",
}: LoadingStateProps) {
  return (
    <div className="state-card loading-card" role="status" aria-live="polite">
      <div className="loading-skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div className="loading-copy">
        <h2>{title}</h2>
        <p>{message}</p>
      </div>
    </div>
  );
}

export function ErrorState({
  title = "Something needs attention",
  message,
  action,
}: ErrorStateProps) {
  return (
    <div className="state-card state-card-error" role="alert">
      <div className="state-icon" aria-hidden="true">
        !
      </div>
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
        {action ? <div className="state-action">{action}</div> : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, message, action }: EmptyStateProps) {
  return (
    <div className="state-card">
      <div className="state-icon" aria-hidden="true">
        ·
      </div>
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
        {action ? <div className="state-action">{action}</div> : null}
      </div>
    </div>
  );
}
