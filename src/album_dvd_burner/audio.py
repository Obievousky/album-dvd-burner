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


def probe_duration(path: Path) -> float:
    """Return the duration of an audio file in seconds."""
    output = run_capture(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(path),
        ]
    )
    data = json.loads(output)
    duration = data.get("format", {}).get("duration")
    if duration is None:
        raise ValueError(f"Could not determine duration for {path}")
    return float(duration)


_soxr_available_cache: bool | None = None


def soxr_available() -> bool:
    """True when this ffmpeg build has the soxr resampler compiled in."""
    global _soxr_available_cache
    if _soxr_available_cache is None:
        try:
            version = run_capture(["ffmpeg", "-hide_banner", "-version"])
            _soxr_available_cache = "--enable-libsoxr" in version
        except Exception:
            # ffmpeg missing or an unexpected build: fall back to the default resampler.
            _soxr_available_cache = False
    return _soxr_available_cache


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


def convert_album_to_48k(workspace: Path, tracker: ProgressTracker | None = None) -> Path:
    source_dir = album_source_dir(workspace)
    audio_files = list_audio_files(source_dir, recursive=True)
    if not audio_files:
        raise ValueError(f"No audio files found in {workspace}")

    infos = [probe_audio(path) for path in audio_files]

    # Pick the highest DVD-safe quality present across the album: 96 kHz when any
    # source is already above 48 kHz, otherwise 48 kHz; 24-bit when any source is
    # above 16-bit (e.g. 20- or 24-bit), otherwise 16-bit.
    target_sample_rate = 96000 if any(info.sample_rate > 48000 for info in infos) else 48000
    target_bit_depth = 24 if any(info.bit_depth > 16 for info in infos) else 16
    codec = "pcm_s24le" if target_bit_depth == 24 else "pcm_s16le"

    # Skip conversion only when every track is already homogeneous DVD-safe stereo.
    if all(
        info.sample_rate == target_sample_rate
        and info.bit_depth == target_bit_depth
        and info.channels == 2
        for info in infos
    ):
        if tracker:
            tracker.log(
                "preparing",
                f"No conversion needed for {workspace.name} "
                f"({target_bit_depth}-bit / {target_sample_rate // 1000} kHz stereo)",
            )
        return source_dir

    distinct_formats = {(info.sample_rate, info.bit_depth, info.channels) for info in infos}
    if len(distinct_formats) > 1 and tracker:
        tracker.log(
            "preparing",
            f"Normalizing mixed audio formats in {workspace.name} → "
            f"{target_bit_depth}-bit / {target_sample_rate // 1000} kHz stereo",
        )

    out_dir = converted_dir(workspace)
    out_dir.mkdir(parents=True, exist_ok=True)

    for index, src in enumerate(audio_files, start=1):
        dst = out_dir / f"{src.stem}.wav"
        if dst.exists():
            # Reuse the cached conversion only if it already matches the target.
            try:
                existing = probe_audio(dst)
            except Exception:
                existing = None
            if (
                existing is not None
                and existing.sample_rate == target_sample_rate
                and existing.bit_depth == target_bit_depth
                and existing.channels == 2
            ):
                if tracker:
                    tracker.log(
                        "preparing",
                        f"[{index}/{len(audio_files)}] Skipping existing conversion: {src.name}",
                    )
                continue

        if tracker:
            tracker.log(
                "preparing",
                f"[{index}/{len(audio_files)}] Converting to "
                f"{target_sample_rate // 1000} kHz / {target_bit_depth}-bit stereo: {src.name}",
            )

        # Use the high-quality soxr resampler when available, otherwise ffmpeg's
        # default (swr) engine, and force stereo output.
        resampler = "soxr" if soxr_available() else "swr"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-af",
            f"aresample=osr={target_sample_rate}:ochl=stereo:resampler={resampler}",
            "-acodec",
            codec,
            str(dst),
        ]

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
