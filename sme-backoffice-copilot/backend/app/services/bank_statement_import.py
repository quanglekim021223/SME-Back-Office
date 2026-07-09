"""CSV bank statement import and lightweight reconciliation trigger."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

from anyio import Path as AsyncPath
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import (
    Reconciliation,
    ReconciliationAllocation,
    ReconciliationAllocationStatus,
    ReconciliationStatus,
)
from app.models.banking import (
    BankAccount,
    BankAccountType,
    StatementImport,
    StatementImportStatus,
    Transaction,
    TransactionDirection,
    TransactionStatus,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.models.operations import (
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.reconciliation.deterministic import (
    ReconciliationInvoiceInput,
    ReconciliationTransactionInput,
    generate_reconciliation_candidates,
)
from app.services.document_events import DocumentIngested

PARSER_NAME = "simple_bank_statement_csv"
PARSER_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class ParsedStatementRow:
    """One normalized CSV statement row."""

    posted_at: date | None
    description: str
    amount: Decimal
    direction: TransactionDirection
    balance: Decimal | None
    currency: str | None
    reference: str | None
    counterparty_name: str | None


@dataclass(frozen=True, slots=True)
class BankStatementImportResult:
    """Summary of rows imported from one bank statement document."""

    statement_import_id: UUID
    transaction_count: int
    reconciliation_count: int
    review_task_count: int


class BankStatementCsvImportService:
    """Parse uploaded bank statement CSVs into transactions and reconciliation rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_document(
        self,
        event: DocumentIngested,
    ) -> BankStatementImportResult | None:
        """Import transactions for a bank-statement upload event."""

        if event.local_path is None:
            return None

        path = Path(event.local_path)
        csv_text = await AsyncPath(path).read_text(encoding="utf-8-sig")
        rows, metadata = parse_statement_csv(csv_text)
        bank_account = await self._get_or_create_bank_account(
            tenant_id=event.tenant_id,
            metadata=metadata,
        )
        statement_import = StatementImport(
            id=uuid4(),
            tenant_id=event.tenant_id,
            bank_account_id=bank_account.id,
            document_id=event.document_id,
            status=StatementImportStatus.PARSED.value,
            source_filename=path.name,
            statement_start_date=metadata.statement_start_date,
            statement_end_date=metadata.statement_end_date,
            currency=metadata.currency,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            row_count=len(rows),
            duplicate_count=0,
            metrics={"source": "document_ingested"},
        )
        self.session.add(statement_import)
        transactions = await self._create_transactions(
            tenant_id=event.tenant_id,
            bank_account=bank_account,
            statement_import=statement_import,
            rows=rows,
        )
        reconciliation_count, review_task_count = await self._reconcile_invoices(
            tenant_id=event.tenant_id,
            document_id=event.document_id,
            transactions=transactions,
        )
        return BankStatementImportResult(
            statement_import_id=statement_import.id,
            transaction_count=len(transactions),
            reconciliation_count=reconciliation_count,
            review_task_count=review_task_count,
        )

    async def _get_or_create_bank_account(
        self,
        *,
        tenant_id: UUID,
        metadata: StatementCsvMetadata,
    ) -> BankAccount:
        account_hash = hashlib.sha256(
            f"{metadata.bank_name}|{metadata.account_number}".encode()
        ).hexdigest()
        stmt = select(BankAccount).where(
            BankAccount.tenant_id == tenant_id,
            BankAccount.account_identifier_hash == account_hash,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        bank_account = BankAccount(
            id=uuid4(),
            tenant_id=tenant_id,
            institution_name=metadata.bank_name or "Uploaded bank statement",
            account_name=metadata.account_holder,
            account_type=BankAccountType.CHECKING.value,
            currency=metadata.currency,
            masked_account_number=metadata.account_number,
            account_identifier_hash=account_hash,
        )
        self.session.add(bank_account)
        await self.session.flush()
        return bank_account

    async def _create_transactions(
        self,
        *,
        tenant_id: UUID,
        bank_account: BankAccount,
        statement_import: StatementImport,
        rows: list[ParsedStatementRow],
    ) -> list[Transaction]:
        transactions: list[Transaction] = []
        for index, row in enumerate(rows, start=1):
            content_hash = transaction_content_hash(
                bank_account_id=bank_account.id,
                row=row,
                index=index,
            )
            existing = await self.session.execute(
                select(Transaction).where(
                    Transaction.tenant_id == tenant_id,
                    Transaction.bank_account_id == bank_account.id,
                    Transaction.content_hash == content_hash,
                )
            )
            duplicate = existing.scalar_one_or_none()
            if duplicate is not None:
                transactions.append(duplicate)
                continue

            transaction = Transaction(
                id=uuid4(),
                tenant_id=tenant_id,
                bank_account_id=bank_account.id,
                statement_import_id=statement_import.id,
                status=TransactionStatus.POSTED.value,
                direction=row.direction.value,
                posted_at=row.posted_at,
                value_at=row.posted_at,
                raw_description=row.description,
                normalized_description=row.description.upper(),
                counterparty_name=row.counterparty_name,
                reference=row.reference,
                amount=row.amount,
                currency=row.currency,
                running_balance=row.balance,
                external_transaction_id=f"{statement_import.id}:{index}",
                content_hash=content_hash,
                confidence="high",
                metadata_={"source_row": index},
            )
            self.session.add(transaction)
            transactions.append(transaction)
        await self.session.flush()
        statement_import.duplicate_count = max(len(rows) - len(transactions), 0)
        return transactions

    async def _reconcile_invoices(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        transactions: list[Transaction],
    ) -> tuple[int, int]:
        if not transactions:
            return 0, 0

        invoice_result = await self.session.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.status != InvoiceStatus.REJECTED.value,
                Invoice.status != InvoiceStatus.SUPERSEDED.value,
            )
        )
        invoices = list(invoice_result.scalars().all())
        reconciliation_count = 0
        review_task_count = 0
        tx_inputs = [transaction_input_from_model(tx) for tx in transactions]

        for invoice in invoices:
            candidates = generate_reconciliation_candidates(
                invoice=invoice_input_from_model(invoice),
                transactions=tx_inputs,
                min_score=1,
            )
            if not candidates:
                continue

            candidate = candidates[0]
            transaction = next(
                tx for tx in transactions if str(tx.id) == candidate.transaction_id
            )
            if await allocation_exists(
                self.session,
                invoice_id=invoice.id,
                transaction_id=transaction.id,
            ):
                continue

            requires_review = len(candidates) > 1 or candidate.score < 85
            reconciliation = Reconciliation(
                id=uuid4(),
                tenant_id=tenant_id,
                status=(
                    ReconciliationStatus.PENDING_REVIEW.value
                    if requires_review
                    else ReconciliationStatus.PROPOSED.value
                ),
                version=1,
                currency=invoice.currency or transaction.currency,
                invoice_total_amount=invoice.total_amount,
                transaction_total_amount=abs(transaction.amount),
                difference_amount=(
                    abs(transaction.amount) - invoice.total_amount
                    if invoice.total_amount is not None
                    else None
                ),
                confidence=candidate.confidence.value,
                source_agent="bank_statement_csv_import",
                source_agent_version=PARSER_VERSION,
                rationale="Matched uploaded bank statement transaction to invoice.",
                evidence_refs=[
                    f"invoice:{invoice.id}",
                    f"transaction:{transaction.id}",
                    f"document:{document_id}",
                ],
                metadata_={
                    "source": "bank_statement_csv_upload",
                    "invoice_id": str(invoice.id),
                    "transaction_id": str(transaction.id),
                    "candidate_score": candidate.score,
                    "candidate_count": len(candidates),
                    "matched_signals": candidate.matched_signals,
                    "requires_review": requires_review,
                },
            )
            self.session.add(reconciliation)
            self.session.add(
                ReconciliationAllocation(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    reconciliation_id=reconciliation.id,
                    invoice_id=invoice.id,
                    transaction_id=transaction.id,
                    status=ReconciliationAllocationStatus.PROPOSED.value,
                    allocated_amount=abs(transaction.amount),
                    currency=reconciliation.currency,
                    allocation_method="deterministic_csv_match",
                    confidence=candidate.confidence.value,
                    notes="Created from uploaded bank statement CSV.",
                    metadata_={"candidate_score": candidate.score},
                )
            )
            reconciliation_count += 1
            if requires_review:
                self.session.add(
                    ReviewTask(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        document_id=document_id,
                        invoice_id=invoice.id,
                        transaction_id=transaction.id,
                        reconciliation_id=reconciliation.id,
                        task_type=ReviewTaskType.RECONCILIATION.value,
                        target_type=ReviewTargetType.RECONCILIATION.value,
                        status=ReviewTaskStatus.OPEN.value,
                        priority=ReviewTaskPriority.NORMAL.value,
                        title=(
                            "Review reconciliation for invoice "
                            f"{invoice.invoice_number or str(invoice.id)[:8]}"
                        ),
                        description=(
                            "Review the uploaded bank transaction match before it "
                            "affects financial reporting."
                        ),
                        reason_code="bank_statement_csv_match_requires_review",
                        source_agent="bank_statement_csv_import",
                        source_agent_version=PARSER_VERSION,
                        evidence_refs=reconciliation.evidence_refs,
                        metadata_=reconciliation.metadata_,
                    )
                )
                review_task_count += 1
        return reconciliation_count, review_task_count


@dataclass(frozen=True, slots=True)
class StatementCsvMetadata:
    """Metadata extracted from optional statement header rows."""

    bank_name: str | None = None
    account_number: str | None = None
    account_holder: str | None = None
    statement_start_date: date | None = None
    statement_end_date: date | None = None
    currency: str | None = "USD"


def parse_statement_csv(
    csv_text: str,
) -> tuple[list[ParsedStatementRow], StatementCsvMetadata]:
    """Parse simple bank statement CSV text with optional metadata rows."""

    lines = [line for line in csv_text.splitlines() if line.strip()]
    metadata = parse_metadata_rows(lines)
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lower().lstrip("\ufeff").startswith("date,")
        ),
        0,
    )
    reader = csv.DictReader(lines[header_index:])
    rows: list[ParsedStatementRow] = []
    for raw in reader:
        description = string_cell(raw, "description")
        debit = decimal_cell(raw, "debit")
        credit = decimal_cell(raw, "credit")
        if not description or (debit is None and credit is None):
            continue
        amount = credit if credit is not None else -abs(debit or Decimal("0"))
        direction = (
            TransactionDirection.INFLOW
            if credit is not None
            else TransactionDirection.OUTFLOW
        )
        rows.append(
            ParsedStatementRow(
                posted_at=date_cell(raw, "date"),
                description=description,
                amount=amount,
                direction=direction,
                balance=decimal_cell(raw, "balance"),
                currency=string_cell(raw, "currency") or metadata.currency,
                reference=extract_reference(description),
                counterparty_name=extract_counterparty(description),
            )
        )
    return rows, metadata


def parse_metadata_rows(lines: list[str]) -> StatementCsvMetadata:
    """Parse optional two-column metadata before the transaction table."""

    data: dict[str, str] = {}
    for line in lines:
        if line.lower().lstrip("\ufeff").startswith("date,"):
            break
        cells = next(csv.reader([line]))
        if len(cells) >= 2:
            data[cells[0].strip().lower()] = cells[1].strip()

    start_date: date | None = None
    end_date: date | None = None
    period = data.get("statement period")
    if period and " to " in period:
        raw_start, raw_end = period.split(" to ", 1)
        start_date = parse_date(raw_start)
        end_date = parse_date(raw_end)

    return StatementCsvMetadata(
        bank_name=data.get("bank name"),
        account_number=data.get("account number"),
        account_holder=data.get("account holder"),
        statement_start_date=start_date,
        statement_end_date=end_date,
    )


def invoice_input_from_model(invoice: Invoice) -> ReconciliationInvoiceInput:
    """Build reconciliation input from a persisted invoice."""

    names = [
        name
        for name in [invoice.supplier_name, invoice.customer_name]
        if name is not None and name.strip()
    ]
    return ReconciliationInvoiceInput(
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        total_amount=invoice.total_amount,
        currency=invoice.currency,
        counterparty_names=names,
        metadata={"source": "persisted_invoice"},
    )


def transaction_input_from_model(
    transaction: Transaction,
) -> ReconciliationTransactionInput:
    """Build reconciliation input from a persisted transaction."""

    return ReconciliationTransactionInput(
        transaction_id=str(transaction.id),
        posted_at=transaction.posted_at,
        value_at=transaction.value_at,
        amount=transaction.amount,
        currency=transaction.currency,
        direction=TransactionDirection(transaction.direction),
        reference=transaction.reference,
        description=transaction.raw_description or transaction.normalized_description,
        counterparty_name=transaction.counterparty_name,
        content_hash=transaction.content_hash,
        metadata=transaction.metadata_ or {},
    )


async def allocation_exists(
    session: AsyncSession,
    *,
    invoice_id: UUID,
    transaction_id: UUID,
) -> bool:
    """Return whether an invoice/transaction allocation already exists."""

    result = await session.execute(
        select(ReconciliationAllocation).where(
            ReconciliationAllocation.invoice_id == invoice_id,
            ReconciliationAllocation.transaction_id == transaction_id,
        )
    )
    return result.scalar_one_or_none() is not None


def transaction_content_hash(
    *,
    bank_account_id: UUID,
    row: ParsedStatementRow,
    index: int,
) -> str:
    """Build stable row hash for duplicate transaction detection."""

    payload = "|".join(
        [
            str(bank_account_id),
            str(row.posted_at),
            row.description,
            str(row.amount),
            str(row.balance),
            str(index),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def string_cell(row: dict[str, str], key: str) -> str | None:
    """Return a non-empty CSV cell by case-insensitive key."""

    value = row.get(key) or row.get(key.title()) or row.get(key.upper())
    return value.strip() if isinstance(value, str) and value.strip() else None


def decimal_cell(row: dict[str, str], key: str) -> Decimal | None:
    """Parse a decimal CSV cell."""

    value = string_cell(row, key)
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def date_cell(row: dict[str, str], key: str) -> date | None:
    """Parse a date CSV cell."""

    value = string_cell(row, key)
    return parse_date(value) if value else None


def parse_date(value: str) -> date | None:
    """Parse common statement date formats."""

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def extract_reference(description: str) -> str | None:
    """Extract simple invoice-like references from transaction text."""

    for token in description.replace("#", " ").split():
        normalized = token.strip(" ,.;:")
        if "-" in normalized and any(char.isdigit() for char in normalized):
            return normalized
    return None


def extract_counterparty(description: str) -> str | None:
    """Extract a compact counterparty hint from transaction description."""

    upper = description.upper()
    for prefix in ("ACH PAYMENT ", "PAYMENT "):
        if upper.startswith(prefix):
            remainder = description[len(prefix) :].strip()
            reference = extract_reference(remainder)
            if reference:
                return remainder.replace(reference, "").strip() or None
            return remainder or None
    return None
