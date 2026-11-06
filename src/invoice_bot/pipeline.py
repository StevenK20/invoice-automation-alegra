"""Orchestration: documents -> validation -> matching -> Alegra bill -> result.

Design rule: **a bill is all-or-nothing.** If any line needs a human decision the
whole document goes to the review queue; posting a partial purchase bill would
leave inventory and accounts payable silently wrong.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .alegra_client import AlegraAPI, AlegraError
from .matcher import ProductMatcher
from .models import DocumentType, Invoice, InvoiceResult, MatchResult, Status
from .validators import is_duplicate, validate_document
from .xml_parser import InvoiceParseError, parse_invoice
from .zip_reader import iter_documents

log = logging.getLogger("invoice_bot.decisions")


class InvoicePipeline:
    def __init__(self, alegra: AlegraAPI, matcher: ProductMatcher, warehouse_id: str = "1"):
        self.alegra = alegra
        self.matcher = matcher
        self.warehouse_id = warehouse_id
        self.known_cufes, self.known_numbers = alegra.registered_bills()

    # ---------------------------------------------------------------- public
    def run(self, folder: Path) -> list[InvoiceResult]:
        results = []
        for source, doc in iter_documents(folder):
            if isinstance(doc, Exception):
                results.append(self._log(InvoiceResult(None, source, Status.ERROR, detail=str(doc))))
                continue
            try:
                invoice = parse_invoice(doc.content, source)
            except InvoiceParseError as exc:
                results.append(self._log(InvoiceResult(None, source, Status.ERROR, detail=str(exc))))
                continue
            results.append(self._log(self.process(invoice)))
        return results

    def process(self, inv: Invoice) -> InvoiceResult:
        issues = validate_document(inv, self.known_cufes, self.known_numbers)
        res = InvoiceResult(inv, inv.source, Status.PROCESSED, issues)
        blocking = [i for i in issues if i.blocking]

        if is_duplicate(issues):
            res.status, res.detail = Status.DUPLICATE, _join(i.message for i in issues if i.code.startswith("DUP"))
            return res
        if inv.doc_type is not DocumentType.INVOICE:
            res.status, res.detail = Status.SKIPPED, _join(i.message for i in blocking)
            return res

        res.matches = [self.matcher.match(inv.supplier.nit, line) for line in inv.lines]
        provider = self.alegra.provider_id(inv.supplier.nit)
        pending = [m for m in res.matches if not m.accepted]

        reasons = [i.message for i in blocking]
        if provider is None:
            reasons.append(f"Supplier NIT {inv.supplier.nit} ({inv.supplier.name}) is not a contact in Alegra")
        if pending:
            reasons.append(f"{len(pending)} of {len(inv.lines)} line(s) need a product decision")
        missing_tax = sorted({m.line.tax_pct for m in res.matches if self.alegra.tax_id(m.line.tax_pct) is None})
        if missing_tax:
            reasons.append(f"VAT rate(s) {missing_tax} not configured in Alegra")
        if reasons:
            res.status, res.detail = Status.NEEDS_REVIEW, _join(reasons)
            return res

        payload = self.build_payload(inv, provider, res.matches)
        try:
            created = self.alegra.create_bill(payload)
        except AlegraError as exc:
            res.status, res.detail = Status.ERROR, str(exc)
            return res
        res.alegra_id = str(created.get("id", ""))
        res.detail = ("dry-run: payload saved, nothing sent" if self.alegra.dry_run
                      else f"created in Alegra (id {res.alegra_id})")
        if inv.cufe:                       # protect against the same file twice in one run
            self.known_cufes.add(inv.cufe)
        self.known_numbers.add(f"{inv.supplier.nit}:{inv.number}")
        return res

    def build_payload(self, inv: Invoice, provider_id: str, matches: list[MatchResult]) -> dict:
        items = []
        for m in matches:
            qty = m.line.quantity * m.pack_factor          # box of 12 -> 12 units
            items.append({
                "id": int(m.item_id),
                "price": round(m.line.unit_price / m.pack_factor, 4),
                "quantity": qty,
                "discount": m.line.discount_pct,
                "tax": [{"id": int(self.alegra.tax_id(m.line.tax_pct))}],
            })
        return {
            "date": inv.issue_date,
            "dueDate": inv.due_date,
            "provider": int(provider_id),
            "numberTemplate": {"number": inv.number},
            "warehouse": {"id": self.warehouse_id},
            "purchases": {"items": items},
            "observations": f"Loaded automatically from e-invoice XML on {date.today():%Y-%m-%d}",
        }

    # ---------------------------------------------------------------- logging
    @staticmethod
    def _log(res: InvoiceResult) -> InvoiceResult:
        number = res.invoice.number if res.invoice else "-"
        log.info("%-12s %-9s %s | %s", res.status.value.upper(), number, res.source, res.detail)
        for m in res.matches:
            if m.accepted:
                log.debug("   line %d %-14s -> item %s via %s (%.0f%%)%s", m.line.line_no,
                          m.line.supplier_code, m.item_id, m.layer, m.confidence * 100,
                          f" x{m.pack_factor:g}" if m.pack_factor != 1 else "")
            else:
                log.info("   line %d %-14s -> REVIEW: %s", m.line.line_no, m.line.supplier_code, m.reason)
        for issue in res.issues:
            log.debug("   check %s: %s", issue.code, issue.message)
        return res


def _join(parts) -> str:
    return "; ".join(p for p in parts if p)
