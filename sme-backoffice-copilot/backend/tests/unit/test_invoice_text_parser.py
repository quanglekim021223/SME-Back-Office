from pathlib import Path

import pytest

from app.extraction.invoice_text_parser import (
    parse_invoice_metadata_group_payload,
    parse_invoice_table_group_payload,
    parse_invoice_totals_group_payload,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "invoices"

SAMPLE_INVOICE_OCR_TEXT = """Your Company Inc.
1234 Company St,
Company Town, ST 12345

INVOICE

Bill To
Customer Name
1234 Customer St,
Customer Town, ST 12345

Invoice # 0000007
Invoice date 10-02-2023
Due date 10-16-2023

QTY Description Unit Price Amount
1.00 Replacement of spark plugs 40.00 $40.00
2.00 Brake pad replacement ( front ) 40.00 $80.00
4.00 Wheel alignment 17.50 $70.00
2.00 Mechanic's rate per hour 30.00 $60.00

Subtotal $250.00
Sales Tax (5%) $12.50
Total (USD) $262.50
"""

NOISY_FLAT_INVOICE_OCR_TEXT = (
    "‘Your Company inc. 1284 Company & Upload Logo ‘company Town, ST12845 "
    "l J INVOICE inte Customer Name Invoice ‘0000007 sasacustomer se "
    "Invoicedate 10-02-2025 ‘customar Town, ST 22545 0-16-2028 "
    "TY Description ice Amount 1100 Replacement of sparkpiugs 4000 $4000 "
    "200 Brake pad replacement (front) 4000 $8000 "
    "“400 whoo aignment 1750 $7000 "
    "200 Mechanic's rate perhour 3000 $6000 "
    "Subtotal $250.00 Sales Tax (5%) sizs0 Total USD) $262.50 "
    "‘Terms and Conditions Payments uein aye Pease make checks payable to: "
    "Your Company ne."
)

PADDLEOCR_LINE_SPLIT_INVOICE_TEXT = """Your Company Inc.
1234 Company St.
Upload Logo
Company Town, ST 12345
INVOICE
Bill To
Customer Name
Invoice#
0000007
1234 Customer St.
Invoice date
10-02-2023
Customer Town, ST 12345
Due date
10-16-2023
QTY Description
Unit Price
Amount
1.00 Replacement of spark plugs
40.00
$40.00
2.00 Brake pad replacement (front)
40.00
$80.00
4.00 Wheel alignment
17.50
$70.00
2.00 Mechanic's rate per hour
30.00
$60.00
Subtotal
$250.00
Sales Tax (5%)
$12.50
Total (USD)
$262.50
Terms and Conditions
Payment is due in 14 days
Please make checks payable to: Your Company Inc.
"""


def test_invoice_text_parser_extracts_metadata_from_common_invoice_ocr() -> None:
    payload = parse_invoice_metadata_group_payload(
        ocr_text=SAMPLE_INVOICE_OCR_TEXT,
        evidence_refs=["page:1"],
    )

    assert payload["extraction_status"] == "partial"
    assert payload["invoice_number"] == "0000007"
    assert payload["supplier_name"] == "Your Company Inc."
    assert payload["customer_name"] == "Customer Name"
    assert payload["issue_date"] == "2023-10-02"
    assert payload["due_date"] == "2023-10-16"
    assert payload["currency"] == "USD"


def test_invoice_text_parser_extracts_totals_from_common_invoice_ocr() -> None:
    payload = parse_invoice_totals_group_payload(
        ocr_text=SAMPLE_INVOICE_OCR_TEXT,
        evidence_refs=["page:1"],
    )

    assert payload["extraction_status"] == "partial"
    assert payload["subtotal_amount"] == "250.00"
    assert payload["tax_amount"] == "12.50"
    assert payload["total_amount"] == "262.50"
    assert payload["currency"] == "USD"


def test_invoice_text_parser_extracts_table_rows_from_common_invoice_ocr() -> None:
    payload = parse_invoice_table_group_payload(
        ocr_text=SAMPLE_INVOICE_OCR_TEXT,
        evidence_refs=["page:1"],
    )

    line_items = payload["line_items"]
    assert isinstance(line_items, list)
    assert len(line_items) == 4
    assert line_items[0]["description"] == "Replacement of spark plugs"
    assert line_items[0]["quantity"] == "1.00"
    assert line_items[0]["unit_price"] == "40.00"
    assert line_items[0]["line_total"] == "40.00"
    assert line_items[-1]["description"] == "Mechanic's rate per hour"
    assert line_items[-1]["line_total"] == "60.00"


def test_invoice_text_parser_extracts_totals_from_line_split_paddleocr_text() -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text=PADDLEOCR_LINE_SPLIT_INVOICE_TEXT,
        evidence_refs=["page:1"],
    )
    totals = parse_invoice_totals_group_payload(
        ocr_text=PADDLEOCR_LINE_SPLIT_INVOICE_TEXT,
        evidence_refs=["page:1"],
    )

    assert metadata["invoice_number"] == "0000007"
    assert metadata["issue_date"] == "2023-10-02"
    assert metadata["due_date"] == "2023-10-16"
    assert totals["subtotal_amount"] == "250.00"
    assert totals["tax_amount"] == "12.50"
    assert totals["total_amount"] == "262.50"


def test_invoice_text_parser_prefers_bill_to_party_in_two_column_invoice() -> None:
    ocr_text = (FIXTURE_DIR / "multi_column_invoice_fly.txt").read_text()

    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )
    totals = parse_invoice_totals_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["invoice_number"] == "1234"
    assert metadata["supplier_name"] == "Invoice Fly"
    assert metadata["customer_name"] == "SAM ALTMAN"
    assert metadata["issue_date"] == "2036-01-01"
    assert metadata["due_date"] is None
    assert totals["total_amount"] == "1512.00"


def test_invoice_text_parser_extracts_receipt_number_and_day_first_date() -> None:
    ocr_text = (FIXTURE_DIR / "receipt_restaurant_gst.txt").read_text()

    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["invoice_number"] == "53"
    assert metadata["supplier_name"] == "SHIVSAGAR"
    assert metadata["issue_date"] == "2017-07-01"


def test_invoice_text_parser_detects_top_left_supplier_block() -> None:
    ocr_text = """INVOICE
Invoice No:
INV-0006487548
Payment Terms:
Credit Card
Date:
02/01/2024
SERVICE RSLL AUTOCARSS
HORTON PARK AVE
BRADFORD
Bill to:
john smith
"""

    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["supplier_name"] == "SERVICE RSLL AUTOCARSS"
    assert metadata["customer_name"] == "john smith"


def test_invoice_text_parser_resolves_uk_long_date_ambiguity() -> None:
    ocr_text = """INVOICE
Invoice No: INV-GB-001
Date: 02/01/2024
Due Date: 03/01/2024
ACME UK SERVICES LTD
Bill to:
john smith
VAT 20%
Total £120.00
United Kingdom
"""

    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["issue_date"] == "2024-01-02"
    assert metadata["due_date"] == "2024-01-03"
    assert metadata["currency"] == "GBP"


def test_invoice_text_parser_keeps_us_long_date_default_month_first() -> None:
    ocr_text = """INVOICE
Invoice # US-001
Invoice date 02/01/2024
Due date 03/01/2024
Your Company Inc.
Bill To
Customer Name
Total (USD) $120.00
"""

    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["issue_date"] == "2024-02-01"
    assert metadata["due_date"] == "2024-03-01"


def test_invoice_text_parser_groups_multiline_line_item_descriptions() -> None:
    ocr_text = (
        Path(__file__).parents[2]
        / "app"
        / "evaluations"
        / "datasets"
        / "sme_local_v1"
        / "documents"
        / "invoices"
        / "invoice_layout_autocare_003.txt"
    ).read_text()

    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )
    totals = parse_invoice_totals_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )
    table = parse_invoice_table_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["supplier_name"] == "SERVICE DEMO AUTOCARE LTD"
    assert metadata["currency"] == "GBP"
    assert metadata["issue_date"] == "2024-01-02"
    assert metadata["due_date"] == "2024-01-02"
    assert totals["total_amount"] == "1482.00"

    line_items = table["line_items"]
    assert isinstance(line_items, list)
    assert len(line_items) == 1
    assert line_items[0]["quantity"] == "1.00"
    assert line_items[0]["unit_price"] == "1300.00"
    assert line_items[0]["line_total"] == "1300.00"
    assert "CONITECH TIMING CHAIN KIT" in line_items[0]["description"]
    assert "ANTIFREEZE COOLANT" in line_items[0]["description"]


def test_invoice_text_parser_recovers_noisy_flat_tesseract_output() -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text=NOISY_FLAT_INVOICE_OCR_TEXT,
        evidence_refs=["page:1"],
    )
    totals = parse_invoice_totals_group_payload(
        ocr_text=NOISY_FLAT_INVOICE_OCR_TEXT,
        evidence_refs=["page:1"],
    )
    table = parse_invoice_table_group_payload(
        ocr_text=NOISY_FLAT_INVOICE_OCR_TEXT,
        evidence_refs=["page:1"],
    )

    assert metadata["invoice_number"] == "0000007"
    assert metadata["supplier_name"] == "Your Company Inc."
    assert metadata["customer_name"] == "Customer Name"
    assert metadata["issue_date"] == "2025-10-02"
    assert totals["subtotal_amount"] == "250.00"
    assert totals["tax_amount"] == "12.50"
    assert totals["total_amount"] == "262.50"

    line_items = table["line_items"]
    assert isinstance(line_items, list)
    assert len(line_items) == 4
    assert line_items[0]["quantity"] == "1.00"
    assert line_items[0]["unit_price"] == "40.00"
    assert line_items[0]["line_total"] == "40.00"
    assert line_items[0]["description"] == "Replacement of spark plugs"
    assert line_items[2]["quantity"] == "4.00"
    assert line_items[2]["description"] == "Wheel alignment"
    assert line_items[3]["description"] == "Mechanic's rate per hour"


@pytest.mark.parametrize(
    ("ocr_text", "expected"),
    [
        (
            "FACTURA SIMPLIFICADA\nRecibo: FS 05021061902/0018579",
            "FS 05021061902/0018579",
        ),
        ("FATURA/RECIBO N:\nK00119/00002763", "K00119/00002763"),
        ("PARQUE CAMOES\nDoc n: 077852\nTerminal:22", "077852"),
        ("Montepio Geral\nDoc. N.:017554\nBilhete:35508372", "017554"),
        ("Factura: 19FT 002/46\nORIGINAL", "19FT 002/46"),
    ],
)
def test_invoice_text_parser_supports_portuguese_document_labels(
    ocr_text: str,
    expected: str,
) -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["invoice_number"] == expected


@pytest.mark.parametrize(
    ("ocr_text", "expected"),
    [
        ("RECIB0 K1190120396", "K1190120396"),
        ("REC1B0 K2190102400", "K2190102400"),
        ("Fatura Simp11f1cada FS 27406_004/363327", "FS 27406_004/363327"),
        ("Fatura número:\nFT 030101732516200003/00005", "FT 030101732516200003/00005"),
        ("FATURA\nNo 13212", "13212"),
        (
            "FATURA\nSIMPLIFICADA\nORIGINAL\nDATA 18/01/2019\n-15:19\n№° A/28064",
            "A/28064",
        ),
        ("TPA:00189471\nA0000000032010", "00189471"),
        ("Terminal Pagamento Automático\nA0000000032010", "A0000000032010"),
        ("501649FF20\nCÓPIA CLIENTE", "501649FF20"),
    ],
)
def test_invoice_text_parser_supports_noisy_portuguese_and_pos_identifiers(
    ocr_text: str,
    expected: str,
) -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["invoice_number"] == expected


@pytest.mark.parametrize(
    ("ocr_text", "expected"),
    [
        ("Empresa SA\nNr.Contr.501564292\nRECIBO K1190026905", "501564292"),
        ("Empresa SA\nCONTRIB.509 684 122\nFATURA", "509684122"),
        ("Empresa SA\nC0NTRTB.509 684 122\nFATURA", "509684122"),
        ("Empresa SA\nCapital Social N11 :505416654\nFatura", "505416654"),
        ("Empresa SA\nC.R.C./NUM. CONTRIB.:\nPT503003808\nNOME CLIENTE:", "503003808"),
        ("IKEA Portugal\nPT506431134\nVendedor: 146170", "506431134"),
        (
            "FATURA-RECIBO\nContribuinte: 510776914\n"
            "Programa certificado\nContribuinte: 510010970",
            "510010970",
        ),
    ],
)
def test_invoice_text_parser_supports_portuguese_supplier_tax_labels(
    ocr_text: str,
    expected: str,
) -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["supplier_tax_id"] == expected


def test_invoice_text_parser_extracts_portuguese_seller_and_customer_nif() -> None:
    ocr_text = """ALGESDECOR COMERCIO DE TINTAS, LDA.
NIF: 502.689.390
Data: 06.04.2018
Cliente: FEELSLIKEHOME LDA
Contribuinte: 510776914
FATURA-RECIBO N. FR MNV2/580
Total Documento: 11,01 EUR
"""

    metadata = parse_invoice_metadata_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert metadata["supplier_tax_id"] == "502689390"
    assert metadata["customer_tax_id"] == "510776914"
    assert metadata["issue_date"] == "2018-04-06"


def test_invoice_text_parser_normalizes_portuguese_short_dotted_date() -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text="FATURA\nNIF: 502689390\nData: 23.01.19",
        evidence_refs=["page:1"],
    )

    assert metadata["issue_date"] == "2019-01-23"


def test_invoice_text_parser_preserves_iso_date_in_portuguese_invoice() -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text=(
            "FATURA\nNIF: 500602760\nData: 2019-01-11 08:52\n"
            "NoCliente:\n10001932\nContribuinte: 510776914"
        ),
        evidence_refs=["page:1"],
    )

    assert metadata["issue_date"] == "2019-01-11"
    assert metadata["supplier_tax_id"] == "500602760"
    assert metadata["customer_tax_id"] == "510776914"


def test_invoice_text_parser_supports_portuguese_data_label() -> None:
    metadata = parse_invoice_metadata_group_payload(
        ocr_text="FATURA\nDATA 18/01/2019\nNIF: 513350535",
        evidence_refs=["page:1"],
    )

    assert metadata["issue_date"] == "2019-01-18"


@pytest.mark.parametrize(
    ("ocr_text", "expected_total"),
    [
        ("Total Documento: 11,01 EUR", "11.01"),
        ("Total a Pagar: 1.234,56 €", "1234.56"),
        ("Total (USD) $1,234.56", "1234.56"),
    ],
)
def test_invoice_text_parser_supports_localized_decimal_amounts(
    ocr_text: str,
    expected_total: str,
) -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert totals["total_amount"] == expected_total


def test_invoice_text_parser_ignores_portuguese_taxable_total_table() -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text=(
            "TOTAL\nREFERENCE\n32,00\nIVA Incluido à taxa\n"
            "Taxa%\nIVA\nTotal\nsujeito\n23,00\n5,98\n32,00"
        ),
        evidence_refs=["page:1"],
    )

    assert totals["total_amount"] == "32.00"


def test_invoice_text_parser_prefers_document_total_over_tax_summary() -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text=(
            "TOTAL\n19,98\nIVA Incluído à taxa indicada\n"
            "Taxa%\nSujeito\nIVA\nTotal\n23,00\n16,24\n3,74\n19,98"
        ),
        evidence_refs=["page:1"],
    )

    assert totals["total_amount"] == "19.98"
    assert totals["confidence"] == "high"


def test_invoice_text_parser_ignores_total_column_before_vat_headers() -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text=(
            "Total\n€ 8.50\nPagamento\n€ 8.50\n"
            "Valor\nTotal\nTaxa\nBase\n€ 0.24\n€ 1.30\n"
            "23.00\n€ 1.06\nIVA Incluido"
        ),
        evidence_refs=["page:1"],
    )

    assert totals["total_amount"] == "8.50"
    assert totals["tax_amount"] == "0.24"
    assert totals["confidence"] == "high"


def test_invoice_text_parser_extracts_tax_from_flattened_iva_summary() -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text=(
            "Total\nEUR\n13,80\nResumo do IVA\n"
            "Taxa\nIncidência\nImposto\nTotal\n"
            "10.00\n8,84\n1,16\n10,00"
        ),
        evidence_refs=["page:1"],
    )

    assert totals["total_amount"] == "13.80"
    assert totals["tax_amount"] == "1.16"


def test_invoice_text_parser_downgrades_inconsistent_explicit_totals() -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text="Subtotal 100.00\nSales tax 10.00\nTotal 105.00",
        evidence_refs=["page:1"],
    )

    assert totals["confidence"] == "medium"


@pytest.mark.parametrize(
    ("ocr_text", "expected_tax"),
    [
        (
            "Iliquido\nTax%\nV.Tax\n(D)\n10,57\n23\n2,43\nTotal a Pagar:\n13,00 €",
            "2.43",
        ),
        (
            "IVA Incluido à taxa indicada\nTaxa%\nIVA\nTotal\nsujeito\n"
            "23,00\n26,02\n5,98\n32,00",
            "5.98",
        ),
        (
            "IVA Incluído à taxa indicada\nTaxa%\nSujeito\nIVA\nTotal\n"
            "23,00\n16,24\n3,74\n19,98",
            "3.74",
        ),
        (
            "Taxa Incidência\nIVA\nTotal\n23,00%\n8,31\n2,03\n10,84\nPago em\n10,84€",
            "2.03",
        ),
    ],
)
def test_invoice_text_parser_extracts_portuguese_vat_summary(
    ocr_text: str,
    expected_tax: str,
) -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert totals["tax_amount"] == expected_tax


@pytest.mark.parametrize(
    ("ocr_text", "expected_total"),
    [
        ("Pago:EUR\n1.20", "1.20"),
        ("COMPRA\n49,99€\nAUT:432370", "49.99"),
        ("Taxa: 1,35 €\nPAGAMENTO AUTOMATICO", "1.35"),
        ("U3lor:EUR\n2,40\nData: 2019-01-17", "2.40"),
    ],
)
def test_invoice_text_parser_uses_explicit_payment_amount_fallbacks(
    ocr_text: str,
    expected_total: str,
) -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text=ocr_text,
        evidence_refs=["page:1"],
    )

    assert totals["total_amount"] == expected_total
    assert totals["confidence"] == "high"


def test_invoice_text_parser_marks_unlabelled_currency_total_as_medium() -> None:
    totals = parse_invoice_totals_group_payload(
        ocr_text="Reference\n49,99€",
        evidence_refs=["page:1"],
    )

    assert totals["total_amount"] == "49.99"
    assert totals["confidence"] == "medium"
