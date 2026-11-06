# Case study: automating supplier-invoice entry for a motorcycle parts retailer

**Client profile:** a parts store and repair shop in Colombia. It has about 4,000 SKUs, more
than 30 regular suppliers, and uses Alegra as its ERP and point of sale.
**Role:** sole developer. I covered discovery, design and implementation, and I rolled the
tool out to the staff.
**Stack:** Python, DIAN UBL 2.1 XML, Alegra REST API, CSV-based human review.

## Problem

Since 2019, Colombian suppliers have had to send invoices electronically. Each one arrives
as a ZIP with a PDF and a signed XML. The data was machine-readable, but the store still
typed every invoice into Alegra by hand: about 35 a month, with roughly 600 product lines.

Typing was not the hard part. Finding the product was. Suppliers use their own codes, and
the store's catalog had grown organically, so the same part existed under barcodes,
supplier codes, or no code at all. Every line meant a search by name. Large invoices were
postponed, and some were never entered. The result was a catalog whose stock did not match
the shelf: some products were negative, others showed stock that wasn't there.

There were also silent errors:
- the same invoice entered twice (suppliers often resend it)
- credit notes typed as purchases
- discounts applied twice
- boxes of 12 entered as one unit

## Approach

1. **Read the source of truth, not the PDF.** The XML is signed and structured. The only
   trick is that the real invoice is embedded as CDATA text inside a DIAN `AttachedDocument`
   wrapper. The parser unwraps it with `defusedxml`, and the ZIP reader enforces size and
   compression limits.
2. **Validate before touching the ERP.**
   - Lines must add up to the subtotal, and subtotal plus tax must equal the payable amount.
   - The NIT must have a valid DIAN check digit.
   - The CUFE (DIAN's unique document hash) must not be registered already.
   - Credit and debit notes are separated from invoices.
3. **Match products in layers of decreasing trust:**
   1. a per-supplier equivalence table (NIT + code → item, plus a pack factor)
   2. the supplier code
   3. the EAN barcode
   4. fuzzy description similarity, tuned so that model numbers must agree

   A fuzzy match is only automatic when it is clearly better than the runner-up.
4. **Keep a human in the loop, but only where needed.** If any line is doubtful, the whole
   invoice goes to a review CSV. The CSV says why, suggests the most likely item, and
   proposes a retail price for new products (cost × margin × VAT, rounded). Each decision
   is fed back as an equivalence rule, so the same supplier code is automatic the next time.
5. **Be safe with the API.**
   - Dry-run is the default.
   - POST requests are never retried, so a timeout can't create a duplicate bill.
   - Constraints learned from real API rejections are checked up front, such as inactive
     items and due dates earlier than the issue date.

## What I learned from real data

- Suppliers disagree on the standard. Some send the price per `BaseQuantity`. Some add a
  discount that is only informative. One sends a 10% "discount" next to the 3% actually
  applied. Deriving the discount from the amounts (`1 − net / gross`) was the only robust
  rule.
- The hardest problem was the catalog, not the code. Two suppliers' product codes did not
  appear anywhere in the store's catalog. For one, the supplier's price list mapped its
  codes to barcodes. For the other, the store decided to adopt the supplier's codes as
  references and print its own labels. Matching stopped guessing in both cases.
- An automated intake exposes years of manual drift. The bot was a good moment to merge
  duplicated products, consolidate warehouses and fix products priced at almost zero.

## Result

Measured from 1 October to 6 November 2026 (63 purchase bills, 522 product lines).

| Metric | Before | After |
|---|---|---|
| Time per invoice | ~30 min | ~2 min |
| A batch of 10 invoices | ~5 hours | ~20 min |
| Monthly effort (~35 invoices) | ~17.5 h | ~1.2 h (~93 % less) |
| Lines matched automatically on the first pass | — | 76 % (397 / 522) |
| Duplicate bills prevented | occurred | 57 blocked by CUFE / number |
| Credit notes entered as purchases, boxes entered as units | occurred | blocked or converted by validation |

Every invoice the store receives now enters the system on the same day, and unclear lines
are routed to a person with the context needed to decide quickly.
