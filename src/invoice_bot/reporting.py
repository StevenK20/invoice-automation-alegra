"""CSV reports and the run summary."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .models import InvoiceResult, Status
from .pricing import suggested_price


def write_reports(results: list[InvoiceResult], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"results": out_dir / "results.csv", "review": out_dir / "review_queue.csv"}

    with open(paths["results"], "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "status", "doc_type", "number", "supplier_nit", "supplier", "issue_date",
                    "lines", "lines_auto_matched", "payable_total", "alegra_id", "issues", "detail"])
        for r in results:
            inv = r.invoice
            w.writerow([
                r.source, r.status.value, inv.doc_type.value if inv else "", inv.number if inv else "",
                inv.supplier.nit if inv else "", inv.supplier.name if inv else "",
                inv.issue_date if inv else "", len(inv.lines) if inv else 0,
                sum(1 for m in r.matches if m.accepted), f"{inv.payable_total:.2f}" if inv else "",
                r.alegra_id, "|".join(i.code for i in r.issues), r.detail,
            ])

    with open(paths["review"], "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["number", "supplier_nit", "line", "supplier_code", "description", "quantity",
                    "unit_cost", "suggested_item_id", "suggested_item", "score", "reason",
                    "suggested_retail_price", "decision_item_id", "decision_pack_factor"])
        for r in results:
            if r.status is not Status.NEEDS_REVIEW:
                continue
            inv = r.invoice
            pending = [m for m in r.matches if not m.accepted]
            if not pending:   # blocked at document level (totals, supplier, tax)
                w.writerow([inv.number, inv.supplier.nit, "", "", "(whole document)", "", "", "", "", "",
                            r.detail, "", "", ""])
            for m in pending:
                cost = m.line.unit_price * (1 - m.line.discount_pct / 100)
                w.writerow([inv.number, inv.supplier.nit, m.line.line_no, m.line.supplier_code,
                            m.line.description, m.line.quantity, f"{cost:.2f}", m.item_id or "",
                            m.item_name, f"{m.confidence:.2f}" if m.item_id else "", m.reason,
                            suggested_price(cost) if m.item_id is None else "", "", ""])
    return paths


def summary(results: list[InvoiceResult]) -> str:
    by_status = Counter(r.status.value for r in results)
    lines = [m for r in results if r.invoice and r.status in (Status.PROCESSED, Status.NEEDS_REVIEW)
             for m in r.matches]
    auto = sum(1 for m in lines if m.accepted)
    layers = Counter(m.layer for m in lines if m.accepted)
    rows = [f"Documents read: {len(results)}"]
    rows += [f"  {k:<13} {v}" for k, v in sorted(by_status.items())]
    if lines:
        rows.append(f"Product lines: {len(lines)} | matched without intervention: {auto} "
                    f"({auto / len(lines):.0%})")
        rows.append("  by layer: " + ", ".join(f"{k}={v}" for k, v in layers.most_common()))
    return "\n".join(rows)
