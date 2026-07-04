from app.extraction.invoice_text_parser import (
    parse_invoice_metadata_group_payload,
    parse_invoice_table_group_payload,
    parse_invoice_totals_group_payload,
)

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

INVOICE_FLY_OCR_TEXT = """INVOICE
Invoice Fly.
NO.1234
1/01/2036
ALBERT SORT
Due date:
5740, N.Sheridan Road.
P.O. Number:
Chicago, IL-60660
Albert@invoicefly.com
123-456-789
BILL TO:
SHIP TO:
SAM ALTMAN
CLIENT NAME
Fifth Avenue New York,
Client Street, City,
10029
State, Zip Code
DESCRIPTION
QTY
PRICE
TOTAL
Item 1
2
$100
$200
Item 2
1
$150
$150
Item 3
2
$300
$600
Item 4
1
$300
$300
SUB TOTAL
$1250
TAX (21%)
$262
DISCOUNT
$0
SHIPPING
$0
TOTAL AMOUNT
$1512
BALANCE DUE
$1512
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
    metadata = parse_invoice_metadata_group_payload(
        ocr_text=INVOICE_FLY_OCR_TEXT,
        evidence_refs=["page:1"],
    )
    totals = parse_invoice_totals_group_payload(
        ocr_text=INVOICE_FLY_OCR_TEXT,
        evidence_refs=["page:1"],
    )

    assert metadata["invoice_number"] == "1234"
    assert metadata["supplier_name"] == "Invoice Fly"
    assert metadata["customer_name"] == "SAM ALTMAN"
    assert metadata["issue_date"] == "2036-01-01"
    assert metadata["due_date"] is None
    assert totals["total_amount"] == "1512.00"


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
