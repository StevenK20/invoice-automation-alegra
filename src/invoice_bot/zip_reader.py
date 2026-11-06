"""Safe extraction of DIAN electronic-invoice XML from the ZIP files suppliers email.

Colombian e-invoices arrive as a ZIP containing a PDF plus an ``AttachedDocument``
XML. The real invoice (``<Invoice>``, ``<CreditNote>`` or ``<DebitNote>``) is
embedded as text (usually CDATA) inside ``cac:Attachment/cac:ExternalReference/
cbc:Description`` of that wrapper. This module handles both the wrapper and a bare
invoice XML, and protects against zip bombs and oversized members.
"""
from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MAX_MEMBER_BYTES = 5 * 1024 * 1024        # 5 MB per XML is far above any real invoice
MAX_TOTAL_BYTES = 20 * 1024 * 1024        # total uncompressed size we accept per ZIP
MAX_COMPRESSION_RATIO = 100               # zip-bomb guard
MAX_MEMBERS = 50


class UnsafeArchiveError(ValueError):
    """The ZIP looks malicious or is too large to process safely."""


@dataclass
class XmlDocument:
    source: str          # "file.zip/member.xml" or "file.xml"
    content: bytes


def _check_member(info: zipfile.ZipInfo) -> None:
    if info.file_size > MAX_MEMBER_BYTES:
        raise UnsafeArchiveError(f"{info.filename}: {info.file_size} bytes exceeds the limit")
    if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise UnsafeArchiveError(f"{info.filename}: suspicious compression ratio")
    name = info.filename.replace("\\", "/")
    if name.startswith("/") or ".." in name.split("/"):
        raise UnsafeArchiveError(f"{info.filename}: path traversal attempt")


def read_zip(path: Path) -> list[XmlDocument]:
    """Return every XML member of ``path`` after size/ratio checks (never extracts to disk)."""
    docs: list[XmlDocument] = []
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise UnsafeArchiveError(f"{path.name}: too many members ({len(infos)})")
        total = 0
        for info in infos:
            if info.is_dir() or not info.filename.lower().endswith(".xml"):
                continue
            _check_member(info)
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise UnsafeArchiveError(f"{path.name}: total uncompressed size too large")
            with zf.open(info) as fh:
                data = fh.read(MAX_MEMBER_BYTES + 1)
            if len(data) > MAX_MEMBER_BYTES:   # header lied about the size
                raise UnsafeArchiveError(f"{info.filename}: real size exceeds the limit")
            docs.append(XmlDocument(f"{path.name}/{info.filename}", data))
    return docs


def iter_documents(folder: Path):
    """Yield (source, XmlDocument | Exception) for every .zip / .xml in ``folder``."""
    for path in sorted(Path(folder).iterdir()):
        suffix = path.suffix.lower()
        try:
            if suffix == ".zip":
                docs = read_zip(path)
                if not docs:
                    raise ValueError("ZIP without XML")
                for doc in docs:
                    yield doc.source, doc
            elif suffix == ".xml":
                if path.stat().st_size > MAX_MEMBER_BYTES:
                    raise UnsafeArchiveError(f"{path.name}: file too large")
                yield path.name, XmlDocument(path.name, path.read_bytes())
        except (zipfile.BadZipFile, UnsafeArchiveError, ValueError) as exc:
            log.warning("Cannot read %s: %s", path.name, exc)
            yield path.name, exc
