import json
import logging
from pathlib import Path

import httpx

from app.agent.gold import GOLD
from app.agent.text_agent import TextAgent
from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store

SECRET = "sk-test-secret-0123456789abcdef"
REAL_DATA = Path(__file__).resolve().parents[2] / "data"


def test_openai_key_not_in_logs_results_or_errors(caplog):
    store = Store()
    assert load_snapshot(store, load_settings({"DATA_PATH": str(REAL_DATA)}))
    replies = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "count_ips", "arguments": "{}"}}]},
        {"role": "assistant", "content": "Hay 9.320 IPS."},
    ]
    n = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(200, json={"choices": [{"message": replies[n - 1]}]})

    agent = TextAgent(store, api_key=SECRET, model="m", transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG):
        text, results = agent.ask(GOLD[0].question)
    assert SECRET not in caplog.text and SECRET not in text and SECRET not in json.dumps(results)
    assert SECRET not in repr(agent.__dict__.get("_brief"))


def test_http_error_does_not_leak_key(caplog):
    store = Store()
    assert load_snapshot(store, load_settings({"DATA_PATH": str(REAL_DATA)}))
    agent = TextAgent(store, api_key=SECRET, model="m",
                      transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad key"})))
    try:
        agent.ask("hola")
    except httpx.HTTPStatusError as e:
        assert SECRET not in str(e)
    else:
        raise AssertionError("debía fallar con 401")
