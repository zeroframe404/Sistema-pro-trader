from __future__ import annotations

import json
from pathlib import Path

from core.logger import configure_logging, get_logger


def test_logger_includes_run_id_in_json_output(tmp_path: Path) -> None:
    configure_logging(
        run_id="run-123",
        environment="production",
        log_level="INFO",
        log_dir=tmp_path,
    )

    logger = get_logger("tests.logger")
    logger.info("signal_generated", symbol="EURUSD", confidence=0.82)

    log_file = tmp_path / "auto_trading_pro.jsonl"
    content = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) >= 1

    parsed = json.loads(content[-1])
    assert parsed["run_id"] == "run-123"
    assert parsed["event"] == "signal_generated"
    assert parsed["symbol"] == "EURUSD"
