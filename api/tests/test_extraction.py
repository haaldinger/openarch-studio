"""Text extraction: Docling primary, Tika fallback."""

from __future__ import annotations

import httpx
import respx

from app.config import Settings
from app.extraction import PAGE_BREAK, build_extractor

DOCLING = "http://docling.test/v1/convert/file"
TIKA = "http://tika.test/tika"


def make_settings(extractor: str = "docling") -> Settings:
    return Settings(
        openarch_url="http://openarch.test",
        tika_url="http://tika.test",
        model_base_url="http://model.test/v1",
        docling_url="http://docling.test",
        extractor=extractor,
    )


def docling_ok(md: str, status: str = "success") -> httpx.Response:
    return httpx.Response(200, json={"document": {"md_content": md}, "status": status, "errors": []})


@respx.mock
async def test_docling_splits_pages_on_break():
    respx.post(DOCLING).mock(return_value=docling_ok(f"# Inv\nA{PAGE_BREAK}B"))
    result = await build_extractor(make_settings()).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "docling"
    assert result.pages == ["# Inv\nA", "B"]
    assert PAGE_BREAK not in result.markdown


@respx.mock
async def test_docling_request_asks_for_markdown_ocr_and_page_breaks():
    route = respx.post(DOCLING).mock(return_value=docling_ok("text"))
    await build_extractor(make_settings()).extract(b"x", "application/pdf", "a.pdf")
    body = route.calls[0].request.content
    assert b'name="files"; filename="a.pdf"' in body
    for name, value in {
        "to_formats": "md",
        "do_ocr": "true",
        "md_page_break_placeholder": PAGE_BREAK,
        "image_export_mode": "placeholder",
    }.items():
        assert f'name="{name}"'.encode() in body
        assert value.encode() in body
    assert b'name="document_timeout"' in body


@respx.mock
async def test_falls_back_to_tika_on_docling_5xx():
    respx.post(DOCLING).mock(return_value=httpx.Response(503))
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="tika text"))
    result = await build_extractor(make_settings()).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "tika"
    assert result.pages == ["tika text"]


@respx.mock
async def test_falls_back_to_tika_on_docling_timeout():
    respx.post(DOCLING).mock(side_effect=httpx.ReadTimeout("slow"))
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="tika text"))
    result = await build_extractor(make_settings()).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "tika"


@respx.mock
async def test_falls_back_to_tika_on_status_failure():
    respx.post(DOCLING).mock(return_value=docling_ok("ignored", status="failure"))
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="tika text"))
    result = await build_extractor(make_settings()).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "tika"


@respx.mock
async def test_partial_success_with_text_is_kept():
    respx.post(DOCLING).mock(return_value=docling_ok("some text", status="partial_success"))
    tika = respx.put(TIKA).mock(return_value=httpx.Response(200, text="tika text"))
    result = await build_extractor(make_settings()).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "docling"
    assert not tika.called


@respx.mock
async def test_empty_markdown_falls_back_to_tika():
    respx.post(DOCLING).mock(return_value=docling_ok("   "))
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="tika text"))
    result = await build_extractor(make_settings()).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "tika"


@respx.mock
async def test_tika_only_mode_never_calls_docling():
    docling = respx.post(DOCLING).mock(return_value=docling_ok("text"))
    respx.put(TIKA).mock(return_value=httpx.Response(200, text="tika text"))
    result = await build_extractor(make_settings("tika")).extract(b"x", "application/pdf", "a.pdf")
    assert result.engine == "tika"
    assert not docling.called
