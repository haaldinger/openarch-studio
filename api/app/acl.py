"""ACL rule model, validation, and mapping to OpenArch sys_acl entries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, TypeAdapter, ValidationError

PERMISSIONS = ("Read", "ReadWrite", "Write", "ManageSecurity", "Everything")
MAX_RULES = 50


class Principal(BaseModel):
    kind: Literal["user", "group"]
    id: str


class RuleIn(BaseModel):
    principal: Principal
    permission: str
    begin: datetime | None = None
    end: datetime | None = None


def _utc(value: datetime) -> datetime:
    # Naive datetimes are interpreted as UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sent(value: datetime) -> datetime:
    # Mirrors the whole-second precision of the sent `.000Z` timestamps.
    return _utc(value).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return _sent(value).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def validate_rules(rules: list[RuleIn], now: datetime) -> None:
    if len(rules) > MAX_RULES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_RULES} rules per folder")
    current = _sent(now)
    for rule in rules:
        if rule.permission not in PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"Unknown permission: {rule.permission}")
        if rule.begin and rule.end and _sent(rule.begin) >= _sent(rule.end):
            raise HTTPException(status_code=400, detail="Access must begin before it ends")
        if rule.end and _sent(rule.end) <= current:
            raise HTTPException(status_code=400, detail="Access end must be in the future")


def to_sys_acl(rules: list[RuleIn]) -> list[dict]:
    entries: list[dict] = []
    for rule in rules:
        principal_key = "user" if rule.principal.kind == "user" else "group"
        entry: dict = {
            "granted": True,
            "permission": rule.permission,
            principal_key: {"id": rule.principal.id},
        }
        if rule.begin is not None:
            entry["begin"] = _iso(rule.begin)
        if rule.end is not None:
            entry["end"] = _iso(rule.end)
        entries.append(entry)
    return entries


_RULES_ADAPTER = TypeAdapter(list[RuleIn])


def parse_access_field(raw: str | None) -> list[RuleIn] | None:
    if raw is None or not raw.strip():
        return None
    try:
        return _RULES_ADAPTER.validate_json(raw)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Access rules are not valid") from None
