import json
import glob
import os
import re
import subprocess
from functools import lru_cache
from typing import Any, Callable


class ConversionError(Exception):
    pass


SUPPORTED_VIDEO_EXTENSIONS_FOR_MP3 = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".flv",
    ".m4v",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".ts",
    ".m2ts",
}

MP3_QUALITY_ARGUMENTS: dict[str, list[str]] = {
    "balanced": ["-q:a", "2"],
    "cbr_192": ["-b:a", "192k"],
    "cbr_320": ["-b:a", "320k"],
}

CURATED_TARGET_ORDER = (
    "mp3",
    "m4a",
    "wav",
    "flac",
    "ogg",
    "opus",
    "mp4",
    "mkv",
    "webm",
    "mov",
    "png",
    "jpg",
)

CURATED_TARGETS: dict[str, dict[str, str]] = {
    "mp3": {
        "label": "MP3 (.mp3)",
        "kind": "audio",
        "extension": ".mp3",
        "audio_encoder": "libmp3lame",
    },
    "m4a": {
        "label": "M4A AAC (.m4a)",
        "kind": "audio",
        "extension": ".m4a",
        "audio_encoder": "aac",
    },
    "wav": {
        "label": "WAV PCM (.wav)",
        "kind": "audio",
        "extension": ".wav",
        "audio_encoder": "pcm_s16le",
    },
    "flac": {
        "label": "FLAC (.flac)",
        "kind": "audio",
        "extension": ".flac",
        "audio_encoder": "flac",
    },
    "ogg": {
        "label": "OGG Vorbis (.ogg)",
        "kind": "audio",
        "extension": ".ogg",
        "audio_encoder": "libvorbis",
    },
    "opus": {
        "label": "OPUS (.opus)",
        "kind": "audio",
        "extension": ".opus",
        "audio_encoder": "libopus",
    },
    "mp4": {
        "label": "MP4 H.264 + AAC (.mp4)",
        "kind": "video",
        "extension": ".mp4",
        "video_encoder": "libx264",
        "audio_encoder": "aac",
    },
    "mkv": {
        "label": "MKV H.264 + AAC (.mkv)",
        "kind": "video",
        "extension": ".mkv",
        "video_encoder": "libx264",
        "audio_encoder": "aac",
    },
    "webm": {
        "label": "WEBM VP9 + Opus (.webm)",
        "kind": "video",
        "extension": ".webm",
        "video_encoder": "libvpx-vp9",
        "audio_encoder": "libopus",
    },
    "mov": {
        "label": "MOV H.264 + AAC (.mov)",
        "kind": "video",
        "extension": ".mov",
        "video_encoder": "libx264",
        "audio_encoder": "aac",
    },
    "png": {
        "label": "PNG image sequence (.png)",
        "kind": "image",
        "extension": ".png",
        "video_encoder": "png",
    },
    "jpg": {
        "label": "JPG image sequence (.jpg)",
        "kind": "image",
        "extension": ".jpg",
        "video_encoder": "mjpeg",
    },
}

ConversionProgressCallback = Callable[[dict[str, Any]], None]


def _unique_output_path(source_path: str, output_dir: str, extension: str) -> str:
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    ext = extension if extension.startswith(".") else f".{extension}"
    candidate = os.path.join(output_dir, f"{base_name}{ext}")
    if not os.path.exists(candidate):
        return candidate

    suffix = 1
    while True:
        candidate = os.path.join(output_dir, f"{base_name} ({suffix}){ext}")
        if not os.path.exists(candidate):
            return candidate
        suffix += 1


def _friendly_copy_to_mp4_error(raw_error: str) -> str:
    normalized = raw_error.strip()
    if not normalized:
        return "FFmpeg failed with an unknown error."

    lowered = normalized.lower()
    if "could not write header" in lowered or "incorrect codec parameters" in lowered:
        return (
            "This MKV contains streams that MP4 cannot store without re-encoding. "
            "Conversion was stopped to keep quality untouched."
        )

    if "invalid data found" in lowered:
        return "Input file is invalid or corrupted."

    return normalized


def _friendly_video_to_mp3_error(raw_error: str) -> str:
    normalized = raw_error.strip()
    if not normalized:
        return "FFmpeg failed with an unknown error."

    lowered = normalized.lower()
    if "matches no streams" in lowered or "does not contain any stream" in lowered:
        return "Input video does not contain an audio track."

    if "unknown encoder 'libmp3lame'" in lowered:
        return "This FFmpeg build does not support MP3 encoding (libmp3lame is missing)."

    if "invalid data found" in lowered:
        return "Input file is invalid or corrupted."

    return normalized


def _friendly_probe_error(raw_error: str) -> str:
    normalized = raw_error.strip()
    if not normalized:
        return "Could not analyze this file with FFprobe."

    lowered = normalized.lower()
    if "invalid data found" in lowered:
        return "Input file is invalid or unsupported."

    return normalized


def _friendly_generic_conversion_error(raw_error: str) -> str:
    normalized = raw_error.strip()
    if not normalized:
        return "FFmpeg failed with an unknown error."

    lowered = normalized.lower()
    if "matches no streams" in lowered or "does not contain any stream" in lowered:
        return "Input file does not contain the required audio/video streams."

    if "unknown encoder" in lowered:
        return "This FFmpeg build does not support a required encoder for the selected format."

    if "invalid data found" in lowered:
        return "Input file is invalid or corrupted."

    return normalized


def _emit_conversion_progress(progress_callback: ConversionProgressCallback | None, event: dict[str, Any]) -> None:
    if progress_callback is not None:
        progress_callback(event)


def _parse_ffmpeg_time_to_seconds(value: str) -> float | None:
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None

    total_seconds = float(hours * 3600 + minutes * 60) + seconds
    if total_seconds < 0:
        return None
    return total_seconds


def _build_progress_command(command: list[str]) -> list[str]:
    if len(command) < 2:
        return list(command)

    output_path = command[-1]
    return [*command[:-1], "-nostats", "-progress", "pipe:1", output_path]


def _run_ffmpeg_with_progress(
    command: list[str],
    duration_seconds: float | None,
    progress_callback: ConversionProgressCallback | None,
) -> None:
    progress_command = _build_progress_command(command)

    try:
        process = subprocess.Popen(
            progress_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as err:
        raise ConversionError("FFmpeg was not found. Install FFmpeg and ensure ffmpeg is available in PATH.") from err
    except OSError as err:
        raise ConversionError(f"Could not start FFmpeg: {err}") from err

    _emit_conversion_progress(
        progress_callback,
        {
            "stage": "preparing",
            "percent": 0.0,
        },
    )

    latest_speed: str | None = None
    latest_time_seconds = 0.0
    last_emitted_percent = -1.0

    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line or "=" not in line:
                continue

            key, value = line.split("=", 1)
            if key == "out_time":
                parsed_seconds = _parse_ffmpeg_time_to_seconds(value)
                if parsed_seconds is not None:
                    latest_time_seconds = max(latest_time_seconds, parsed_seconds)
                continue

            if key == "speed":
                speed_value = value.strip()
                latest_speed = speed_value if speed_value else None
                continue

            if key != "progress":
                continue

            progress_state = value.strip().lower()
            if progress_state == "continue":
                percent: float | None = None
                if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
                    computed = latest_time_seconds / float(duration_seconds) * 100.0
                    percent = max(0.0, min(computed, 99.0))

                if isinstance(percent, float):
                    if percent < 99.0 and abs(percent - last_emitted_percent) < 0.2:
                        continue
                    last_emitted_percent = percent

                _emit_conversion_progress(
                    progress_callback,
                    {
                        "stage": "converting",
                        "percent": percent,
                        "speed": latest_speed,
                    },
                )
                continue

            if progress_state == "end":
                _emit_conversion_progress(
                    progress_callback,
                    {
                        "stage": "finalizing",
                        "percent": 99.0,
                    },
                )

    stderr_output = process.stderr.read() if process.stderr is not None else ""
    return_code = process.wait()
    if return_code != 0:
        raise ConversionError(_friendly_generic_conversion_error(stderr_output))

    _emit_conversion_progress(
        progress_callback,
        {
            "stage": "done",
            "percent": 100.0,
        },
    )


def _normalize_target_format(target_format: str) -> str:
    normalized = target_format.strip().lower()
    if normalized.startswith("."):
        normalized = normalized[1:]
    return normalized


@lru_cache(maxsize=1)
def _available_encoders() -> set[str] | None:
    command = ["ffmpeg", "-hide_banner", "-encoders"]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    if completed.returncode != 0:
        return None

    encoders: set[str] = set()
    encoder_line_pattern = re.compile(r"^\s*[A-Z.]{6}\s+([A-Za-z0-9_.-]+)")
    for line in completed.stdout.splitlines():
        match = encoder_line_pattern.match(line)
        if match is None:
            continue
        encoders.add(match.group(1))

    if not encoders:
        return None

    return encoders


def _is_encoder_available(encoder_name: str) -> bool:
    encoders = _available_encoders()
    if encoders is None:
        return True
    return encoder_name in encoders


def detect_source_media(source_path: str) -> dict[str, Any]:
    source_path = os.path.abspath(source_path)
    if not os.path.isfile(source_path):
        raise ConversionError("Source file does not exist.")

    source_extension = os.path.splitext(source_path)[1].lower()
    if source_extension == ".pdf":
        return {
            "source_path": source_path,
            "extension": source_extension,
            "has_audio": False,
            "has_video": False,
            "duration_seconds": None,
        }

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type:format=duration",
        "-of",
        "json",
        source_path,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as err:
        raise ConversionError("FFprobe was not found. Install FFmpeg and ensure ffprobe is available in PATH.") from err
    except OSError as err:
        raise ConversionError(f"Could not start FFprobe: {err}") from err

    if completed.returncode != 0:
        message = completed.stderr or completed.stdout
        raise ConversionError(_friendly_probe_error(message))

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as err:
        raise ConversionError("Could not parse FFprobe output.") from err

    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []

    duration_seconds: float | None = None
    raw_format = payload.get("format")
    if isinstance(raw_format, dict):
        raw_duration = raw_format.get("duration")
        if isinstance(raw_duration, str):
            try:
                parsed_duration = float(raw_duration)
            except ValueError:
                parsed_duration = 0.0
            if parsed_duration > 0:
                duration_seconds = parsed_duration

    has_audio = False
    has_video = False
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = stream.get("codec_type")
        if codec_type == "audio":
            has_audio = True
        elif codec_type == "video":
            has_video = True

    return {
        "source_path": source_path,
        "extension": source_extension,
        "has_audio": has_audio,
        "has_video": has_video,
        "duration_seconds": duration_seconds,
    }


def get_available_conversion_targets(source_path: str) -> list[tuple[str, str]]:
    source_info = detect_source_media(source_path)
    source_extension = str(source_info["extension"])
    has_audio = bool(source_info["has_audio"])
    has_video = bool(source_info["has_video"])

    if source_extension == ".pdf":
        result: list[tuple[str, str]] = []
        for target_format in CURATED_TARGET_ORDER:
            target_info = CURATED_TARGETS[target_format]
            if target_info["kind"] != "image":
                continue

            image_encoder = target_info.get("video_encoder")
            if image_encoder and not _is_encoder_available(image_encoder):
                continue

            result.append((target_format, target_info["label"]))
        return result

    if not has_audio and not has_video:
        return []

    result: list[tuple[str, str]] = []
    for target_format in CURATED_TARGET_ORDER:
        target_info = CURATED_TARGETS[target_format]
        target_extension = target_info["extension"]
        target_kind = target_info["kind"]

        if source_extension == target_extension:
            continue

        if target_kind == "audio" and not has_audio:
            continue

        if target_kind == "video" and not has_video:
            continue

        if target_kind == "image":
            continue

        video_encoder = target_info.get("video_encoder")
        if video_encoder and not _is_encoder_available(video_encoder):
            continue

        audio_encoder = target_info.get("audio_encoder")
        if audio_encoder and target_kind == "audio" and not _is_encoder_available(audio_encoder):
            continue

        if audio_encoder and target_kind == "video" and has_audio and not _is_encoder_available(audio_encoder):
            continue

        result.append((target_format, target_info["label"]))

    return result


def _build_audio_conversion_command(
    source_path: str,
    output_path: str,
    target_format: str,
    mp3_quality_preset: str,
) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        source_path,
        "-map",
        "0:a:0",
        "-vn",
    ]

    if target_format == "mp3":
        quality_args = MP3_QUALITY_ARGUMENTS.get(mp3_quality_preset)
        if quality_args is None:
            raise ConversionError("Unsupported MP3 quality preset.")
        command.extend(["-c:a", "libmp3lame", *quality_args, output_path])
        return command

    if target_format == "m4a":
        command.extend(["-c:a", "aac", "-b:a", "192k", output_path])
        return command

    if target_format == "wav":
        command.extend(["-c:a", "pcm_s16le", output_path])
        return command

    if target_format == "flac":
        command.extend(["-c:a", "flac", output_path])
        return command

    if target_format == "ogg":
        command.extend(["-c:a", "libvorbis", "-q:a", "5", output_path])
        return command

    if target_format == "opus":
        command.extend(["-c:a", "libopus", "-b:a", "160k", output_path])
        return command

    raise ConversionError("Unsupported target format.")


def _build_video_conversion_command(
    source_path: str,
    output_path: str,
    target_format: str,
    has_audio: bool,
) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        source_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]

    if target_format in {"mp4", "mkv", "mov"}:
        command.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "20"])
        if has_audio:
            command.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            command.append("-an")
        if target_format in {"mp4", "mov"}:
            command.extend(["-movflags", "+faststart"])
        command.append(output_path)
        return command

    if target_format == "webm":
        command.extend(["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "31", "-deadline", "good"])
        if has_audio:
            command.extend(["-c:a", "libopus", "-b:a", "160k"])
        else:
            command.append("-an")
        command.append(output_path)
        return command

    raise ConversionError("Unsupported target format.")


def _build_pdf_output_pattern(source_path: str, output_dir: str, extension: str) -> str:
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    ext = extension if extension.startswith(".") else f".{extension}"

    suffix = 0
    while True:
        suffix_label = "" if suffix == 0 else f" ({suffix})"
        prefix = f"{base_name}{suffix_label} - page "
        wildcard = os.path.join(output_dir, f"{prefix}*{ext}")
        if not glob.glob(wildcard):
            return os.path.join(output_dir, f"{prefix}%03d{ext}")
        suffix += 1


def _collect_sequence_outputs(output_pattern: str) -> list[str]:
    wildcard = re.sub(r"%0?\d*d", "*", output_pattern)
    return sorted(glob.glob(wildcard))


def _render_sequence_output_path(output_pattern: str, index: int) -> str:
    match = re.search(r"%0?(\d*)d", output_pattern)
    if match is None:
        return output_pattern

    width_text = match.group(1)
    width = int(width_text) if width_text else 0
    replacement = f"{index:0{width}d}" if width > 0 else str(index)
    return f"{output_pattern[:match.start()]}{replacement}{output_pattern[match.end():]}"


def _safe_close(value: Any) -> None:
    close_method = getattr(value, "close", None)
    if callable(close_method):
        close_method()


def _convert_pdf_to_images_with_pdfium(
    source_path: str,
    output_pattern: str,
    target_format: str,
    progress_callback: ConversionProgressCallback | None,
) -> list[str] | None:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except Exception:
        return None

    try:
        document = pdfium.PdfDocument(source_path)
    except Exception as err:
        raise ConversionError(f"Could not open PDF file: {err}") from err

    try:
        page_count = len(document)
        if page_count <= 0:
            raise ConversionError("PDF file does not contain any pages.")

        _emit_conversion_progress(
            progress_callback,
            {
                "stage": "preparing",
                "percent": 0.0,
            },
        )

        output_files: list[str] = []
        for page_index in range(page_count):
            page = document[page_index]
            bitmap = page.render(scale=2.0)
            image = bitmap.to_pil()
            save_image = image
            output_path = _render_sequence_output_path(output_pattern, page_index + 1)
            try:
                if target_format == "jpg":
                    if save_image.mode != "RGB":
                        save_image = save_image.convert("RGB")
                    save_image.save(output_path, format="JPEG", quality=95)
                else:
                    save_image.save(output_path, format="PNG")
            finally:
                if save_image is not image:
                    _safe_close(save_image)
                _safe_close(image)
                _safe_close(bitmap)
                _safe_close(page)

            output_files.append(output_path)
            _emit_conversion_progress(
                progress_callback,
                {
                    "stage": "converting",
                    "percent": min((page_index + 1) / page_count * 100.0, 99.0),
                },
            )

        _emit_conversion_progress(
            progress_callback,
            {
                "stage": "finalizing",
                "percent": 99.0,
            },
        )
        _emit_conversion_progress(
            progress_callback,
            {
                "stage": "done",
                "percent": 100.0,
            },
        )
        return output_files
    finally:
        _safe_close(document)


def _build_pdf_conversion_command(source_path: str, output_pattern: str, target_format: str) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        source_path,
        "-map",
        "0:v",
        "-start_number",
        "1",
    ]

    if target_format == "png":
        command.extend(["-c:v", "png", output_pattern])
        return command

    if target_format == "jpg":
        command.extend(["-c:v", "mjpeg", "-q:v", "2", output_pattern])
        return command

    raise ConversionError("Unsupported PDF image format.")


def _convert_pdf_to_images(
    source_path: str,
    output_dir: str,
    target_format: str,
    progress_callback: ConversionProgressCallback | None,
) -> list[str]:
    target_info = CURATED_TARGETS.get(target_format)
    if target_info is None:
        raise ConversionError("Unsupported target format.")

    target_extension = target_info["extension"]
    output_pattern = _build_pdf_output_pattern(source_path, output_dir, target_extension)
    pdfium_output = _convert_pdf_to_images_with_pdfium(
        source_path=source_path,
        output_pattern=output_pattern,
        target_format=target_format,
        progress_callback=progress_callback,
    )
    if pdfium_output is not None:
        if not pdfium_output:
            raise ConversionError("PDF conversion finished, but no output images were created.")
        return pdfium_output

    command = _build_pdf_conversion_command(source_path, output_pattern, target_format)
    try:
        _run_ffmpeg_with_progress(
            command=command,
            duration_seconds=None,
            progress_callback=progress_callback,
        )
    except ConversionError as err:
        lowered = str(err).lower()
        if "invalid or corrupted" in lowered or "required audio/video streams" in lowered:
            raise ConversionError(
                "Could not render PDF pages. Install pypdfium2 (`pip install pypdfium2`) "
                "or use an FFmpeg build with PDF support."
            ) from err
        raise

    output_files = _collect_sequence_outputs(output_pattern)
    if not output_files:
        raise ConversionError("PDF conversion finished, but no output images were created.")

    return output_files


def convert_media(
    source_path: str,
    output_dir: str,
    target_format: str,
    mp3_quality_preset: str = "balanced",
    progress_callback: ConversionProgressCallback | None = None,
) -> str | list[str]:
    normalized_target = _normalize_target_format(target_format)
    target_info = CURATED_TARGETS.get(normalized_target)
    if target_info is None:
        raise ConversionError("Unsupported target format.")

    source_info = detect_source_media(source_path)
    source_path = str(source_info["source_path"])
    source_extension = str(source_info["extension"])
    has_audio = bool(source_info["has_audio"])
    has_video = bool(source_info["has_video"])
    duration_seconds_raw = source_info.get("duration_seconds")
    duration_seconds = duration_seconds_raw if isinstance(duration_seconds_raw, (int, float)) else None

    target_kind = target_info["kind"]
    target_extension = target_info["extension"]
    if source_extension == target_extension:
        raise ConversionError("Source file already has this format.")

    if target_kind == "image":
        if source_extension != ".pdf":
            raise ConversionError("Image conversion is currently supported only for PDF files.")

        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        return _convert_pdf_to_images(
            source_path=source_path,
            output_dir=output_dir,
            target_format=normalized_target,
            progress_callback=progress_callback,
        )

    if not has_audio and not has_video:
        raise ConversionError("Source file is not supported for conversion.")

    if target_kind == "audio" and not has_audio:
        raise ConversionError("Source file does not contain an audio stream.")

    if target_kind == "video" and not has_video:
        raise ConversionError("Source file does not contain a video stream.")

    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    output_path = _unique_output_path(source_path, output_dir, target_extension)

    if target_kind == "audio":
        command = _build_audio_conversion_command(
            source_path=source_path,
            output_path=output_path,
            target_format=normalized_target,
            mp3_quality_preset=mp3_quality_preset,
        )
    else:
        command = _build_video_conversion_command(
            source_path=source_path,
            output_path=output_path,
            target_format=normalized_target,
            has_audio=has_audio,
        )

    _run_ffmpeg_with_progress(
        command=command,
        duration_seconds=duration_seconds,
        progress_callback=progress_callback,
    )

    return output_path


def convert_mkv_to_mp4(source_path: str, output_dir: str) -> str:
    source_path = os.path.abspath(source_path)
    output_dir = os.path.abspath(output_dir)

    if not os.path.isfile(source_path):
        raise ConversionError("Source file does not exist.")

    if not source_path.lower().endswith(".mkv"):
        raise ConversionError("Source file must be an .mkv video.")

    os.makedirs(output_dir, exist_ok=True)
    output_path = _unique_output_path(source_path, output_dir, ".mp4")

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        source_path,
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-c",
        "copy",
        output_path,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as err:
        raise ConversionError("FFmpeg was not found. Install FFmpeg and ensure ffmpeg is available in PATH.") from err
    except OSError as err:
        raise ConversionError(f"Could not start FFmpeg: {err}") from err

    if completed.returncode != 0:
        message = completed.stderr or completed.stdout
        raise ConversionError(_friendly_copy_to_mp4_error(message))

    return output_path


def convert_video_to_mp3(source_path: str, output_dir: str, quality_preset: str = "balanced") -> str:
    source_path = os.path.abspath(source_path)
    output_dir = os.path.abspath(output_dir)

    if not os.path.isfile(source_path):
        raise ConversionError("Source file does not exist.")

    source_ext = os.path.splitext(source_path)[1].lower()
    if source_ext not in SUPPORTED_VIDEO_EXTENSIONS_FOR_MP3:
        raise ConversionError("Source file must be a supported video file (for example .mp4 or .mkv).")

    quality_args = MP3_QUALITY_ARGUMENTS.get(quality_preset)
    if quality_args is None:
        raise ConversionError("Unsupported MP3 quality preset.")

    os.makedirs(output_dir, exist_ok=True)
    output_path = _unique_output_path(source_path, output_dir, ".mp3")

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        source_path,
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "libmp3lame",
        *quality_args,
        output_path,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as err:
        raise ConversionError("FFmpeg was not found. Install FFmpeg and ensure ffmpeg is available in PATH.") from err
    except OSError as err:
        raise ConversionError(f"Could not start FFmpeg: {err}") from err

    if completed.returncode != 0:
        message = completed.stderr or completed.stdout
        raise ConversionError(_friendly_video_to_mp3_error(message))

    return output_path
