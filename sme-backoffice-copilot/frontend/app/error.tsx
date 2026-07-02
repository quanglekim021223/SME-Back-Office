"use client";

import { ErrorState } from "./_components/status-states";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <ErrorState
      action={
        <button className="button button-primary" onClick={reset} type="button">
          Try again
        </button>
      }
      message={error.message}
      title="The workspace could not load"
    />
  );
}
