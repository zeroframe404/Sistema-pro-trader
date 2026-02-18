"""Configuration loading, saving, and hot-reload utilities."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from core.config_models import RootConfig

try:
    from watchfiles import awatch  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    awatch = None

logger = logging.getLogger(__name__)


def load_config(path: Path) -> RootConfig:
    """Load and validate YAML configuration from a file or config directory."""

    raw_data = _load_raw_data(path)
    _apply_env_overrides(raw_data)
    try:
        return RootConfig.model_validate(raw_data)
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(value) for value in error.get("loc", ()))
            message = error.get("msg", "validation error")
            logger.error("Config validation error", extra={"field": location, "error": message})
        raise


def save_config(config: RootConfig, path: Path) -> None:
    """Save a validated config object to YAML file(s)."""

    payload = config.model_dump(mode="python")
    if path.is_dir() or path.suffix == "":
        path.mkdir(parents=True, exist_ok=True)
        _write_yaml(path / "system.yaml", {"system": payload["system"]})
        _write_yaml(path / "brokers.yaml", {"brokers": payload["brokers"]})
        _write_yaml(path / "strategies.yaml", {"strategies": payload["strategies"]})
        _write_yaml(path / "indicators.yaml", {"indicators": payload["indicators"]})
        return

    _write_yaml(path, payload)


def watch_config(
    path: Path,
    callback: Callable[[RootConfig], Any],
    *,
    debounce_seconds: float = 0.5,
) -> asyncio.Task[None]:
    """Start a cancellable async watcher and call callback on config changes."""

    watch_target = path if path.is_dir() else path.parent
    polling_state = _capture_watch_state(watch_target) if awatch is None else None

    async def _watch_loop() -> None:
        if awatch is not None:
            async for _changes in awatch(str(watch_target), debounce=int(debounce_seconds * 1000)):
                try:
                    latest = load_config(path)
                except ValidationError:
                    continue
                result = callback(latest)
                if inspect.isawaitable(result):
                    await result
            return

        previous_state = polling_state or _capture_watch_state(watch_target)
        while True:
            await asyncio.sleep(max(debounce_seconds, 0.1))
            current_state = _capture_watch_state(watch_target)
            if current_state == previous_state:
                continue
            previous_state = current_state

            try:
                latest = load_config(path)
            except ValidationError:
                continue
            result = callback(latest)
            if inspect.isawaitable(result):
                await result

    return asyncio.create_task(_watch_loop(), name="config-watch-task")


def _load_raw_data(path: Path) -> dict[str, Any]:
    if path.is_dir() or path.suffix == "":
        return _load_from_directory(path)

    return _read_yaml(path)


def _load_from_directory(config_dir: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    files = ("system.yaml", "brokers.yaml", "strategies.yaml", "indicators.yaml")

    for file_name in files:
        file_path = config_dir / file_name
        if not file_path.exists():
            continue
        content = _read_yaml(file_path)
        _deep_merge(merged, content)

    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _apply_env_overrides(data: dict[str, Any]) -> None:
    prefix = "ATP_"
    for env_key, raw_value in os.environ.items():
        if not env_key.startswith(prefix):
            continue

        path_parts = env_key[len(prefix) :].lower().split("__")
        parsed_value = yaml.safe_load(raw_value) if raw_value else raw_value

        cursor = data
        for part in path_parts[:-1]:
            next_cursor = cursor.get(part)
            if not isinstance(next_cursor, dict):
                next_cursor = {}
                cursor[part] = next_cursor
            cursor = next_cursor

        cursor[path_parts[-1]] = parsed_value


def _capture_watch_state(path: Path) -> dict[str, tuple[int, int]]:
    if path.is_file():
        if not path.exists():
            return {str(path): (0, 0)}
        stat = path.stat()
        return {str(path): (stat.st_mtime_ns, stat.st_size)}

    state: dict[str, tuple[int, int]] = {}
    for file_path in sorted(path.rglob("*.yaml")):
        stat = file_path.stat()
        state[str(file_path)] = (stat.st_mtime_ns, stat.st_size)
    return state
