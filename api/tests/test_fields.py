import json

import pytest

from app.fields import normalize_name, parse_classification


def test_normalize_name():
    assert normalize_name("Numéro Facture") == "numero_facture"
    assert normalize_name("Total ($)") == "total"
    assert normalize_name("!!!") == ""


def test_normalize_name_length_capped():
    assert len(normalize_name("a" * 100)) == 64


def test_parse_tolerates_code_fences():
    r = parse_classification('```json\n{"type":"Invoice","fields":{"Vendor Name":"ACME"}}\n```')
    assert r.document_type == "invoice" and r.fields == {"vendor_name": "ACME"}


def test_parse_tolerates_surrounding_prose():
    r = parse_classification('Sure! {"type":"memo","fields":{"a":"b"}} Hope that helps.')
    assert r.document_type == "memo" and r.fields == {"a": "b"}


def test_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_classification("not json")


def test_malformed_json_object_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_classification('{"type": "invoice", ')


def test_non_object_top_level_raises():
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_classification("[1, 2, 3]")


def test_values_coerced():
    r = parse_classification(
        '{"type":"invoice","fields":{"total":"$1,234.50","date":"03/01/2026",'
        '"items":["a","b"],"nested":{"x":1},"empty":""}}'
    )
    assert r.fields == {"total": 1234.5, "date": "2026-03-01", "items": "a, b"}


def test_caps():
    many = {f"f{i}": "v" * 900 for i in range(40)}
    r = parse_classification(json.dumps({"type": "x", "fields": many}))
    assert len(r.fields) == 25 and all(len(v) == 500 for v in r.fields.values())
    assert list(r.fields) == [f"f{i}" for i in range(25)]


def test_missing_type_becomes_other():
    assert parse_classification('{"fields":{}}').document_type == "other"


@pytest.mark.parametrize("type_value", ["null", "5", '"!!!"', '""'])
def test_unusable_type_becomes_other(type_value):
    assert parse_classification(f'{{"type":{type_value},"fields":{{}}}}').document_type == "other"


@pytest.mark.parametrize("fields_value", ["null", '"x"', "[1]", "5"])
def test_non_object_fields_is_empty(fields_value):
    assert parse_classification(f'{{"type":"a","fields":{fields_value}}}').fields == {}


def test_missing_fields_is_empty():
    assert parse_classification('{"type":"a"}').fields == {}


def test_bool_is_not_a_number():
    r = parse_classification('{"type":"a","fields":{"paid":true,"void":false}}')
    assert r.fields == {"paid": "true", "void": "false"}
    assert all(isinstance(v, str) for v in r.fields.values())


def test_native_numbers_kept():
    r = parse_classification('{"type":"a","fields":{"qty":3,"price":2.5}}')
    assert r.fields == {"qty": 3, "price": 2.5}
    assert isinstance(r.fields["qty"], int)


def test_none_dropped():
    assert parse_classification('{"type":"a","fields":{"x":null}}').fields == {}


def test_strings_stripped_and_blank_dropped():
    r = parse_classification('{"type":"a","fields":{"x":"  hi  ","y":"   "}}')
    assert r.fields == {"x": "hi"}


def test_list_of_scalars_joined():
    r = parse_classification('{"type":"a","fields":{"x":["a"," ","b",null,2,true],"y":[],"z":[""]}}')
    assert r.fields == {"x": "a, b, 2, true"}


def test_list_with_containers_dropped():
    r = parse_classification('{"type":"a","fields":{"x":[{"a":1}],"y":["a",[1]]}}')
    assert r.fields == {}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("9.733,33", 9733.33),
        ("1,234", 1234),
        ("1,234.50", 1234.5),
        ("1,234,567", 1234567),
        ("12,50", 12.5),
        ("€ 1.234,56", 1234.56),
        ("EUR 100", 100),
        ("100 USD", 100),
        ("-42.5", -42.5),
        ("1234", 1234),
    ],
)
def test_number_coercion(text, expected):
    value = parse_classification(json.dumps({"type": "a", "fields": {"n": text}})).fields["n"]
    assert value == expected
    assert isinstance(value, int) == isinstance(expected, int)


@pytest.mark.parametrize("text", ["INV-2024-001", "DE1234 5678", "1.2.3", "12abc", "1,2,3"])
def test_non_numbers_left_alone(text):
    r = parse_classification(json.dumps({"type": "a", "fields": {"n": text}}))
    assert r.fields == {"n": text}


@pytest.mark.parametrize(
    "text",
    ["2026-03-01", "01.03.2026", "03/01/2026", "2026/03/01"],
)
def test_date_coercion(text):
    r = parse_classification(json.dumps({"type": "a", "fields": {"d": text}}))
    assert r.fields == {"d": "2026-03-01"}


def test_unrecognised_date_unchanged():
    r = parse_classification('{"type":"a","fields":{"d":"March 1, 2026"}}')
    assert r.fields == {"d": "March 1, 2026"}


def test_key_collision_first_wins():
    r = parse_classification('{"type":"a","fields":{"Vendor Name":"first","vendor_name":"second"}}')
    assert r.fields == {"vendor_name": "first"}


def test_empty_normalizing_key_dropped():
    r = parse_classification('{"type":"a","fields":{"!!!":"x","ok":"y"}}')
    assert r.fields == {"ok": "y"}
