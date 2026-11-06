import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from invoice_bot.matcher import Catalog, CatalogItem, Equivalence, ProductMatcher  # noqa: E402
from invoice_bot.models import DocumentType, Invoice, InvoiceLine, Supplier  # noqa: E402

SAMPLE = ROOT / "sample_data"


def make_line(n=1, code="X-1", desc="PRODUCTO DEMO", qty=1.0, price=1000.0, disc=0.0, vat=19.0, ean=""):
    net = round(qty * price * (1 - disc / 100), 2)
    return InvoiceLine(n, code, ean, desc, qty, price, disc, net, vat, round(net * vat / 100, 2))


def make_invoice(lines=None, nit="900111222", dv="1", cufe="abc123", number="F1",
                 doc_type=DocumentType.INVOICE, subtotal=None):
    lines = lines if lines is not None else [make_line()]
    sub = sum(l.net_amount for l in lines) if subtotal is None else subtotal
    tax = round(sum(l.tax_amount for l in lines), 2)
    return Invoice("test.xml", doc_type, number, cufe, "2026-01-10", "2026-02-10",
                   Supplier(nit, dv, "PROVEEDOR DEMO"), "COP", lines, sub, tax, sub + tax)


@pytest.fixture
def matcher():
    catalog = Catalog([
        CatalogItem("1", "PASTILLAS FRENO DELANTERAS 150CC", "PF-150", "7709990000011"),
        CatalogItem("2", "CADENA 428H 120L REFORZADA", "CD-428"),
        CatalogItem("3", "CADENA 428H 120L VIEJA", "CD-428-OLD", active=False),
        CatalogItem("4", "KIT ARRASTRE CB 125 ESTANDAR", "KA-E"),
        CatalogItem("5", "KIT ARRASTRE CB 125 REFORZADO", "KA-R"),
        CatalogItem("6", "ACEITE 4T 20W50 1L", "AC-1L"),
        CatalogItem("7", "FILTRO ACEITE CB 190", "FA-190"),
    ])
    eqs = {("900333444", "LVC12"): Equivalence("6", 12.0),
           ("900333444", "LVOLD"): Equivalence("3")}          # points to an inactive item
    return ProductMatcher(catalog, eqs)
