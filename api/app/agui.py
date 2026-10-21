"""AG-UI shaped event names for the chat stream.

Studio already streamed SSE; this names the events after the AG-UI taxonomy and
adds the lifecycle and tool-call events the ad-hoc stream lacked, so retrieval
progress is visible instead of happening before the stream opens.

Each frame carries the event name both as the SSE `event:` field and as a `type`
key in the payload, so a client that only reads the JSON still works.
"""

from __future__ import annotations

import json
from typing import Any

RUN_STARTED = "RUN_STARTED"
RUN_FINISHED = "RUN_FINISHED"
RUN_ERROR = "RUN_ERROR"
TOOL_CALL_START = "TOOL_CALL_START"
TOOL_CALL_END = "TOOL_CALL_END"
TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
STATE_SNAPSHOT = "STATE_SNAPSHOT"
CUSTOM = "CUSTOM"


def event(name: str, payload: dict[str, Any] | None = None) -> str:
    return f"event: {name}\ndata: {json.dumps({'type': name, **(payload or {})})}\n\n"
