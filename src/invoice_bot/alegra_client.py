"""Alegra API client (https://developer.alegra.com) plus an offline dry-run twin.

Both expose the same small interface used by the pipeline, so the whole flow can be
demonstrated without an Alegra account.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Protocol

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.alegra.com/api/v1"
RETRYABLE = {429, 500, 502, 503, 504}


class AlegraError(RuntimeError):
    pass


class AlegraAPI(Protocol):
    dry_run: bool

    def provider_id(self, nit: str) -> str | None: ...
    def tax_id(self, percent: float) -> str | None: ...
    def registered_bills(self) -> tuple[set[str], set[str]]: ...
    def create_bill(self, payload: dict) -> dict: ...


class AlegraClient:
    """Thin HTTP client. GETs are retried with backoff; POSTs are **never** retried,
    because a timeout after Alegra stored the bill would create a duplicate."""

    dry_run = False

    def __init__(self, email: str, token: str, base_url: str = API_URL, timeout: int = 25,
                 session: requests.Session | None = None):
        if not email or not token:
            raise AlegraError("ALEGRA_EMAIL and ALEGRA_TOKEN must be set (see .env.example)")
        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Basic {auth}",
                                     "Accept": "application/json",
                                     "Content-Type": "application/json"})
        self._taxes: dict[float, str] | None = None
        self._providers: dict[str, str | None] = {}

    def _request(self, method: str, path: str, *, params=None, body=None, retries: int = 3):
        attempts = 1 if method == "POST" else retries
        for attempt in range(1, attempts + 1):
            try:
                resp = self.session.request(method, f"{self.base_url}/{path}", params=params,
                                            data=json.dumps(body) if body is not None else None,
                                            timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise AlegraError(f"Cannot reach Alegra: {exc}") from exc
            if resp.status_code == 401:
                raise AlegraError("Alegra rejected the credentials (401)")
            if resp.status_code in RETRYABLE and attempt < attempts:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise AlegraError(f"Alegra {resp.status_code}: {resp.text[:300]}")
            return resp.json() if resp.content else None
        raise AlegraError("unreachable")

    def _paginate(self, path: str, **params):
        start = 0
        while True:
            page = self._request("GET", path, params={**params, "start": start, "limit": 30})
            page = page.get("data", page) if isinstance(page, dict) else page
            if not page:
                return
            yield from page
            if len(page) < 30:
                return
            start += 30

    def provider_id(self, nit: str) -> str | None:
        if nit not in self._providers:
            found = self._request("GET", "contacts", params={"identification": nit, "type": "provider"})
            found = found.get("data", found) if isinstance(found, dict) else found
            self._providers[nit] = str(found[0]["id"]) if found else None
        return self._providers[nit]

    def tax_id(self, percent: float) -> str | None:
        if self._taxes is None:
            self._taxes = {float(t.get("percentage") or 0): str(t["id"])
                           for t in self._request("GET", "taxes") or [] if t.get("type") == "IVA"}
        return self._taxes.get(float(percent))

    def registered_bills(self) -> tuple[set[str], set[str]]:
        cufes, numbers = set(), set()
        for bill in self._paginate("bills", order_field="id"):
            stamp = bill.get("stamp") or {}
            if stamp.get("cufe"):
                cufes.add(stamp["cufe"])
            ident = ((bill.get("provider") or {}).get("identification") or "").split("-")[0]
            number = (bill.get("numberTemplate") or {}).get("fullNumber") or ""
            if number:
                numbers.add(f"{ident}:{number}")
        return cufes, numbers

    def create_bill(self, payload: dict) -> dict:
        return self._request("POST", "bills", body=payload)


class DryRunClient:
    """Offline stand-in: answers from local sample files and records what it *would* send."""

    dry_run = True

    def __init__(self, providers: dict[str, str], taxes: dict[float, str] | None = None,
                 registered_cufes: set[str] | None = None, outbox: Path | None = None):
        self.providers = providers
        self.taxes = taxes or {0.0: "1", 5.0: "2", 19.0: "3"}
        self.cufes = set(registered_cufes or ())
        self.numbers: set[str] = set()
        self.outbox = outbox
        self.sent: list[dict] = []
        self._next_id = 1000

    @classmethod
    def from_sample_data(cls, folder: Path, outbox: Path | None = None) -> "DryRunClient":
        data = json.loads((Path(folder) / "alegra_mock.json").read_text(encoding="utf-8"))
        return cls(providers=data["providers"],
                   taxes={float(k): v for k, v in data["taxes"].items()},
                   registered_cufes=set(data.get("registered_cufes", [])), outbox=outbox)

    def provider_id(self, nit: str) -> str | None:
        return self.providers.get(nit)

    def tax_id(self, percent: float) -> str | None:
        return self.taxes.get(float(percent))

    def registered_bills(self) -> tuple[set[str], set[str]]:
        return set(self.cufes), set(self.numbers)

    def create_bill(self, payload: dict) -> dict:
        self._next_id += 1
        self.sent.append(payload)
        if self.outbox:
            self.outbox.mkdir(parents=True, exist_ok=True)
            name = f"bill_{payload['numberTemplate']['number']}.json"
            (self.outbox / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
        log.info("[dry-run] would POST /bills for %s (%d items)", payload["numberTemplate"]["number"],
                 len(payload["purchases"].get("items", [])))
        return {"id": f"DRY-{self._next_id}", "dry_run": True}
