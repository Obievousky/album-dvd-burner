import shutil
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .artwork import prepare_artwork
from .audio import AudioInfo, prepare_album_audio
from .progress import ProgressTracker
from .utils import run, run_capture


@dataclass
class AlbumTitle:
    name: str
    source_folder: Path
    work_dir: Path
    tracks: list[Path]
    artwork: Path
    audio_info: AudioInfo


def prepare_album(workspace: Path, tracker: ProgressTracker | None = None) -> AlbumTitle:
    if tracker:
        tracker.log("preparing", f"Scanning album: {workspace.name}")

    work_dir, tracks, info = prepare_album_audio(workspace, tracker)

    if tracker:
        tracker.log("preparing", f"Preparing artwork for {workspace.name}")

    artwork = prepare_artwork(workspace)

    if tracker:
        tracker.log("preparing", f"Artwork ready: {artwork.name}")

    return AlbumTitle(
        name=workspace.name,
        source_folder=workspace,
        work_dir=work_dir,
        tracks=tracks,
        artwork=artwork,
        audio_info=info,
    )


def _ffmpeg_target(standard: str) -> str:
    return "ntsc-dvd" if standard == "ntsc" else "pal-dvd"


def _create_track_vob(
    track: Path,
    artwork: Path,
    vob_path: Path,
    *,
    standard: str,
    album_audio_info: AudioInfo | None = None,
) -> None:
    """Create a VOB for a single track.

    Preserve highest reasonable audio quality: if the album audio is 24-bit (or higher)
    encode audio as 24-bit PCM; otherwise use 16-bit. Use soxr resampler for best quality.
    """
    vob_path.parent.mkdir(parents=True, exist_ok=True)

    # Decide target audio codec and sample rate
    target_samplerate = 48000
    target_codec = "pcm_s16be"
    if album_audio_info is not None:
        if album_audio_info.sample_rate == 96000:
            target_samplerate = 96000
        else:
            # For DVD we target 48 kHz (we convert 44.1 -> 48 earlier in pipeline)
            target_samplerate = 48000
        if album_audio_info.bit_depth >= 24:
            target_codec = "pcm_s24be"
        else:
            target_codec = "pcm_s16be"

    # Build ffmpeg command using soxr resampler and preserve bit depth when possible
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-i",
        str(artwork),
        "-i",
        str(track),
        "-c:v",
        "mpeg2video",
        "-q:v",
        "4",
        # Let ffmpeg choose threads optimally
        "-threads",
        "0",
        # audio: use soxr resampler for highest quality
        "-af",
        "aresample=resampler=soxr",
        "-ar",
        str(target_samplerate),
        "-c:a",
        target_codec,
        "-f",
        "vob",
        "-target",
        _ffmpeg_target(standard),
        "-shortest",
        str(vob_path),
    ]

    run(cmd)


def _build_dvdauthor_xml(albums: list[AlbumTitle], vob_map: dict[Path, str], standard: str) -> str:
    root = ET.Element("dvdauthor", dest=".")
    for album in albums:
        titleset = ET.SubElement(root, "titleset")
        titles = ET.SubElement(titleset, "titles")
        ET.SubElement(titles, "video", format=standard, aspect="4:3")
        pgc = ET.SubElement(titles, "pgc")
        for track in album.tracks:
            ET.SubElement(pgc, "vob", file=vob_map[track])

    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def _encode_vob_task(
    album_index: int,
    track_index: int,
    album: AlbumTitle,
    track: Path,
    work_root: Path,
    standard: str,
) -> tuple[Path, str]:
    vob_name = f"title{album_index:02d}_track{track_index:02d}.vob"
    vob_path = work_root / vob_name
    _create_track_vob(track, album.artwork, vob_path, standard=standard, album_audio_info=album.audio_info)
    return track, vob_name


def author_dvd(
    albums: list[AlbumTitle],
    output_dir: Path,
    *,
    standard: str = "ntsc",
    work_root: Path | None = None,
    tracker: ProgressTracker | None = None,
) -> Path:
    if not albums:
        raise ValueError("At least one album folder is required")

    work_root = work_root or (output_dir.parent / ".dvd_work")
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    try:
        total_tracks = sum(len(album.tracks) for album in albums)
        vob_map: dict[Path, str] = {}
        completed = 0

        if tracker:
            tracker.log(
                "authoring",
                f"Encoding {total_tracks} track(s) to DVD VOB (parallel, this may take several minutes)...",
            )

        tasks = []
        for album_index, album in enumerate(albums, start=1):
            for track_index, track in enumerate(album.tracks, start=1):
                tasks.append((album_index, track_index, album, track))

        max_workers = min(4, max(1, len(tasks)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    _encode_vob_task,
                    album_index,
                    track_index,
                    album,
                    track,
                    work_root,
                    standard,
                ): (album, track, album_index, track_index)
                for album_index, track_index, album, track in tasks
            }

            for future in as_completed(futures):
                album, track, album_index, track_index = futures[future]
                track_path, vob_name = future.result()
                vob_map[track_path] = vob_name
                completed += 1
                if tracker:
                    tracker.advance(
                        "authoring",
                        f"[{completed}/{total_tracks}] VOB ready — title {album_index}, "
                        f"track {track_index}: {album.name} / {track.name}",
                    )

        if tracker:
            tracker.log("authoring", "Building DVD structure with dvdauthor...")

        xml_path = work_root / "dvdauthor.xml"
        xml_path.write_text(_build_dvdauthor_xml(albums, vob_map, standard), encoding="utf-8")

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Run dvdauthor while capturing stdout/stderr for diagnostics
        proc = subprocess.run(["dvdauthor", "-o", str(output_dir), "-x", str(xml_path)], cwd=work_root, capture_output=True, text=True)
        if tracker:
            tracker.advance("authoring", "dvdauthor finished")
            if proc.stdout:
                tracker.advance("authoring", f"dvdauthor stdout: {proc.stdout.strip()[:2000]}")
            if proc.stderr:
                tracker.advance("authoring", f"dvdauthor stderr: {proc.stderr.strip()[:2000]}")
        if proc.returncode != 0:
            files_list = '\n'.join(sorted(str(p.relative_to(output_dir)) for p in output_dir.rglob('*')))
            raise RuntimeError(
                f"dvdauthor failed (exit {proc.returncode}).\n"
                f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}\n\n"
                f"Output directory contents:\n{files_list}"
            )

        if tracker:
            tracker.advance("authoring", "DVD structure built (VIDEO_TS)")

        # Basic verification: ensure VIDEO_TS exists and contains IFO files before creating ISO
        video_ts = output_dir / "VIDEO_TS"
        # Check for .IFO files case-insensitively
        has_ifo = False
        if video_ts.is_dir():
            for p in video_ts.iterdir():
                if p.is_file() and p.suffix.lower() == ".ifo":
                    has_ifo = True
                    break
        if not video_ts.is_dir() or not has_ifo:
            files_list = '\n'.join(sorted(str(p.relative_to(output_dir)) for p in output_dir.rglob('*')))
            raise RuntimeError(
                "dvdauthor did not produce a valid VIDEO_TS directory. "
                "genisoimage requires a VIDEO_TS folder with .IFO files. "
                "Check previous 'authoring' logs for errors.\n"
                f"Output directory contents:\n{files_list}"
            )

        if tracker:
            tracker.log("authoring", "Creating disc ISO with genisoimage...")

        iso_path = output_dir / "disc.iso"
        # Force input charset to UTF-8 and capture output for diagnostics
        # Try genisoimage without -input-charset for maximum compatibility
        proc_iso = subprocess.run(
            [
                "genisoimage",
                "-o",
                str(iso_path),
                "-dvd-video",
                str(output_dir),
            ],
            cwd=output_dir,
            capture_output=True,
            text=True,
        )

        if tracker:
            if proc_iso.stdout:
                tracker.advance("authoring", f"genisoimage stdout: {proc_iso.stdout.strip()[:2000]}")
            if proc_iso.stderr:
                tracker.advance("authoring", f"genisoimage stderr: {proc_iso.stderr.strip()[:2000]}")

        # If genisoimage fails, surface stderr and output contents to help debugging
        if proc_iso.returncode != 0:
            files_list = '\n'.join(sorted(str(p.relative_to(output_dir)) for p in output_dir.rglob('*')))
            # If failure mentions input-charset or other charset hints, recommend trying alternate genisoimage
            raise RuntimeError(
                f"genisoimage failed (exit {proc_iso.returncode}).\n"
                f"stdout:\n{proc_iso.stdout}\n\nstderr:\n{proc_iso.stderr}\n\n"
                f"Output directory contents:\n{files_list}"
            )

        if tracker:
            size_mb = iso_path.stat().st_size / (1024 * 1024)
            tracker.advance("authoring", f"ISO created ({size_mb:.1f} MB): {iso_path}")

        return iso_path
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
