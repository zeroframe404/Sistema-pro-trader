from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.config_loader import load_config, save_config, watch_config


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _make_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(
        config_dir / "system.yaml",
        {
            "system": {
                "environment": "development",
                "log_level": "INFO",
                "event_bus_backend": "asyncio",
                "redis_url": None,
                "snapshot_interval_seconds": 300,
                "timezone": "UTC",
            }
        },
    )
    _write_yaml(config_dir / "brokers.yaml", {"brokers": []})
    _write_yaml(config_dir / "strategies.yaml", {"strategies": []})
    _write_yaml(config_dir / "signals.yaml", {"signals": {"enabled": True}})
    return config_dir


def test_load_valid_yaml(tmp_path: Path) -> None:
    config_dir = _make_config_dir(tmp_path)
    config = load_config(config_dir)

    assert config.system.environment.value == "development"
    assert config.system.run_id is not None


def test_invalid_field_has_clear_error(tmp_path: Path) -> None:
    config_dir = _make_config_dir(tmp_path)
    _write_yaml(
        config_dir / "system.yaml",
        {
            "system": {
                "environment": "development",
                "log_level": "INVALID",
                "event_bus_backend": "asyncio",
                "redis_url": None,
                "snapshot_interval_seconds": 300,
                "timezone": "UTC",
            }
        },
    )

    with pytest.raises(ValidationError) as exc:
        load_config(config_dir)

    errors = exc.value.errors()
    assert any("log_level" in ".".join(map(str, item["loc"])) for item in errors)


def test_env_override_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = _make_config_dir(tmp_path)
    monkeypatch.setenv("ATP_SYSTEM__ENVIRONMENT", "live")

    config = load_config(config_dir)
    assert config.system.environment.value == "live"


@pytest.mark.asyncio
async def test_hot_reload_calls_callback(tmp_path: Path) -> None:
    config_dir = _make_config_dir(tmp_path)
    reloaded = asyncio.Event()

    async def callback(_config) -> None:
        reloaded.set()

    task = watch_config(config_dir, callback)

    _write_yaml(
        config_dir / "system.yaml",
        {
            "system": {
                "environment": "paper",
                "log_level": "INFO",
                "event_bus_backend": "asyncio",
                "redis_url": None,
                "snapshot_interval_seconds": 300,
                "timezone": "UTC",
            }
        },
    )

    await asyncio.wait_for(reloaded.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_save_config_persists_signals_file(tmp_path: Path) -> None:
    config_dir = _make_config_dir(tmp_path)
    config = load_config(config_dir)
    output_dir = tmp_path / "output"
    save_config(config, output_dir)
    assert (output_dir / "signals.yaml").exists()
    assert (output_dir / "risk.yaml").exists()
