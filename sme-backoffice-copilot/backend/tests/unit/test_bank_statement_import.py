from decimal import Decimal

from app.models.banking import TransactionDirection
from app.services.bank_statement_import import parse_statement_csv


def test_parse_statement_csv_supports_metadata_header_rows() -> None:
    rows, metadata = parse_statement_csv(
        "\n".join(
            [
                "Bank Name,Local First Bank",
                "Account Type,Business Checking",
                "Account Number,XXXX-XXXX-4821",
                "Statement Period,02/01/2019 to 02/28/2019",
                "Account Holder,Demo Coffee Co. / John Smith",
                "",
                "Date,Description,Debit,Credit,Balance",
                '02/12/2019,ACH PAYMENT EAST REPAIR INC US-001,154.06,,"4,845.94"',
            ]
        )
    )

    assert metadata.bank_name == "Local First Bank"
    assert metadata.account_number == "XXXX-XXXX-4821"
    assert metadata.statement_start_date is not None
    assert metadata.statement_start_date.isoformat() == "2019-02-01"
    assert len(rows) == 1
    assert rows[0].posted_at is not None
    assert rows[0].posted_at.isoformat() == "2019-02-12"
    assert rows[0].amount == Decimal("-154.06")
    assert rows[0].direction == TransactionDirection.OUTFLOW
    assert rows[0].balance == Decimal("4845.94")
    assert rows[0].reference == "US-001"
    assert rows[0].counterparty_name == "EAST REPAIR INC"
