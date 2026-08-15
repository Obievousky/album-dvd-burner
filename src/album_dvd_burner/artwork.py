from pathlib import Path

from PIL import Image

from .config import ARTWORK_NAMES
from .workspaces import PROCESSED_ARTWORK, album_source_dir


def find_artwork(workspace: Path) -> Path | None:
    for folder in (album_source_dir(workspace), workspace):
        if not folder.is_dir():
            continue
        for name in ARTWORK_NAMES:
            candidate = folder / name
            if candidate.exists():
                return candidate

        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"} and path.is_file():
                return path

    return None


def resize_artwork(source: Path, dest: Path, width: int = 720, height: int = 480) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        fitted = Image.new("RGB", (width, height), (0, 0, 0))
        rgb.thumbnail((width, height), Image.Resampling.LANCZOS)
        offset = ((width - rgb.width) // 2, (height - rgb.height) // 2)
        fitted.paste(rgb, offset)
        fitted.save(dest, format="JPEG", quality=95)
    return dest


def prepare_artwork(workspace: Path) -> Path:
    source = find_artwork(workspace)
    if source is None:
        raise ValueError(
            f"No artwork found in {workspace}. Add cover.jpg or similar image file."
        )

    dest = workspace / PROCESSED_ARTWORK
    return resize_artwork(source, dest)
