"""Deterministic invoice extraction fallback from OCR text.

This module is intentionally conservative. It does not try to replace OCR/LLM
providers; it gives the workflow a useful local fallback when a model returns
invalid structured JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class ParsedInvoiceLine:
    """One line item parsed from OCR text."""

    line_number: int
    quantity: str
    description: str
    unit_price: str
    line_total: str


MONEY_PATTERN = r"[$£]?\s*([0-9][0-9,]*\.\d{2})"
WHOLE_DOLLAR_PATTERN = r"[$£]\s*([0-9][0-9,]*)"
DATE_PATTERN = r"([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})"


def parse_invoice_metadata_group_payload(
    *,
    ocr_text: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    """Parse invoice metadata fields from OCR text into group contract payload."""

    lines = normalized_lines(ocr_text)
    invoice_number = find_invoice_number(ocr_text) or find_labeled_value(
        lines,
        labels=(
            "invoice #",
            "invoice no",
            "invoice number",
            "bill no",
            "receipt no",
            "no.",
        ),
        value_pattern=r"([A-Z0-9][A-Z0-9-]*)",
    )
    issue_date = normalize_invoice_date(
        find_labeled_value(
            lines,
            labels=("invoice date", "date"),
            value_pattern=DATE_PATTERN,
        )
    )
    if issue_date is None:
        issue_date = normalize_invoice_date(find_header_date(lines))
    due_date = normalize_invoice_date(
        find_labeled_value(
            lines,
            labels=("due date", "payment due", "duedate"),
            value_pattern=DATE_PATTERN,
        )
    )
    if due_date is None:
        due_date = infer_due_date_from_terms(
            issue_date=issue_date,
            ocr_text=ocr_text,
        )
    currency = find_currency(ocr_text)
    supplier_name = find_supplier_name(lines)
    customer_name = find_customer_name(lines)
    extracted = any(
        [
            invoice_number,
            supplier_name,
            customer_name,
            issue_date,
            due_date,
            currency,
        ]
    )

    return {
        "schema_version": "invoice-metadata-group.v1",
        "extraction_status": "partial" if extracted else "placeholder",
        "invoice_number": invoice_number,
        "supplier_name": supplier_name,
        "supplier_tax_id": None,
        "customer_name": customer_name,
        "customer_tax_id": None,
        "issue_date": issue_date,
        "due_date": due_date,
        "currency": currency,
        "evidence_refs": evidence_refs or ["ocr:text:fallback:metadata"],
        "confidence": "medium" if extracted else "unknown",
    }


def parse_invoice_totals_group_payload(
    *,
    ocr_text: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    """Parse subtotal, tax, total, and currency from OCR text."""

    subtotal_amount = find_money_after_label(ocr_text, labels=("subtotal",))
    tax_amount = find_money_after_label(
        ocr_text,
        labels=("sales tax", "tax"),
        reject_labels=("subtotal", "total"),
    )
    total_amount = find_total_amount(ocr_text)
    if tax_amount is None:
        tax_amount = infer_tax_amount(
            subtotal_amount=subtotal_amount,
            total_amount=total_amount,
        )
    currency = find_currency(ocr_text)
    extracted = any([subtotal_amount, tax_amount, total_amount, currency])

    return {
        "schema_version": "invoice-totals-group.v1",
        "extraction_status": "partial" if extracted else "placeholder",
        "subtotal_amount": subtotal_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "currency": currency,
        "evidence_refs": evidence_refs or ["ocr:text:fallback:totals"],
        "confidence": "medium" if extracted else "unknown",
    }


def parse_invoice_table_group_payload(
    *,
    ocr_text: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    """Parse common invoice line item rows from OCR text."""

    line_items = [
        {
            "line_number": parsed.line_number,
            "description": parsed.description,
            "quantity": parsed.quantity,
            "unit_price": parsed.unit_price,
            "tax_amount": None,
            "line_total": parsed.line_total,
            "evidence_refs": [
                f"ocr:text:fallback:table:row:{parsed.line_number}",
            ],
            "confidence": "medium",
        }
        for parsed in parse_line_items(ocr_text)
    ]

    return {
        "schema_version": "invoice-table-group.v1",
        "extraction_status": "partial" if line_items else "placeholder",
        "line_items": line_items,
        "table_region_ref": "ocr:text:fallback:table" if line_items else None,
        "evidence_refs": evidence_refs or ["ocr:text:fallback:table"],
        "confidence": "medium" if line_items else "unknown",
    }


def normalized_lines(text: str) -> list[str]:
    """Return non-empty OCR lines with collapsed whitespace."""

    return [clean_ocr_text(line) for line in text.splitlines() if clean_ocr_text(line)]


def clean_ocr_text(text: str) -> str:
    """Normalize common OCR punctuation noise without changing meaning."""

    return re.sub(r"\s+", " ", text).strip(" \t\r\n'‘’“”")


def find_labeled_value(
    lines: list[str],
    *,
    labels: tuple[str, ...],
    value_pattern: str,
) -> str | None:
    """Find a label/value pair on the same line or the next line."""

    compiled_value = re.compile(value_pattern, flags=re.IGNORECASE)
    for index, line in enumerate(lines):
        lower_line = line.lower()
        matching_label = next(
            (label for label in labels if label in lower_line),
            None,
        )
        if matching_label is None:
            continue

        after_label = line[lower_line.find(matching_label) + len(matching_label) :]
        same_line_match = compiled_value.search(after_label)
        if same_line_match:
            return same_line_match.group(1).strip()

        if index + 1 < len(lines):
            next_line_match = compiled_value.search(lines[index + 1])
            if next_line_match:
                return next_line_match.group(1).strip()
    return None


def normalize_invoice_date(value: str | None) -> str | None:
    """Normalize MM-DD-YYYY or MM/DD/YYYY dates to ISO YYYY-MM-DD."""

    if value is None:
        return None

    parts = re.split(r"[-/]", value)
    if len(parts) != 3:
        return value

    first, second, year = parts
    is_short_year = len(year) == 2
    if is_short_year:
        year = f"20{year}"

    try:
        first_number = int(first)
        second_number = int(second)
        normalized_year = int(year)
    except ValueError:
        return value

    if is_short_year and first_number <= 31 and second_number <= 12:
        day = first_number
        month = second_number
    else:
        month = first_number
        day = second_number

    if not (1 <= month <= 12 and 1 <= day <= 31):
        return value
    return f"{normalized_year:04d}-{month:02d}-{day:02d}"


def find_header_date(lines: list[str]) -> str | None:
    """Find an unlabeled date in the invoice header before billing sections."""

    for line in lines[:12]:
        lower_line = line.lower()
        if "due date" in lower_line or "bill to" in lower_line:
            return None
        match = re.search(DATE_PATTERN, line)
        if match:
            return match.group(1)
    return None


def find_invoice_number(text: str) -> str | None:
    """Find invoice number in noisy OCR text."""

    cleaned = clean_ocr_text(text)
    patterns = (
        r"\b(?:bill|receipt)\s*no\.?\s*:?\s*([A-Z0-9][A-Z0-9-]*)\b",
        r"\bno\.?\s*([0-9]{3,})\b",
        r"\binvoice\s*(?:#|no\.?|number|num|[:*])?\s*[#:'‘’“”]*\s*([A-Z0-9][A-Z0-9-]{3,})",
        r"\binvoice\s+[A-Za-z\s]{0,24}?[#:'‘’“”]*\s*([0-9]{4,})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned, flags=re.IGNORECASE):
            candidate = match.group(1).strip(" :'‘’“”")
            if candidate.lower().startswith("date"):
                continue
            if re.search(r"\d", candidate):
                return candidate
    return None


def infer_due_date_from_terms(
    *,
    issue_date: str | None,
    ocr_text: str,
) -> str | None:
    """Infer due date from payment terms when OCR loses the due-date label."""

    if issue_date is None:
        return None

    match = re.search(r"\bdue\s+in\s+([0-9]{1,3})\s+days\b", ocr_text, re.IGNORECASE)
    if match is None:
        return None

    try:
        year, month, day = (int(part) for part in issue_date.split("-"))
        base_date = date(year, month, day)
        return (base_date + timedelta(days=int(match.group(1)))).isoformat()
    except ValueError:
        return None


def find_currency(text: str) -> str | None:
    """Infer a currency code from total labels or currency symbols."""

    code_match = re.search(r"\b(?:total|amount)\s*\(([A-Z]{3})\)", text, re.I)
    if code_match:
        return code_match.group(1).upper()
    if "$" in text:
        return "USD"
    if "£" in text:
        return "GBP"
    return None


def find_supplier_name(lines: list[str]) -> str | None:
    """Return the first plausible supplier/company line."""

    sender_block_name = find_supplier_name_from_sender_block(lines)
    if sender_block_name is not None:
        return sender_block_name

    flattened = " ".join(lines)
    company_match = re.search(
        r"\b([A-Z][A-Za-z0-9 .&'-]{1,80}?\b(?:Inc\.?|LLC|Ltd\.?|Corp\.?))\b",
        flattened,
        flags=re.IGNORECASE,
    )
    if company_match:
        return clean_party_name(company_match.group(1))

    for line in lines[:8]:
        cleaned = clean_party_name(line)
        lower_line = line.lower()
        if (
            lower_line.strip(" :.") == "invoice"
            or "no." in lower_line
            or re.search(r"\d", line)
            or "upload logo" in lower_line
            or "bill to" in lower_line
            or looks_like_address(line)
        ):
            continue
        if cleaned:
            return cleaned
    return None


def find_supplier_name_from_sender_block(lines: list[str]) -> str | None:
    """Find a supplier from the sender block before bill-to/customer sections."""

    for line in lines[:18]:
        lower_line = line.lower().strip(" :.")
        if lower_line in {"bill to", "billto", "ship to", "client name"}:
            break
        if is_invoice_fact_line(line):
            continue
        cleaned = clean_party_name(line)
        if not is_plausible_supplier_name(cleaned):
            continue
        return cleaned
    return None


def find_customer_name(lines: list[str]) -> str | None:
    """Return the first line after Bill To that looks like a customer name."""

    bill_to_candidate = find_party_name_after_label(
        lines,
        labels=("bill to", "bill to:"),
    )
    if bill_to_candidate is not None:
        return bill_to_candidate

    flattened = " ".join(lines)
    generic_match = re.search(
        r"(?:bill\s*to|inte)\s+([A-Z][A-Za-z0-9 .&'-]{2,80}?)\s+invoice\b",
        flattened,
        flags=re.IGNORECASE,
    )
    if generic_match:
        return clean_party_name(generic_match.group(1))
    if re.search(r"\bcustomer\s+name\b", flattened, flags=re.IGNORECASE):
        return "Customer Name"

    return None


def find_party_name_after_label(
    lines: list[str],
    *,
    labels: tuple[str, ...],
) -> str | None:
    """Return first plausible party name after a label in OCR reading order."""

    for index, line in enumerate(lines):
        lower_line = line.lower()
        matching_label = next(
            (label for label in labels if label.rstrip(":") in lower_line),
            None,
        )
        if matching_label is None:
            continue

        stripped_label = matching_label.rstrip(":")
        label_end = lower_line.find(stripped_label) + len(stripped_label)
        after_label = line[label_end:]
        same_line_name = clean_party_name(after_label)
        if is_plausible_party_name(same_line_name):
            return same_line_name

        for candidate in lines[index + 1 : index + 8]:
            cleaned = clean_party_name(candidate)
            if not is_plausible_party_name(cleaned):
                continue
            return cleaned
    return None


def is_plausible_party_name(value: str | None) -> bool:
    """Return whether text is likely a party/person/company name."""

    if value is None:
        return False
    lower_value = value.lower().strip(" :")
    if not lower_value:
        return False
    blocked_exact = {
        "bill to",
        "bill to:",
        "ship to",
        "ship to:",
        "client name",
        "phone number",
        "p.o. number",
        "po number",
        "due date",
        "invoice",
    }
    if lower_value in blocked_exact:
        return False
    if looks_like_address(value):
        return False
    if re.search(r"\d", value):
        return False
    return bool(re.search(r"[A-Za-z]", value))


def is_plausible_supplier_name(value: str | None) -> bool:
    """Return whether a sender-block line can be a supplier name."""

    if not is_plausible_party_name(value):
        return False
    if value is None:
        return False
    lower_value = value.lower()
    blocked_fragments = (
        "payment terms",
        "credit card",
        "due date",
        "date",
        "po no",
        "p.o.",
        "email",
        "phone",
        "upload logo",
        "source:",
        "layout notes",
        "synthetic",
        "photographed",
    )
    if any(fragment in lower_value for fragment in blocked_fragments):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", value))


def is_invoice_fact_line(line: str) -> bool:
    """Return whether a line is an invoice fact label/value, not a party name."""

    lower_line = line.lower()
    return bool(
        lower_line.strip(" :.") == "invoice"
        or "invoice no" in lower_line
        or "invoice #" in lower_line
        or "invoice number" in lower_line
        or "payment terms" in lower_line
        or "due date" in lower_line
        or lower_line.startswith("source:")
        or "layout notes" in lower_line
        or re.fullmatch(r"[a-z]{0,3}[0-9][a-z0-9-]*", lower_line.strip())
    )


def clean_party_name(value: str | None) -> str | None:
    """Clean OCR punctuation from party names."""

    if value is None:
        return None
    cleaned = clean_ocr_text(value)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\binc\.?$", "Inc.", cleaned, flags=re.IGNORECASE)
    if not re.search(r"\binc\.$", cleaned, flags=re.IGNORECASE):
        cleaned = cleaned.rstrip(".")
    return cleaned or None


def looks_like_address(line: str) -> bool:
    """Return whether a line looks more like an address than a party name."""

    lower_line = line.lower()
    return bool(
        re.search(r"\d", line)
        and any(token in lower_line for token in (" st", " street", " town", " ave"))
    )


def find_money_after_label(
    text: str,
    *,
    labels: tuple[str, ...],
    reject_labels: tuple[str, ...] = (),
) -> str | None:
    """Find a money value on lines that contain a target label."""

    lines = normalized_lines(text)
    for index, line in enumerate(lines):
        lower_line = line.lower()
        if not any(label in lower_line for label in labels):
            continue
        if any(reject_label in lower_line for reject_label in reject_labels):
            continue
        label_positions = [
            lower_line.find(label) for label in labels if lower_line.find(label) >= 0
        ]
        search_text = line[min(label_positions) :] if label_positions else line
        matches = find_money_values(search_text)
        if matches:
            return clean_money(matches[0])
        if index + 1 < len(lines):
            next_line_matches = find_money_values(lines[index + 1])
            if next_line_matches:
                return clean_money(next_line_matches[0])
    return None


def find_total_amount(text: str) -> str | None:
    """Find the final total amount without accidentally selecting subtotal."""

    candidates: list[str] = []
    lines = normalized_lines(text)
    for index, line in enumerate(lines):
        lower_line = line.lower()
        if "total" not in lower_line:
            continue
        explicit_total_match = re.search(
            r"(?<!sub)\btotal\b(?:\s*\(?[A-Z]{3}\)?)?[^0-9$]{0,24}" + MONEY_PATTERN,
            line,
            flags=re.IGNORECASE,
        )
        if explicit_total_match:
            candidates.append(clean_money(explicit_total_match.group(1)))
            continue
        if "subtotal" in lower_line:
            continue
        matches = find_money_values(line)
        if matches:
            candidates.append(clean_money(matches[-1]))
            continue
        if index + 1 < len(lines):
            next_line_matches = find_money_values(lines[index + 1])
            if next_line_matches:
                candidates.append(clean_money(next_line_matches[0]))
    return candidates[-1] if candidates else None


def find_money_values(text: str) -> list[str]:
    """Return money values, allowing whole dollars only when prefixed by ``$``."""

    decimal_matches = re.findall(MONEY_PATTERN, text)
    whole_dollar_matches = re.findall(WHOLE_DOLLAR_PATTERN, text)
    return [*decimal_matches, *whole_dollar_matches]


def clean_money(value: str) -> str:
    """Normalize a money-like OCR value."""

    cleaned = value.replace(",", "").strip()
    try:
        return format_decimal(Decimal(cleaned))
    except InvalidOperation:
        return cleaned


def infer_tax_amount(
    *,
    subtotal_amount: str | None,
    total_amount: str | None,
) -> str | None:
    """Infer tax as total - subtotal when OCR loses the tax amount."""

    if subtotal_amount is None or total_amount is None:
        return None
    try:
        subtotal = Decimal(subtotal_amount)
        total = Decimal(total_amount)
    except InvalidOperation:
        return None
    tax = total - subtotal
    if tax < 0:
        return None
    return format_decimal(tax)


def parse_line_items(text: str) -> list[ParsedInvoiceLine]:
    """Parse line items from common OCR row shapes."""

    parsed = parse_line_items_from_lines(text)
    if parsed:
        return parsed
    return parse_line_items_from_flat_text(text)


def parse_line_items_from_lines(text: str) -> list[ParsedInvoiceLine]:
    """Parse line items when OCR preserves one row per line."""

    parsed: list[ParsedInvoiceLine] = []
    quantity_first_row_pattern = re.compile(
        r"^\s*(?P<quantity>\d+(?:\.\d+)?)\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<unit_price>[$£]?\s*\d+(?:,\d{3})*(?:\.\d{2})?)\s+"
        r"(?P<line_total>[$£]?\s*\d+(?:,\d{3})*(?:\.\d{2})?)\s*$"
    )
    description_first_row_pattern = re.compile(
        r"^\s*(?P<description>.+?)\s+"
        r"(?P<quantity>\d+(?:\.\d+)?)\s*(?:[A-Za-z]{1,8})?\s+"
        r"(?P<unit_price>[$£]\s*\d+(?:,\d{3})*(?:\.\d{2})?)\s+"
        r"(?P<line_total>[$£]\s*\d+(?:,\d{3})*(?:\.\d{2})?)\s*$"
    )

    for line in normalized_lines(text):
        if should_skip_table_line(line):
            continue
        if parsed and is_line_item_continuation(line):
            previous = parsed[-1]
            parsed[-1] = ParsedInvoiceLine(
                line_number=previous.line_number,
                quantity=previous.quantity,
                description=(
                    f"{previous.description} {clean_line_description(line)}".strip()
                ),
                unit_price=previous.unit_price,
                line_total=previous.line_total,
            )
            continue

        match = quantity_first_row_pattern.match(line) or (
            description_first_row_pattern.match(line)
        )
        if match is None:
            continue
        unit_price = normalize_money_token(match.group("unit_price"))
        line_total = normalize_money_token(match.group("line_total"))
        quantity = normalize_quantity_token(
            raw_quantity=match.group("quantity"),
            unit_price=unit_price,
            line_total=line_total,
        )
        parsed.append(
            ParsedInvoiceLine(
                line_number=len(parsed) + 1,
                quantity=quantity,
                description=clean_line_description(match.group("description")),
                unit_price=unit_price,
                line_total=line_total,
            )
        )
    return parsed


def parse_line_items_from_flat_text(text: str) -> list[ParsedInvoiceLine]:
    """Parse line items when OCR collapses the whole table into one line."""

    table_text = extract_table_region_text(text)
    row_pattern = re.compile(
        r"[^\d]*(?P<quantity>\d{1,4}(?:\.\d{1,2})?)\s+"
        r"(?P<description>[A-Za-z][A-Za-z0-9 '&().-]{3,90}?)\s+"
        r"(?P<unit_price>\$?\s*\d{2,6}(?:\.\d{2})?)\s+"
        r"\$?\s*(?P<line_total>\d{2,6}(?:\.\d{2})?)",
        flags=re.IGNORECASE,
    )

    parsed: list[ParsedInvoiceLine] = []
    for match in row_pattern.finditer(table_text):
        raw_description = clean_line_description(match.group("description"))
        if should_skip_table_line(raw_description):
            continue
        unit_price = normalize_money_token(match.group("unit_price"))
        line_total = normalize_money_token(match.group("line_total"))
        quantity = normalize_quantity_token(
            raw_quantity=match.group("quantity"),
            unit_price=unit_price,
            line_total=line_total,
        )
        parsed.append(
            ParsedInvoiceLine(
                line_number=len(parsed) + 1,
                quantity=quantity,
                description=raw_description,
                unit_price=unit_price,
                line_total=line_total,
            )
        )
    return parsed


def extract_table_region_text(text: str) -> str:
    """Return the OCR span most likely to contain invoice item rows."""

    flattened = clean_ocr_text(text)
    lower_text = flattened.lower()
    start_candidates = [
        lower_text.find(token)
        for token in ("qty description", "ty description", "description")
        if lower_text.find(token) >= 0
    ]
    end_candidates = [
        lower_text.find(token)
        for token in ("subtotal", "sales tax", "total")
        if lower_text.find(token) >= 0
    ]
    start = min(start_candidates) if start_candidates else 0
    end = min(
        (candidate for candidate in end_candidates if candidate > start),
        default=len(flattened),
    )
    return flattened[start:end]


def normalize_money_token(value: str) -> str:
    """Normalize OCR money tokens, including missing decimal points."""

    cleaned = value.replace("$", "").replace("£", "").replace(",", "").strip()
    if "." in cleaned:
        return format_decimal(Decimal(cleaned))
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return cleaned
    amount = Decimal(int(digits)) / Decimal(100)
    return format_decimal(amount)


def normalize_quantity_token(
    *,
    raw_quantity: str,
    unit_price: str,
    line_total: str,
) -> str:
    """Normalize quantity, preferring amount/unit arithmetic for noisy OCR."""

    try:
        unit = Decimal(unit_price)
        total = Decimal(line_total)
    except InvalidOperation:
        unit = Decimal(0)
        total = Decimal(0)

    if unit > 0 and total > 0:
        inferred = total / unit
        if inferred > 0:
            return format_decimal(inferred)

    cleaned = raw_quantity.strip()
    if "." in cleaned:
        return format_decimal(Decimal(cleaned))
    digits = re.sub(r"\D", "", cleaned)
    if digits.endswith("00") and len(digits) >= 3:
        return format_decimal(Decimal(int(digits[:-2] or "0")))
    return cleaned


def clean_line_description(value: str) -> str:
    """Clean common OCR spelling and spacing issues in line descriptions."""

    cleaned = clean_ocr_text(value)
    replacements = {
        "sparkpiugs": "spark plugs",
        "sparkplugs": "spark plugs",
        "whoo aignment": "Wheel alignment",
        "wheel aignment": "Wheel alignment",
        "perhour": "per hour",
        "( front )": "(front)",
    }
    for source, target in replacements.items():
        cleaned = re.sub(source, target, cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def format_decimal(value: Decimal) -> str:
    """Format decimal values with two fractional digits."""

    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def should_skip_table_line(line: str) -> bool:
    """Return whether a line is a table header/summary rather than an item."""

    lower_line = line.lower()
    return any(
        token in lower_line
        for token in (
            "qty description",
            "unit price",
            "subtotal",
            "sales tax",
            "discount",
            "vat",
            "tax ",
            "tax(",
            "shipping",
            "amount paid",
            "balance due",
            "total",
            "terms and conditions",
        )
    )


def is_line_item_continuation(line: str) -> bool:
    """Return whether a line should extend the previous item description."""

    lower_line = line.lower()
    if should_skip_table_line(line) or is_invoice_fact_line(line):
        return False
    if find_money_values(line) or re.fullmatch(r"\d+(?:\.\d+)?(?:\s+[a-z]+)?", line):
        return False
    if any(
        token in lower_line
        for token in (
            "bill to",
            "ship to",
            "balance due",
            "paid",
            "discount",
            "vat",
            "tax",
            "created by",
            "payment",
            "notes:",
        )
    ):
        return False
    return bool(re.search(r"[A-Za-z]", line))
