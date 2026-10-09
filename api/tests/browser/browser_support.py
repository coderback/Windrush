"""Fixtures and scripted LLMs for the real-browser tests (imported by test_browser_agent.py)."""
import asyncio
import functools
import http.server
import re
import threading
from pathlib import Path

import psutil
import pytest
from browser_use.llm.views import ChatInvokeCompletion

SITE = Path(__file__).parent / "site"


@pytest.fixture(scope="module")
def site():
    """Serve tests/browser/site on 127.0.0.1; yields the base URL."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def ba(monkeypatch):
    """app.browser_agent with IP blocking relaxed — the local test site is a raw IP."""
    import app.browser_agent as module
    monkeypatch.setattr(module, "_BLOCK_IP_ADDRESSES", False)
    return module


def chromium_processes() -> list:
    found = []
    for p in psutil.Process().children(recursive=True):
        try:
            name = p.name().lower()
            if "chrom" in name or "headless_shell" in name:
                found.append(p)
        except psutil.Error:
            pass
    return found


def assert_no_chromium_left(timeout: float = 10.0):
    """Chromium shuts down asynchronously after kill(); wait for it rather than sleeping blind."""
    async def wait():
        for _ in range(int(timeout / 0.25)):
            if not chromium_processes():
                return
            await asyncio.sleep(0.25)
    asyncio.run(wait())
    assert chromium_processes() == [], "Chromium processes left running"


def _with_defaults(model_cls, data: dict):
    for name, field in model_cls.model_fields.items():
        if name not in data and field.is_required():
            ann = field.annotation
            data[name] = ([] if getattr(ann, "__origin__", None) is list
                          else "" if ann is str else False if ann is bool else None)
    return model_cls.model_validate(data)


class ScriptedLLM:
    """
    browser-use BaseChatModel stand-in. The fill agent and the submit agent each get one `done`
    action (success configurable); other structured calls get schema defaults. Every message
    text the model is sent is recorded in `.seen`.
    """
    model = "scripted"
    _verified_api_keys = True
    provider = property(lambda self: "scripted")
    name = property(lambda self: "scripted")
    model_name = property(lambda self: "scripted")

    def __init__(self, fill_success: bool = True, submit_success: bool = True):
        self.fill_success, self.submit_success = fill_success, submit_success
        self.tasks: list[str] = []
        self.seen: list[str] = []

    @staticmethod
    def _text(messages) -> str:
        return "\n".join(str(getattr(m, "text", "") or getattr(m, "content", "")) for m in messages)

    def next_action(self, text: str) -> list[dict]:
        is_submit = "candidate has reviewed" in text
        self.tasks.append("submit" if is_submit else "fill")
        ok = self.submit_success if is_submit else self.fill_success
        return [{"done": {"text": "submit agent ran" if is_submit else "Filled every field", "success": ok}}]

    async def ainvoke(self, messages, output_format=None, **kwargs):
        text = self._text(messages)
        self.seen.append(text)
        if output_format is None:
            return ChatInvokeCompletion(completion="ok", usage=None)
        if "action" not in output_format.model_fields:
            return ChatInvokeCompletion(completion=_with_defaults(output_format, {}), usage=None)
        return ChatInvokeCompletion(completion=_with_defaults(output_format, {"action": self.next_action(text)}),
                                    usage=None)


class SecretTypingLLM(ScriptedLLM):
    """Types the password via its placeholder, reads the form back with JS (as a real model did), then finishes."""

    def __init__(self):
        super().__init__()
        self.typed = self.read_back = False

    def next_action(self, text: str) -> list[dict]:
        field = re.search(r"\[(\d+)\]<input[^\n]*?(?:type=password|id=pw|name=password)", text)
        if field and not self.typed:
            self.typed = True
            return [{"input": {"index": int(field.group(1)), "text": "<secret>job_password</secret>"}}]
        if self.typed and not self.read_back:
            self.read_back = True
            return [{"evaluate": {"code": "(function(){return document.getElementById('pw').value})()"}}]
        return [{"done": {"text": "ready for review", "success": True}}]


async def run_apply_flow(ba, url: str, commands: list[str], **kwargs) -> list[dict]:
    """Drive apply_with_browser, answering each interactive prompt with the next command."""
    queue: asyncio.Queue = asyncio.Queue()
    events = []
    async for event in ba.apply_with_browser(url, {"core_info": {"first_name": "Ada"}}, "Dear Hiring Manager",
                                             queue, kwargs.pop("frame_queue", None), **kwargs):
        events.append(event)
        if event.get("interactive") and commands:
            await queue.put(commands.pop(0))
        if event.get("done"):
            break
    return events
