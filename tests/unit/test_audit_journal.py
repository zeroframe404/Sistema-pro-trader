from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.audit_journal import AuditJournal, JournalEntry


@pytest.mark.asyncio
async def test_write_and_query_jsonl(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    base_time = datetime.now(UTC)

    first = JournalEntry(
        entry_id="1",
        timestamp=base_time,
        run_id="run-1",
        strategy_id="ema",
        strategy_version="1.0.0",
        symbol="EURUSD",
        timeframe="M5",
        raw_inputs={"close": 1.2},
        features={"ema": 1.1},
        scores={"trend": 0.7},
        decision="BUY",
        confidence=0.8,
        reasons=[{"factor": "ema"}],
        triggered_rule="cross_up",
        triggered_condition="fast>slow",
    )
    second = JournalEntry(
        entry_id="2",
        timestamp=base_time + timedelta(minutes=1),
        run_id="run-1",
        strategy_id="rsi",
        strategy_version="1.0.0",
        symbol="BTCUSD",
        timeframe="M5",
        raw_inputs={"close": 60000},
        features={"rsi": 29},
        scores={"mean_revert": 0.8},
        decision="BUY",
        confidence=0.9,
        reasons=[{"factor": "rsi"}],
        triggered_rule="rsi_oversold",
        triggered_condition="rsi<30",
    )

    await journal.write(first)
    await journal.write(second)

    result = await journal.query(strategy_id="ema")
    assert len(result) == 1
    assert result[0].symbol == "EURUSD"


@pytest.mark.asyncio
async def test_query_empty_file_returns_empty_list(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "missing.jsonl")
    result = await journal.query()
    assert result == []
