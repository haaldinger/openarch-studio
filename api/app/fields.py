"""Parsing and normalization of the model's document-classification reply."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

import httpx

from .config import Settings
from .openarch import OpenArchClient

MAX_FIELDS = 25
MAX_VALUE_LEN = 500
MAX_NAME_LEN = 64

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%Y/%m/%d")
_CURRENCY = re.compile(r"[$€£¥]|\b(?:USD|EUR|GBP|CHF|JPY|CAD|AUD)\b", re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"-?\d+(\.\d+)?")
_SPACE_GROUPED = re.compile(r"-?\d{1,3}(?: \d{3})+(?:[.,][^ ]*)?")
MAX_SIGNIFICANT_DIGITS = 15


@dataclass
class ClassifiedFields:
    document_type: str
    fields: dict[str, str | int | float]


def normalize_name(raw: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")[:MAX_NAME_LEN].strip("_")


def _as_date(text: str) -> str | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _as_number(text: str) -> int | float | None:
    s = re.sub(r"\s+", " ", _CURRENCY.sub("", text)).strip()
    if " " in s:
        if not _SPACE_GROUPED.fullmatch(s):
            return None
        s = s.replace(" ", "")
    if "." in s and "," in s:
        decimal = "." if s.rfind(".") > s.rfind(",") else ","
    elif "," in s:
        decimal = "," if s.count(",") == 1 and len(s) - s.rfind(",") - 1 == 2 else None
    else:
        decimal = None
    thousands = "," if decimal != "," and "," in s else "." if decimal == "," and "." in s else None
    whole, _, frac = s.partition(decimal) if decimal else (s, "", "")
    if thousands:
        if not re.fullmatch(rf"-?\d{{1,3}}(?:{re.escape(thousands)}\d{{3}})+", whole):
            return None
        whole = whole.replace(thousands, "")
    s = f"{whole}.{frac}" if decimal else whole
    if not _PLAIN_NUMBER.fullmatch(s):
        return None
    integer_part = s.lstrip("-").partition(".")[0]
    if len(integer_part) > MAX_SIGNIFICANT_DIGITS or re.match(r"0\d", integer_part):
        return None
    value = float(s) if "." in s else int(s)
    return value if _is_finite(value) else None


def _is_finite(value: int | float) -> bool:
    return isinstance(value, int) or math.isfinite(value)


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value) if _is_finite(value) else None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _clean_value(value: object) -> str | int | float | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value if _is_finite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        as_date = _as_date(text)
        if as_date:
            return as_date
        as_number = _as_number(text)
        return as_number if as_number is not None else text[:MAX_VALUE_LEN]
    if isinstance(value, list):
        if any(isinstance(item, (dict, list)) for item in value):
            return None
        joined = ", ".join(t for t in map(_scalar_text, value) if t)
        return joined[:MAX_VALUE_LEN] or None
    return None


def parse_classification(raw: str) -> ClassifiedFields:
    """Parse the model's JSON reply defensively (tolerates code fences / prose)."""
    text = re.sub(r"```(?:json)?", "", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    try:
        if start == -1 or end < start:
            raise ValueError
        data = json.loads(text[start : end + 1])
    except (ValueError, RecursionError):
        raise ValueError("model returned invalid JSON") from None
    if not isinstance(data, dict):
        raise ValueError("model returned invalid JSON")

    raw_type = data.get("type")
    document_type = (normalize_name(raw_type) if isinstance(raw_type, str) else "") or "other"

    fields: dict[str, str | int | float] = {}
    raw_fields = data.get("fields")
    for key, value in (raw_fields.items() if isinstance(raw_fields, dict) else ()):
        name = normalize_name(key)
        if not name or name in fields:
            continue
        cleaned = _clean_value(value)
        if cleaned is None:
            continue
        fields[name] = cleaned
        if len(fields) == MAX_FIELDS:
            break
    return ClassifiedFields(document_type, fields)


_VOCABULARY_QUERY = (
    "SELECT * FROM SysContent WHERE sys_mixinTypes = 'CinContext' ORDER BY sys_modified DESC"
)
_VOCABULARY_LIMIT = 200
_PROMPT_CHARS = 6000
_MAX_TYPES = 50
_TYPE_KEY = "document_type"
_SYSTEM_PROMPT = (
    "You classify a document and extract its key fields.\n"
    "- Choose one of the known document types when it fits; otherwise invent a short new type name.\n"
    "- Reuse an existing field name when its meaning matches; otherwise use a short snake_case name.\n"
    "- Only include values that appear in the document text. Never guess.\n"
    "- Document type and field names must be English snake_case, regardless of the document's language; values stay as written.\n"
    'Reply with exactly this JSON: {"type": "...", "fields": {"name": "value"}}'
)


def _is_clean_name(value: object) -> bool:
    return isinstance(value, str) and bool(value) and normalize_name(value) == value


class FieldsService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def vocabulary(self, client: OpenArchClient) -> dict[str, list[str]]:
        """Known document types and their field names (never values), as visible to the caller."""
        result = await client.query({"query": _VOCABULARY_QUERY, "limit": _VOCABULARY_LIMIT})
        names: dict[str, set[str]] = {}
        for doc in result.get("documents", []):
            doc_type = (doc.get("cinctx_contextProperties") or {}).get(_TYPE_KEY)
            if not _is_clean_name(doc_type):
                continue
            if doc_type not in names and len(names) >= _MAX_TYPES:
                continue
            fields = {
                n
                for n in doc.get("cinctx_contextPropertyNames") or []
                if n != _TYPE_KEY and _is_clean_name(n)
            }
            names.setdefault(doc_type, set()).update(fields)
        return {t: sorted(n)[:MAX_FIELDS] for t, n in names.items()}

    async def classify(self, markdown: str, vocabulary: dict[str, list[str]]) -> ClassifiedFields:
        known = "\n".join(f"{t}: {', '.join(n)}" for t, n in vocabulary.items()) or "none yet"
        user = f"Known document types and fields:\n{known}\n\nDocument:\n{markdown[:_PROMPT_CHARS]}"
        payload = {
            "model": self._settings.extract_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        url = f"{self._settings.model_base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return parse_classification(content)

    async def store(self, client: OpenArchClient, doc_id: str, result: ClassifiedFields) -> None:
        await client.ensure_mixin(doc_id, "CinContext")
        properties = {_TYPE_KEY: result.document_type, **result.fields}
        await client.update_document(
            doc_id,
            {
                "cinctx_contextProperties": properties,
                "cinctx_contextPropertyNames": sorted(properties),
            },
        )
