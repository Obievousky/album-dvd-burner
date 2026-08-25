from pathlib import Path

from album_dvd_burner.audio import AudioInfo, convert_album_to_48k


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "Album"
    source = workspace / "source"
    source.mkdir(parents=True)
    return workspace, source


def test_mixed_bit_depths_are_normalized_to_16bit(monkeypatch, tmp_path):
    workspace, source = _make_workspace(tmp_path)
    track1 = source / "01.flac"
    track2 = source / "02.flac"
    files = [track1, track2]

    def fake_probe(path):
        if path.name == "01.flac":
            return AudioInfo(44100, 24, 2, "flac")
        return AudioInfo(44100, 16, 2, "flac")

    commands: list[list[str]] = []
    monkeypatch.setattr("album_dvd_burner.audio.list_audio_files", lambda *a, **k: files)
    monkeypatch.setattr("album_dvd_burner.audio.probe_audio", fake_probe)
    monkeypatch.setattr("album_dvd_burner.audio.run", lambda cmd, **k: commands.append(cmd))

    result = convert_album_to_48k(workspace)

    assert result == workspace / "16-48"
    assert len(commands) == 2
    for command in commands:
        af = command[command.index("-af") + 1]
        assert "osr=48000" in af
        assert "ochl=stereo" in af
        assert "osf=s16" in af
        assert command[command.index("-acodec") + 1] == "pcm_s16le"


def test_homogeneous_dvd_safe_album_skips_conversion(monkeypatch, tmp_path):
    workspace, source = _make_workspace(tmp_path)
    files = [source / "01.flac"]

    commands: list[list[str]] = []
    monkeypatch.setattr("album_dvd_burner.audio.list_audio_files", lambda *a, **k: files)
    monkeypatch.setattr(
        "album_dvd_burner.audio.probe_audio",
        lambda path: AudioInfo(48000, 16, 2, "flac"),
    )
    monkeypatch.setattr("album_dvd_burner.audio.run", lambda cmd, **k: commands.append(cmd))

    result = convert_album_to_48k(workspace)

    assert result == source
    assert commands == []


def test_mono_tracks_are_forced_to_stereo(monkeypatch, tmp_path):
    workspace, source = _make_workspace(tmp_path)
    files = [source / "01.flac"]

    commands: list[list[str]] = []
    monkeypatch.setattr("album_dvd_burner.audio.list_audio_files", lambda *a, **k: files)
    monkeypatch.setattr(
        "album_dvd_burner.audio.probe_audio",
        lambda path: AudioInfo(48000, 16, 1, "flac"),
    )
    monkeypatch.setattr("album_dvd_burner.audio.run", lambda cmd, **k: commands.append(cmd))

    result = convert_album_to_48k(workspace)

    assert result == workspace / "16-48"
    assert len(commands) == 1
    command = commands[0]
    assert "ochl=stereo" in command[command.index("-af") + 1]
    assert command[command.index("-acodec") + 1] == "pcm_s16le"


def test_existing_matching_conversion_is_reused(monkeypatch, tmp_path):
    workspace, source = _make_workspace(tmp_path)
    track1 = source / "01.flac"
    track2 = source / "02.flac"
    files = [track1, track2]

    converted = workspace / "16-48"
    converted.mkdir()
    cached = converted / "01.wav"
    cached.write_bytes(b"x")

    def fake_probe(path):
        if path == cached:
            return AudioInfo(48000, 16, 2, "pcm_s16le")
        return AudioInfo(44100, 24, 2, "flac")

    commands: list[list[str]] = []
    monkeypatch.setattr("album_dvd_burner.audio.list_audio_files", lambda *a, **k: files)
    monkeypatch.setattr("album_dvd_burner.audio.probe_audio", fake_probe)
    monkeypatch.setattr("album_dvd_burner.audio.run", lambda cmd, **k: commands.append(cmd))

    result = convert_album_to_48k(workspace)

    assert result == converted
    assert len(commands) == 1
    assert commands[0][commands[0].index("-i") + 1] == str(track2)


def test_twenty_bit_source_targets_16bit_96k(monkeypatch, tmp_path):
    workspace, source = _make_workspace(tmp_path)
    files = [source / "01.flac"]

    commands: list[list[str]] = []
    monkeypatch.setattr("album_dvd_burner.audio.list_audio_files", lambda *a, **k: files)
    monkeypatch.setattr(
        "album_dvd_burner.audio.probe_audio",
        lambda path: AudioInfo(96000, 20, 2, "flac"),
    )
    monkeypatch.setattr("album_dvd_burner.audio.run", lambda cmd, **k: commands.append(cmd))

    result = convert_album_to_48k(workspace)

    assert result == workspace / "16-48"
    assert len(commands) == 1
    command = commands[0]
    assert command[command.index("-acodec") + 1] == "pcm_s16le"
    assert "osr=96000" in command[command.index("-af") + 1]
