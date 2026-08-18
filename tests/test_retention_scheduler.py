from pathlib import Path

from album_dvd_burner.retention_scheduler import RetentionScheduler


def test_scheduler_refuses_sibling_with_matching_prefix(tmp_path):
    data_root = tmp_path / "data"
    sibling = tmp_path / "data-backup"
    data_root.mkdir()
    sibling.mkdir()
    target = sibling / "important.wav"
    target.touch()

    scheduler = RetentionScheduler()
    try:
        scheduler.configure(data_root, delay_hours=1)
        assert scheduler.schedule(target, label="audio") is None
        assert scheduler.list_pending() == []
    finally:
        scheduler.stop()
