from pathlib import Path

import pytest

from app.services.sync_b3 import parse_b3_lines, sync_from_file


@pytest.mark.asyncio
async def test_parse_b3_fixture():
    lines = Path("/home/ubuntu/thlpro/backend/tests/fixtures/b3_series_sample.txt").read_text(encoding="utf-8").splitlines()
    parsed = parse_b3_lines(lines)
    assert len(parsed) >= 4
    assert parsed[0].option_symbol.startswith("BOVA")


@pytest.mark.asyncio
async def test_sync_from_file_creates_updates(db_session, seeded_db):
    summary = await sync_from_file(db_session, "/home/ubuntu/thlpro/backend/tests/fixtures/b3_series_sample.txt")
    assert summary["created"] >= 1 or summary["updated"] >= 1
