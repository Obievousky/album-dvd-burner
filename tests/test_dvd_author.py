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


def test_vob_uses_mplex_and_preserves_24bit_96k_audio(monkeypatch, tmp_path):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "album_dvd_burner.dvd_author.probe_duration",
        lambda path: 180.0,
    )
    monkeypatch.setattr(
        "album_dvd_burner.dvd_author.run",
        lambda cmd, **k: commands.append(cmd),
    )

    _create_track_vob(
        tmp_path / "track.wav",
        tmp_path / "cover.jpg",
        tmp_path / "track.vob",
        standard="ntsc",
        album_audio_info=AudioInfo(96000, 24, 2, "flac"),
    )

    assert len(commands) == 3
    video_cmd, audio_cmd, mplex_cmd = commands

    # Still image is encoded to a DVD-compliant MPEG-2 elementary stream.
    assert video_cmd[0] == "ffmpeg"
    assert video_cmd[video_cmd.index("-f") + 1] == "mpeg2video"
    assert video_cmd[video_cmd.index("-r") + 1] == "30000/1001"
    assert video_cmd[video_cmd.index("-g") + 1] == "18"

    # Audio is emitted as raw big-endian 24-bit PCM at 96 kHz.
    assert audio_cmd[0] == "ffmpeg"
    assert audio_cmd[audio_cmd.index("-c:a") + 1] == "pcm_s24be"
    assert audio_cmd[audio_cmd.index("-f") + 1] == "s24be"
    assert audio_cmd[audio_cmd.index("-ar") + 1] == "96000"

    # Streams are multiplexed with mplex in DVD format, preserving LPCM quality.
    assert mplex_cmd[0] == "mplex"
    assert mplex_cmd[mplex_cmd.index("-f") + 1] == "8"
    assert mplex_cmd[mplex_cmd.index("-L") + 1] == "96000:2:24"
    assert mplex_cmd[-2].endswith(".m2v")
    assert mplex_cmd[-1].endswith(".lpcm")


def test_vob_uses_16bit_pcm_for_cd_quality_pal(monkeypatch, tmp_path):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "album_dvd_burner.dvd_author.probe_duration",
        lambda path: 180.0,
    )
    monkeypatch.setattr(
        "album_dvd_burner.dvd_author.run",
        lambda cmd, **k: commands.append(cmd),
    )

    _create_track_vob(
        tmp_path / "track.wav",
        tmp_path / "cover.jpg",
        tmp_path / "track.vob",
        standard="pal",
        album_audio_info=AudioInfo(48000, 16, 2, "wav"),
    )

    video_cmd, audio_cmd, mplex_cmd = commands
    assert video_cmd[video_cmd.index("-r") + 1] == "25"
    assert audio_cmd[audio_cmd.index("-c:a") + 1] == "pcm_s16be"
    assert audio_cmd[audio_cmd.index("-f") + 1] == "s16be"
    assert mplex_cmd[mplex_cmd.index("-L") + 1] == "48000:2:16"


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
