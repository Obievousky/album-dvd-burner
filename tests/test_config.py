import pytest

from album_dvd_burner.config import Settings


def test_settings_reject_invalid_dvd_standard(monkeypatch):
    monkeypatch.setenv("DVD_STANDARD", "secam")

    with pytest.raises(ValueError, match="DVD_STANDARD"):
        Settings.from_env()


def test_settings_rejects_negative_retention_delay(monkeypatch):
    monkeypatch.setenv("RETENTION_DELAY_HOURS", "-1")

    with pytest.raises(ValueError, match="RETENTION_DELAY_HOURS"):
        Settings.from_env()
