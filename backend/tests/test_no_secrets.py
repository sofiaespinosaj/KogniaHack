import logging

import httpx

from app.config import load_settings
from app.datastore.store import Store
from app.ingestion.client import SodaClient
from app.ingestion.refresh import refresh_once

SECRET = "tok-super-secret-123"


async def _run(handler, caplog):
    s = load_settings({"SODA_APP_TOKEN": SECRET, "SODA_MAX_TRIES": "2"})

    async def no_sleep(_):
        pass

    c = SodaClient(s, transport=httpx.MockTransport(handler), sleep=no_sleep)
    with caplog.at_level(logging.DEBUG):
        await refresh_once(Store(), c)
    await c.aclose()
    return s


async def test_logs_do_not_contain_token_on_auth_error(caplog):
    s = await _run(lambda r: httpx.Response(401), caplog)
    assert caplog.records and SECRET not in caplog.text and SECRET not in repr(s)


async def test_logs_do_not_contain_token_on_retries_and_network_errors(caplog):
    def h(request):
        raise httpx.ConnectError("boom", request=request)

    await _run(h, caplog)
    assert "reintento" in caplog.text and SECRET not in caplog.text


async def test_logs_do_not_contain_token_on_5xx(caplog):
    await _run(lambda r: httpx.Response(503), caplog)
    assert SECRET not in caplog.text
