import pytest

from album_dvd_burner.workspaces import safe_resolve_under, sanitize_name


def test_sanitize_name_rejects_reserved(tmp_path):
    with pytest.raises(ValueError, match="Reserved"):
        sanitize_name("_jobs")


def test_sanitize_name_strips_invalid_chars():
    assert sanitize_name('Artist: "Test"') == 'Artist- -Test-'


def test_safe_resolve_under_allows_child(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    target = safe_resolve_under(base, "Artist/source/track.wav")
    assert target == (base / "Artist/source/track.wav").resolve()


def test_safe_resolve_under_blocks_traversal(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    with pytest.raises(ValueError):
        safe_resolve_under(base, "../outside.txt")
