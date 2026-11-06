from conftest import make_line
from invoice_bot.matcher import normalize_code, similarity


def test_normalize_code_strips_decimals_and_separators():
    assert normalize_code(" 7701234-567.00 ") == "7701234567"
    assert normalize_code("ab_12/3") == "AB123"


def test_equivalence_layer_with_pack_factor(matcher):
    m = matcher.match("900333444", make_line(code="LVC12", desc="ACEITE CAJA X12"))
    assert (m.item_id, m.layer, m.pack_factor, m.accepted) == ("6", "equivalence", 12.0, True)


def test_equivalence_is_supplier_specific(matcher):
    m = matcher.match("900999999", make_line(code="LVC12", desc="ZZZ"))
    assert m.layer != "equivalence"


def test_equivalence_to_inactive_item_goes_to_review(matcher):
    m = matcher.match("900333444", make_line(code="LVOLD"))
    assert not m.accepted and "inactive" in m.reason


def test_supplier_code_layer(matcher):
    m = matcher.match("1", make_line(code="cd-428"))
    assert (m.item_id, m.layer) == ("2", "supplier_code")


def test_inactive_items_are_never_matched(matcher):
    m = matcher.match("1", make_line(code="CD-428-OLD", desc="QQQ"))
    assert m.item_id != "3"


def test_standard_code_layer_uses_barcode(matcher):
    m = matcher.match("1", make_line(code="SUP-77", ean="7709990000011"))
    assert (m.item_id, m.layer) == ("1", "standard_code")


def test_fuzzy_high_confidence_is_accepted(matcher):
    m = matcher.match("1", make_line(code="NOPE", desc="CADENA 428H 120L REFORZADA"))
    assert (m.item_id, m.layer, m.accepted) == ("2", "fuzzy", True)


def test_fuzzy_ambiguous_goes_to_review(matcher):
    m = matcher.match("1", make_line(code="NOPE", desc="KIT ARRASTRE CB 125"))
    assert not m.accepted and m.item_id in {"4", "5"} and "also" in m.reason


def test_unknown_product_goes_to_review(matcher):
    m = matcher.match("1", make_line(code="NOPE", desc="CASCO ABATIBLE BLUETOOTH"))
    assert m.item_id is None and m.reason.startswith("Unknown product")


def test_numbers_must_agree_in_similarity():
    assert similarity("FILTRO ACEITE CB 125", "FILTRO ACEITE CB 190") < similarity(
        "FILTRO ACEITE CB 125", "FILTRO DE ACEITE CB125")
    assert similarity("FILTRO ACEITE CB125", "FILTRO ACEITE CB 125") == 1.0
