"""Command line entry point.

    python -m invoice_bot demo                     # dry-run over sample_data/ (no account needed)
    python -m invoice_bot run --input invoices/    # dry-run over your own files
    python -m invoice_bot run --input invoices/ --send   # really create bills (needs .env)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .alegra_client import AlegraClient, AlegraError, DryRunClient
from .matcher import Catalog, ProductMatcher, load_equivalences
from .pipeline import InvoicePipeline
from .reporting import summary, write_reports

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "sample_data"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines) so python-dotenv is not required."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _setup_logging(out_dir: Path, verbose: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    file_handler = logging.FileHandler(out_dir / "decisions.log", mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [file_handler, console]
    root.setLevel(logging.DEBUG)


def learn_from_review(review_csv: Path, equivalences_csv: Path) -> int:
    """Close the human-in-the-loop: every reviewed line with a decision becomes a rule,
    so the same supplier code is matched automatically next month."""
    import csv

    with open(review_csv, encoding="utf-8") as fh:
        decided = [r for r in csv.DictReader(fh)
                   if (r.get("decision_item_id") or "").strip() and r.get("supplier_code")]
    if not decided:
        return 0
    new_file = not equivalences_csv.exists()
    with open(equivalences_csv, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["supplier_nit", "supplier_code", "item_id", "pack_factor", "note"])
        for r in decided:
            w.writerow([r["supplier_nit"], r["supplier_code"], r["decision_item_id"].strip(),
                        (r.get("decision_pack_factor") or "1").strip() or "1",
                        f"reviewed: {r['description'][:60]}"])
    return len(decided)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="invoice_bot", description="DIAN e-invoice -> Alegra purchase bills")
    sub = ap.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="dry-run over the bundled fictitious sample data")
    run = sub.add_parser("run", help="process a folder of ZIP/XML invoices")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--catalog", type=Path, default=SAMPLE / "catalog.csv")
    run.add_argument("--equivalences", type=Path, default=SAMPLE / "equivalences.csv")
    run.add_argument("--send", action="store_true", help="really create bills in Alegra (default: dry-run)")
    for p in (demo, run):
        p.add_argument("--output", type=Path, default=ROOT / "output")
        p.add_argument("-v", "--verbose", action="store_true", help="show every matching decision")
    learn = sub.add_parser("learn", help="turn reviewed lines (decision_item_id filled) into equivalences")
    learn.add_argument("--review", type=Path, default=ROOT / "output" / "review_queue.csv")
    learn.add_argument("--equivalences", type=Path, default=SAMPLE / "equivalences.csv")
    args = ap.parse_args(argv)

    if args.command == "learn":
        added = learn_from_review(args.review, args.equivalences)
        print(f"{added} equivalence(s) added to {args.equivalences}")
        return 0

    _setup_logging(args.output, args.verbose)
    log = logging.getLogger("invoice_bot")

    if args.command == "demo":
        folder, catalog, eqs, send = SAMPLE / "invoices", SAMPLE / "catalog.csv", SAMPLE / "equivalences.csv", False
    else:
        folder, catalog, eqs, send = args.input, args.catalog, args.equivalences, args.send

    if send:
        _load_dotenv(ROOT / ".env")
        try:
            alegra = AlegraClient(os.getenv("ALEGRA_EMAIL", ""), os.getenv("ALEGRA_TOKEN", ""))
        except AlegraError as exc:
            log.error(str(exc))
            return 2
        mode = "LIVE: bills will be created in Alegra"
    else:
        alegra = DryRunClient.from_sample_data(SAMPLE, outbox=args.output / "dry_run_payloads")
        mode = "DRY-RUN: nothing is sent; payloads are written to output/dry_run_payloads/"

    log.info("=" * 78)
    log.info("Mode: %s", mode)
    try:
        shown = Path(folder).resolve().relative_to(ROOT)
    except ValueError:
        shown = folder
    log.info("Input: %s", shown)
    log.info("=" * 78)
    matcher = ProductMatcher(Catalog.from_csv(catalog), load_equivalences(eqs))
    pipeline = InvoicePipeline(alegra, matcher, warehouse_id=os.getenv("ALEGRA_WAREHOUSE_ID", "1"))
    results = pipeline.run(folder)
    paths = write_reports(results, args.output)

    log.info("-" * 78)
    log.info(summary(results))
    log.info("Reports: %s | %s | %s", paths["results"].name, paths["review"].name, "decisions.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
