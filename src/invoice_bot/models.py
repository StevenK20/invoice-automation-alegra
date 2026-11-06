"""Domain models shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DocumentType(str, Enum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"


class Status(str, Enum):
    PROCESSED = "processed"          # sent to Alegra (or would be, in dry-run)
    NEEDS_REVIEW = "needs_review"    # a human has to decide something
    DUPLICATE = "duplicate"          # already registered (same CUFE / number)
    SKIPPED = "skipped"              # not a purchase document we handle (e.g. credit note)
    ERROR = "error"                  # could not be read or the API rejected it


@dataclass
class Supplier:
    nit: str                 # digits only, without verification digit
    dv: str = ""             # verification digit as sent in the XML (schemeID)
    name: str = ""


@dataclass
class InvoiceLine:
    line_no: int
    supplier_code: str       # SellersItemIdentification
    standard_code: str       # StandardItemIdentification (usually EAN-13 barcode)
    description: str
    quantity: float
    unit_price: float        # before discount, before tax
    discount_pct: float      # 0-100
    net_amount: float        # LineExtensionAmount (after discount, before tax)
    tax_pct: float
    tax_amount: float

    @property
    def gross_amount(self) -> float:
        return self.unit_price * self.quantity


@dataclass
class Invoice:
    source: str              # zip/xml file it came from
    doc_type: DocumentType
    number: str
    cufe: str                # DIAN unique code (cbc:UUID)
    issue_date: str
    due_date: str
    supplier: Supplier
    currency: str
    lines: list[InvoiceLine] = field(default_factory=list)
    line_extension_total: float = 0.0   # LegalMonetaryTotal/LineExtensionAmount
    tax_total: float = 0.0              # TaxTotal/TaxAmount (document level)
    payable_total: float = 0.0          # LegalMonetaryTotal/PayableAmount
    billing_reference: str = ""         # invoice a credit/debit note refers to


@dataclass
class MatchResult:
    """Outcome of matching one invoice line against the catalog."""
    line: InvoiceLine
    item_id: str | None
    item_name: str = ""
    layer: str = ""          # equivalence | supplier_code | standard_code | fuzzy | none
    confidence: float = 0.0  # 0..1
    pack_factor: float = 1.0 # supplier sells boxes, catalog counts units
    reason: str = ""         # why it went to review (if it did)

    @property
    def accepted(self) -> bool:
        return self.item_id is not None and not self.reason


@dataclass
class ValidationIssue:
    code: str                # TOTALS_MISMATCH, INVALID_NIT, DUPLICATE_CUFE, ...
    message: str
    blocking: bool = True


@dataclass
class InvoiceResult:
    invoice: Invoice | None
    source: str
    status: Status
    issues: list[ValidationIssue] = field(default_factory=list)
    matches: list[MatchResult] = field(default_factory=list)
    alegra_id: str = ""
    detail: str = ""
