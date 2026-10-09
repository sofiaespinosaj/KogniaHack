import threading

import pytest

from app.datastore.store import Store
from app.ingestion.client import SodaError
from app.ingestion.refresh import refresh_once
from tests.conftest import raw_row


class FakeClient:
    def __init__(self, rows=None, total=None, error=None):
        self.rows, self.total, self.error = rows, total, error

    async def fetch_all(self):
        if self.error:
            raise self.error
        return self.rows, self.total


def seeded_store():
    s = Store()
    s.replace_from_rows([raw_row(i, departamento="Cauca") for i in range(5)], 5, "snapshot")
    return s


async def test_successful_refresh_swaps_table_and_sets_origin_api(rows):
    s = seeded_store()
    assert await refresh_once(s, FakeClient(rows, len(rows)))
    assert s.provenance.source == "api" and s.provenance.rows == len(rows)
    assert s.state == "ready"


async def test_count_mismatch_keeps_current_table(rows):
    s = seeded_store()
    assert not await refresh_once(s, FakeClient(rows, len(rows) + 1))  # total reportado distinto
    assert s.provenance.source == "snapshot" and s._count() == 5
    assert s.state == "ready"
    tables = {t[0] for t in s.cursor().execute("SHOW TABLES").fetchall()}
    assert "ips_new" not in tables


@pytest.mark.parametrize("err", [SodaError("incompleta"), RuntimeError("boom")])
async def test_download_failure_keeps_current_table(err):
    s = seeded_store()
    assert not await refresh_once(s, FakeClient(error=err))
    assert s.provenance.source == "snapshot" and s._count() == 5 and s.state == "ready"


def test_queries_during_swap_do_not_fail(rows):
    s = seeded_store()
    errors, stop = [], threading.Event()

    def reader():
        cur = s.cursor()
        while not stop.is_set():
            try:
                n = cur.execute("SELECT count(*) FROM ips").fetchone()[0]
                assert n in (5, 50)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    t = threading.Thread(target=reader)
    t.start()
    for _ in range(5):
        s.replace_from_rows(rows, len(rows), "api")
        s.replace_from_rows(rows[:5], 5, "snapshot")
    stop.set()
    t.join()
    assert not errors
