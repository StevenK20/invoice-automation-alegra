"""Parse DIAN UBL 2.1 documents (Invoice / CreditNote / DebitNote) into models.

All parsing goes through ``defusedxml`` so entity-expansion and external-entity
attacks are rejected. The embedded document inside an ``AttachedDocument`` is
parsed with the same safe parser.
"""
from __future__ import annotations

import re

from defusedxml import ElementTree as ET

from .models import DocumentType, Invoice, InvoiceLine, Supplier

NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
_ROOTS = {"Invoice": DocumentType.INVOICE, "CreditNote": DocumentType.CREDIT_NOTE,
          "DebitNote": DocumentType.DEBIT_NOTE}
_LINE_TAG = {DocumentType.INVOICE: ("InvoiceLine", "InvoicedQuantity"),
             DocumentType.CREDIT_NOTE: ("CreditNoteLine", "CreditedQuantity"),
             DocumentType.DEBIT_NOTE: ("DebitNoteLine", "DebitedQuantity")}
VAT_SCHEME_ID = "01"   # DIAN tax scheme code for IVA


class InvoiceParseError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _txt(node, path: str, default: str = "") -> str:
    if node is None:
        return default
    el = node.find(path, NS)
    return el.text.strip() if el is not None and el.text else default


def _num(node, path: str, default: float = 0.0) -> float:
    value = _txt(node, path)
    try:
        return float(value) if value else default
    except ValueError:
        return default


def extract_document(xml_bytes: bytes):
    """Return the UBL root element, unwrapping an AttachedDocument if needed."""
    text = xml_bytes.decode("utf-8", errors="replace").lstrip("﻿")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise InvoiceParseError(f"Malformed XML: {exc}") from exc
    if _local(root.tag) in _ROOTS:
        return root
    # AttachedDocument: the real document lives as text inside a cbc:Description
    for desc in root.iter("{%s}Description" % NS["cbc"]):
        body = desc.text or ""
        if any(f"<{name}" in body for name in _ROOTS):
            inner = body[body.find("<"):].strip()
            inner = re.sub(r"^<\?xml[^>]*\?>", "", inner).strip()
            return ET.fromstring(inner.encode("utf-8"))
    raise InvoiceParseError("No Invoice/CreditNote/DebitNote found in the XML")


def _unit_price(price_xml: float, base_qty: float, qty: float, net: float,
                allowances: list[float], bases: list[float]) -> float:
    """Some suppliers send PriceAmount per unit and others per BaseQuantity, and some
    add 'informative' discounts that are not really applied. The price is the
    candidate that reproduces one of the plausible gross amounts."""
    targets = bases + [net + a for a in allowances] + [net + sum(allowances), net]
    candidates = [price_xml, price_xml / base_qty] if price_xml else []
    for target in targets:
        for cand in candidates:
            if qty and cand * qty >= net - 1 and abs(cand * qty - target) <= max(2, target * 0.001):
                return cand
    if qty:
        return (bases[0] if bases else net + sum(allowances)) / qty
    return 0.0


def _parse_line(node, n: int, qty_tag: str) -> InvoiceLine:
    qty = _num(node, f"cbc:{qty_tag}")
    net = _num(node, "cbc:LineExtensionAmount")
    allowances, bases = [], []
    for ac in node.findall("cac:AllowanceCharge", NS):
        if _txt(ac, "cbc:ChargeIndicator", "false").lower() == "false":
            allowances.append(_num(ac, "cbc:Amount"))
            if _num(ac, "cbc:BaseAmount"):
                bases.append(_num(ac, "cbc:BaseAmount"))
    price = _unit_price(_num(node, "cac:Price/cbc:PriceAmount"),
                        _num(node, "cac:Price/cbc:BaseQuantity", 1.0) or 1.0,
                        qty, net, allowances, bases)
    gross = price * qty
    # the discount is always derived from the amounts, never trusted from MultiplierFactorNumeric
    discount = (1 - net / gross) * 100 if gross and net < gross - 0.5 else 0.0
    tax_pct, tax_amount = 0.0, 0.0
    for sub in node.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        if _txt(sub, "cac:TaxCategory/cac:TaxScheme/cbc:ID", VAT_SCHEME_ID) == VAT_SCHEME_ID:
            tax_pct = _num(sub, "cac:TaxCategory/cbc:Percent", _num(sub, "cbc:Percent"))
            tax_amount += _num(sub, "cbc:TaxAmount")
    return InvoiceLine(
        line_no=n,
        supplier_code=_txt(node, "cac:Item/cac:SellersItemIdentification/cbc:ID"),
        standard_code=_txt(node, "cac:Item/cac:StandardItemIdentification/cbc:ID"),
        description=" ".join(_txt(node, "cac:Item/cbc:Description").split()),
        quantity=qty,
        unit_price=round(price, 4),
        discount_pct=round(max(discount, 0.0), 4),
        net_amount=net,
        tax_pct=tax_pct,
        tax_amount=round(tax_amount, 2),
    )


def parse_invoice(xml_bytes: bytes, source: str = "") -> Invoice:
    root = extract_document(xml_bytes)
    doc_type = _ROOTS[_local(root.tag)]
    line_tag, qty_tag = _LINE_TAG[doc_type]

    party = root.find("cac:AccountingSupplierParty/cac:Party", NS)
    cid = None
    if party is not None:
        # explicit None checks: an Element without children is falsy
        cid = party.find("cac:PartyTaxScheme/cbc:CompanyID", NS)
        if cid is None:
            cid = party.find("cac:PartyLegalEntity/cbc:CompanyID", NS)
    nit = re.sub(r"\D", "", cid.text if cid is not None and cid.text else "")
    name = (_txt(party, "cac:PartyTaxScheme/cbc:RegistrationName")
            or _txt(party, "cac:PartyLegalEntity/cbc:RegistrationName"))
    supplier = Supplier(nit=nit, dv=(cid.get("schemeID") or "") if cid is not None else "",
                        name=" ".join(name.split()))

    issue = _txt(root, "cbc:IssueDate")
    due = _txt(root, "cbc:DueDate") or _txt(root, "cac:PaymentMeans/cbc:PaymentDueDate") or issue
    if due and issue and due < issue:      # Alegra rejects due < issue date
        due = issue

    lines = [_parse_line(node, i, qty_tag)
             for i, node in enumerate(root.findall(f"cac:{line_tag}", NS), start=1)]
    totals = root.find("cac:LegalMonetaryTotal", NS)
    if totals is None:                      # debit notes use RequestedMonetaryTotal
        totals = root.find("cac:RequestedMonetaryTotal", NS)
    tax_total = sum(_num(t, "cbc:TaxAmount") for t in root.findall("cac:TaxTotal", NS))

    return Invoice(
        source=source,
        doc_type=doc_type,
        number=_txt(root, "cbc:ID"),
        cufe=_txt(root, "cbc:UUID"),
        issue_date=issue,
        due_date=due,
        supplier=supplier,
        currency=_txt(root, "cbc:DocumentCurrencyCode", "COP"),
        lines=lines,
        line_extension_total=_num(totals, "cbc:LineExtensionAmount"),
        tax_total=round(tax_total, 2),
        payable_total=_num(totals, "cbc:PayableAmount"),
        billing_reference=_txt(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"),
    )
