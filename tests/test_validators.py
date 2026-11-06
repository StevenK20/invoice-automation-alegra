import pytest

from conftest import make_invoice, make_line
from invoice_bot.models import DocumentType
from invoice_bot.validators import nit_check_digit, validate_document, validate_nit, validate_totals


@pytest.mark.parametrize("nit,dv", [("900111222", 1), ("900333444", 0), ("900555666", 1), ("800777888", 1)])
def test_nit_check_digit(nit, dv):
    assert nit_check_digit(nit) == dv


def test_valid_nit_has_no_issues():
    assert validate_nit("900111222", "1") == []


def test_wrong_check_digit_is_reported():
    issues = validate_nit("900111222", "5")
    assert issues[0].code == "INVALID_NIT_DV" and "should be 1" in issues[0].message


@pytest.mark.parametrize("nit", ["", "12AB", "123", "12345678901"])
def test_malformed_nit(nit):
    assert validate_nit(nit, "")[0].code == "INVALID_NIT"


def test_totals_ok_within_rounding_tolerance():
    inv = make_invoice([make_line(qty=3, price=333.33)])
    inv.line_extension_total += 1.0       # one peso of rounding is fine
    inv.payable_total += 1.0
    assert validate_totals(inv) == []


def test_totals_mismatch_is_blocking():
    inv = make_invoice([make_line(qty=2, price=10000)], subtotal=25000)
    codes = {i.code: i for i in validate_totals(inv)}
    assert codes["TOTALS_MISMATCH"].blocking


def test_payable_difference_is_only_a_warning():
    inv = make_invoice()
    inv.payable_total -= 500          # e.g. withholding tax
    issue = validate_totals(inv)[0]
    assert issue.code == "PAYABLE_DIFFERS" and not issue.blocking


def test_duplicate_cufe_detected():
    issues = validate_document(make_invoice(cufe="XYZ"), {"XYZ"}, set())
    assert "DUPLICATE_CUFE" in [i.code for i in issues]


def test_duplicate_number_when_no_cufe_match():
    issues = validate_document(make_invoice(cufe="NEW", number="F9"), set(), {"900111222:F9"})
    assert "DUPLICATE_NUMBER" in [i.code for i in issues]


def test_credit_note_flagged_as_not_an_invoice():
    issues = validate_document(make_invoice(doc_type=DocumentType.CREDIT_NOTE), set(), set())
    assert "NOT_AN_INVOICE" in [i.code for i in issues]


def test_document_without_lines():
    assert "NO_LINES" in [i.code for i in validate_document(make_invoice(lines=[]), set(), set())]
