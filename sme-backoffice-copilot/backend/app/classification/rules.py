"""Deterministic rule-based category classification."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.fixtures.loader import StatementTransactionFixture
from app.models.accounting import CategoryType, ClassificationTargetType
from app.models.banking import TransactionDirection
from app.validation import parse_decimal
from app.workflows.contracts import ConfidenceLevel
from app.workflows.invoice_extraction import InvoiceExtractionGroups


class RuleBasedCategoryRule(BaseModel):
    """One deterministic keyword rule for category classification."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1)
    category_code: str = Field(min_length=1)
    category_type: CategoryType
    keywords: list[str] = Field(min_length=1)
    target_types: list[ClassificationTargetType] = Field(default_factory=list)
    required_direction: TransactionDirection | None = None
    score_per_keyword: int = Field(default=10, ge=1)
    base_score: int = Field(default=0, ge=0)
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    rationale: str = Field(min_length=1)


class CategoryClassificationInput(BaseModel):
    """Provider-neutral input for deterministic category classification."""

    model_config = ConfigDict(extra="forbid")

    target_type: ClassificationTargetType
    text: str = ""
    amount: Decimal | None = None
    currency: str | None = None
    direction: TransactionDirection | None = None
    counterparty_name: str | None = None
    reference: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CategoryClassificationResult(BaseModel):
    """Deterministic category classification result."""

    model_config = ConfigDict(extra="forbid")

    classifier_name: str = "rule_based_category_classifier"
    category_code: str = Field(min_length=1)
    category_type: CategoryType
    proposed_direction: str
    confidence: ConfidenceLevel
    score: int = Field(ge=0)
    matched_rule_ids: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    rationale: str
    metadata: dict[str, object] = Field(default_factory=dict)


DEFAULT_CATEGORY_RULES: tuple[RuleBasedCategoryRule, ...] = (
    RuleBasedCategoryRule(
        rule_id="revenue_professional_services",
        category_code="professional_services",
        category_type=CategoryType.REVENUE,
        keywords=["consulting", "advisory", "retainer", "professional service"],
        target_types=[
            ClassificationTargetType.INVOICE,
            ClassificationTargetType.INVOICE_LINE_ITEM,
            ClassificationTargetType.TRANSACTION,
        ],
        score_per_keyword=14,
        base_score=8,
        confidence=ConfidenceLevel.HIGH,
        rationale="Matched professional-services revenue keywords.",
    ),
    RuleBasedCategoryRule(
        rule_id="revenue_sales_invoice_payment",
        category_code="sales_revenue",
        category_type=CategoryType.REVENUE,
        keywords=["invoice", "inv-", "ach credit", "wire credit", "payment received"],
        target_types=[ClassificationTargetType.TRANSACTION],
        required_direction=TransactionDirection.INFLOW,
        score_per_keyword=12,
        base_score=6,
        confidence=ConfidenceLevel.MEDIUM,
        rationale="Matched incoming payment or invoice reference keywords.",
    ),
    RuleBasedCategoryRule(
        rule_id="expense_software_subscription",
        category_code="software_subscription",
        category_type=CategoryType.EXPENSE,
        keywords=[
            "cloud hosting",
            "hosting",
            "software",
            "saas",
            "subscription",
            "aws",
            "vercel",
            "openai",
            "github",
        ],
        target_types=[
            ClassificationTargetType.INVOICE,
            ClassificationTargetType.INVOICE_LINE_ITEM,
            ClassificationTargetType.TRANSACTION,
        ],
        score_per_keyword=14,
        base_score=8,
        confidence=ConfidenceLevel.HIGH,
        rationale="Matched software, SaaS, or cloud hosting expense keywords.",
    ),
    RuleBasedCategoryRule(
        rule_id="expense_advertising",
        category_code="advertising_expense",
        category_type=CategoryType.EXPENSE,
        keywords=[
            "google ads",
            "meta ads",
            "facebook ads",
            "advertising",
            "marketing",
            "campaign",
        ],
        score_per_keyword=14,
        base_score=8,
        confidence=ConfidenceLevel.HIGH,
        rationale="Matched advertising or marketing expense keywords.",
    ),
    RuleBasedCategoryRule(
        rule_id="expense_rent",
        category_code="rent_expense",
        category_type=CategoryType.EXPENSE,
        keywords=["office rent", "rent", "lease", "coworking"],
        score_per_keyword=12,
        base_score=6,
        confidence=ConfidenceLevel.MEDIUM,
        rationale="Matched rent, lease, or coworking expense keywords.",
    ),
    RuleBasedCategoryRule(
        rule_id="expense_utilities",
        category_code="utilities_expense",
        category_type=CategoryType.EXPENSE,
        keywords=["electricity", "water", "utility", "utilities", "internet"],
        score_per_keyword=12,
        base_score=6,
        confidence=ConfidenceLevel.MEDIUM,
        rationale="Matched utilities expense keywords.",
    ),
    RuleBasedCategoryRule(
        rule_id="expense_bank_fees",
        category_code="bank_fees",
        category_type=CategoryType.EXPENSE,
        keywords=["bank fee", "service charge", "monthly fee", "wire fee"],
        score_per_keyword=12,
        base_score=6,
        confidence=ConfidenceLevel.MEDIUM,
        rationale="Matched bank fee keywords.",
    ),
    RuleBasedCategoryRule(
        rule_id="expense_payroll",
        category_code="payroll_expense",
        category_type=CategoryType.EXPENSE,
        keywords=["payroll", "salary", "wages", "contractor payroll"],
        score_per_keyword=12,
        base_score=6,
        confidence=ConfidenceLevel.MEDIUM,
        rationale="Matched payroll expense keywords.",
    ),
)


class RuleBasedCategoryClassifier:
    """Deterministic keyword-based category classifier."""

    def __init__(
        self,
        rules: tuple[RuleBasedCategoryRule, ...] = DEFAULT_CATEGORY_RULES,
    ) -> None:
        self.rules = rules

    def classify(
        self,
        classification_input: CategoryClassificationInput,
    ) -> CategoryClassificationResult:
        """Classify one accounting target using deterministic keyword rules."""

        haystack = build_haystack(classification_input)
        matches = [
            score_rule(
                rule=rule, classification_input=classification_input, haystack=haystack
            )
            for rule in self.rules
        ]
        valid_matches = [match for match in matches if match is not None]
        if not valid_matches:
            return fallback_classification(classification_input)

        best_match = max(
            valid_matches,
            key=lambda match: (
                match.score,
                confidence_rank(match.rule.confidence),
                len(match.matched_keywords),
            ),
        )
        return CategoryClassificationResult(
            category_code=best_match.rule.category_code,
            category_type=best_match.rule.category_type,
            proposed_direction=proposed_direction_for_category(
                best_match.rule.category_type
            ),
            confidence=best_match.rule.confidence,
            score=best_match.score,
            matched_rule_ids=[best_match.rule.rule_id],
            matched_keywords=best_match.matched_keywords,
            rationale=best_match.rule.rationale,
            metadata={
                "target_type": classification_input.target_type.value,
                "direction": classification_input.direction.value
                if classification_input.direction is not None
                else None,
                "currency": classification_input.currency,
            },
        )


class RuleMatch(BaseModel):
    """Internal score for one matched rule."""

    model_config = ConfigDict(extra="forbid")

    rule: RuleBasedCategoryRule
    score: int
    matched_keywords: list[str]


def score_rule(
    *,
    rule: RuleBasedCategoryRule,
    classification_input: CategoryClassificationInput,
    haystack: str,
) -> RuleMatch | None:
    """Return a rule match when target, direction, and keywords match."""

    if rule.target_types and classification_input.target_type not in rule.target_types:
        return None
    if (
        rule.required_direction is not None
        and classification_input.direction != rule.required_direction
    ):
        return None

    matched_keywords = [
        keyword for keyword in rule.keywords if keyword.lower() in haystack
    ]
    if not matched_keywords:
        return None

    direction_bonus = 5 if direction_matches_category(rule, classification_input) else 0
    score = (
        rule.base_score
        + len(matched_keywords) * rule.score_per_keyword
        + direction_bonus
    )
    return RuleMatch(
        rule=rule,
        score=score,
        matched_keywords=matched_keywords,
    )


def direction_matches_category(
    rule: RuleBasedCategoryRule,
    classification_input: CategoryClassificationInput,
) -> bool:
    """Return true when transaction direction agrees with category type."""

    if classification_input.direction == TransactionDirection.INFLOW:
        return rule.category_type == CategoryType.REVENUE
    if classification_input.direction == TransactionDirection.OUTFLOW:
        return rule.category_type == CategoryType.EXPENSE
    return False


def build_haystack(classification_input: CategoryClassificationInput) -> str:
    """Build normalized searchable text from all classification fields."""

    parts = [
        classification_input.text,
        classification_input.counterparty_name or "",
        classification_input.reference or "",
        classification_input.currency or "",
    ]
    return " ".join(part.lower() for part in parts if part)


def fallback_classification(
    classification_input: CategoryClassificationInput,
) -> CategoryClassificationResult:
    """Return a deterministic fallback when no rule matches."""

    category_type = infer_fallback_category_type(classification_input)
    return CategoryClassificationResult(
        category_code=f"uncategorized_{category_type.value}",
        category_type=category_type,
        proposed_direction=proposed_direction_for_category(category_type),
        confidence=ConfidenceLevel.LOW,
        score=0,
        rationale="No rule matched; returned deterministic fallback category.",
        metadata={
            "target_type": classification_input.target_type.value,
            "direction": classification_input.direction.value
            if classification_input.direction is not None
            else None,
            "currency": classification_input.currency,
        },
    )


def infer_fallback_category_type(
    classification_input: CategoryClassificationInput,
) -> CategoryType:
    """Infer broad fallback category type from direction or amount sign."""

    if classification_input.direction == TransactionDirection.INFLOW:
        return CategoryType.REVENUE
    if classification_input.direction == TransactionDirection.OUTFLOW:
        return CategoryType.EXPENSE
    if classification_input.amount is not None:
        if classification_input.amount > Decimal("0"):
            return CategoryType.REVENUE
        if classification_input.amount < Decimal("0"):
            return CategoryType.EXPENSE
    return CategoryType.OTHER


def proposed_direction_for_category(category_type: CategoryType) -> str:
    """Return product-friendly direction text for one category type."""

    if category_type == CategoryType.REVENUE:
        return "income"
    if category_type == CategoryType.EXPENSE:
        return "expense"
    return category_type.value


def confidence_rank(confidence: ConfidenceLevel) -> int:
    """Return comparable confidence rank."""

    ranks = {
        ConfidenceLevel.UNKNOWN: 0,
        ConfidenceLevel.LOW: 1,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.HIGH: 3,
    }
    return ranks[confidence]


def build_invoice_classification_input(
    groups: InvoiceExtractionGroups,
) -> CategoryClassificationInput:
    """Build classification input from invoice extraction groups."""

    text_parts: list[str] = []
    amount: Decimal | None = None
    currency: str | None = None

    if groups.metadata is not None:
        text_parts.extend(
            [
                groups.metadata.invoice_number or "",
                groups.metadata.supplier_name or "",
                groups.metadata.customer_name or "",
            ]
        )
        currency = groups.metadata.currency

    if groups.table is not None:
        text_parts.extend(
            line_item.description or "" for line_item in groups.table.line_items
        )

    if groups.totals is not None:
        amount = parse_decimal(groups.totals.total_amount)
        currency = groups.totals.currency or currency

    return CategoryClassificationInput(
        target_type=ClassificationTargetType.INVOICE,
        text=" ".join(part for part in text_parts if part),
        amount=amount,
        currency=currency,
        metadata={"source": "invoice_extraction_groups"},
    )


def build_transaction_classification_input(
    transaction: StatementTransactionFixture,
) -> CategoryClassificationInput:
    """Build classification input from a parsed statement transaction."""

    text = " ".join(
        part
        for part in [
            transaction.raw_description,
            transaction.normalized_description,
            transaction.counterparty_name,
            transaction.reference,
        ]
        if part
    )
    return CategoryClassificationInput(
        target_type=ClassificationTargetType.TRANSACTION,
        text=text,
        amount=transaction.amount,
        currency=transaction.currency,
        direction=transaction.direction,
        counterparty_name=transaction.counterparty_name,
        reference=transaction.reference,
        metadata={
            "content_hash": transaction.content_hash,
            "external_transaction_id": transaction.external_transaction_id,
        },
    )


def classify_invoice_extraction(
    groups: InvoiceExtractionGroups,
    *,
    classifier: RuleBasedCategoryClassifier | None = None,
) -> CategoryClassificationResult:
    """Classify invoice extraction output using the rule-based classifier."""

    resolved_classifier = classifier or RuleBasedCategoryClassifier()
    return resolved_classifier.classify(build_invoice_classification_input(groups))


def classify_statement_transaction(
    transaction: StatementTransactionFixture,
    *,
    classifier: RuleBasedCategoryClassifier | None = None,
) -> CategoryClassificationResult:
    """Classify one parsed statement transaction using deterministic rules."""

    resolved_classifier = classifier or RuleBasedCategoryClassifier()
    return resolved_classifier.classify(
        build_transaction_classification_input(transaction)
    )
