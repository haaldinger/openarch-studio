from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.acl import PERMISSIONS, Principal, RuleIn, parse_access_field, to_sys_acl, validate_rules

NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)


def _rule(permission: str = "Read", begin=None, end=None, kind="group", pid="g1") -> RuleIn:
    return RuleIn(principal=Principal(kind=kind, id=pid), permission=permission, begin=begin, end=end)


def _status(fn) -> int:
    with pytest.raises(HTTPException) as exc:
        fn()
    assert isinstance(exc.value.detail, str) and exc.value.detail
    return exc.value.status_code


def test_permissions_whitelist_is_exact():
    assert PERMISSIONS == ("Read", "ReadWrite", "Write", "ManageSecurity", "Everything")


def test_unknown_permission_is_rejected():
    assert _status(lambda: validate_rules([_rule("Bogus")], NOW)) == 400


def test_begin_not_before_end_is_rejected():
    later = NOW + timedelta(days=2)
    assert _status(lambda: validate_rules([_rule(begin=later, end=later)], NOW)) == 400
    assert _status(lambda: validate_rules([_rule(begin=later, end=NOW + timedelta(days=1))], NOW)) == 400


def test_end_in_the_past_is_rejected():
    assert _status(lambda: validate_rules([_rule(end=NOW)], NOW)) == 400
    assert _status(lambda: validate_rules([_rule(end=NOW - timedelta(hours=1))], NOW)) == 400


def test_more_than_fifty_rules_is_rejected():
    rules = [_rule(pid=f"g{i}") for i in range(51)]
    assert _status(lambda: validate_rules(rules, NOW)) == 400


def test_fifty_rules_and_valid_window_pass():
    rules = [_rule(pid=f"g{i}") for i in range(50)]
    validate_rules(rules, NOW)
    validate_rules([_rule(begin=NOW, end=NOW + timedelta(days=1))], NOW)


def test_naive_datetime_is_treated_as_utc():
    naive_end = datetime(2026, 10, 29, 12, 0, 0)
    validate_rules([_rule(end=naive_end)], NOW)
    out = to_sys_acl([_rule(end=naive_end)])
    assert out[0]["end"] == "2026-10-29T12:00:00.000Z"


def test_aware_datetime_is_converted_to_utc():
    tz_end = datetime(2026, 10, 29, 8, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
    out = to_sys_acl([_rule(end=tz_end)])
    assert out[0]["end"] == "2026-10-29T12:00:00.000Z"


def test_to_sys_acl_group_rule_with_end():
    end = datetime(2026, 10, 28, 16, 6, 7, tzinfo=timezone.utc)
    assert to_sys_acl([_rule("Read", end=end, kind="group", pid="g1")]) == [
        {"granted": True, "permission": "Read", "group": {"id": "g1"}, "end": "2026-10-28T16:06:07.000Z"}
    ]


def test_to_sys_acl_user_rule_with_begin_and_end():
    begin = datetime(2026, 10, 28, 13, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 29, 13, 0, 0, tzinfo=timezone.utc)
    assert to_sys_acl([_rule("ReadWrite", begin=begin, end=end, kind="user", pid="u1")]) == [
        {
            "granted": True,
            "permission": "ReadWrite",
            "user": {"id": "u1"},
            "begin": "2026-10-28T13:00:00.000Z",
            "end": "2026-10-29T13:00:00.000Z",
        }
    ]


def test_to_sys_acl_omits_absent_window_keys():
    out = to_sys_acl([_rule("Read", kind="user", pid="u1")])
    assert out == [{"granted": True, "permission": "Read", "user": {"id": "u1"}}]


def test_every_mapped_rule_is_granted():
    rules = [_rule("Read", pid="g1"), _rule("Write", kind="user", pid="u1")]
    assert all(entry["granted"] is True for entry in to_sys_acl(rules))


def test_parse_access_field_none_and_empty_return_none():
    assert parse_access_field(None) is None
    assert parse_access_field("") is None


def test_parse_access_field_bad_json_is_400():
    assert _status(lambda: parse_access_field("not json")) == 400


def test_parse_access_field_valid_json_returns_rules():
    raw = '[{"principal": {"kind": "group", "id": "finance"}, "permission": "Read"}]'
    rules = parse_access_field(raw)
    assert isinstance(rules, list) and len(rules) == 1
    assert rules[0].principal == Principal(kind="group", id="finance")
    assert rules[0].permission == "Read"
