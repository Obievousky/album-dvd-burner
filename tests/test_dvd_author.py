from pathlib import Path

import pytest

from album_dvd_burner.audio import AudioInfo
from album_dvd_burner.dvd_author import (
    AlbumTitle,
    _create_track_vob,
    _encode_vob_task,
    author_dvd,
    prepare_album,
)


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
    assert command[command.index("-c:a") + 1] == "pcm_dvd"
    assert command[command.index("-ar") + 1] == "96000"


def test_author_rejects_unknown_standard(tmp_path):
    with pytest.raises(ValueError, match="DVD standard"):
        author_dvd([object()], tmp_path / "output", standard="secam")


def test_prepare_album_handles_missing_artwork(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "album_dvd_burner.dvd_author.prepare_album_audio",
        lambda workspace, tracker: (tmp_path, [tmp_path / "01.wav"], AudioInfo(48000, 16, 2, "wav")),
    )
    monkeypatch.setattr("album_dvd_burner.dvd_author.prepare_artwork", lambda workspace: None)

    album = prepare_album(tmp_path)

    assert album.artwork is None


def test_encode_vob_uses_placeholder_when_no_artwork(monkeypatch, tmp_path):
    captured: dict = {}
    monkeypatch.setattr(
        "album_dvd_burner.dvd_author._create_track_vob",
        lambda track, artwork, vob_path, standard=None, album_audio_info=None: captured.update(
            track=track, artwork=artwork, vob_path=vob_path
        ),
    )
    track = tmp_path / "01.wav"
    placeholder = tmp_path / ".black.jpg"
    album = AlbumTitle(
        name="NoCover",
        source_folder=tmp_path,
        work_dir=tmp_path,
        tracks=[track],
        artwork=None,
        audio_info=AudioInfo(48000, 16, 2, "wav"),
    )

    _encode_vob_task(1, 1, album, track, tmp_path, "ntsc", placeholder)

    assert captured["artwork"] == placeholder
    assert captured["track"] == track
