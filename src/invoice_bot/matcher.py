"""Layered product matching: invoice line -> catalog item.

Layers, in order of trust:

1. **Equivalence table** (``supplier NIT + supplier code -> item``): decisions a human
   already made once. Also carries a *pack factor* (supplier bills a box of 12,
   the catalog counts units).
2. **Supplier code** equals the catalog reference.
3. **Standard code** (EAN-13 barcode) equals the catalog reference or barcode.
4. **Fuzzy description**: token similarity. Only auto-accepted above a high
   threshold *and* with a clear gap to the runner-up; otherwise it is a suggestion
   that goes to the human-review queue with the reason.

Anything not matched goes to review. Inactive catalog items are never used.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .models import InvoiceLine, MatchResult

FUZZY_ACCEPT = 0.90      # auto-accept fuzzy matches only above this score...
FUZZY_MARGIN = 0.10      # ...and when the second best is at least this far behind
FUZZY_SUGGEST = 0.55     # below this, not even suggested

_STOPWORDS = {"DE", "DEL", "LA", "EL", "PARA", "CON", "Y", "X", "EN", "UND", "UNIDAD", "REF"}


def normalize_code(code: str) -> str:
    """'7701234-567.00 ' -> '7701234567' (catalog exports often append .00)."""
    code = re.sub(r"\.0+$", "", (code or "").strip())
    return re.sub(r"[\s\-_/.]", "", code).upper()


def _tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    # split letters from digits so "CB125F" and "CB 125 F" compare equal
    text = re.sub(r"(?<=[A-Z])(?=\d)|(?<=\d)(?=[A-Z])", " ", text)
    return {w for w in re.split(r"[^A-Z0-9]+", text) if w and w not in _STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Weighted token F1. Numeric tokens (models, sizes) weigh double, and a pair whose
    numbers do not overlap is penalised: 'FILTER CB125' must not match 'FILTER CB190'."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    weight = lambda w: 2.0 if any(c.isdigit() for c in w) else 1.0
    common = sum(weight(w) for w in ta & tb)
    if not common:
        return 0.0
    p, r = common / sum(map(weight, ta)), common / sum(map(weight, tb))
    score = 2 * p * r / (p + r)
    na = {w for w in ta if w.isdigit()}
    nb = {w for w in tb if w.isdigit()}
    if na and nb and not (na & nb):
        score -= 0.3
    return max(score, 0.0)


@dataclass
class CatalogItem:
    item_id: str
    name: str
    reference: str
    barcode: str = ""
    active: bool = True


@dataclass
class Equivalence:
    item_id: str
    pack_factor: float = 1.0
    note: str = ""


class Catalog:
    def __init__(self, items: list[CatalogItem]):
        self.items = [i for i in items if i.active]
        self.by_code: dict[str, CatalogItem] = {}
        for item in self.items:
            for code in (item.reference, item.barcode):
                if normalize_code(code):
                    self.by_code.setdefault(normalize_code(code), item)
        self.by_id = {i.item_id: i for i in self.items}

    @classmethod
    def from_csv(cls, path: Path) -> "Catalog":
        with open(path, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        return cls([CatalogItem(r["item_id"], r["name"], r.get("reference", ""), r.get("barcode", ""),
                                r.get("status", "active").strip().lower() != "inactive") for r in rows])


def load_equivalences(path: Path) -> dict[tuple[str, str], Equivalence]:
    """CSV columns: supplier_nit, supplier_code, item_id, pack_factor, note."""
    table: dict[tuple[str, str], Equivalence] = {}
    if not Path(path).exists():
        return table
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            factor = float(r.get("pack_factor") or 1) or 1.0
            table[(r["supplier_nit"].strip(), normalize_code(r["supplier_code"]))] = \
                Equivalence(r["item_id"].strip(), factor, r.get("note", ""))
    return table


class ProductMatcher:
    def __init__(self, catalog: Catalog, equivalences: dict[tuple[str, str], Equivalence]):
        self.catalog = catalog
        self.equivalences = equivalences

    def match(self, supplier_nit: str, line: InvoiceLine) -> MatchResult:
        code = normalize_code(line.supplier_code)

        # 1. human-approved equivalence (supplier-specific)
        eq = self.equivalences.get((supplier_nit, code))
        if eq:
            item = self.catalog.by_id.get(eq.item_id)
            if item is None:
                return MatchResult(line, None, layer="equivalence",
                                   reason=f"Equivalence points to item {eq.item_id}, which is inactive or missing")
            return MatchResult(line, item.item_id, item.name, "equivalence", 1.0, eq.pack_factor)

        # 2. supplier code == catalog reference
        item = self.catalog.by_code.get(code) if code else None
        if item:
            return MatchResult(line, item.item_id, item.name, "supplier_code", 1.0)

        # 3. standard code (EAN) == catalog reference/barcode
        std = normalize_code(line.standard_code)
        item = self.catalog.by_code.get(std) if std else None
        if item:
            return MatchResult(line, item.item_id, item.name, "standard_code", 0.98)

        # 4. fuzzy description
        scored = sorted(((similarity(line.description, i.name), i) for i in self.catalog.items),
                        key=lambda x: -x[0])[:2]
        if scored and scored[0][0] >= FUZZY_SUGGEST:
            best_score, best = scored[0]
            second = scored[1][0] if len(scored) > 1 else 0.0
            if best_score >= FUZZY_ACCEPT and best_score - second >= FUZZY_MARGIN:
                return MatchResult(line, best.item_id, best.name, "fuzzy", round(best_score, 3))
            why = (f"Similar name to item {best.item_id} '{best.name}' ({best_score:.0%})"
                   + (f", but item {scored[1][1].item_id} is also {second:.0%}" if second >= FUZZY_SUGGEST
                      and best_score - second < FUZZY_MARGIN else ", confirm before linking"))
            return MatchResult(line, best.item_id, best.name, "fuzzy", round(best_score, 3), reason=why)

        return MatchResult(line, None, layer="none",
                           reason=f"Unknown product: code '{line.supplier_code}' not in catalog or equivalences")
