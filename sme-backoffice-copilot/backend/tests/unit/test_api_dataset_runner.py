import json
from pathlib import Path

import pytest

from app.evaluations.api_dataset_runner import (
    ApiClient,
    discover_cases,
    evaluate_dataset,
    normalize_amount,
    normalize_date,
    normalize_identifier,
    score_invoice,
    write_case_artifacts,
)


def test_discover_cases_pairs_images_and_annotations_by_basename(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    annotations = tmp_path / "annotations"
    images.mkdir()
    annotations.mkdir()
    (images / "case-b.jpg").write_bytes(b"image")
    (images / "case-a.png").write_bytes(b"image")
    (images / "unlabelled.jpg").write_bytes(b"image")
    (annotations / "case-a.txt").write_text("{}", encoding="utf-8")
    (annotations / "case-b.json").write_text("{}", encoding="utf-8")

    pairs = discover_cases(images, annotations)

    assert [(image.stem, label.stem) for image, label in pairs] == [
        ("case-a", "case-a"),
        ("case-b", "case-b"),
    ]


def test_discover_cases_applies_offset_before_limit(tmp_path: Path) -> None:
    images = tmp_path / "images"
    annotations = tmp_path / "annotations"
    images.mkdir()
    annotations.mkdir()
    for stem in ("case-c", "case-a", "case-b"):
        (images / f"{stem}.jpg").write_bytes(b"image")
        (annotations / f"{stem}.json").write_text("{}", encoding="utf-8")

    pairs = discover_cases(images, annotations, offset=1, limit=2)

    assert [image.stem for image, _ in pairs] == ["case-b", "case-c"]


def test_public_dataset_annotation_is_valid_json(tmp_path: Path) -> None:
    annotation = tmp_path / "case.txt"
    annotation.write_text(
        json.dumps({"company": "Empresa Exemplo", "total": "32,00"}),
        encoding="utf-8",
    )

    assert json.loads(annotation.read_text(encoding="utf-8"))["total"] == "32,00"


def test_normalizers_support_portuguese_invoice_values() -> None:
    assert normalize_amount("1.234,56 €") == "1234.56"
    assert normalize_amount("1234.56") == "1234.56"
    assert normalize_date("18/01/2019") == "2019-01-18"
    assert normalize_date("2019/01/24") == "2019-01-24"
    assert normalize_date("23.01.19") == "2019-01-23"
    assert normalize_date("06 abr 2018") == "2018-04-06"
    assert normalize_identifier("513 350 535") == "513350535"
    assert normalize_identifier("NIF:500602760") == "500602760"


def test_score_invoice_maps_public_labels_to_api_fields() -> None:
    score = score_invoice(
        {
            "company": "JMTD - Ferragens do Combro Lda",
            "date": "18/01/2019",
            "total": "32,00",
            "invoice_number": "A/28564",
            "nif_buyer": "510776914",
            "iva_amount": "5,98",
            "nif_seller": "513 350 535",
        },
        {
            "supplier_name": "JMTD Ferragens do Combro Lda.",
            "issue_date": "2019-01-18",
            "total_amount": "32.00",
            "invoice_number": "A-28564",
            "customer_tax_id": "510776914",
            "tax_amount": "5.98",
            "supplier_tax_id": "513350535",
        },
    )

    assert score["score"] == 1.0
    assert score["passed_fields"] == 7
    assert score["compared_fields"] == 7


def test_score_invoice_accepts_short_brand_inside_legal_supplier_name() -> None:
    score = score_invoice(
        {"company": "algesdecor"},
        {"supplier_name": "ALGESDECOR\nCOMERCIO DE TINTAS, LDA."},
    )

    assert score["score"] == 1.0


def test_score_invoice_reports_fuzzy_and_exact_supplier_metrics() -> None:
    score = score_invoice(
        {"company": "Nascimento da Silva Filhos Lda"},
        {"supplier_name": "NASCIMENTO DA SILUA FILHOS LDA"},
    )

    assert score["score"] == 1.0
    assert score["exact_score"] == 0.0
    assert score["checks"]["supplier_name"]["passed"] is True
    assert score["checks"]["supplier_name"]["exact_passed"] is False
    assert score["checks"]["supplier_name"]["similarity"] >= 0.85


def test_score_invoice_accepts_equivalent_invoice_document_prefixes() -> None:
    score = score_invoice(
        {"invoice_number": "K1190120396"},
        {"invoice_number": "RECIB0 K1190120396"},
    )

    assert score["score"] == 1.0
    assert score["exact_score"] == 0.0


class FailedWorkflowClient(ApiClient):
    def __init__(self, status: str = "failed") -> None:
        self.status = status

    def upload(self, image_path: Path) -> tuple[str, str | None, bool]:
        del image_path
        return "document-1", "workflow-1", False

    def wait_for_workflow(
        self,
        workflow_run_id: str,
        *,
        timeout_seconds: float,
        poll_interval: float,
    ) -> dict:
        del workflow_run_id, timeout_seconds, poll_interval
        return {
            "status": self.status,
            "stage": "failed",
            "error_code": "ERR_OCR_PROVIDER_FAILED",
            "error_message": "HTTP 429",
        }

    def wait_for_invoice(
        self,
        document_id: str,
        *,
        timeout_seconds: float,
        poll_interval: float,
    ) -> dict:
        raise AssertionError("failed workflow must not wait for an invoice")


@pytest.mark.parametrize(
    "terminal_status",
    ["failed", "lost", "cancelled", "dead_lettered"],
)
def test_evaluator_skips_invoice_poll_when_workflow_failed(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    images = tmp_path / "images"
    annotations = tmp_path / "annotations"
    images.mkdir()
    annotations.mkdir()
    (images / "case.jpg").write_bytes(b"image")
    (annotations / "case.json").write_text(
        json.dumps({"total": "10.00"}),
        encoding="utf-8",
    )

    report = evaluate_dataset(
        images_dir=images,
        annotations_dir=annotations,
        client=FailedWorkflowClient(terminal_status),
        limit=None,
        timeout_seconds=180,
        poll_interval=2,
    )

    assert report["error_case_count"] == 1
    assert report["results"][0]["error_type"] == "RuntimeError"
    assert f"status={terminal_status}" in report["results"][0]["error"]
    assert "HTTP 429" in report["results"][0]["error"]


class DuplicateFailedClient(ApiClient):
    def __init__(self) -> None:
        self.reprocessed_document_id: str | None = None

    def upload(self, image_path: Path) -> tuple[str, str | None, bool]:
        del image_path
        return "document-1", None, True

    def find_invoice(self, document_id: str) -> dict | None:
        assert document_id == "document-1"
        return None

    def reprocess(self, document_id: str) -> str:
        self.reprocessed_document_id = document_id
        return "workflow-2"

    def wait_for_workflow(
        self,
        workflow_run_id: str,
        *,
        timeout_seconds: float,
        poll_interval: float,
    ) -> dict:
        del timeout_seconds, poll_interval
        assert workflow_run_id == "workflow-2"
        return {
            "status": "review_required",
            "stage": "review",
            "progress": {"is_terminal": True},
        }

    def wait_for_invoice(
        self,
        document_id: str,
        *,
        timeout_seconds: float,
        poll_interval: float,
    ) -> dict:
        del timeout_seconds, poll_interval
        assert document_id == "document-1"
        return {
            "id": "invoice-1",
            "document_id": document_id,
            "status": "pending_review",
            "total_amount": "10.00",
        }

    def find_ocr_evidence(self, invoice_id: str) -> dict:
        assert invoice_id == "invoice-1"
        return {
            "text": "FATURA A/28564\nTOTAL 10,00",
            "text_length": 28,
            "possibly_truncated": False,
            "layout_blocks": [],
            "layout_diagnostics": {},
            "extraction_routing": {
                "metadata": {
                    "strategy": "deterministic_fast_path",
                    "llm_invoked": False,
                },
                "totals": {
                    "strategy": "llm_fallback",
                    "llm_invoked": True,
                },
            },
        }


def test_evaluator_reprocesses_duplicate_without_invoice(tmp_path: Path) -> None:
    images = tmp_path / "images"
    annotations = tmp_path / "annotations"
    images.mkdir()
    annotations.mkdir()
    (images / "case.jpg").write_bytes(b"image")
    (annotations / "case.json").write_text(
        json.dumps({"total": "10.00"}),
        encoding="utf-8",
    )
    client = DuplicateFailedClient()

    report = evaluate_dataset(
        images_dir=images,
        annotations_dir=annotations,
        client=client,
        limit=None,
        timeout_seconds=180,
        poll_interval=2,
    )

    result = report["results"][0]
    assert client.reprocessed_document_id == "document-1"
    assert result["reprocessed"] is True
    assert result["workflow_run_id"] == "workflow-2"
    assert result["status"] == "scored"
    assert result["score"] == 1.0
    assert report["exact_field_accuracy"] == 1.0
    assert result["ocr_evidence"]["text"].startswith("FATURA")
    assert report["routing"] == {
        "decision_count": 2,
        "llm_invocation_count": 1,
        "llm_invocation_rate": 0.5,
        "deterministic_fast_path_count": 1,
    }


def test_write_case_artifacts_exports_ocr_text_and_diagnostics(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    write_case_artifacts(
        {
            "results": [
                {
                    "case_id": "invoice-1",
                    "image": "/tmp/invoice-1.jpg",
                    "annotation": "/tmp/invoice-1.json",
                    "status": "scored",
                    "ocr_evidence": {
                        "text": "FATURA A/28564\nTOTAL 10,00",
                        "text_length": 28,
                        "possibly_truncated": False,
                        "layout_blocks": [{"text": "FATURA"}],
                    },
                    "extracted_invoice": {"invoice_number": "A/28564"},
                    "checks": {"invoice_number": {"passed": True}},
                }
            ]
        },
        artifacts_dir,
    )

    assert (artifacts_dir / "invoice-1.ocr.txt").read_text(
        encoding="utf-8"
    ) == "FATURA A/28564\nTOTAL 10,00"
    payload = json.loads((artifacts_dir / "invoice-1.json").read_text(encoding="utf-8"))
    assert payload["ocr_evidence"]["layout_blocks"] == [{"text": "FATURA"}]
    assert payload["extracted_invoice"]["invoice_number"] == "A/28564"


class CapturingProfileClient(ApiClient):
    def __init__(self) -> None:
        super().__init__(
            api_url="http://test/api/v1",
            tenant_id="tenant",
            user_id="user",
            user_role="member",
            profile="local",
        )
        self.paths: list[str] = []

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict:
        del method, body, content_type
        self.paths.append(path)
        if "/reprocess" in path:
            return {"workflow_run_id": "workflow-2"}
        return {
            "id": "document-1",
            "workflow_trigger": {"workflow_run_id": "workflow-1"},
        }


def test_api_client_sends_selected_profile(tmp_path: Path) -> None:
    image = tmp_path / "invoice.jpg"
    image.write_bytes(b"image")
    client = CapturingProfileClient()

    client.upload(image)
    client.reprocess("document-1")

    assert "profile=local" in client.paths[0]
    assert client.paths[1].endswith("/reprocess?profile=local")
