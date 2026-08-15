import json
from dataclasses import dataclass
from pathlib import Path

from .progress import ProgressTracker
from .workspaces import album_source_dir, converted_dir
from .utils import list_audio_files, run, run_capture


@dataclass(frozen=True)
class AudioInfo:
    sample_rate: int
    bit_depth: int
    channels: int
    codec: str


def probe_audio(path: Path) -> AudioInfo:
    output = run_capture(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            str(path),
        ]
    )
    data = json.loads(output)
    stream = next(s for s in data["streams"] if s["codec_type"] == "audio")
    bit_depth = int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 16)
    return AudioInfo(
        sample_rate=int(stream["sample_rate"]),
        bit_depth=bit_depth,
        channels=int(stream["channels"]),
        codec=stream["codec_name"],
    )


def needs_conversion(info: AudioInfo) -> bool:
    # Convert when source is 44.1 kHz (typical CD) — preserve higher sample rates
    return info.sample_rate == 44100


def convert_album_to_48k(workspace: Path, tracker: ProgressTracker | None = None) -> Path:
    source_dir = album_source_dir(workspace)
    audio_files = list_audio_files(source_dir, recursive=True)
    if not audio_files:
        raise ValueError(f"No audio files found in {workspace}")

    first = probe_audio(audio_files[0])
    if not needs_conversion(first):
        if tracker:
            tracker.log("preparing", f"No conversion needed for {workspace.name} (already DVD-ready)")
        return source_dir

    for path in audio_files[1:]:
        info = probe_audio(path)
        if info.sample_rate != first.sample_rate or info.bit_depth != first.bit_depth:
            raise ValueError(
                f"Mixed audio formats in {workspace}: {first} vs {info} ({path.name})"
            )

    out_dir = converted_dir(workspace)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Choose the best reasonable target bit depth: if source is 24-bit or higher, keep 24-bit
    target_bit_depth = 24 if first.bit_depth >= 24 else 16
    codec = "pcm_s24le" if target_bit_depth == 24 else "pcm_s16le"

    for index, src in enumerate(audio_files, start=1):
        dst = out_dir / f"{src.stem}.wav"
        if dst.exists():
            if tracker:
                tracker.log(
                    "preparing",
                    f"[{index}/{len(audio_files)}] Skipping existing conversion: {src.name}",
                )
            continue

        if tracker:
            tracker.log(
                "preparing",
                f"[{index}/{len(audio_files)}] Converting {first.sample_rate // 1000}→48 kHz ({target_bit_depth}-bit): {src.name}",
            )

        # Use high-quality resampler (soxr) when available
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-ar",
            "48000",
            "-acodec",
            codec,
        ]
        # Use aresample filter with soxr if ffmpeg supports it — improves quality
        cmd.extend(["-af", "aresample=resampler=soxr"])
        cmd.append(str(dst))

        run(cmd)

    if tracker:
        tracker.log("preparing", f"Converted audio saved to {out_dir.name}/")

    return out_dir


def prepare_album_audio(
    workspace: Path,
    tracker: ProgressTracker | None = None,
) -> tuple[Path, list[Path], AudioInfo]:
    """Return working folder, ordered tracks, and final audio info."""
    work_dir = convert_album_to_48k(workspace, tracker)
    tracks = list_audio_files(work_dir, recursive=True)
    if not tracks:
        raise ValueError(f"No audio files available after conversion in {workspace}")

    info = probe_audio(tracks[0])
    if info.sample_rate not in (48000, 96000):
        raise ValueError(
            f"DVD requires 48 kHz or 96 kHz audio; got {info.sample_rate} Hz in {workspace}"
        )
    if info.bit_depth not in (16, 24):
        raise ValueError(f"DVD requires 16- or 24-bit audio; got {info.bit_depth}-bit")

    for track in tracks[1:]:
        other = probe_audio(track)
        if (
            other.sample_rate != info.sample_rate
            or other.bit_depth != info.bit_depth
            or other.channels != info.channels
        ):
            raise ValueError(f"Inconsistent audio within album {workspace}: {track.name}")

    if tracker:
        tracker.log(
            "preparing",
            f"Album ready: {len(tracks)} tracks, {info.bit_depth}-bit / {info.sample_rate // 1000} kHz",
        )

    return work_dir, tracks, info
