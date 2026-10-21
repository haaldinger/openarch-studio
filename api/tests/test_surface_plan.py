"""The model picks a surface, but only from the set Studio knows how to build."""

from __future__ import annotations

import httpx
import respx

from app.agent import AgentService
from app.config import Settings
from app.enrichment import EnrichmentService

CHAT = "http://model.test/v1/chat/completions"


def make_agent() -> AgentService:
    settings = Settings(
        openarch_url="http://openarch.test",
        model_base_url="http://model.test/v1",
        chat_model="llama3.2:3b",
    )
    return AgentService(settings, EnrichmentService(settings))


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_no_documents_skips_the_model_entirely() -> None:
    assert await make_agent().plan_surface("q", "a", 0) == ("sources", [])


@respx.mock
async def test_followups_are_returned_with_their_questions() -> None:
    respx.post(CHAT).mock(
        return_value=_reply('{"surface":"followups","questions":["What is the total?","Who signed?"]}')
    )
    surface, questions = await make_agent().plan_surface("q", "a", 2)
    assert surface == "followups"
    assert questions == ["What is the total?", "Who signed?"]


@respx.mock
async def test_unknown_surface_falls_back_to_sources() -> None:
    respx.post(CHAT).mock(return_value=_reply('{"surface":"render_iframe"}'))
    assert await make_agent().plan_surface("q", "a", 2) == ("sources", [])


@respx.mock
async def test_unparseable_reply_falls_back_to_sources() -> None:
    respx.post(CHAT).mock(return_value=_reply("sure! here you go, friend"))
    assert await make_agent().plan_surface("q", "a", 2) == ("sources", [])


@respx.mock
async def test_followups_without_questions_falls_back() -> None:
    respx.post(CHAT).mock(return_value=_reply('{"surface":"followups","questions":[]}'))
    assert await make_agent().plan_surface("q", "a", 2) == ("sources", [])


@respx.mock
async def test_model_outage_does_not_break_the_answer() -> None:
    respx.post(CHAT).mock(side_effect=httpx.ConnectError("down"))
    assert await make_agent().plan_surface("q", "a", 2) == ("sources", [])
