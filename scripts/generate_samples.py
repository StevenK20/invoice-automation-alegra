"""Generate the FICTITIOUS sample invoices in sample_data/invoices/.

Every company, NIT, product, code and amount here is invented. NITs carry a valid
DIAN verification digit so the validator can be exercised, but they do not belong
to the businesses named here (all names end in "DEMO").

    python scripts/generate_samples.py
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from invoice_bot.validators import nit_check_digit  # noqa: E402

OUT = ROOT / "sample_data" / "invoices"

BUYER = ("900000017", "TALLER Y REPUESTOS EJEMPLO DEMO S.A.S.")
SUPPLIERS = {
    "A": ("900111222", "DISTRIBUIDORA ANDINA DE PARTES DEMO S.A.S."),
    "B": ("900333444", "LUBRICANTES DEL VALLE DEMO S.A.S."),
    "C": ("900555666", "IMPORTADORA MOTOPIEZAS DEMO LTDA"),
    "D": ("800777888", "FRENOS Y CLUTCH DEMO S.A."),
}


def cufe(seed: str) -> str:
    return hashlib.sha384(f"FICTITIOUS-{seed}".encode()).hexdigest()


def line_xml(tag: str, qty_tag: str, n: int, ln: dict) -> str:
    qty, price, disc_pct, vat = ln["qty"], ln["price"], ln.get("disc", 0.0), ln.get("vat", 19.0)
    base_qty = ln.get("base_qty", 1)
    gross = round(qty * price, 2)
    discount = round(gross * disc_pct / 100, 2)
    net = round(gross - discount, 2)
    tax = round(net * vat / 100, 2)
    allowance = ""
    if discount:
        allowance = f"""
      <cac:AllowanceCharge>
        <cbc:ID>1</cbc:ID><cbc:ChargeIndicator>false</cbc:ChargeIndicator>
        <cbc:AllowanceChargeReason>Descuento comercial</cbc:AllowanceChargeReason>
        <cbc:MultiplierFactorNumeric>{disc_pct}</cbc:MultiplierFactorNumeric>
        <cbc:Amount currencyID="COP">{discount:.2f}</cbc:Amount>
        <cbc:BaseAmount currencyID="COP">{gross:.2f}</cbc:BaseAmount>
      </cac:AllowanceCharge>"""
    std = (f"<cac:StandardItemIdentification><cbc:ID schemeID=\"010\">{ln['ean']}</cbc:ID>"
           f"</cac:StandardItemIdentification>") if ln.get("ean") else ""
    xml = f"""
    <cac:{tag}>
      <cbc:ID>{n}</cbc:ID>
      <cbc:{qty_tag} unitCode="94">{qty}</cbc:{qty_tag}>
      <cbc:LineExtensionAmount currencyID="COP">{net:.2f}</cbc:LineExtensionAmount>{allowance}
      <cac:TaxTotal>
        <cbc:TaxAmount currencyID="COP">{tax:.2f}</cbc:TaxAmount>
        <cac:TaxSubtotal>
          <cbc:TaxableAmount currencyID="COP">{net:.2f}</cbc:TaxableAmount>
          <cbc:TaxAmount currencyID="COP">{tax:.2f}</cbc:TaxAmount>
          <cac:TaxCategory><cbc:Percent>{vat:.2f}</cbc:Percent>
            <cac:TaxScheme><cbc:ID>01</cbc:ID><cbc:Name>IVA</cbc:Name></cac:TaxScheme>
          </cac:TaxCategory>
        </cac:TaxSubtotal>
      </cac:TaxTotal>
      <cac:Item>
        <cbc:Description>{escape(ln['desc'])}</cbc:Description>
        <cac:SellersItemIdentification><cbc:ID>{escape(ln['code'])}</cbc:ID></cac:SellersItemIdentification>
        {std}
      </cac:Item>
      <cac:Price>
        <cbc:PriceAmount currencyID="COP">{price * base_qty:.2f}</cbc:PriceAmount>
        <cbc:BaseQuantity unitCode="94">{base_qty}</cbc:BaseQuantity>
      </cac:Price>
    </cac:{tag}>"""
    return xml, net, tax


def document(kind: str, number: str, supplier: str, issue: str, due: str, lines: list[dict],
             *, override_subtotal: float | None = None, billing_ref: str = "", seed: str = "") -> str:
    root, tag, qty_tag, type_el = {
        "invoice": ("Invoice", "InvoiceLine", "InvoicedQuantity", "<cbc:InvoiceTypeCode>01</cbc:InvoiceTypeCode>"),
        "credit": ("CreditNote", "CreditNoteLine", "CreditedQuantity",
                   "<cbc:CreditNoteTypeCode>91</cbc:CreditNoteTypeCode>"),
    }[kind]
    nit, name = SUPPLIERS[supplier]
    body, subtotal, taxes = "", 0.0, 0.0
    for i, ln in enumerate(lines, 1):
        xml, net, tax = line_xml(tag, qty_tag, i, ln)
        body += xml
        subtotal += net
        taxes += tax
    subtotal, taxes = round(subtotal, 2), round(taxes, 2)
    declared = override_subtotal if override_subtotal is not None else subtotal
    ref = (f"<cac:BillingReference><cac:InvoiceDocumentReference><cbc:ID>{billing_ref}</cbc:ID>"
           f"</cac:InvoiceDocumentReference></cac:BillingReference>") if billing_ref else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<{root} xmlns="urn:oasis:names:specification:ubl:schema:xsd:{root}-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>UBL 2.1</cbc:UBLVersionID>
  <cbc:ProfileExecutionID>2</cbc:ProfileExecutionID>
  <cbc:ID>{number}</cbc:ID>
  <cbc:UUID schemeName="CUFE-SHA384">{cufe(seed or number)}</cbc:UUID>
  <cbc:IssueDate>{issue}</cbc:IssueDate>
  <cbc:DueDate>{due}</cbc:DueDate>
  {type_el}
  <cbc:Note>FICTITIOUS DOCUMENT FOR DEMONSTRATION PURPOSES ONLY</cbc:Note>
  <cbc:DocumentCurrencyCode>COP</cbc:DocumentCurrencyCode>
  {ref}
  <cac:AccountingSupplierParty>
    <cbc:AdditionalAccountID>1</cbc:AdditionalAccountID>
    <cac:Party>
      <cac:PartyTaxScheme>
        <cbc:RegistrationName>{name}</cbc:RegistrationName>
        <cbc:CompanyID schemeAgencyID="195" schemeID="{nit_check_digit(nit)}" schemeName="31">{nit}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>01</cbc:ID><cbc:Name>IVA</cbc:Name></cac:TaxScheme>
      </cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyTaxScheme>
        <cbc:RegistrationName>{BUYER[1]}</cbc:RegistrationName>
        <cbc:CompanyID schemeID="{nit_check_digit(BUYER[0])}" schemeName="31">{BUYER[0]}</cbc:CompanyID>
      </cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="COP">{taxes:.2f}</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="COP">{declared:.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="COP">{declared:.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="COP">{declared + taxes:.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="COP">{declared + taxes:.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>{body}
</{root}>
"""


def attached(inner: str, number: str) -> str:
    """Wrap the document the way DIAN-authorised providers deliver it."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<AttachedDocument xmlns="urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>UBL 2.1</cbc:UBLVersionID>
  <cbc:ID>AD-{number}</cbc:ID>
  <cac:Attachment>
    <cac:ExternalReference>
      <cbc:MimeCode>text/xml</cbc:MimeCode>
      <cbc:EncodingCode>UTF-8</cbc:EncodingCode>
      <cbc:Description><![CDATA[{inner}]]></cbc:Description>
    </cac:ExternalReference>
  </cac:Attachment>
</AttachedDocument>
"""


def write_zip(name: str, number: str, xml: str) -> None:
    with zipfile.ZipFile(OUT / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"ad{number}.xml", attached(xml, number))
        zf.writestr(f"{number}.pdf", b"%PDF-1.4\n% placeholder: fictitious invoice\n")


NORMAL = [
    {"code": "DA-1001", "desc": "PASTILLAS FRENO DELANTERAS MOTO 150CC", "qty": 10, "price": 14500, "ean": "7709990000011"},
    {"code": "DA-2040", "desc": "CADENA 428H X 120L REFORZADA", "qty": 6, "price": 38900},
    {"code": "DA-3310", "desc": "BUJIA ESTANDAR C7HSA", "qty": 24, "price": 6200, "ean": "7709990000035"},
    {"code": "XZ-0001", "desc": "FILTRO ACEITE MOTOR 125-200CC", "qty": 12, "price": 7800, "ean": "7709990000042"},
]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # 1. normal invoice: codes and barcodes found directly in the catalog
    write_zip("01_normal_DAP1001", "DAP1001",
              document("invoice", "DAP1001", "A", "2026-03-02", "2026-04-01", NORMAL))

    # 2. discounts + price per BaseQuantity + box of 12 resolved by the equivalence table
    write_zip("02_discounts_LUB2210", "LUB2210", document("invoice", "LUB2210", "B", "2026-03-05", "2026-04-04", [
        {"code": "LV-20W50-C12", "desc": "ACEITE 4T 20W50 MINERAL 1L CAJA X12", "qty": 3, "price": 228000, "disc": 8},
        {"code": "LV-CAD-400", "desc": "LUBRICANTE CADENA SPRAY 400ML", "qty": 12, "price": 15400, "disc": 5,
         "base_qty": 12},
        {"code": "LV-REF-1L", "desc": "REFRIGERANTE LISTO PARA USAR 1L", "qty": 6, "price": 9900, "disc": 0},
    ]))

    # 3. credit note (supplier returned part of DAP1001): must not become a purchase bill
    write_zip("03_credit_note_NCA77", "NCA77", document("credit", "NCA77", "A", "2026-03-09", "2026-03-09", [
        {"code": "DA-2040", "desc": "CADENA 428H X 120L REFORZADA", "qty": 2, "price": 38900},
    ], billing_ref="DAP1001"))

    # 4. duplicate: the supplier emailed DAP1001 again with another file name (same CUFE)
    write_zip("04_duplicate_resend_DAP1001", "DAP1001",
              document("invoice", "DAP1001", "A", "2026-03-02", "2026-04-01", NORMAL))

    # 5. unknown product + ambiguous description -> human review queue
    write_zip("05_unknown_product_IMP5501", "IMP5501", document("invoice", "IMP5501", "C", "2026-03-11", "2026-04-10", [
        {"code": "IM-77801", "desc": "DIRECCIONAL LED UNIVERSAL AMBAR PAR", "qty": 4, "price": 21000},
        {"code": "IM-90001", "desc": "KIT ARRASTRE 428 CB 125", "qty": 2, "price": 96000},
        {"code": "IM-55511", "desc": "RETROVISOR PLEGABLE NEGRO PAR", "qty": 5, "price": 18500},
    ]))

    # 6. totals do not add up: header subtotal disagrees with the lines
    write_zip("06_totals_mismatch_LUB2231", "LUB2231", document("invoice", "LUB2231", "B", "2026-03-15", "2026-04-14", [
        {"code": "LV-CAD-400", "desc": "LUBRICANTE CADENA SPRAY 400ML", "qty": 6, "price": 15400},
        {"code": "LV-REF-1L", "desc": "REFRIGERANTE LISTO PARA USAR 1L", "qty": 12, "price": 9900},
    ], override_subtotal=245000.00))

    # 7. bare XML (no ZIP, no AttachedDocument) whose codes are unknown but whose
    #    descriptions match the catalog with high confidence (fuzzy layer)
    (OUT / "07_bare_xml_fuzzy_FYC310.xml").write_text(document("invoice", "FYC310", "D", "2026-03-18", "2026-03-18", [
        {"code": "FC-9001", "desc": "DISCO CLUTCH 125CC JUEGO 5 PIEZAS", "qty": 4, "price": 32000},
        {"code": "FC-9002", "desc": "GUAYA ACELERADOR 125CC UNIVERSAL", "qty": 10, "price": 8500},
    ]), encoding="utf-8")

    # 8. corrupt attachment: not a real ZIP
    (OUT / "08_corrupt_file.zip").write_bytes(b"this is not a zip archive")

    print(f"Fictitious samples written to {OUT.relative_to(ROOT)}:")
    for p in sorted(OUT.iterdir()):
        print("  ", p.name)


if __name__ == "__main__":
    main()
