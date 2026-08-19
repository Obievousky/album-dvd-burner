from pathlib import Path

from PIL import Image

from album_dvd_burner.artwork import create_placeholder_artwork, prepare_artwork
from album_dvd_burner.workspaces import PROCESSED_ARTWORK


def test_prepare_artwork_returns_none_without_cover(tmp_path):
    workspace = tmp_path / "Album"
    workspace.mkdir()

    assert prepare_artwork(workspace) is None


def test_prepare_artwork_resizes_cover(tmp_path):
    workspace = tmp_path / "Album"
    source_dir = workspace / "source"
    source_dir.mkdir(parents=True)
    cover = source_dir / "cover.jpg"
    Image.new("RGB", (100, 100), (255, 0, 0)).save(cover)

    result = prepare_artwork(workspace)

    assert result == workspace / PROCESSED_ARTWORK
    assert result.exists()


def test_create_placeholder_artwork_writes_black_image(tmp_path):
    dest = tmp_path / "nested" / "placeholder.jpg"

    result = create_placeholder_artwork(dest)

    assert result == dest
    assert dest.exists()
    with Image.open(dest) as image:
        assert image.size == (720, 480)
        assert image.getpixel((0, 0)) == (0, 0, 0)
