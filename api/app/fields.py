"""Parsing and normalization of the model's document-classification reply."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

MAX_FIELDS = 25
MAX_VALUE_LEN = 500
MAX_NAME_LEN = 64

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%Y/%m/%d")
_CURRENCY = re.compile(r"[$€£¥]|\b(?:USD|EUR|GBP|CHF|JPY|CAD|AUD)\b", re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"-?\d+(\.\d+)?")


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
    s = re.sub(r"\s+", "", _CURRENCY.sub("", text))
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
    return float(s) if "." in s else int(s)


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip() or None
    return None


def _clean_value(value: object) -> str | int | float | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
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
    except ValueError:
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
