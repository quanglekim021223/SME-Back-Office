import Link from "next/link";

export default function NotFound() {
  return (
    <section className="not-found-card">
      <p className="eyebrow">Route not found</p>
      <h2>This workspace page does not exist.</h2>
      <p>
        The route may belong to a future phase, or the link may be outdated. You
        can return to the dashboard and continue from the current MVP surface.
      </p>
      <div className="hero-actions">
        <Link className="button button-primary" href="/">
          Back to dashboard
        </Link>
        <Link className="button button-secondary" href="/review">
          Open review queue
        </Link>
      </div>
    </section>
  );
}
