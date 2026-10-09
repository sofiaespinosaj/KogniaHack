import httpx
import pytest

from app.config import load_settings
from app.ingestion.client import SodaAuthError, SodaClient, SodaError

TOTAL = 2500  # 3 páginas con pageSize 1000


def make_rows(n):
    return [{":id": f"row-{i}", "departamento": "X"} for i in range(n)]


def api_handler(total=TOTAL, drop=0, dup=False, calls=None):
    rows = make_rows(total)

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        body = __import__("json").loads(request.content)
        if "count(*)" in body["query"]:
            return httpx.Response(200, json=[{"n": str(total)}])
        p = body["page"]
        start = (p["pageNumber"] - 1) * p["pageSize"]
        chunk = rows[start:start + p["pageSize"]]
        if drop and p["pageNumber"] == 3:
            chunk = chunk[:-drop]
        if dup and p["pageNumber"] == 2:
            chunk = [dict(chunk[0])] + chunk[1:]
            chunk[0][":id"] = "row-0"
        return httpx.Response(200, json=chunk)

    return handler


def client(handler, **env):
    s = load_settings({"SODA_APP_TOKEN": "tok-secret", **env})
    sleeps = []

    async def fake_sleep(t):
        sleeps.append(t)

    c = SodaClient(s, transport=httpx.MockTransport(handler), sleep=fake_sleep)
    return c, sleeps


async def test_pagination_count_and_unique_ids_and_token_header():
    calls = []
    c, _ = client(api_handler(calls=calls))
    rows, total = await c.fetch_all()
    assert total == len(rows) == TOTAL
    assert len({r[":id"] for r in rows}) == TOTAL
    assert all(r.headers["X-App-Token"] == "tok-secret" for r in calls)
    pages = [__import__("json").loads(r.content).get("page", {}).get("pageNumber") for r in calls]
    assert sorted(p for p in pages if p) == [1, 2, 3]
    await c.aclose()


async def test_incomplete_download_raises():
    c, _ = client(api_handler(drop=5))
    with pytest.raises(SodaError, match="incompleta"):
        await c.fetch_all()


async def test_duplicate_ids_raise():
    c, _ = client(api_handler(dup=True))
    with pytest.raises(SodaError, match="IDs"):
        await c.fetch_all()


@pytest.mark.parametrize("code", [401, 403])
async def test_auth_errors_not_retried(code):
    n = 0

    def h(request):
        nonlocal n
        n += 1
        return httpx.Response(code)

    c, sleeps = client(h)
    with pytest.raises(SodaAuthError) as exc:
        await c.total()
    assert n == 1 and not sleeps
    assert "tok-secret" not in str(exc.value)


async def test_429_respects_retry_after():
    seq = iter([httpx.Response(429, headers={"Retry-After": "7"}),
                httpx.Response(200, json=[{"n": "10"}])])
    c, sleeps = client(lambda r: next(seq))
    assert await c.total() == 10
    assert sleeps == [7.0]


async def test_503_then_200_recovers_with_backoff():
    seq = iter([httpx.Response(503), httpx.Response(200, json=[{"n": "10"}])])
    c, sleeps = client(lambda r: next(seq))
    assert await c.total() == 10
    assert len(sleeps) == 1 and 1 <= sleeps[0] < 2


async def test_network_error_retries_then_gives_up_without_token():
    def h(request):
        raise httpx.ConnectError("boom", request=request)

    c, sleeps = client(h, SODA_MAX_TRIES="3")
    with pytest.raises(SodaError) as exc:
        await c.total()
    assert len(sleeps) == 2  # no espera tras el último intento
    assert "tok-secret" not in str(exc.value)
