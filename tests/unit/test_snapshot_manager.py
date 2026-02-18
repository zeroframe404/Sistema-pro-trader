from __future__ import annotations

from pathlib import Path

from core.snapshot_manager import SnapshotManager


def test_save_and_load_latest_snapshot(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path, retention_count=5)
    manager.save_snapshot({"equity": 1000})

    latest = manager.load_latest_snapshot()
    assert latest == {"equity": 1000}


def test_retention_keeps_last_n(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path, retention_count=2)
    manager.save_snapshot({"n": 1})
    manager.save_snapshot({"n": 2})
    manager.save_snapshot({"n": 3})

    files = list(tmp_path.glob("snapshot_*.json"))
    assert len(files) == 2


def test_tolerates_corrupt_snapshot(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path, retention_count=5)
    valid_path = manager.save_snapshot({"equity": 1000})
    corrupt_path = tmp_path / "snapshot_99999999T999999999999Z.json"
    corrupt_path.write_text("{invalid-json", encoding="utf-8")

    latest = manager.load_latest_snapshot()
    assert latest == {"equity": 1000}
    assert valid_path.exists()
