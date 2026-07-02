const uploadChecks = [
  "File type, size, and MIME validation",
  "Content hash for duplicate detection",
  "DocumentIngested workflow trigger",
];

const acceptedTypes = ["PDF", "PNG", "JPEG", "CSV"];

const recentUploads = [
  {
    name: "invoice-acme-1042.pdf",
    status: "Pending review",
    meta: "Invoice · $2,480.00 · 2 min ago",
  },
  {
    name: "bank-statement-june.csv",
    status: "Parsed",
    meta: "Statement · 84 transactions · 8 min ago",
  },
  {
    name: "saas-vendor-receipt.png",
    status: "Duplicate",
    meta: "Expense · matched by content hash",
  },
];

export default function UploadPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Document intake</p>
          <h2>Upload invoices and bank statements.</h2>
          <p>
            Validate documents before agent workflows create extraction and
            review proposals.
          </p>
        </div>
        <span className="status-pill">Upload API ready</span>
      </section>

      <section className="upload-layout">
        <article className="upload-dropzone">
          <div className="upload-toolbar" aria-label="Upload mode selector">
            <span className="toolbar-chip toolbar-chip-active">Documents</span>
            <span className="toolbar-chip">Bank statements</span>
          </div>
          <div className="upload-icon" aria-hidden="true">
            DOC
          </div>
          <h3>Drop files here or browse</h3>
          <p>
            Invoices, receipts, and bank statements will be validated before the
            workflow starts.
          </p>
          <button className="button button-primary" type="button">
            Choose files
          </button>
          <div className="file-type-row" aria-label="Accepted file types">
            {acceptedTypes.map((type) => (
              <span key={type}>{type}</span>
            ))}
          </div>
          <small>Placeholder only, file picker will be wired next.</small>
        </article>

        <aside className="panel-card">
          <p className="eyebrow">Preflight checks</p>
          <h3>What happens before processing</h3>
          <div className="check-list">
            {uploadChecks.map((check) => (
              <div className="check-row" key={check}>
                <span className="check-marker" aria-hidden="true">
                  OK
                </span>
                <p>{check}</p>
              </div>
            ))}
          </div>
        </aside>
      </section>

      <section className="panel-card">
        <div className="card-header">
          <div>
            <p className="eyebrow">Recent activity</p>
            <h3>Upload status preview</h3>
          </div>
          <span className="status-pill status-pill-muted">Mock data</span>
        </div>
        <div className="activity-list">
          {recentUploads.map((upload) => (
            <div className="activity-row" key={upload.name}>
              <div>
                <strong>{upload.name}</strong>
                <span>{upload.meta}</span>
              </div>
              <em>{upload.status}</em>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
