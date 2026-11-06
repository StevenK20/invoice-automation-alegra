from conftest import SAMPLE
from invoice_bot.alegra_client import DryRunClient
from invoice_bot.matcher import Catalog, ProductMatcher, load_equivalences
from invoice_bot.models import Status
from invoice_bot.pipeline import InvoicePipeline
from invoice_bot.reporting import write_reports


def _run(tmp_path):
    client = DryRunClient.from_sample_data(SAMPLE, outbox=tmp_path / "payloads")
    matcher = ProductMatcher(Catalog.from_csv(SAMPLE / "catalog.csv"),
                             load_equivalences(SAMPLE / "equivalences.csv"))
    return client, InvoicePipeline(client, matcher).run(SAMPLE / "invoices")


def test_demo_outcomes(tmp_path):
    _, results = _run(tmp_path)
    by_file = {r.source.split("/")[0]: r.status for r in results}
    assert by_file == {
        "01_normal_DAP1001.zip": Status.PROCESSED,
        "02_discounts_LUB2210.zip": Status.PROCESSED,
        "03_credit_note_NCA77.zip": Status.SKIPPED,
        "04_duplicate_resend_DAP1001.zip": Status.DUPLICATE,
        "05_unknown_product_IMP5501.zip": Status.NEEDS_REVIEW,
        "06_totals_mismatch_LUB2231.zip": Status.NEEDS_REVIEW,
        "07_bare_xml_fuzzy_FYC310.xml": Status.PROCESSED,
        "08_corrupt_file.zip": Status.ERROR,
    }


def test_dry_run_sends_nothing_but_records_payloads(tmp_path):
    client, _ = _run(tmp_path)
    assert len(client.sent) == 3
    assert len(list((tmp_path / "payloads").glob("*.json"))) == 3


def test_pack_factor_converts_boxes_to_units(tmp_path):
    client, _ = _run(tmp_path)
    bill = next(b for b in client.sent if b["numberTemplate"]["number"] == "LUB2210")
    oil = next(i for i in bill["purchases"]["items"] if i["id"] == 201)
    assert oil["quantity"] == 36 and oil["price"] == 19000      # 3 boxes x 12 at 228,000/box


def test_review_queue_has_reasons(tmp_path):
    _, results = _run(tmp_path)
    paths = write_reports(results, tmp_path)
    text = paths["review"].read_text(encoding="utf-8")
    assert "IM-77801" in text and "Unknown product" in text
    assert "(whole document)" in text and "subtotal" in text
