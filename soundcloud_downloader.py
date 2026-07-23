import os
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


ProgressCallback = Callable[[dict[str, Any]], None]

SOUNDCLOUD_AUDIO_FORMATS: tuple[tuple[str, str], ...] = (
    ("mp3", "MP3 (.mp3)"),
    ("m4a", "M4A AAC (.m4a)"),
    ("wav", "WAV PCM (.wav)"),
    ("flac", "FLAC (.flac)"),
    ("ogg", "OGG Vorbis (.ogg)"),
    ("opus", "OPUS (.opus)"),
)

YTDLP_AUDIO_CODECS: dict[str, str] = {
    "mp3": "mp3",
    "m4a": "m4a",
    "wav": "wav",
    "flac": "flac",
    "ogg": "vorbis",
    "opus": "opus",
}


def _emit_progress(progress_callback: ProgressCallback | None, event: dict[str, Any]) -> None:
    if progress_callback is not None:
        progress_callback(event)


def _parse_download_percent(progress_info: dict[str, Any]) -> float | None:
    downloaded = progress_info.get("downloaded_bytes")
    total = progress_info.get("total_bytes") or progress_info.get("total_bytes_estimate")
    if isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total > 0:
        percent = float(downloaded) / float(total) * 100.0
        if percent < 0:
            return 0.0
        if percent > 100:
            return 100.0
        return percent
    return None


def _normalize_soundcloud_url(url: str) -> str:
    normalized = url.strip()
    if not normalized:
        raise DownloadError("SoundCloud URL is empty.")

    parsed = urlparse(normalized)
    if not parsed.scheme:
        normalized = f"https://{normalized}"
        parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"}:
        raise DownloadError("Only HTTP and HTTPS SoundCloud URLs are supported.")

    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    if hostname != "soundcloud.com" and not hostname.endswith(".soundcloud.com"):
        raise DownloadError("Only soundcloud.com links are supported.")

    return normalized


def _normalize_target_format(target_format: str) -> str:
    normalized = target_format.strip().lower()
    if normalized.startswith("."):
        normalized = normalized[1:]
    if normalized not in YTDLP_AUDIO_CODECS:
        raise DownloadError("Unsupported SoundCloud audio format.")
    return normalized


def _normalize_reported_path(path: str) -> str:
    normalized = path.strip()
    if normalized.startswith("file://"):
        parsed = urlparse(normalized)
        normalized = unquote(parsed.path)
        if os.name == "nt" and len(normalized) >= 3 and normalized[0] == "/" and normalized[2] == ":":
            normalized = normalized[1:]
    return os.path.abspath(normalized)


def _build_progress_hook(progress_callback: ProgressCallback | None) -> Callable[[dict[str, Any]], None]:
    def _hook(progress_info: dict[str, Any]) -> None:
        status = progress_info.get("status")
        if status == "downloading":
            _emit_progress(
                progress_callback,
                {
                    "event": "downloading",
                    "percent": _parse_download_percent(progress_info),
                    "downloaded_bytes": progress_info.get("downloaded_bytes"),
                    "total_bytes": progress_info.get("total_bytes") or progress_info.get("total_bytes_estimate"),
                    "speed": progress_info.get("speed"),
                    "eta": progress_info.get("eta"),
                    "filename": progress_info.get("filename"),
                },
            )
            return

        if status == "finished":
            _emit_progress(
                progress_callback,
                {
                    "event": "processing",
                    "message": "Download complete, converting audio...",
                    "filename": progress_info.get("filename"),
                },
            )

    return _hook


def _build_postprocessor_hook(
    progress_callback: ProgressCallback | None,
    output_paths: list[str],
) -> Callable[[dict[str, Any]], None]:
    def _hook(progress_info: dict[str, Any]) -> None:
        status = str(progress_info.get("status", "")).strip().lower()
        postprocessor = str(progress_info.get("postprocessor", "")).strip()
        info_dict = progress_info.get("info_dict")
        if not isinstance(info_dict, dict):
            info_dict = {}

        if status in {"started", "processing"}:
            _emit_progress(
                progress_callback,
                {
                    "event": "processing",
                    "message": f"{postprocessor or 'Post-processing'}...",
                    "postprocessor": postprocessor,
                },
            )
            return

        if status != "finished":
            return

        raw_path = info_dict.get("filepath")
        if isinstance(raw_path, str) and raw_path.strip():
            path = _normalize_reported_path(raw_path)
            if os.path.isfile(path) and path not in output_paths:
                output_paths.append(path)
                _emit_progress(
                    progress_callback,
                    {
                        "event": "item_finished",
                        "path": path,
                        "title": info_dict.get("title"),
                    },
                )

        _emit_progress(
            progress_callback,
            {
                "event": "processing",
                "message": f"{postprocessor or 'Post-processing'} complete.",
                "postprocessor": postprocessor,
            },
        )

    return _hook


def _ydl_opts(
    out_dir: str,
    target_format: str,
    output_paths: list[str],
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    codec = YTDLP_AUDIO_CODECS[target_format]
    opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "noplaylist": False,
        "quiet": False,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "continuedl": True,
        "overwrites": False,
        "keepvideo": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": "192",
            }
        ],
        "progress_hooks": [_build_progress_hook(progress_callback)],
        "postprocessor_hooks": [_build_postprocessor_hook(progress_callback, output_paths)],
    }
    return opts


def download_soundcloud_audio(
    url: str,
    out_dir: str,
    target_format: str,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    normalized_url = _normalize_soundcloud_url(url)
    normalized_format = _normalize_target_format(target_format)
    output_dir = os.path.abspath(out_dir)
    os.makedirs(output_dir, exist_ok=True)

    output_paths: list[str] = []
    _emit_progress(progress_callback, {"event": "processing", "message": "Preparing SoundCloud download..."})

    opts = _ydl_opts(
        out_dir=output_dir,
        target_format=normalized_format,
        output_paths=output_paths,
        progress_callback=progress_callback,
    )
    with YoutubeDL(opts) as ydl:
        ydl.download([normalized_url])

    if not output_paths:
        raise DownloadError("Download finished, but no audio files were reported.")

    _emit_progress(progress_callback, {"event": "done", "paths": list(output_paths)})
    return output_paths
