from pathlib import Path

import pytest

from album_dvd_burner.audio import AudioInfo
from album_dvd_burner.dvd_author import _create_track_vob, author_dvd


def test_vob_command_keeps_explicit_audio_quality_after_dvd_target(monkeypatch, tmp_path):
    command: list[str] = []
    monkeypatch.setattr("album_dvd_burner.dvd_author.run", lambda value: command.extend(value))

    _create_track_vob(
        tmp_path / "track.wav",
        tmp_path / "cover.jpg",
        tmp_path / "track.vob",
        standard="ntsc",
        album_audio_info=AudioInfo(96000, 24, 2, "flac"),
    )

    assert command.index("-target") < command.index("-c:a")
    assert command[command.index("-c:a") + 1] == "pcm_s24be"
    assert command[command.index("-ar") + 1] == "96000"


def test_author_rejects_unknown_standard(tmp_path):
    with pytest.raises(ValueError, match="DVD standard"):
        author_dvd([object()], tmp_path / "output", standard="secam")
