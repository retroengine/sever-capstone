"""The assistant: a language model writes the answer from the passages SEVER-DB returned.

Groq's OpenAI-compatible ``chat/completions`` with ``llama-3.1-8b-instant``, called with the
standard library on Studio's worker thread, 20 s timeout. The key is read from ``GROQ_API_KEY`` at
each call; it is never logged, shown, saved or put in an error. The question and the retrieved
passages are sent to Groq, and the screen says so: what Groq receives is outside the database and
outside anything SEVER-DB can delete or prove. With no key, or on any error, the answer is the
passages themselves, labelled "AI off".
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.1-8b-instant"
TIMEOUT = 20.0
SYSTEM = (
    "You are the assistant of Acme Notes. Answer only from the numbered passages you are given, "
    "and cite each passage you use as [n]. If they do not answer the question, say so."
)

#: ``(url, headers, body, timeout) -> response body``; replaced in tests
Post = Callable[[str, dict[str, str], bytes, float], bytes]


@dataclass(frozen=True)
class Answer:
    text: str
    #: written by the model (``True``) or the passages shown as they are (``False``, "AI off")
    ai: bool
    #: why the AI is off, or which model answered; never holds the key
    note: str
    #: exactly what was (or would have been) sent: the system line, the question, the passages
    sent: str


def messages(question: str, passages: list[str]) -> list[dict[str, str]]:
    body = "\n\n".join(f"[{n}] {p}" for n, p in enumerate(passages, 1))
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Passages:\n{body}\n\nQuestion: {question}"},
    ]


def _post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out: bytes = r.read()
        return out


def off(passages: list[str]) -> str:
    return "\n\n".join(f"[{n}] {p}" for n, p in enumerate(passages, 1)) or "(no passages found)"


def answer(question: str, passages: list[str], post: Post | None = None) -> Answer:
    msgs = messages(question, passages)
    sent = "\n\n".join(m["content"] for m in msgs)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return Answer(off(passages), False, "AI off: no GROQ_API_KEY set", sent)
    if not passages:
        return Answer(off(passages), False, "AI off: nothing was retrieved to answer from", sent)
    body = json.dumps({"model": MODEL, "messages": msgs, "temperature": 0}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "sever-studio",
    }
    try:
        raw = (post or _post)(URL, headers, body, TIMEOUT)
        text = json.loads(raw)["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return Answer(off(passages), False, f"AI off: Groq answered HTTP {e.code}", sent)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        return Answer(off(passages), False, f"AI off: {type(e).__name__} calling Groq", sent)
    return Answer(text, True, f"written by {MODEL} on Groq from the passages below", sent)
