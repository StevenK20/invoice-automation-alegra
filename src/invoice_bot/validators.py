"""Business validations run before any product matching or API call."""
from __future__ import annotations

import re

from .models import DocumentType, Invoice, ValidationIssue

# DIAN "dígito de verificación" weights, applied from the rightmost digit
_DV_WEIGHTS = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
TOTALS_TOLERANCE = 2.0          # COP; rounding differences between lines and totals


def nit_check_digit(nit: str) -> int:
    """Return the DIAN verification digit for a NIT (digits only)."""
    digits = re.sub(r"\D", "", nit)
    if not digits or len(digits) > len(_DV_WEIGHTS):
        raise ValueError(f"Invalid NIT: {nit!r}")
    total = sum(int(d) * w for d, w in zip(reversed(digits), _DV_WEIGHTS))
    rest = total % 11
    return rest if rest in (0, 1) else 11 - rest


def validate_nit(nit: str, dv: str) -> list[ValidationIssue]:
    if not re.fullmatch(r"\d{6,10}", nit or ""):
        return [ValidationIssue("INVALID_NIT", f"NIT '{nit}' must have 6 to 10 digits")]
    if dv and dv.isdigit() and int(dv) != nit_check_digit(nit):
        return [ValidationIssue(
            "INVALID_NIT_DV",
            f"NIT {nit}-{dv}: verification digit should be {nit_check_digit(nit)}")]
    return []


def validate_totals(inv: Invoice) -> list[ValidationIssue]:
    """Sum of line nets must equal the document subtotal; subtotal + tax must equal payable."""
    issues = []
    lines_sum = round(sum(l.net_amount for l in inv.lines), 2)
    if abs(lines_sum - inv.line_extension_total) > TOTALS_TOLERANCE:
        issues.append(ValidationIssue(
            "TOTALS_MISMATCH",
            f"Lines add up to {lines_sum:,.2f} but the invoice subtotal is "
            f"{inv.line_extension_total:,.2f}"))
    line_taxes = round(sum(l.tax_amount for l in inv.lines), 2)
    if abs(line_taxes - inv.tax_total) > TOTALS_TOLERANCE:
        issues.append(ValidationIssue(
            "TAX_MISMATCH", f"Line taxes {line_taxes:,.2f} vs document tax {inv.tax_total:,.2f}"))
    expected = inv.line_extension_total + inv.tax_total
    # payable may legitimately differ by withholdings/charges, so this one is a warning
    if abs(expected - inv.payable_total) > TOTALS_TOLERANCE:
        issues.append(ValidationIssue(
            "PAYABLE_DIFFERS",
            f"Subtotal + tax = {expected:,.2f}, payable = {inv.payable_total:,.2f} "
            "(withholding or other charges?)", blocking=False))
    return issues


def validate_document(inv: Invoice, known_cufes: set[str], known_numbers: set[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not inv.lines:
        issues.append(ValidationIssue("NO_LINES", "Document has no product lines"))
    issues += validate_nit(inv.supplier.nit, inv.supplier.dv)
    if inv.cufe and inv.cufe in known_cufes:
        issues.append(ValidationIssue("DUPLICATE_CUFE", f"CUFE already registered ({inv.cufe[:16]}...)"))
    elif f"{inv.supplier.nit}:{inv.number}" in known_numbers:
        issues.append(ValidationIssue("DUPLICATE_NUMBER", f"Invoice {inv.number} already registered"))
    if not inv.cufe:
        issues.append(ValidationIssue("MISSING_CUFE", "Document has no CUFE/CUDE", blocking=False))
    if inv.doc_type is not DocumentType.INVOICE:
        ref = f" (refers to {inv.billing_reference})" if inv.billing_reference else ""
        issues.append(ValidationIssue(
            "NOT_AN_INVOICE", f"{inv.doc_type.value.replace('_', ' ')}{ref}: register it as a "
            "supplier credit/debit note, not as a purchase bill"))
    issues += validate_totals(inv)
    return issues


def is_duplicate(issues: list[ValidationIssue]) -> bool:
    return any(i.code.startswith("DUPLICATE") for i in issues)
