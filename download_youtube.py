import argparse
import os
import shutil
from typing import Any, Callable, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


MAX_QUALITY_FORMAT = "bv*+ba/bestvideo*+bestaudio/best"
COMPAT_FALLBACK_FORMAT = "best[ext=mp4]/best"
PROBE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
ProgressCallback = Callable[[dict[str, Any]], None]
OPTIONAL_NONE_VALUES = {"", "none", "null", "nil", "no", "-"}


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if normalized.lower() in OPTIONAL_NONE_VALUES:
        return None

    return normalized


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


def _build_progress_hook(progress_callback: ProgressCallback | None, active_height: int) -> Callable[[dict[str, Any]], None]:
    def _hook(progress_info: dict[str, Any]) -> None:
        status = progress_info.get("status")
        if status == "downloading":
            _emit_progress(
                progress_callback,
                {
                    "event": "downloading",
                    "height": active_height,
                    "percent": _parse_download_percent(progress_info),
                    "downloaded_bytes": progress_info.get("downloaded_bytes"),
                    "total_bytes": progress_info.get("total_bytes") or progress_info.get("total_bytes_estimate"),
                    "speed": progress_info.get("speed"),
                    "eta": progress_info.get("eta"),
                },
            )
            return

        if status == "finished":
            _emit_progress(
                progress_callback,
                {
                    "event": "processing",
                    "height": active_height,
                    "message": "Download complete, finalizing file...",
                    "filename": progress_info.get("filename"),
                },
            )

    return _hook


def _is_retryable_download_error(err: DownloadError) -> bool:
    message_lower = str(err).lower()
    retryable_markers = (
        "http error 403: forbidden",
        "requested format is not available",
        "the downloaded file is empty",
        "downloaded file is empty",
        "unable to download video data",
        "fragment not found",
        "hls",
    )
    return any(marker in message_lower for marker in retryable_markers)


def _build_js_runtimes() -> dict[str, dict[str, str]]:
    runtimes: dict[str, dict[str, str]] = {}

    node_path = shutil.which("node")
    if node_path:
        runtimes["node"] = {"path": node_path}

    deno_path = shutil.which("deno")
    if deno_path:
        runtimes["deno"] = {"path": deno_path}

    return runtimes


def _build_extractor_args(po_token: str | None) -> dict[str, Any] | None:
    token = _normalize_optional_string(po_token)
    if token is None:
        return None

    if ".gvs+" not in token:
        token = f"web.gvs+{token}"

    return {
        "youtube": {
            "po_token": [token],
        }
    }


def _build_cookie_tuple(browser: str | None, profile: str | None) -> tuple[str, str | None, None, None] | None:
    browser = _normalize_optional_string(browser)
    profile = _normalize_optional_string(profile)
    if not browser:
        return None
    return (browser, profile, None, None)


def _apply_optional_extractor_opts(
    opts: dict[str, Any],
    cookies_browser: str | None,
    cookies_profile: str | None,
    po_token: str | None,
) -> None:
    js_runtimes = _build_js_runtimes()
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes

    extractor_args = _build_extractor_args(po_token)
    if extractor_args is not None:
        opts["extractor_args"] = extractor_args

    cookie_tuple = _build_cookie_tuple(cookies_browser, cookies_profile)
    if cookie_tuple is not None:
        opts["cookiesfrombrowser"] = cookie_tuple


def _ydl_opts(
    out_dir: str,
    format_selector: str,
    source_address: str | None = None,
    http_chunk_size: int | None = None,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
    progress_hooks: list[Callable[[dict[str, Any]], None]] | None = None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "format": format_selector,
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
        "noplaylist": True,
        "quiet": False,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 2,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "continuedl": True,
        "overwrites": False,
        "concurrent_fragment_downloads": 1,
    }

    _apply_optional_extractor_opts(
        opts,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
    )

    if source_address is not None:
        opts["source_address"] = source_address
    if http_chunk_size is not None:
        opts["http_chunk_size"] = http_chunk_size
    if progress_hooks:
        opts["progress_hooks"] = progress_hooks

    return opts


def _download_with_attempts(
    url: str,
    out_dir: str,
    attempts: list[tuple[str, str, str | None, int | None]],
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
    progress_hooks: list[Callable[[dict[str, Any]], None]] | None = None,
) -> None:
    os.makedirs(out_dir, exist_ok=True)

    last_error: DownloadError | None = None
    for attempt_index, (attempt_name, format_selector, source_address, chunk_size) in enumerate(attempts, start=1):
        opts = _ydl_opts(
            out_dir=out_dir,
            format_selector=format_selector,
            source_address=source_address,
            http_chunk_size=chunk_size,
            cookies_browser=cookies_browser,
            cookies_profile=cookies_profile,
            po_token=po_token,
            progress_hooks=progress_hooks,
        )

        try:
            with YoutubeDL(cast(Any, opts)) as ydl:
                ydl.download([url])
                return
        except DownloadError as err:
            last_error = err
            is_retryable = _is_retryable_download_error(err)
            has_next_attempt = attempt_index < len(attempts)

            if is_retryable and has_next_attempt:
                print(f"[retry] transient error in profile '{attempt_name}'. Trying next profile...")
                continue

            raise

    if last_error is not None:
        raise last_error


def _download_with_selector_fallbacks(
    url: str,
    out_dir: str,
    selectors: list[str],
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
    progress_hooks: list[Callable[[dict[str, Any]], None]] | None = None,
    progress_callback: ProgressCallback | None = None,
    include_network_profiles: bool = True,
) -> None:
    if not selectors:
        raise DownloadError("No downloadable format selector was found.")

    last_error: DownloadError | None = None
    for selector_index, selector in enumerate(selectors, start=1):
        attempts: list[tuple[str, str, str | None, int | None]] = [("default", selector, None, None)]
        if include_network_profiles:
            attempts.extend([
                ("ipv4_10mb_chunks", selector, "0.0.0.0", 10 * 1024 * 1024),
                ("ipv4_1mb_chunks", selector, "0.0.0.0", 1 * 1024 * 1024),
            ])

        try:
            _download_with_attempts(
                url=url,
                out_dir=out_dir,
                attempts=attempts,
                cookies_browser=cookies_browser,
                cookies_profile=cookies_profile,
                po_token=po_token,
                progress_hooks=progress_hooks,
            )
            return
        except DownloadError as err:
            last_error = err
            has_next_selector = selector_index < len(selectors)
            if has_next_selector and _is_retryable_download_error(err):
                _emit_progress(
                    progress_callback,
                    {
                        "event": "retry",
                        "message": "Selected stream failed, trying a fallback stream...",
                    },
                )
                print("[retry] Selected format failed. Trying next format fallback...")
                continue

            raise

    if last_error is not None:
        raise last_error


def download(
    url: str,
    out_dir: str = ".",
    compat_fallback: bool = False,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
):
    attempts = [
        ("default", MAX_QUALITY_FORMAT, None, None),
        ("ipv4_10mb_chunks", MAX_QUALITY_FORMAT, "0.0.0.0", 10 * 1024 * 1024),
        ("ipv4_1mb_chunks", MAX_QUALITY_FORMAT, "0.0.0.0", 1 * 1024 * 1024),
    ]

    if compat_fallback:
        attempts.append(("compat_fallback", COMPAT_FALLBACK_FORMAT, "0.0.0.0", 1 * 1024 * 1024))

    _download_with_attempts(
        url=url,
        out_dir=out_dir,
        attempts=attempts,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
    )


def _extract_video_info(
    url: str,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
    format_selector: str | None = None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    if format_selector:
        opts["format"] = format_selector

    _apply_optional_extractor_opts(
        opts,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
    )

    with YoutubeDL(cast(Any, opts)) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise DownloadError("Could not analyze video metadata.")

    entries = info.get("entries")
    if entries and not info.get("formats"):
        for entry in cast(Any, entries):
            if isinstance(entry, dict):
                return entry
        raise DownloadError("No downloadable entries found for this URL.")

    return cast(dict[str, Any], info)


def _is_drm_format(format_info: dict[str, Any]) -> bool:
    has_drm = format_info.get("has_drm")
    if isinstance(has_drm, bool) and has_drm:
        return True

    format_note = format_info.get("format_note")
    if isinstance(format_note, str) and "drm" in format_note.lower():
        return True

    return False


def _is_audio_only_format(format_info: dict[str, Any]) -> bool:
    vcodec = format_info.get("vcodec")
    acodec = format_info.get("acodec")
    return vcodec in (None, "none") and isinstance(acodec, str) and acodec != "none"


def _is_video_format(format_info: dict[str, Any]) -> bool:
    vcodec = format_info.get("vcodec")
    return isinstance(vcodec, str) and vcodec != "none"


def _selected_video_height(info: dict[str, Any]) -> int | None:
    height = info.get("height")
    if isinstance(height, int) and height > 0:
        return height

    requested_formats = info.get("requested_formats")
    if isinstance(requested_formats, list):
        requested_heights = [
            format_info.get("height")
            for format_info in requested_formats
            if isinstance(format_info, dict) and _is_video_format(format_info)
        ]
        valid_requested_heights = [height for height in requested_heights if isinstance(height, int) and height > 0]
        if valid_requested_heights:
            return max(valid_requested_heights)

    raw_formats = info.get("formats")
    if isinstance(raw_formats, list):
        format_heights = [
            format_info.get("height")
            for format_info in raw_formats
            if isinstance(format_info, dict) and _is_usable_format(format_info) and _is_video_format(format_info)
        ]
        valid_format_heights = [height for height in format_heights if isinstance(height, int) and height > 0]
        if valid_format_heights:
            return max(valid_format_heights)

    return None


def _is_video_only_format(format_info: dict[str, Any]) -> bool:
    return _is_video_format(format_info) and format_info.get("acodec") in (None, "none")


def _is_progressive_video_format(format_info: dict[str, Any]) -> bool:
    if not _is_video_format(format_info):
        return False
    acodec = format_info.get("acodec")
    return isinstance(acodec, str) and acodec != "none"


def _is_usable_format(format_info: dict[str, Any]) -> bool:
    if _is_drm_format(format_info):
        return False
    if str(format_info.get("ext", "")).lower() == "mhtml":
        return False
    return True


def _numeric(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _video_sort_key(format_info: dict[str, Any]) -> tuple[int, int, int, float, float]:
    ext = str(format_info.get("ext", "")).lower()
    format_id = str(format_info.get("format_id", ""))
    vcodec = str(format_info.get("vcodec", "")).lower()
    return (
        0 if ext == "mp4" else 1,
        0 if "av01" not in vcodec else 1,
        0 if "-drc" not in format_id else 1,
        -_numeric(format_info.get("tbr")),
        -_numeric(format_info.get("fps")),
    )


def _audio_sort_key(format_info: dict[str, Any]) -> tuple[int, int, float]:
    ext = str(format_info.get("ext", "")).lower()
    format_id = str(format_info.get("format_id", ""))
    abr_or_tbr = _numeric(format_info.get("abr"))
    if abr_or_tbr == 0:
        abr_or_tbr = _numeric(format_info.get("tbr"))
    return (
        0 if ext in ("m4a", "mp4") else 1,
        0 if "-drc" not in format_id else 1,
        -abr_or_tbr,
    )


def _progressive_sort_key(format_info: dict[str, Any]) -> tuple[int, int, float, float]:
    ext = str(format_info.get("ext", "")).lower()
    format_id = str(format_info.get("format_id", ""))
    return (
        0 if ext == "mp4" else 1,
        0 if "-drc" not in format_id else 1,
        -_numeric(format_info.get("tbr")),
        -_numeric(format_info.get("fps")),
    )


def _dedupe_selectors(selectors: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        result.append(selector)
    return result


def _build_format_index(formats: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for format_info in formats:
        format_id = format_info.get("format_id")
        if isinstance(format_id, str) and format_id not in index:
            index[format_id] = format_info
    return index


def _build_height_candidate_selectors(formats: list[dict[str, Any]], height: int) -> list[str]:
    video_only = [
        fmt
        for fmt in formats
        if _is_usable_format(fmt)
        and _is_video_only_format(fmt)
        and isinstance(fmt.get("height"), int)
        and fmt.get("height") == height
    ]
    audio_only = [fmt for fmt in formats if _is_usable_format(fmt) and _is_audio_only_format(fmt)]
    progressive = [
        fmt
        for fmt in formats
        if _is_usable_format(fmt)
        and _is_progressive_video_format(fmt)
        and isinstance(fmt.get("height"), int)
        and fmt.get("height") == height
    ]

    video_only.sort(key=_video_sort_key)
    audio_only.sort(key=_audio_sort_key)
    progressive.sort(key=_progressive_sort_key)

    selectors: list[str] = []
    for video in video_only[:3]:
        video_id = video.get("format_id")
        if not isinstance(video_id, str):
            continue

        for audio in audio_only[:3]:
            audio_id = audio.get("format_id")
            if not isinstance(audio_id, str):
                continue
            selectors.append(f"{video_id}+{audio_id}")

    for format_info in progressive[:3]:
        format_id = format_info.get("format_id")
        if isinstance(format_id, str):
            selectors.append(format_id)

    return _dedupe_selectors(selectors)


def _extract_probe_headers(format_info: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {"User-Agent": PROBE_USER_AGENT}
    raw_headers = format_info.get("http_headers")
    if isinstance(raw_headers, dict):
        for key, value in raw_headers.items():
            if isinstance(key, str) and isinstance(value, str):
                headers[key] = value
    return headers


def _probe_stream_url(stream_url: str, headers: dict[str, str], size_hint: int | None = None) -> bool:
    offsets: list[int] = [0, 1 * 1024 * 1024, 2 * 1024 * 1024]
    if isinstance(size_hint, int) and size_hint > 0:
        quarter = size_hint // 4
        half = size_hint // 2
        three_quarters = (size_hint * 3) // 4
        near_end = max(0, size_hint - 64 * 1024)
        offsets.extend([quarter, half, three_quarters, near_end])

    range_headers: list[str] = []
    seen_ranges: set[str] = set()
    for start in offsets:
        if start < 0:
            continue
        range_header = f"bytes={start}-{start + 65535}"
        if range_header in seen_ranges:
            continue
        seen_ranges.add(range_header)
        range_headers.append(range_header)

    for range_header in range_headers:
        request_headers = dict(headers)
        request_headers["Range"] = range_header
        request = Request(stream_url, headers=request_headers)

        try:
            with urlopen(request, timeout=10) as response:
                status = getattr(response, "status", 200)
                if isinstance(status, int) and status >= 400:
                    return False
        except HTTPError as err:
            if err.code == 416:
                continue

            if err.code in (400, 405):
                fallback_request = Request(stream_url, headers=dict(headers))
                try:
                    with urlopen(fallback_request, timeout=10) as response:
                        status = getattr(response, "status", 200)
                        if isinstance(status, int) and status >= 400:
                            return False
                        continue
                except (HTTPError, URLError, TimeoutError):
                    return False

            return False
        except (URLError, TimeoutError):
            return False

    return True


def _selector_is_simple_format_ids(selector: str) -> bool:
    return not any(token in selector for token in ("[", "]", "(", ")", "/", ",", " "))


def _selector_streams_accessible(
    selector: str,
    format_index: dict[str, dict[str, Any]],
    probe_cache: dict[str, bool],
) -> bool:
    if not _selector_is_simple_format_ids(selector):
        return False

    for part in selector.split("+"):
        if not part:
            return False

        cached_result = probe_cache.get(part)
        if cached_result is not None:
            if not cached_result:
                return False
            continue

        format_info = format_index.get(part)
        if format_info is None or not _is_usable_format(format_info):
            probe_cache[part] = False
            return False

        stream_url = format_info.get("url")
        if not isinstance(stream_url, str) or not stream_url:
            probe_cache[part] = False
            return False

        headers = _extract_probe_headers(format_info)
        size_hint: int | None = None
        for size_key in ("filesize", "filesize_approx"):
            size_value = format_info.get(size_key)
            if isinstance(size_value, int) and size_value > 0:
                size_hint = size_value
                break

        accessible = _probe_stream_url(stream_url, headers, size_hint=size_hint)
        probe_cache[part] = accessible
        if not accessible:
            return False

    return True


def get_downloadable_resolutions(
    url: str,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
    verify_streams: bool = True,
) -> list[tuple[int, str]]:
    info = _extract_video_info(
        url,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
    )

    raw_formats = info.get("formats")
    if not isinstance(raw_formats, list):
        return []

    formats = [fmt for fmt in raw_formats if isinstance(fmt, dict)]
    heights: set[int] = set()
    for format_info in formats:
        if not _is_usable_format(format_info) or not _is_video_format(format_info):
            continue

        height = format_info.get("height")
        if isinstance(height, int) and height > 0:
            heights.add(height)

    format_index = _build_format_index(formats)
    probe_cache: dict[str, bool] = {}
    options: list[tuple[int, str]] = []

    for height in sorted(heights):
        selectors = _build_height_candidate_selectors(formats, height)
        if not selectors:
            continue

        chosen_selector: str | None = None
        for selector in selectors:
            if not verify_streams or _selector_streams_accessible(selector, format_index, probe_cache):
                chosen_selector = selector
                break

        if chosen_selector is not None:
            options.append((height, chosen_selector))

    return options


def get_available_resolutions(
    url: str,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
) -> list[int]:
    options = get_downloadable_resolutions(
        url,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
        verify_streams=False,
    )
    return [height for height, _selector in options]


def get_best_available_resolution(
    url: str,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
) -> int:
    info = _extract_video_info(
        url,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
        format_selector=MAX_QUALITY_FORMAT,
    )

    best_height = _selected_video_height(info)
    if best_height is None:
        raise DownloadError("No downloadable resolutions found for this video.")

    return best_height


def download_best_available(
    url: str,
    out_dir: str,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> int:
    normalized_browser = _normalize_optional_string(cookies_browser)
    normalized_profile = _normalize_optional_string(cookies_profile)
    normalized_po_token = _normalize_optional_string(po_token)

    auth_profiles: list[tuple[str | None, str | None]] = [(normalized_browser, normalized_profile)]
    if normalized_browser is not None:
        auth_profiles.append((None, None))

    last_error: DownloadError | None = None
    for profile_index, (active_browser, active_profile) in enumerate(auth_profiles):
        if profile_index > 0:
            _emit_progress(
                progress_callback,
                {
                    "event": "auth_fallback",
                    "message": "Cookie-based stream failed, retrying without browser cookies...",
                },
            )

        try:
            return _download_best_available_with_auth(
                url=url,
                out_dir=out_dir,
                cookies_browser=active_browser,
                cookies_profile=active_profile,
                po_token=normalized_po_token,
                progress_callback=progress_callback,
            )
        except DownloadError as err:
            last_error = err
            has_next_profile = profile_index < len(auth_profiles) - 1
            if has_next_profile and _is_retryable_download_error(err):
                continue
            raise

    if last_error is not None:
        raise last_error

    raise DownloadError("No downloadable resolutions found for this video.")


def _download_best_available_with_auth(
    url: str,
    out_dir: str,
    cookies_browser: str | None,
    cookies_profile: str | None,
    po_token: str | None,
    progress_callback: ProgressCallback | None,
) -> int:
    best_height = get_best_available_resolution(
        url,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
    )

    _emit_progress(
        progress_callback,
        {
            "event": "trying_resolution",
            "requested_height": best_height,
            "active_height": best_height,
        },
    )
    progress_hooks = [_build_progress_hook(progress_callback, best_height)] if progress_callback is not None else None

    _download_with_selector_fallbacks(
        url=url,
        out_dir=out_dir,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
        selectors=[MAX_QUALITY_FORMAT],
        progress_hooks=progress_hooks,
        progress_callback=progress_callback,
        include_network_profiles=True,
    )

    _emit_progress(
        progress_callback,
        {
            "event": "resolution_used",
            "requested_height": best_height,
            "active_height": best_height,
        },
    )
    return best_height


def _build_height_format_selector(height: int) -> str:
    return (
        f"bestvideo[height={height}][vcodec!=none]+bestaudio[acodec!=none]/"
        f"best[height={height}][vcodec!=none][acodec!=none]"
    )


def _download_resolution_with_auth(
    url: str,
    out_dir: str,
    height: int,
    cookies_browser: str | None,
    cookies_profile: str | None,
    po_token: str | None,
    format_selector: str | None,
    progress_callback: ProgressCallback | None,
    allow_lower_fallback: bool,
) -> int:
    if height <= 0:
        raise ValueError("Height must be a positive integer.")

    info = _extract_video_info(
        url,
        cookies_browser=cookies_browser,
        cookies_profile=cookies_profile,
        po_token=po_token,
    )
    raw_formats = info.get("formats")
    if not isinstance(raw_formats, list):
        raise DownloadError("Could not read downloadable formats for this video.")

    formats = [fmt for fmt in raw_formats if isinstance(fmt, dict)]
    heights_set: set[int] = set()
    for format_info in formats:
        if not _is_usable_format(format_info) or not _is_video_format(format_info):
            continue

        raw_height = format_info.get("height")
        if isinstance(raw_height, int) and raw_height > 0:
            heights_set.add(raw_height)

    all_heights = sorted(heights_set, reverse=True)

    if allow_lower_fallback:
        if height in all_heights:
            lower_heights = [candidate_height for candidate_height in all_heights if candidate_height < height]
            candidate_heights = [height, *lower_heights]
        else:
            candidate_heights = all_heights.copy()
    else:
        candidate_heights = [height]

    candidate_heights = list(dict.fromkeys(candidate_heights))

    if not candidate_heights:
        candidate_heights = [height]

    last_error: DownloadError | None = None
    for height_index, active_height in enumerate(candidate_heights):
        _emit_progress(
            progress_callback,
            {
                "event": "trying_resolution",
                "requested_height": height,
                "active_height": active_height,
            },
        )

        selectors = _build_height_candidate_selectors(formats, active_height)
        fallback_selector = _build_height_format_selector(active_height)

        ordered_selectors: list[str] = []
        if active_height == height and isinstance(format_selector, str) and format_selector.strip():
            ordered_selectors.append(format_selector.strip())
        ordered_selectors.extend(selectors)
        ordered_selectors.append(fallback_selector)
        ordered_selectors = _dedupe_selectors(ordered_selectors)

        if allow_lower_fallback and active_height < height and len(ordered_selectors) > 4:
            ordered_selectors = ordered_selectors[:4]

        if not ordered_selectors:
            continue

        progress_hooks = [_build_progress_hook(progress_callback, active_height)] if progress_callback is not None else None

        try:
            _download_with_selector_fallbacks(
                url=url,
                out_dir=out_dir,
                selectors=ordered_selectors,
                cookies_browser=cookies_browser,
                cookies_profile=cookies_profile,
                po_token=po_token,
                progress_hooks=progress_hooks,
                progress_callback=progress_callback,
                include_network_profiles=True,
            )
            _emit_progress(
                progress_callback,
                {
                    "event": "resolution_used",
                    "requested_height": height,
                    "active_height": active_height,
                },
            )
            return active_height
        except DownloadError as err:
            last_error = err
            has_next_height = height_index < len(candidate_heights) - 1
            if has_next_height and _is_retryable_download_error(err):
                next_height = candidate_heights[height_index + 1]
                _emit_progress(
                    progress_callback,
                    {
                        "event": "fallback_height",
                        "from_height": active_height,
                        "to_height": next_height,
                    },
                )
                continue
            raise

    if last_error is not None:
        raise last_error

    raise DownloadError(f"Requested resolution {height}p is not available for this video.")


def download_resolution(
    url: str,
    out_dir: str,
    height: int,
    cookies_browser: str | None = None,
    cookies_profile: str | None = None,
    po_token: str | None = None,
    format_selector: str | None = None,
    progress_callback: ProgressCallback | None = None,
    allow_lower_fallback: bool = True,
    allow_auth_fallback: bool = True,
) -> int:
    normalized_browser = _normalize_optional_string(cookies_browser)
    normalized_profile = _normalize_optional_string(cookies_profile)
    normalized_po_token = _normalize_optional_string(po_token)

    auth_profiles: list[tuple[str | None, str | None]] = [(normalized_browser, normalized_profile)]
    if allow_auth_fallback and normalized_browser is not None:
        auth_profiles.append((None, None))

    last_error: DownloadError | None = None
    for profile_index, (active_browser, active_profile) in enumerate(auth_profiles):
        if profile_index > 0:
            _emit_progress(
                progress_callback,
                {
                    "event": "auth_fallback",
                    "message": "Cookie-based stream failed, retrying without browser cookies...",
                },
            )

        active_allow_lower_fallback = allow_lower_fallback
        has_auth_fallback_profile = len(auth_profiles) > 1
        if profile_index == 0 and has_auth_fallback_profile and active_browser is not None:
            active_allow_lower_fallback = False

        try:
            return _download_resolution_with_auth(
                url=url,
                out_dir=out_dir,
                height=height,
                cookies_browser=active_browser,
                cookies_profile=active_profile,
                po_token=normalized_po_token,
                format_selector=format_selector,
                progress_callback=progress_callback,
                allow_lower_fallback=active_allow_lower_fallback,
            )
        except DownloadError as err:
            last_error = err
            has_next_profile = profile_index < len(auth_profiles) - 1
            if has_next_profile and _is_retryable_download_error(err):
                continue
            raise

    if last_error is not None:
        raise last_error

    raise DownloadError(f"Requested resolution {height}p is not available for this video.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a YouTube video with yt-dlp.")
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("out_dir", nargs="?", default=".", help="Output directory")
    parser.add_argument(
        "--cookies-browser",
        choices=["chrome", "edge", "firefox", "brave", "opera", "vivaldi"],
        help="Load cookies from browser for authenticated streams",
    )
    parser.add_argument("--cookies-profile", help="Browser profile name/path for cookie extraction")
    parser.add_argument(
        "--po-token",
        help="YouTube GVS PO token. Accepts either raw token or scoped token like web.gvs+TOKEN",
    )
    parser.add_argument(
        "--compat-fallback",
        action="store_true",
        help="Allow progressive fallback if max-quality streams keep returning 403",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    try:
        download(
            args.url,
            args.out_dir,
            compat_fallback=args.compat_fallback,
            cookies_browser=args.cookies_browser,
            cookies_profile=args.cookies_profile,
            po_token=args.po_token,
        )
    except DownloadError as err:
        print(f"Download failed: {err}")

        if "HTTP Error 403: Forbidden" in str(err):
            print("Hint: high-quality YouTube streams can require cookies or a PO token.")
            print("Try one of the following:")
            print("  1) Close browser windows and run with --cookies-browser edge")
            print("  2) Pass a token: --po-token <token>")
            print("  3) If quality can be lower, add --compat-fallback")

        raise SystemExit(1)
