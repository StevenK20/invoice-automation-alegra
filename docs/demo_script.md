# Demo video script (≈ 3 minutes)

**Setup before recording:** terminal at the repo root with a large font (zoom 130%),
VS Code open with `sample_data/invoices/`, and `output/` deleted (`make clean`). The
recording runs in dry-run mode only, and no real data appears on screen.

---

### 0:00 – 0:25 · The problem (face cam or slide)

> "A parts store receives about 35 supplier invoices a month, around 600 product lines.
> Every line was typed into the ERP by hand. Finding each product took most of the time,
> because suppliers use their own codes. And mistakes were silent: the same invoice entered
> twice, credit notes entered as purchases, a box of 12 entered as one unit.
> I automated that process. Let me show you, in safe demo mode, with fictitious data."

### 0:25 – 0:45 · What goes in

Show `sample_data/invoices/` in the file explorer.

> "These are eight fictitious invoices, built like real DIAN e-invoices: a ZIP with an
> XML whose real invoice is embedded inside a wrapper. Each one is a case the bot must
> handle: a normal invoice, discounts, a credit note, a duplicate, an unknown product,
> totals that don't add up, a bare XML and a corrupt file."

### 0:45 – 1:30 · Run it

Type `python run_demo.py` in the terminal.

> "One command. It runs in dry-run, so nothing is sent to Alegra."

Point at the lines as they appear:
- **PROCESSED:** "These three are ready. Codes and barcodes matched, and the box of 12
  oil was converted into 36 units at the unit price."
- **SKIPPED:** "That's a credit note. It must not become a purchase."
- **DUPLICATE:** "The supplier sent the same invoice twice. Same CUFE, so it's blocked."
- **NEEDS_REVIEW:** "Here the bot is not sure, and it tells you why. One product is
  unknown, one description matches two items equally, and in the other invoice the totals
  don't add up."
- **Summary:** "Eleven of fourteen lines needed no human at all."

### 1:30 – 2:10 · The human in the loop

Open `output/review_queue.csv` in VS Code or Excel.

> "Everything doubtful lands here: the reason, the suggested item, and for new
> products a suggested retail price. A person fills in this column with the right item..."

Type `302` in `decision_item_id` for line IM-90001, save, then run
`python -m invoice_bot learn`.

> "...and the bot learns it as a rule for that supplier. Next month this code goes
> through automatically. The share of automatic lines keeps growing."

### 2:10 – 2:35 · What would be sent

Open `output/dry_run_payloads/bill_LUB2210.json`.

> "This is the exact payload that goes to Alegra's API: provider, quantities, unit
> prices, discount, VAT. With `--send` and credentials in a `.env` file it creates the bill.
> POST requests are never retried, so a timeout can't create a duplicate."

### 2:35 – 3:00 · Quality and close

Run `python -m pytest -q` and let `44 passed` show.

> "Forty-four automated tests cover validations, product matching, parsing and security:
> XML bombs, oversized ZIPs, path traversal. The code is modular, so the Alegra client can
> be swapped for another ERP. In production this tool processes every supplier invoice the
> store receives. Thanks for watching. The repository link is in the description."

---

**Recording tips**
- Record at 1920×1080. Hide the bookmarks bar and notifications.
- If a take runs long, cut the `learn` step. The review CSV alone tells the story.
- Add captions: many recruiters watch without sound.
