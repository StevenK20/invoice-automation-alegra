import zipfile

import pytest

from conftest import SAMPLE
from invoice_bot.models import DocumentType
from invoice_bot.xml_parser import InvoiceParseError, parse_invoice
from invoice_bot.zip_reader import UnsafeArchiveError, read_zip

INVOICES = SAMPLE / "invoices"


def _first_xml(name):
    return read_zip(INVOICES / name)[0].content


def test_attached_document_is_unwrapped():
    inv = parse_invoice(_first_xml("01_normal_DAP1001.zip"))
    assert inv.number == "DAP1001" and inv.doc_type is DocumentType.INVOICE
    assert inv.supplier.nit == "900111222" and inv.supplier.dv == "1"
    assert len(inv.cufe) == 96 and len(inv.lines) == 4


def test_line_discount_and_base_quantity():
    lines = parse_invoice(_first_xml("02_discounts_LUB2210.zip")).lines
    assert lines[0].discount_pct == pytest.approx(8.0)
    assert lines[1].unit_price == pytest.approx(15400)   # price was sent per BaseQuantity=12
    assert lines[1].discount_pct == pytest.approx(5.0)


def test_credit_note_is_recognised():
    inv = parse_invoice(_first_xml("03_credit_note_NCA77.zip"))
    assert inv.doc_type is DocumentType.CREDIT_NOTE and inv.billing_reference == "DAP1001"
    assert inv.lines[0].quantity == 2


def test_bare_xml_without_wrapper():
    inv = parse_invoice((INVOICES / "07_bare_xml_fuzzy_FYC310.xml").read_bytes())
    assert inv.number == "FYC310"


def test_xml_bomb_is_rejected():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">
    <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><Invoice>&lol2;</Invoice>"""
    with pytest.raises(Exception):     # defusedxml raises EntitiesForbidden
        parse_invoice(bomb)


def test_not_an_invoice():
    with pytest.raises(InvoiceParseError):
        parse_invoice(b"<Order><ID>1</ID></Order>")


def test_oversized_zip_member_rejected(tmp_path, monkeypatch):
    import invoice_bot.zip_reader as zr
    monkeypatch.setattr(zr, "MAX_MEMBER_BYTES", 100)
    path = tmp_path / "big.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a.xml", "x" * 500)
    with pytest.raises(UnsafeArchiveError):
        read_zip(path)


def test_path_traversal_rejected(tmp_path):
    path = tmp_path / "evil.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("../../evil.xml", "<x/>")
    with pytest.raises(UnsafeArchiveError):
        read_zip(path)
