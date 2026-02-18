"""Snapshot management for crash recovery and state persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class SnapshotMeta(BaseModel):
    """Snapshot metadata entry."""

    snapshot_id: str
    path: str
    timestamp: datetime
    size_bytes: int


class SnapshotManager:
    """Save, list, and restore state snapshots with retention."""

    def __init__(self, snapshot_dir: Path, retention_count: int = 20) -> None:
        self._snapshot_dir = snapshot_dir
        self._retention_count = retention_count
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, state: dict) -> Path:
        """Persist one snapshot to disk and enforce retention."""

        now = datetime.now(UTC)
        base_snapshot_id = now.strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_id = base_snapshot_id
        path = self._snapshot_dir / f"snapshot_{snapshot_id}.json"
        collision_index = 1
        while path.exists():
            snapshot_id = f"{base_snapshot_id}_{collision_index:02d}"
            path = self._snapshot_dir / f"snapshot_{snapshot_id}.json"
            collision_index += 1

        payload = {
            "snapshot_id": snapshot_id,
            "timestamp": now.isoformat(),
            "state": state,
        }
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        self._enforce_retention()
        return path

    def load_latest_snapshot(self) -> dict | None:
        """Load the newest valid snapshot from disk."""

        for file_path in sorted(self._snapshot_dir.glob("snapshot_*.json"), reverse=True):
            try:
                parsed = json.loads(file_path.read_text(encoding="utf-8"))
                state = parsed.get("state")
                if isinstance(state, dict):
                    return state
            except Exception:  # noqa: BLE001
                continue
        return None

    def list_snapshots(self) -> list[SnapshotMeta]:
        """List available snapshots sorted newest-first."""

        results: list[SnapshotMeta] = []
        for file_path in sorted(self._snapshot_dir.glob("snapshot_*.json"), reverse=True):
            try:
                parsed = json.loads(file_path.read_text(encoding="utf-8"))
                timestamp = datetime.fromisoformat(parsed["timestamp"])
                results.append(
                    SnapshotMeta(
                        snapshot_id=parsed["snapshot_id"],
                        path=str(file_path),
                        timestamp=timestamp,
                        size_bytes=file_path.stat().st_size,
                    )
                )
            except Exception:  # noqa: BLE001
                continue

        return results

    def _enforce_retention(self) -> None:
        files = sorted(self._snapshot_dir.glob("snapshot_*.json"), reverse=True)
        if len(files) <= self._retention_count:
            return

        for file_path in files[self._retention_count :]:
            file_path.unlink(missing_ok=True)
