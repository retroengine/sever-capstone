"""The assistant writes only from the retrieved passages, and never leaks the key (Stage 6.2).

Oracle A: the plan's Stage 6.2 (no key or an error gives the passages labelled "AI off"; the
prompt holds only the retrieved passages; the key is never in a log, the call log or the report).
The live Groq call runs in the full tier only, and only with ``GROQ_API_KEY`` set.
"""

import json
import os
import urllib.error

import pytest

from sever_studio import assistant

PASSAGES = ["The shed code is 4471.", "The party is on Saturday."]
KEY = "gsk_test_not_a_real_key_0123456789"


def test_assistant_without_a_key_shows_the_passages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    a = assistant.answer("What is the shed code?", PASSAGES)
    assert not a.ai
    assert a.note.startswith("AI off")
    assert "[1] The shed code is 4471." in a.text
    assert "[2] The party is on Saturday." in a.text


def test_assistant_sends_only_the_question_and_the_passages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    seen: dict[str, object] = {}

    def post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        seen.update(url=url, headers=headers, body=json.loads(body), timeout=timeout)
        return json.dumps({"choices": [{"message": {"content": "It is 4471 [1]."}}]}).encode()

    a = assistant.answer("What is the shed code?", PASSAGES, post)
    assert a.ai
    assert a.text == "It is 4471 [1]."
    assert seen["url"] == assistant.URL
    assert seen["timeout"] == 20.0
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["reasoning_effort"] == "low"
    user = body["messages"][1]["content"]
    assert user == (
        "Passages:\n[1] The shed code is 4471.\n\n[2] The party is on Saturday.\n\n"
        "Question: What is the shed code?"
    )
    assert KEY not in repr(a)  # the key is only in the request header
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == f"Bearer {KEY}"


def test_assistant_groq_model_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    seen: dict[str, object] = {}

    def post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        seen.update(body=json.loads(body))
        return json.dumps({"choices": [{"message": {"content": "ok [1]"}}]}).encode()

    a = assistant.answer("q", PASSAGES, post)
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen/qwen3.8-27b"
    assert "reasoning_effort" not in body  # only the gpt-oss models take it
    assert "qwen/qwen3.8-27b" in a.note


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(assistant.URL, 401, f"bad key {KEY}", {}, None),  # type: ignore[arg-type]
        TimeoutError(f"timed out {KEY}"),
        ValueError("not json"),
    ],
)
def test_assistant_an_error_falls_back_without_the_key(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", KEY)

    def post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        raise error

    a = assistant.answer("q?", PASSAGES, post)
    assert not a.ai
    assert a.note.startswith("AI off")
    assert KEY not in a.note
    assert KEY not in a.text
    assert KEY not in a.sent


@pytest.mark.full
def test_assistant_one_live_groq_call() -> None:
    if not os.environ.get("GROQ_API_KEY"):
        pytest.skip("no GROQ_API_KEY")
    a = assistant.answer("What is the shed code?", PASSAGES)
    assert a.ai, a.note
    assert "4471" in a.text
