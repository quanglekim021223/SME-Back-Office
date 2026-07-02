from decimal import Decimal

from app.classification import (
    CategoryClassificationInput,
    RuleBasedCategoryClassifier,
    RuleBasedCategoryRule,
    build_invoice_classification_input,
    build_transaction_classification_input,
    classify_invoice_extraction,
    classify_statement_transaction,
)
from app.fixtures import load_invoice_extraction_fixture, load_statement_parsing_fixture
from app.models.accounting import CategoryType, ClassificationTargetType
from app.models.banking import TransactionDirection
from app.workflows import ConfidenceLevel


def test_classifier_classifies_invoice_fixture_as_professional_services() -> None:
    fixture = load_invoice_extraction_fixture()

    result = classify_invoice_extraction(fixture.extraction_groups)

    assert result.category_code == "professional_services"
    assert result.category_type == CategoryType.REVENUE
    assert result.proposed_direction == "income"
    assert result.confidence == ConfidenceLevel.HIGH
    assert result.matched_rule_ids == ["revenue_professional_services"]
    assert {"advisory", "retainer"}.issubset(set(result.matched_keywords))


def test_invoice_classification_input_collects_text_amount_and_currency() -> None:
    fixture = load_invoice_extraction_fixture()

    classification_input = build_invoice_classification_input(fixture.extraction_groups)

    assert classification_input.target_type == ClassificationTargetType.INVOICE
    assert classification_input.amount == Decimal("110.00")
    assert classification_input.currency == "USD"
    assert "Advisory retainer" in classification_input.text
    assert "Northwind Consulting LLC" in classification_input.text


def test_rule_based_classifier_classifies_statement_transactions() -> None:
    fixture = load_statement_parsing_fixture()

    first_result = classify_statement_transaction(fixture.transactions[0])
    second_result = classify_statement_transaction(fixture.transactions[1])
    third_result = classify_statement_transaction(fixture.transactions[2])

    assert first_result.category_code == "sales_revenue"
    assert first_result.category_type == CategoryType.REVENUE
    assert first_result.proposed_direction == "income"
    assert "inv-" in first_result.matched_keywords

    assert second_result.category_code == "software_subscription"
    assert second_result.category_type == CategoryType.EXPENSE
    assert second_result.proposed_direction == "expense"
    assert "cloud hosting" in second_result.matched_keywords

    assert third_result.category_code == "professional_services"
    assert third_result.category_type == CategoryType.REVENUE
    assert third_result.proposed_direction == "income"
    assert "retainer" in third_result.matched_keywords


def test_transaction_classification_input_collects_transaction_context() -> None:
    fixture = load_statement_parsing_fixture()
    transaction = fixture.transactions[0]

    classification_input = build_transaction_classification_input(transaction)

    assert classification_input.target_type == ClassificationTargetType.TRANSACTION
    assert classification_input.amount == Decimal("110.00")
    assert classification_input.direction == TransactionDirection.INFLOW
    assert classification_input.counterparty_name == "Northwind Consulting LLC"
    assert classification_input.reference == "INV-FIX-001"
    assert classification_input.metadata["content_hash"] == (
        "fixture-transaction-hash-001"
    )


def test_rule_based_classifier_returns_expense_fallback_for_unmatched_outflow() -> None:
    classifier = RuleBasedCategoryClassifier()

    result = classifier.classify(
        CategoryClassificationInput(
            target_type=ClassificationTargetType.TRANSACTION,
            text="unknown vendor purchase",
            amount=Decimal("-25.00"),
            direction=TransactionDirection.OUTFLOW,
            currency="USD",
        )
    )

    assert result.category_code == "uncategorized_expense"
    assert result.category_type == CategoryType.EXPENSE
    assert result.proposed_direction == "expense"
    assert result.confidence == ConfidenceLevel.LOW
    assert result.score == 0
    assert result.matched_rule_ids == []


def test_rule_based_classifier_returns_revenue_fallback_for_unmatched_inflow() -> None:
    classifier = RuleBasedCategoryClassifier()

    result = classifier.classify(
        CategoryClassificationInput(
            target_type=ClassificationTargetType.TRANSACTION,
            text="unrecognized incoming transfer",
            amount=Decimal("100.00"),
            direction=TransactionDirection.INFLOW,
            currency="USD",
        )
    )

    assert result.category_code == "uncategorized_revenue"
    assert result.category_type == CategoryType.REVENUE
    assert result.proposed_direction == "income"


def test_rule_target_type_filter_prevents_wrong_target_match() -> None:
    classifier = RuleBasedCategoryClassifier(
        rules=(
            RuleBasedCategoryRule(
                rule_id="transaction_only_rule",
                category_code="sales_revenue",
                category_type=CategoryType.REVENUE,
                keywords=["invoice"],
                target_types=[ClassificationTargetType.TRANSACTION],
                rationale="Only transaction records should match this rule.",
            ),
        )
    )

    result = classifier.classify(
        CategoryClassificationInput(
            target_type=ClassificationTargetType.INVOICE,
            text="invoice payment received",
            amount=Decimal("100.00"),
            currency="USD",
        )
    )

    assert result.category_code == "uncategorized_revenue"
    assert result.matched_rule_ids == []


def test_direction_requirement_prevents_outflow_from_matching_inflow_rule() -> None:
    classifier = RuleBasedCategoryClassifier()

    result = classifier.classify(
        CategoryClassificationInput(
            target_type=ClassificationTargetType.TRANSACTION,
            text="ACH CREDIT INV-123",
            amount=Decimal("-100.00"),
            direction=TransactionDirection.OUTFLOW,
            currency="USD",
        )
    )

    assert result.category_code == "uncategorized_expense"
    assert "revenue_sales_invoice_payment" not in result.matched_rule_ids
