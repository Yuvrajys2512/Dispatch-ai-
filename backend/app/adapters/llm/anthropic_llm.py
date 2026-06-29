"""Real LLM adapter — Claude (default **Haiku 4.5**) via the Anthropic SDK.

Honors :class:`~app.adapters.base.LLMProvider`. It is a **witness, not a judge**:
``extract`` fills only the "what was said" fields of whatever Pydantic ``schema``
the caller asks for (incident type, people, service needs, summary), and the
triage agent still owns severity / junk / route (see ``agent/triage.py`` — it
overwrites the safety-critical fields). So even a hallucinating model can never
move the routing decision.

Structured extraction uses **forced tool use**: we expose a single tool whose
``input_schema`` is the requested model's JSON schema and force the model to call
it, then validate the returned ``tool_use.input`` into the schema. ``generate``
streams tokens for the spoken reply.

Haiku 4.5 is the natural pick here — the agent never trusts the LLM for the
decision, so the cheap, fast model wins. The model id is configurable
(``LLM_MODEL``); Gemini Flash or any other model could sit behind this same
interface unchanged.

The Anthropic client is **injected**, so the contract tests drive a mocked HTTP
transport and never touch the network or a real key.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.adapters.base import ExtractT

logger = logging.getLogger("dispatch.llm")

EXTRACT_TOOL_NAME = "record_incident"
MAX_EXTRACT_TOKENS = 1024
MAX_GENERATE_TOKENS = 512

_EXTRACT_SYSTEM = (
    "You are a field-extraction assistant for India's 112 emergency line. "
    "From the caller's (Hindi/Hinglish/English) words, record ONLY the facts the "
    "caller actually stated, by calling the record_incident tool. Never guess a "
    "severity or invent details that were not said; leave unknown fields empty."
)

_GENERATE_SYSTEM = (
    "You are the calm, authoritative voice of India's 112 emergency line. Reply in "
    "simple Hindi/Hinglish, briefly, reassuring the caller and asking for the one "
    "most important missing detail. Begin a fresh call by identifying as 112."
)


def _tool_input_schema(schema: type[ExtractT]) -> dict:
    """The requested model's JSON schema, shaped for an Anthropic tool input."""
    js = schema.model_json_schema()
    # Anthropic tool input_schema is a JSON Schema object; keep $defs/properties.
    js.setdefault("type", "object")
    return js


class AnthropicLLMProvider:
    def __init__(self, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    async def extract(self, prompt: str, schema: type[ExtractT]) -> ExtractT:
        tool = {
            "name": EXTRACT_TOOL_NAME,
            "description": "Record the structured facts an emergency caller stated.",
            "input_schema": _tool_input_schema(schema),
        }
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=MAX_EXTRACT_TOKENS,
            system=_EXTRACT_SYSTEM,
            tools=[tool],
            tool_choice={"type": "tool", "name": EXTRACT_TOOL_NAME},
            messages=[{"role": "user", "content": prompt or "(silence — no speech)"}],
        )
        raw: dict = {}
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == EXTRACT_TOOL_NAME:
                raw = dict(block.input or {})
                break
        # Keep only known, non-null fields and let schema defaults fill the rest.
        fields = schema.model_fields
        data = {k: v for k, v in raw.items() if k in fields and v is not None}
        return schema.model_validate(data)

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=MAX_GENERATE_TOKENS,
            system=_GENERATE_SYSTEM,
            messages=[
                {"role": "user", "content": prompt or "(call connected; caller silent)"}
            ],
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text


def build_anthropic_llm(
    *, api_key: str, model: str, base_url: str = ""
) -> AnthropicLLMProvider:
    """Construct the real LLM provider from settings (no network on construction)."""
    kwargs: dict = {"api_key": api_key, "http_client": DefaultAsyncHttpxClient()}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncAnthropic(**kwargs)
    return AnthropicLLMProvider(client, model)
