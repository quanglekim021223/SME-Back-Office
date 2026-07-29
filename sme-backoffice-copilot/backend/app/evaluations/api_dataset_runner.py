"""Evaluate the live invoice API against paired image and JSON annotations."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import time
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_API_URL = "http://localhost:8000/api/v1"
DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_USER_ID = "00000000-0000-4000-8000-000000000101"
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".pdf"}
PROCESSING_PROFILES = ("azure", "local", "hybrid")

FIELD_SPECS = {
    "invoice_number": ("invoice_number", "invoice_number"),
    "supplier_name": ("company", "entity_name"),
    "supplier_tax_id": ("nif_seller", "identifier"),
    "customer_tax_id": ("nif_buyer", "identifier"),
    "issue_date": ("date", "date"),
    "tax_amount": ("iva_amount", "amount"),
    "total_amount": ("total", "amount"),
}

PORTUGUESE_MONTHS = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}


def print_status(message: str) -> None:
    """Print one timestamped progress event immediately."""

    timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


class ApiRequestError(RuntimeError):
    """An API call failed with a structured response."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        super().__init__(f"API request failed with HTTP {status}")
        self.status = status
        self.payload = payload


def discover_cases(
    images_dir: Path,
    annotations_dir: Path,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[tuple[Path, Path]]:
    """Pair supported document files with annotation files by basename."""

    annotation_by_stem = {
        path.stem: path
        for path in annotations_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".txt", ".json"}
    }
    pairs = [
        (image, annotation_by_stem[image.stem])
        for image in sorted(images_dir.iterdir())
        if image.is_file()
        and image.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
        and image.stem in annotation_by_stem
    ]
    end = offset + limit if limit is not None else None
    return pairs[offset:end]


def load_annotation(path: Path) -> dict[str, Any]:
    """Load one JSON annotation, including datasets that use a .txt suffix."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Annotation must be a JSON object: {path}")
    return payload


def normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split()) or None


def normalize_identifier(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    digits = "".join(re.findall(r"\d+", text))
    if digits:
        return digits
    normalized = re.sub(r"\W+", "", text, flags=re.UNICODE).casefold()
    return normalized or None


def normalize_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    for date_format in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d.%m.%y",
    ):
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    portuguese_date = re.fullmatch(
        r"(\d{1,2})\s+([a-zç]{3})\s+(\d{4})",
        text.casefold(),
    )
    if portuguese_date:
        day, month_name, year = portuguese_date.groups()
        month = PORTUGUESE_MONTHS.get(month_name)
        if month is not None:
            return datetime(int(year), month, int(day)).date().isoformat()
    return normalize_text(text)


def normalize_amount(value: object) -> str | None:
    if value is None:
        return None
    text = re.sub(r"[^\d,.\-]", "", str(value).strip())
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return format(Decimal(text).quantize(Decimal("0.01")), "f")
    except InvalidOperation:
        return normalize_text(value)


def normalize_value(value: object, kind: str) -> str | None:
    normalizers = {
        "amount": normalize_amount,
        "date": normalize_date,
        "entity_name": normalize_text,
        "identifier": normalize_identifier,
        "invoice_number": normalize_text,
        "text": normalize_text,
    }
    return normalizers[kind](value)


def values_match(expected: str | None, actual: str | None, kind: str) -> bool:
    """Match normalized values, allowing a labelled brand inside a legal name."""

    if expected is None or actual is None:
        return expected == actual
    if kind == "entity_name":
        expected_tokens = set(expected.split())
        actual_tokens = set(actual.split())
        if expected_tokens <= actual_tokens or actual_tokens <= expected_tokens:
            return True
        return entity_name_similarity(expected, actual) >= 0.85
    if kind == "invoice_number":
        return canonical_invoice_number(expected) == canonical_invoice_number(actual)
    return expected == actual


def entity_name_similarity(expected: str, actual: str) -> float:
    """Return typo-tolerant similarity without hiding the exact-match metric."""

    compact_expected = re.sub(r"\W+", "", expected, flags=re.UNICODE)
    compact_actual = re.sub(r"\W+", "", actual, flags=re.UNICODE)
    return SequenceMatcher(None, compact_expected, compact_actual).ratio()


def canonical_invoice_number(value: str) -> str:
    """Remove document-type prefixes while preserving the printed identifier."""

    tokens = value.split()
    while tokens and re.fullmatch(
        r"(?:fatura|factura|rec[i1]b[o0]|p[o0]st|f[st1r]|fac)",
        tokens[0],
        flags=re.IGNORECASE,
    ):
        tokens.pop(0)
    return " ".join(tokens)


def score_invoice(
    annotation: dict[str, Any],
    invoice: dict[str, Any],
) -> dict[str, Any]:
    """Compare supported public-dataset labels with the persisted invoice."""

    checks: dict[str, dict[str, Any]] = {}
    for output_field, (annotation_field, kind) in FIELD_SPECS.items():
        expected_raw = annotation.get(annotation_field)
        if expected_raw in (None, ""):
            continue
        actual_raw = invoice.get(output_field)
        expected = normalize_value(expected_raw, kind)
        actual = normalize_value(actual_raw, kind)
        exact_passed = expected == actual
        similarity = (
            entity_name_similarity(expected, actual)
            if kind == "entity_name" and expected is not None and actual is not None
            else None
        )
        checks[output_field] = {
            "passed": values_match(expected, actual, kind),
            "exact_passed": exact_passed,
            "expected": expected,
            "actual": actual,
            "expected_raw": expected_raw,
            "actual_raw": actual_raw,
        }
        if similarity is not None:
            checks[output_field]["similarity"] = round(similarity, 4)

    passed = sum(1 for check in checks.values() if check["passed"])
    exact_passed_count = sum(1 for check in checks.values() if check["exact_passed"])
    total = len(checks)
    return {
        "score": passed / total if total else 0.0,
        "exact_score": exact_passed_count / total if total else 0.0,
        "passed_fields": passed,
        "exact_passed_fields": exact_passed_count,
        "compared_fields": total,
        "checks": checks,
    }


class ApiClient:
    """Small stdlib HTTP client for the development API."""

    def __init__(
        self,
        *,
        api_url: str,
        tenant_id: str,
        user_id: str,
        user_role: str,
        profile: str,
        reuse_existing: bool = False,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.profile = profile
        self.reuse_existing = reuse_existing
        self.headers = {
            "X-Tenant-ID": tenant_id,
            "X-User-ID": user_id,
            "X-User-Role": user_role,
        }

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        headers = dict(self.headers)
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(
            f"{self.api_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            try:
                error_payload = json.loads(raw_body)
            except json.JSONDecodeError:
                error_payload = {"detail": raw_body}
            raise ApiRequestError(exc.code, error_payload) from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach API at {self.api_url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Expected JSON object from {path}")
        return payload

    def upload(self, image_path: Path) -> tuple[str, str | None, bool]:
        params = urlencode(
            {
                "filename": image_path.name,
                "document_type": "invoice",
                "profile": self.profile,
            }
        )
        content_type = (
            mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        )
        try:
            payload = self.request_json(
                "POST",
                f"/documents/upload?{params}",
                body=image_path.read_bytes(),
                content_type=content_type,
            )
            trigger = payload.get("workflow_trigger") or {}
            return (
                str(payload["id"]),
                str(trigger["workflow_run_id"])
                if trigger.get("workflow_run_id")
                else None,
                False,
            )
        except ApiRequestError as exc:
            error = exc.payload.get("error") or {}
            if exc.status != 409 or error.get("code") != "duplicate_document":
                raise
            document_id = (error.get("details") or {}).get("document_id")
            if not document_id:
                raise
            return str(document_id), None, True

    def wait_for_workflow(
        self,
        workflow_run_id: str,
        *,
        timeout_seconds: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_state: tuple[object, object, object] | None = None
        while time.monotonic() < deadline:
            payload = self.request_json("GET", f"/workflow-runs/{workflow_run_id}")
            progress = payload.get("progress") or {}
            state = (
                payload.get("status"),
                payload.get("stage"),
                payload.get("current_agent"),
            )
            if state != last_state:
                print_status(
                    "workflow "
                    f"{workflow_run_id[:8]} status={state[0]} "
                    f"stage={state[1]} agent={state[2] or '—'}"
                )
                last_state = state
            if progress.get("is_terminal") is True:
                return payload
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Workflow {workflow_run_id} exceeded {timeout_seconds:.0f}s"
        )

    def wait_for_invoice(
        self,
        document_id: str,
        *,
        timeout_seconds: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        print_status(f"waiting for invoice document={document_id[:8]}")
        while time.monotonic() < deadline:
            invoice = self.find_invoice(document_id)
            if invoice is not None:
                print_status(
                    f"invoice found id={str(invoice['id'])[:8]} "
                    f"status={invoice.get('status')}"
                )
                return invoice
            time.sleep(poll_interval)
        raise TimeoutError(
            f"No invoice was persisted for document {document_id} "
            f"within {timeout_seconds:.0f}s"
        )

    def find_invoice(self, document_id: str) -> dict[str, Any] | None:
        """Return a persisted invoice for a document without polling."""

        payload = self.request_json(
            "GET", "/invoices?limit=200&exclude_superseded=false"
        )
        for invoice in payload.get("items", []):
            if str(invoice.get("document_id")) == document_id:
                return self.request_json("GET", f"/invoices/{invoice['id']}")
        return None

    def find_ocr_evidence(self, invoice_id: str) -> dict[str, Any] | None:
        """Return persisted OCR diagnostics from an invoice review task."""

        payload = self.request_json(
            "GET",
            "/review-tasks?task_type=extraction&limit=100&offset=0",
        )
        for summary in payload.get("items", []):
            review_task_id = summary.get("id")
            if not review_task_id:
                continue
            detail = self.request_json("GET", f"/review-tasks/{review_task_id}")
            if str(detail.get("invoice_id")) != invoice_id:
                continue
            metadata = detail.get("metadata") or {}
            raw_text = metadata.get("ocr_text_preview")
            layout_blocks = metadata.get("ocr_layout_blocks") or []
            diagnostics = metadata.get("ocr_layout_diagnostics") or {}
            extraction_routing = metadata.get("extraction_routing") or {}
            return {
                "review_task_id": str(review_task_id),
                "text": raw_text if isinstance(raw_text, str) else "",
                "text_length": len(raw_text) if isinstance(raw_text, str) else 0,
                "possibly_truncated": (
                    isinstance(raw_text, str) and len(raw_text) >= 2000
                ),
                "layout_blocks": layout_blocks
                if isinstance(layout_blocks, list)
                else [],
                "layout_diagnostics": diagnostics
                if isinstance(diagnostics, dict)
                else {},
                "extraction_routing": extraction_routing
                if isinstance(extraction_routing, dict)
                else {},
            }
        return None

    def reprocess(self, document_id: str) -> str:
        """Queue a fresh workflow run for a previously failed document."""

        params = urlencode({"profile": self.profile})
        payload = self.request_json(
            "POST",
            f"/documents/{document_id}/reprocess?{params}",
        )
        workflow_run_id = payload.get("workflow_run_id")
        if not workflow_run_id:
            raise RuntimeError(
                f"Reprocess response for document {document_id} had no workflow run."
            )
        return str(workflow_run_id)


def evaluate_dataset(
    *,
    images_dir: Path,
    annotations_dir: Path,
    client: ApiClient,
    limit: int | None,
    timeout_seconds: float,
    poll_interval: float,
    offset: int = 0,
) -> dict[str, Any]:
    """Run the end-to-end API evaluation sequentially."""

    pairs = discover_cases(
        images_dir,
        annotations_dir,
        offset=offset,
        limit=limit,
    )
    if not pairs:
        raise ValueError("No image/annotation pairs were found.")

    results: list[dict[str, Any]] = []
    field_totals: dict[str, dict[str, int]] = {}
    started_at = time.monotonic()

    selection_end = offset + len(pairs)
    for index, (image_path, annotation_path) in enumerate(
        pairs,
        start=offset + 1,
    ):
        case_started_at = time.monotonic()
        case_label = f"[{index}/{selection_end}] {image_path.name}"
        print_status(f"{case_label} started")
        result: dict[str, Any] = {
            "case_id": image_path.stem,
            "image": str(image_path),
            "annotation": str(annotation_path),
        }
        try:
            annotation = load_annotation(annotation_path)
            print_status(f"{case_label} annotation loaded")
            document_id, workflow_run_id, duplicate = client.upload(image_path)
            print_status(
                f"{case_label} uploaded document={document_id[:8]} "
                f"duplicate={duplicate}"
            )
            result.update(
                {
                    "document_id": document_id,
                    "workflow_run_id": workflow_run_id,
                    "duplicate": duplicate,
                }
            )
            existing_invoice = client.find_invoice(document_id) if duplicate else None
            if (
                duplicate
                and existing_invoice is not None
                and not getattr(client, "reuse_existing", False)
            ):
                raise RuntimeError(
                    "Duplicate already has an invoice. Reset the evaluation tenant "
                    "for a clean profile comparison, or pass --reuse-existing "
                    "to score the stored result."
                )
            if duplicate and existing_invoice is None:
                print_status(
                    f"{case_label} duplicate has no invoice; queueing reprocess"
                )
                workflow_run_id = client.reprocess(document_id)
                result["workflow_run_id"] = workflow_run_id
                result["reprocessed"] = True
                print_status(
                    f"{case_label} reprocess queued workflow={workflow_run_id[:8]}"
                )
            if workflow_run_id:
                workflow = client.wait_for_workflow(
                    workflow_run_id,
                    timeout_seconds=timeout_seconds,
                    poll_interval=poll_interval,
                )
                result["workflow_status"] = workflow.get("status")
                result["workflow_stage"] = workflow.get("stage")
                if workflow.get("status") in {
                    "failed",
                    "lost",
                    "cancelled",
                    "dead_lettered",
                }:
                    raise RuntimeError(
                        "Workflow terminated "
                        f"with status={workflow.get('status')} "
                        f"({workflow.get('error_code') or 'unknown'}): "
                        f"{workflow.get('error_message') or 'no error message'}"
                    )
            invoice = existing_invoice or client.wait_for_invoice(
                document_id,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
            score = score_invoice(annotation, invoice)
            try:
                ocr_evidence = client.find_ocr_evidence(str(invoice["id"]))
            except Exception as exc:  # noqa: BLE001 - scoring must still complete
                ocr_evidence = {
                    "capture_error": f"{type(exc).__name__}: {exc}",
                }
            result.update(
                {
                    "status": "scored",
                    "invoice_id": invoice.get("id"),
                    "invoice_status": invoice.get("status"),
                    "extracted_invoice": invoice,
                    "ocr_evidence": ocr_evidence,
                    **score,
                }
            )
            print_status(
                f"{case_label} scored "
                f"{score['passed_fields']}/{score['compared_fields']} "
                f"({score['score']:.1%})"
            )
            for field, check in score["checks"].items():
                totals = field_totals.setdefault(
                    field,
                    {"passed": 0, "exact_passed": 0, "total": 0},
                )
                totals["total"] += 1
                totals["passed"] += int(check["passed"])
                totals["exact_passed"] += int(check["exact_passed"])
        except Exception as exc:  # noqa: BLE001 - report and continue the batch
            result.update(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            print_status(f"{case_label} error: {type(exc).__name__}: {exc}")
        result["duration_seconds"] = round(time.monotonic() - case_started_at, 3)
        print_status(
            f"{case_label} finished in {result['duration_seconds']:.1f}s "
            f"status={result['status']}"
        )
        results.append(result)

    passed_fields = sum(item["passed"] for item in field_totals.values())
    exact_passed_fields = sum(item["exact_passed"] for item in field_totals.values())
    compared_fields = sum(item["total"] for item in field_totals.values())
    routing_decisions = [
        decision
        for result in results
        if result.get("status") == "scored"
        for decision in (
            (result.get("ocr_evidence") or {}).get("extraction_routing") or {}
        ).values()
        if isinstance(decision, dict)
    ]
    llm_invocation_count = sum(
        1 for decision in routing_decisions if decision.get("llm_invoked") is True
    )
    return {
        "schema_version": "api-dataset-evaluation.v1",
        "profile": getattr(client, "profile", "azure"),
        "images_dir": str(images_dir),
        "annotations_dir": str(annotations_dir),
        "offset": offset,
        "case_count": len(results),
        "scored_case_count": sum(
            1 for result in results if result["status"] == "scored"
        ),
        "error_case_count": sum(1 for result in results if result["status"] == "error"),
        "field_accuracy": (passed_fields / compared_fields if compared_fields else 0.0),
        "exact_field_accuracy": (
            exact_passed_fields / compared_fields if compared_fields else 0.0
        ),
        "passed_fields": passed_fields,
        "exact_passed_fields": exact_passed_fields,
        "compared_fields": compared_fields,
        "routing": {
            "decision_count": len(routing_decisions),
            "llm_invocation_count": llm_invocation_count,
            "llm_invocation_rate": (
                llm_invocation_count / len(routing_decisions)
                if routing_decisions
                else 0.0
            ),
            "deterministic_fast_path_count": sum(
                1
                for decision in routing_decisions
                if str(decision.get("strategy", "")).startswith("deterministic")
            ),
        },
        "fields": {
            field: {
                **counts,
                "accuracy": counts["passed"] / counts["total"]
                if counts["total"]
                else 0.0,
                "exact_accuracy": counts["exact_passed"] / counts["total"]
                if counts["total"]
                else 0.0,
            }
            for field, counts in sorted(field_totals.items())
        },
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload paired invoice images to the live API and compare persisted "
            "fields with JSON annotations."
        )
    )
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--user-role", default="member")
    parser.add_argument(
        "--profile",
        choices=PROCESSING_PROFILES,
        default="azure",
        help="Provider profile used for every uploaded or reprocessed invoice.",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Score stored duplicate invoices instead of requiring a clean run.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N sorted image/annotation pairs.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help=(
            "Directory for per-case OCR text and JSON diagnostics. Defaults to "
            "<output-stem>-artifacts beside the report."
        ),
    )
    return parser.parse_args()


def write_case_artifacts(report: dict[str, Any], artifacts_dir: Path) -> None:
    """Write human-readable OCR text and diagnostics for every evaluated case."""

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for result in report.get("results", []):
        case_id = str(result.get("case_id") or "unknown")
        evidence = result.get("ocr_evidence") or {}
        text = evidence.get("text") if isinstance(evidence, dict) else ""
        (artifacts_dir / f"{case_id}.ocr.txt").write_text(
            text if isinstance(text, str) else "",
            encoding="utf-8",
        )
        artifact_payload = {
            "case_id": case_id,
            "image": result.get("image"),
            "annotation": result.get("annotation"),
            "status": result.get("status"),
            "ocr_evidence": evidence,
            "extracted_invoice": result.get("extracted_invoice"),
            "field_checks": result.get("checks"),
        }
        (artifacts_dir / f"{case_id}.json").write_text(
            json.dumps(artifact_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def main() -> int:
    args = parse_args()
    if not args.images.is_dir():
        raise SystemExit(f"Images directory does not exist: {args.images}")
    if not args.annotations.is_dir():
        raise SystemExit(f"Annotations directory does not exist: {args.annotations}")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if args.offset < 0:
        raise SystemExit("--offset must be at least 0")

    client = ApiClient(
        api_url=args.api_url,
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        user_role=args.user_role,
        profile=args.profile,
        reuse_existing=args.reuse_existing,
    )
    report = evaluate_dataset(
        images_dir=args.images.resolve(),
        annotations_dir=args.annotations.resolve(),
        client=client,
        limit=args.limit,
        timeout_seconds=args.timeout,
        poll_interval=args.poll_interval,
        offset=args.offset,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    artifacts_dir = (
        args.artifacts_dir
        if args.artifacts_dir is not None
        else args.output.with_name(f"{args.output.stem}-artifacts")
    )
    write_case_artifacts(report, artifacts_dir)
    print(
        f"Scored {report['scored_case_count']}/{report['case_count']} cases; "
        f"profile={report['profile']}; "
        f"field accuracy={report['field_accuracy']:.2%}; "
        f"exact field accuracy={report['exact_field_accuracy']:.2%}; "
        f"report={args.output}; artifacts={artifacts_dir}"
    )
    return 0 if report["error_case_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
