import shutil
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .artwork import create_placeholder_artwork, prepare_artwork
from .audio import AudioInfo, prepare_album_audio, probe_duration
from .progress import ProgressTracker
from .utils import run


@dataclass
class AlbumTitle:
    name: str
    source_folder: Path
    work_dir: Path
    tracks: list[Path]
    artwork: Path | None
    audio_info: AudioInfo


def prepare_album(workspace: Path, tracker: ProgressTracker | None = None) -> AlbumTitle:
    if tracker:
        tracker.log("preparing", f"Scanning album: {workspace.name}")

    work_dir, tracks, info = prepare_album_audio(workspace, tracker)

    if tracker:
        tracker.log("preparing", f"Preparing artwork for {workspace.name}")

    artwork = prepare_artwork(workspace)

    if artwork is None:
        if tracker:
            tracker.log(
                "preparing",
                f"No cover image found for {workspace.name}; using black background",
            )
    elif tracker:
        tracker.log("preparing", f"Artwork ready: {artwork.name}")

    return AlbumTitle(
        name=workspace.name,
        source_folder=workspace,
        work_dir=work_dir,
        tracks=tracks,
        artwork=artwork,
        audio_info=info,
    )


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
    encode audio as 24-bit DVD PCM; otherwise use 16-bit.

    The still image is encoded to a DVD-compliant MPEG-2 elementary stream and then
    multiplexed with raw LPCM audio using mplex (DVD format). mplex produces VOBs that
    dvdauthor 0.7.2 can parse reliably, unlike ffmpeg's own ``-f vob`` muxer whose
    system headers dvdauthor fails to recognise ("no VOBUs found").
    """
    vob_path.parent.mkdir(parents=True, exist_ok=True)

    if standard not in {"ntsc", "pal"}:
        raise ValueError("DVD standard must be 'ntsc' or 'pal'")

    # Keep the highest DVD-safe audio quality available: 96 kHz whenever the source is
    # above 48 kHz, otherwise 48 kHz, while preserving 24-bit PCM when present.
    target_samplerate = 48000
    target_bits = 16
    if album_audio_info is not None:
        target_samplerate = 96000 if album_audio_info.sample_rate > 48000 else 48000
        target_bits = 24 if album_audio_info.bit_depth >= 24 else 16

    # Determine display aspect from artwork dimensions to avoid dvdauthor warnings.
    # Auto-detect between 4:3 and 16:9 based on artwork aspect ratio; fallback to 4:3.
    display_aspect = "4:3"
    try:
        from PIL import Image

        with Image.open(artwork) as img:
            w, h = img.size
            ratio = float(w) / float(h) if h else 0.0
            # Choose threshold halfway between 4:3 (~1.333) and 16:9 (~1.777)
            threshold = (4.0 / 3.0 + 16.0 / 9.0) / 2.0  # ~1.555
            display_aspect = "16:9" if ratio >= threshold else "4:3"
    except Exception:
        # If PIL is not available or reading fails, default to 4:3
        display_aspect = "4:3"

    if standard == "ntsc":
        # NTSC DVD resolution is 720x480 at 30000/1001 fps
        width, height = 720, 480
        fps = "30000/1001"
        gop = 18
        sar = "8/9" if display_aspect == "4:3" else "32/27"
    else:
        # PAL DVD resolution is 720x576 at 25 fps
        width, height = 720, 576
        fps = "25"
        gop = 15
        sar = "8/7" if display_aspect == "4:3" else "64/45"

    m2v_path = vob_path.with_suffix(".m2v")
    lpcm_path = vob_path.with_suffix(".lpcm")
    duration = probe_duration(track)

    # 1) Encode the still image into a DVD-compliant MPEG-2 video elementary stream.
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(artwork),
            "-t",
            f"{duration:.6f}",
            "-r",
            fps,
            "-c:v",
            "mpeg2video",
            "-q:v",
            "4",
            # DVD VBV constraints keep the stream player-safe.
            "-maxrate",
            "9000000",
            "-bufsize",
            "1835008",
            "-g",
            str(gop),
            "-bf",
            "2",
            "-threads",
            "0",
            "-vf",
            f"scale={width}:{height},setsar={sar}",
            "-f",
            "mpeg2video",
            str(m2v_path),
        ]
    )

    # 2) Encode audio to raw big-endian PCM for mplex LPCM multiplexing.
    pcm_codec = "pcm_s16be" if target_bits == 16 else "pcm_s24be"
    pcm_format = "s16be" if target_bits == 16 else "s24be"
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(track),
            "-ar",
            str(target_samplerate),
            "-ac",
            "2",
            "-c:a",
            pcm_codec,
            "-f",
            pcm_format,
            str(lpcm_path),
        ]
    )

    # 3) Multiplex video + LPCM audio into a DVD VOB. ``-f 8`` (DVD with NAV
    # sectors) is required so dvdauthor can detect the first VOBU.
    try:
        run(
            [
                "mplex",
                "-f",
                "8",
                "-L",
                f"{target_samplerate}:2:{target_bits}",
                "-o",
                str(vob_path),
                str(m2v_path),
                str(lpcm_path),
            ]
        )
    finally:
        m2v_path.unlink(missing_ok=True)
        lpcm_path.unlink(missing_ok=True)


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
    placeholder_artwork: Path | None = None,
) -> tuple[Path, str]:
    vob_name = f"title{album_index:02d}_track{track_index:02d}.vob"
    vob_path = work_root / vob_name
    artwork = album.artwork if album.artwork is not None else placeholder_artwork
    _create_track_vob(track, artwork, vob_path, standard=standard, album_audio_info=album.audio_info)
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
    if standard not in {"ntsc", "pal"}:
        raise ValueError("DVD standard must be 'ntsc' or 'pal'")

    work_root = work_root or (output_dir.parent / ".dvd_work")
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    # Fallback image used for albums without cover art.
    placeholder_artwork = create_placeholder_artwork(work_root / ".black.jpg")

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
                    placeholder_artwork,
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
            raise RuntimeError(
                f"dvdauthor failed (exit {proc.returncode}).\n"
                f"See dvdauthor stdout/stderr in authoring logs for details."
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
            raise RuntimeError(
                "dvdauthor did not produce a valid VIDEO_TS directory. "
                "A VIDEO_TS folder with .IFO files is required. "
                "Check previous 'authoring' logs for errors."
            )

        if tracker:
            tracker.log("authoring", "Creating disc ISO with xorriso...")

        # Ensure VIDEO_TS contains a VIDEO_TS.IFO (VMG). Some dvdauthor setups produce only VTS_01_0.IFO.
        vts0 = video_ts / "VTS_01_0.IFO"
        vmg = video_ts / "VIDEO_TS.IFO"
        bup0 = video_ts / "VTS_01_0.BUP"
        vmg_bup = video_ts / "VIDEO_TS.BUP"
        try:
            if not vmg.exists() and vts0.exists():
                shutil.copy2(vts0, vmg)
                if bup0.exists():
                    shutil.copy2(bup0, vmg_bup)
                if tracker:
                    tracker.advance("authoring", "Created VIDEO_TS.IFO/VIDEO_TS.BUP from VTS_01_0 files for compatibility")
        except Exception as exc:
            if tracker:
                tracker.advance("authoring", f"Warning: failed to create VIDEO_TS.IFO: {exc}")

        iso_path = output_dir / "disc.iso"
        tmp_iso_path = output_dir.parent / f"{output_dir.name}.tmp.iso"
        if tmp_iso_path.exists():
            tmp_iso_path.unlink()

        # xorriso is the canonical ISO writer here; generate the ISO outside of the DVD tree to avoid self-scanning.
        # Use xorriso native actions: create an image file and map VIDEO_TS into it, then commit.
        # This avoids mkisofs emulation options that may not be supported in some xorriso builds.
        video_ts = output_dir / "VIDEO_TS"
        proc_iso = subprocess.run(
            [
                "xorriso",
                "-outdev",
                str(tmp_iso_path),
                "-volid",
                "DVD_VIDEO",
                "-map",
                str(video_ts),
                "VIDEO_TS",
                "-commit",
            ],
            cwd=output_dir.parent,
            capture_output=True,
            text=True,
        )

        if tracker:
            if proc_iso.stdout:
                tracker.advance("authoring", f"xorriso stdout: {proc_iso.stdout.strip()[:2000]}")
            if proc_iso.stderr:
                tracker.advance("authoring", f"xorriso stderr: {proc_iso.stderr.strip()[:2000]}")

        if proc_iso.returncode != 0:
            raise RuntimeError(
                f"xorriso failed (exit {proc_iso.returncode}).\n"
                f"See xorriso stdout/stderr in the authoring logs for details."
            )

        if tmp_iso_path.exists():
            if iso_path.exists():
                iso_path.unlink()
            shutil.move(str(tmp_iso_path), str(iso_path))

        if not iso_path.is_file() or iso_path.stat().st_size == 0:
            raise RuntimeError("xorriso completed without creating a usable ISO image")

        if tracker:
            size_mb = iso_path.stat().st_size / (1024 * 1024)
            tracker.advance("authoring", f"ISO created ({size_mb:.1f} MB): {iso_path}")

        return iso_path
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
