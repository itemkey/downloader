import os
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import Any
from urllib.parse import unquote, urlparse

from yt_dlp.utils import DownloadError

from download_youtube import download_best_available, download_resolution, get_best_available_resolution, get_downloadable_resolutions
from media_converter import ConversionError, convert_media, get_available_conversion_targets
from soundcloud_downloader import SOUNDCLOUD_AUDIO_FORMATS, download_soundcloud_audio

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None


class YouTubeDownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._setup_i18n()
        self.root.title(self._tr("app.title"))
        self.root.geometry("860x620")
        self.root.minsize(760, 540)

        self._setup_styles()

        self.output_dir_var = tk.StringVar()
        self.url_vars: list[tk.StringVar] = []
        self.url_entries: list[ttk.Entry] = []
        self.url_remove_buttons: list[ttk.Button] = []
        self.status_var = tk.StringVar(value=self._tr("status.paste_url"))

        self.converter_format_var = tk.StringVar()
        self.converter_source_var = tk.StringVar()
        self.converter_output_dir_var = tk.StringVar()
        self.converter_status_var = tk.StringVar(value=self._tr("converter.status.default"))
        self.converter_progress_var = tk.DoubleVar(value=0.0)
        self.converter_progress_text_var = tk.StringVar(value=self._tr("converter.progress.zero"))
        self.converter_format_options: dict[str, str] = {}

        self.soundcloud_url_var = tk.StringVar()
        self.soundcloud_format_var = tk.StringVar()
        self.soundcloud_output_dir_var = tk.StringVar()
        self.soundcloud_status_var = tk.StringVar(value=self._tr("soundcloud.status.default"))
        self.soundcloud_progress_var = tk.DoubleVar(value=0.0)
        self.soundcloud_progress_text_var = tk.StringVar(value=self._tr("soundcloud.progress.zero"))
        self.soundcloud_format_options: dict[str, str] = {}

        self.analyzed_url: str | None = None
        self.is_busy = False
        self.converter_is_busy = False
        self.soundcloud_is_busy = False
        self.download_buttons: list[ttk.Button] = []
        self.selector_by_height: dict[int, str] = {}
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="Progress: 0%")
        self.cookies_browser_var = tk.StringVar(value="none")
        self.cookies_profile_var = tk.StringVar()
        self.po_token_var = tk.StringVar()
        self.analyzed_auth_signature: tuple[str | None, str | None, str | None] | None = None
        self.entry_menu_target: tk.Entry | ttk.Entry | None = None
        self.settings_window: tk.Toplevel | None = None
        self.settings_language_var = tk.StringVar()
        self.settings_language_options: dict[str, str] = {}
        self.outer_frame: ttk.Frame | None = None
        self.tabs: ttk.Notebook | None = None

        self.entry_context_menu = tk.Menu(self.root, tearoff=0)
        self.entry_context_menu.configure(
            bg=self.colors["surface_alt"],
            fg=self.colors["text"],
            activebackground=self.colors["accent"],
            activeforeground="#ffffff",
            bd=1,
            relief="flat",
        )
        self.entry_context_menu.add_command(label="Cut", command=lambda: self._entry_menu_generate("<<Cut>>"))
        self.entry_context_menu.add_command(label="Copy", command=lambda: self._entry_menu_generate("<<Copy>>"))
        self.entry_context_menu.add_command(label="Paste", command=lambda: self._entry_menu_generate("<<Paste>>"))

        self._build_ui()

    def _setup_i18n(self) -> None:
        self.language_code = "ru"
        self.translations: dict[str, dict[str, str]] = {
            "ru": {
                "app.title": "YouTube Downloader + Conventer",
                "tabs.downloader": "YouTube Downloader",
                "tabs.converter": "Conventer",
                "tabs.soundcloud": "SoundCloud Downloader",
                "header.app": "Downloader Toolkit",
                "button.settings": "\u2699",
                "settings.title": "Settings",
                "settings.language": "Language",
                "settings.apply": "Apply",
                "settings.close": "Close",
                "settings.option_ru": "Russian (ru)",
                "settings.option_en": "English (en)",
                "busy.title": "Busy",
                "busy.language_change": "Language cannot be changed while download or conversion is running.",
                "status.paste_url": "Paste a YouTube URL and click Analyze.",
                "status.batch_detected": "Batch mode: multiple URLs detected.",
                "status.invalid_po_ignored": "Invalid PO token was ignored.",
                "status.retry_no_cookies": "Retrying without browser cookies...",
                "status.downloading_height": "Downloading {height}p...",
                "status.downloading_best": "Downloading best available quality...",
                "status.requested_trying": "Requested {requested}p, trying {active}p...",
                "status.batch_ready": "Batch mode ready. Click Download All (best).",
                "status.analyzing": "Analyzing available resolutions...",
                "status.no_resolutions": "No downloadable resolutions found.",
                "status.select_resolution": "Select a resolution and click Download.",
                "status.analyze_failed": "Analyze failed.",
                "status.download_canceled_no_folder": "Download canceled: folder not selected.",
                "status.batch_started": "Batch download started: 0/{total} completed.",
                "status.batch_downloading_video": "Batch downloading video {index}/{total}...",
                "status.batch_video_failed": "Video {index}/{total} failed, continuing...",
                "status.batch_complete": "Batch complete: {done}/{total} downloaded.",
                "status.download_failed_empty_url": "Download failed: URL is empty.",
                "status.batch_mode_active": "Batch mode active. Use Download All (best).",
                "status.analyze_current_url": "Analyze the current URL first.",
                "status.done_exact": "Done: {height}p saved to {path}",
                "status.done_best": "Done: best available quality ({height}p) saved to {path}",
                "status.done_fallback": "Done: requested {requested}p, downloaded {actual}p to {path}",
                "status.download_failed": "Download failed.",
                "progress.zero": "Progress: 0%",
                "progress.downloading": "Downloading",
                "progress.processing": "Finalizing...",
                "progress.switching": "Switching from {from_height}p to {to_height}p...",
                "progress.retry_stream": "Trying another stream...",
                "progress.retry_no_cookies": "Retrying without browser cookies...",
                "progress.batch_start": "Batch: 1/{total} starting...",
                "progress.batch_downloading": "Batch: downloading {index}/{total}...",
                "progress.batch_complete": "Batch complete.",
                "progress.batch_failed": "Batch failed.",
                "progress.starting_height": "Starting {height}p download...",
                "progress.starting_best": "Starting best-quality download...",
                "progress.download_complete": "Download complete.",
                "progress.download_failed": "Download failed.",
                "downloader.title": "YouTube Downloader",
                "downloader.download_folder": "Download folder",
                "downloader.urls": "YouTube URLs",
                "downloader.cookies_browser": "Cookies browser",
                "downloader.cookies_profile": "Cookies profile",
                "downloader.po_token": "PO token",
                "downloader.available": "Available resolutions",
                "downloader.empty": "No resolutions yet.",
                "downloader.best_available": "Best available: {height}p",
                "downloader.batch_hint": "{count} videos selected. Batch mode uses best quality automatically.",
                "button.browse": "Browse",
                "button.analyze": "Analyze",
                "button.download": "Download",
                "button.download_best": "Download Best",
                "button.download_all_best": "Download All (best)",
                "button.convert": "Convert",
                "button.download_soundcloud": "Download",
                "converter.title": "Conventer",
                "converter.format": "Format",
                "converter.what": "What to convert",
                "converter.from": "From",
                "converter.to": "To",
                "converter.mp3_quality": "MP3 quality",
                "converter.source_file": "Source file",
                "converter.download_folder": "Output folder",
                "converter.lossless": "The app auto-detects source type and shows available conversion formats.",
                "converter.status.default": "Choose source file, format, and output folder.",
                "converter.status.missing_source": "Conversion failed: source file is missing.",
                "converter.status.invalid_source": "Conversion failed: source file is not supported.",
                "converter.status.no_formats": "Conversion failed: no target formats are available for this file.",
                "converter.status.canceled_no_folder": "Conversion canceled: output folder not selected.",
                "converter.status.converting": "Converting...",
                "converter.status.done": "Done: saved to {path}",
                "converter.status.failed": "Conversion failed.",
                "converter.progress.zero": "Conversion progress: 0%",
                "converter.progress.preparing": "Preparing conversion...",
                "converter.progress.converting": "Converting...",
                "converter.progress.converting_percent": "Converting: {percent:.1f}%",
                "converter.progress.finalizing": "Finalizing output...",
                "converter.progress.done": "Conversion complete.",
                "converter.progress.failed": "Conversion failed.",
                "soundcloud.title": "SoundCloud Downloader",
                "soundcloud.url": "SoundCloud URL",
                "soundcloud.format": "Audio format",
                "soundcloud.output_folder": "Output folder",
                "soundcloud.status.default": "Paste a SoundCloud track or playlist URL, choose format and folder.",
                "soundcloud.status.missing_url": "Download failed: URL is empty.",
                "soundcloud.status.missing_folder": "Download canceled: folder not selected.",
                "soundcloud.status.downloading": "Downloading from SoundCloud...",
                "soundcloud.status.processing": "Converting audio...",
                "soundcloud.status.done": "Done: saved to {path}",
                "soundcloud.status.failed": "SoundCloud download failed.",
                "soundcloud.progress.zero": "SoundCloud progress: 0%",
                "soundcloud.progress.downloading": "Downloading",
                "soundcloud.progress.processing": "Processing...",
                "soundcloud.progress.finalizing": "Finalizing output...",
                "soundcloud.progress.done": "SoundCloud download complete.",
                "soundcloud.progress.failed": "SoundCloud download failed.",
                "dialog.folder_required.title": "Folder required",
                "dialog.folder_required.download": "You must choose a folder before downloading.",
                "dialog.folder_required.convert": "You must choose a folder before converting.",
                "dialog.folder_required.soundcloud": "You must choose a folder before downloading from SoundCloud.",
                "dialog.source_required.title": "Source file required",
                "dialog.source_required.message": "Choose a source file first.",
                "dialog.format_required.title": "Format required",
                "dialog.format_required.message": "Choose output format first.",
                "dialog.soundcloud_url_required.title": "URL required",
                "dialog.soundcloud_url_required.message": "Paste a SoundCloud URL first.",
                "dialog.soundcloud_format_required.title": "Format required",
                "dialog.soundcloud_format_required.message": "Choose an audio format first.",
                "dialog.soundcloud_complete.title": "SoundCloud download complete",
                "dialog.soundcloud_complete.message": "Audio was downloaded successfully:\n{path}",
                "dialog.soundcloud_failed.title": "SoundCloud download failed",
                "dialog.drag_drop_file_required.title": "File required",
                "dialog.drag_drop_file_required.message": "Drop a file here.",
                "dialog.drag_drop_folder_required.title": "Folder required",
                "dialog.drag_drop_folder_required.message": "Drop a folder here.",
                "dialog.invalid_source.title": "Invalid source file",
                "dialog.invalid_source.message": "This file type is not supported for conversion.",
                "dialog.conversion_complete.title": "Conversion complete",
                "dialog.conversion_complete.message": "File was converted successfully:\n{path}",
                "dialog.conversion_failed.title": "Conversion failed",
                "dialog.url_required.title": "URL required",
                "dialog.url_required.message": "Paste a YouTube video URL first.",
                "dialog.analyze_failed.title": "Analyze failed",
                "dialog.batch_mode.title": "Batch mode",
                "dialog.batch_mode.need_two": "Add at least two URLs for batch downloading.",
                "dialog.batch_mode.use_button": "Multiple URLs are filled. Use Download All (best).",
                "dialog.batch_complete.title": "Batch complete",
                "dialog.batch_complete.message": "Downloaded {count} videos to:\n{path}",
                "dialog.batch_complete_with_errors.title": "Batch complete with errors",
                "dialog.batch_complete_with_errors.message": "Downloaded: {done}/{total}.\nFailed: {failed}.\n\n{preview}",
                "dialog.analyze_required.title": "Analyze required",
                "dialog.analyze_required.url_changed": "URL changed. Click Analyze again for this URL.",
                "dialog.analyze_required.auth_changed": "Authentication settings changed. Click Analyze again.",
                "dialog.analyze_required.auth_missing": "Could not read current auth settings. Click Analyze again.",
                "dialog.analyze_required.stream_missing": "Could not find a valid stream for this resolution. Click Analyze again.",
                "dialog.download_complete.title": "Download complete",
                "dialog.download_complete.exact": "{height}p was downloaded to:\n{path}",
                "dialog.download_complete.best": "Best available quality ({height}p) was downloaded to:\n{path}",
                "dialog.download_complete.fallback": "{requested}p was not available. Downloaded {actual}p to:\n{path}",
                "dialog.download_failed.title": "Download failed",
                "dialog.download_failed.message": "Could not download {height}p.\n\n{error}",
                "dialog.download_failed.best": "Could not download the best available quality.\n\n{error}",
                "dialog.po_ignored.title": "PO token ignored",
                "dialog.po_ignored.message": "This value does not look like a valid PO token, so it was ignored.",
                "dialog.select_folder": "Select folder",
                "dialog.select_mkv_file": "Select source file",
                "dialog.filetype_mkv": "MKV files",
                "dialog.filetype_video": "Video files",
                "dialog.filetype_all": "All files",
                "friendly.firefox_cookies": "Firefox cookies database was not found. Leave Cookies profile empty to use default profile, or enter an existing Firefox profile path/name.",
                "friendly.browser_cookies": "Could not read browser cookies. Close browser windows and try Analyze again, or use Firefox cookies if available.",
                "friendly.dpapi": "Windows blocked cookie decryption for this browser profile. Try another browser profile or leave Cookies browser = none.",
                "friendly.http403": "YouTube blocked this stream (HTTP 403). Try selecting Cookies browser/PO token and analyze again.",
                "friendly.empty_stream": "The selected stream returned empty fragments. The app will try lower fallback quality automatically, or retry with another auth mode.",
            },
            "en": {},
        }
        self.translations["en"] = dict(self.translations["ru"])
        self.translations["ru"].update({
            "app.title": "YouTube Downloader + Конвертер",
            "header.app": "Новая панель",
            "settings.title": "Настройки",
            "settings.language": "Язык",
            "settings.apply": "Применить",
            "settings.close": "Закрыть",
            "settings.option_ru": "Русский (ru)",
            "settings.option_en": "English (en)",
            "busy.title": "Занято",
            "busy.language_change": "Нельзя переключить язык во время загрузки или конвертации.",
            "status.paste_url": "Вставьте ссылку YouTube и нажмите Анализ.",
            "status.batch_detected": "Пакетный режим: обнаружено несколько ссылок.",
            "status.invalid_po_ignored": "Некорректный PO token был проигнорирован.",
            "status.retry_no_cookies": "Повтор без cookies браузера...",
            "status.downloading_height": "Скачивание {height}p...",
            "status.requested_trying": "Запрошено {requested}p, пробуем {active}p...",
            "status.batch_ready": "Пакетный режим готов. Нажмите Скачать все (лучшее).",
            "status.analyzing": "Анализ доступных разрешений...",
            "status.no_resolutions": "Не найдено доступных разрешений.",
            "status.select_resolution": "Выберите разрешение и нажмите Скачать.",
            "status.analyze_failed": "Анализ не удался.",
            "status.download_canceled_no_folder": "Скачивание отменено: папка не выбрана.",
            "status.batch_started": "Пакетная загрузка начата: 0/{total} завершено.",
            "status.batch_downloading_video": "Пакетная загрузка видео {index}/{total}...",
            "status.batch_video_failed": "Видео {index}/{total} не удалось, продолжаем...",
            "status.batch_complete": "Пакетная загрузка завершена: {done}/{total} скачано.",
            "status.download_failed_empty_url": "Скачивание не удалось: пустая ссылка.",
            "status.batch_mode_active": "Активен пакетный режим. Используйте Скачать все (лучшее).",
            "status.analyze_current_url": "Сначала выполните Анализ для текущей ссылки.",
            "status.done_exact": "Готово: {height}p сохранено в {path}",
            "status.done_fallback": "Готово: запрошено {requested}p, скачано {actual}p в {path}",
            "status.download_failed": "Скачивание не удалось.",
            "progress.zero": "Прогресс: 0%",
            "progress.downloading": "Скачивание",
            "progress.processing": "Финализация...",
            "progress.switching": "Переключение с {from_height}p на {to_height}p...",
            "progress.retry_stream": "Пробуем другой поток...",
            "progress.retry_no_cookies": "Повтор без cookies браузера...",
            "progress.batch_start": "Пакет: старт 1/{total}...",
            "progress.batch_downloading": "Пакет: скачивание {index}/{total}...",
            "progress.batch_complete": "Пакет завершен.",
            "progress.batch_failed": "Пакет не удался.",
            "progress.starting_height": "Старт скачивания {height}p...",
            "progress.download_complete": "Скачивание завершено.",
            "progress.download_failed": "Скачивание не удалось.",
            "downloader.title": "YouTube Downloader",
            "downloader.download_folder": "Папка загрузки",
            "downloader.urls": "Ссылки YouTube",
            "downloader.cookies_browser": "Браузер cookies",
            "downloader.cookies_profile": "Профиль cookies",
            "downloader.po_token": "PO token",
            "downloader.available": "Доступные разрешения",
            "downloader.empty": "Разрешения пока не получены.",
            "downloader.batch_hint": "Выбрано видео: {count}. Пакетный режим автоматически использует лучшее качество.",
            "button.browse": "Обзор",
            "button.analyze": "Анализ",
            "button.download": "Скачать",
            "button.download_all_best": "Скачать все (лучшее)",
            "button.convert": "Конвертировать",
            "converter.title": "Conventer",
            "converter.format": "Формат",
            "converter.what": "Что конвертировать",
            "converter.from": "Из",
            "converter.to": "В",
            "converter.mp3_quality": "Качество MP3",
            "converter.source_file": "Исходный файл",
            "converter.download_folder": "Папка назначения",
            "converter.lossless": "Приложение автоматически определяет тип исходного файла и показывает доступные форматы конвертации.",
            "converter.status.default": "Выберите исходный файл, формат и папку назначения.",
            "converter.status.missing_source": "Конвертация не удалась: не выбран исходный файл.",
            "converter.status.invalid_source": "Конвертация не удалась: файл не поддерживается.",
            "converter.status.no_formats": "Конвертация не удалась: для этого файла нет доступных форматов.",
            "converter.status.canceled_no_folder": "Конвертация отменена: не выбрана папка назначения.",
            "converter.status.converting": "Конвертация...",
            "converter.status.done": "Готово: сохранено в {path}",
            "converter.status.failed": "Конвертация не удалась.",
            "converter.progress.zero": "Прогресс конвертации: 0%",
            "converter.progress.preparing": "Подготовка конвертации...",
            "converter.progress.converting": "Конвертация...",
            "converter.progress.converting_percent": "Конвертация: {percent:.1f}%",
            "converter.progress.finalizing": "Финализация файла...",
            "converter.progress.done": "Конвертация завершена.",
            "converter.progress.failed": "Конвертация не удалась.",
            "dialog.folder_required.title": "Нужна папка",
            "dialog.folder_required.download": "Перед скачиванием нужно выбрать папку.",
            "dialog.folder_required.convert": "Перед конвертацией нужно выбрать папку.",
            "dialog.source_required.title": "Нужен исходный файл",
            "dialog.source_required.message": "Сначала выберите исходный файл.",
            "dialog.format_required.title": "Нужен формат",
            "dialog.format_required.message": "Сначала выберите формат конвертации.",
            "dialog.invalid_source.title": "Некорректный исходный файл",
            "dialog.invalid_source.message": "Этот тип файла не поддерживается для конвертации.",
            "dialog.conversion_complete.title": "Конвертация завершена",
            "dialog.conversion_complete.message": "Файл успешно конвертирован:\n{path}",
            "dialog.conversion_failed.title": "Конвертация не удалась",
            "dialog.url_required.title": "Нужна ссылка",
            "dialog.url_required.message": "Сначала вставьте ссылку на видео YouTube.",
            "dialog.analyze_failed.title": "Анализ не удался",
            "dialog.batch_mode.title": "Пакетный режим",
            "dialog.batch_mode.need_two": "Для пакетной загрузки добавьте минимум две ссылки.",
            "dialog.batch_mode.use_button": "Заполнено несколько ссылок. Используйте Скачать все (лучшее).",
            "dialog.batch_complete.title": "Пакетная загрузка завершена",
            "dialog.batch_complete.message": "Скачано {count} видео в:\n{path}",
            "dialog.batch_complete_with_errors.title": "Пакет завершен с ошибками",
            "dialog.batch_complete_with_errors.message": "Скачано: {done}/{total}.\nОшибок: {failed}.\n\n{preview}",
            "dialog.analyze_required.title": "Нужно выполнить Анализ",
            "dialog.analyze_required.url_changed": "Ссылка изменилась. Нажмите Анализ еще раз для этой ссылки.",
            "dialog.analyze_required.auth_changed": "Настройки авторизации изменились. Нажмите Анализ еще раз.",
            "dialog.analyze_required.auth_missing": "Не удалось прочитать текущие настройки авторизации. Нажмите Анализ еще раз.",
            "dialog.analyze_required.stream_missing": "Не удалось найти валидный поток для этого разрешения. Нажмите Анализ еще раз.",
            "dialog.download_complete.title": "Скачивание завершено",
            "dialog.download_complete.exact": "{height}p было скачано в:\n{path}",
            "dialog.download_complete.fallback": "{requested}p недоступно. Скачано {actual}p в:\n{path}",
            "dialog.download_failed.title": "Скачивание не удалось",
            "dialog.download_failed.message": "Не удалось скачать {height}p.\n\n{error}",
            "dialog.po_ignored.title": "PO token проигнорирован",
            "dialog.po_ignored.message": "Это значение не похоже на валидный PO token, поэтому оно было проигнорировано.",
            "dialog.select_folder": "Выберите папку",
            "dialog.select_mkv_file": "Выберите исходный файл",
            "dialog.filetype_mkv": "Файлы MKV",
            "dialog.filetype_video": "Видео файлы",
            "dialog.filetype_all": "Все файлы",
            "friendly.firefox_cookies": "База cookies Firefox не найдена. Оставьте Cookies profile пустым для профиля по умолчанию или укажите существующий профиль/путь Firefox.",
            "friendly.browser_cookies": "Не удалось прочитать cookies браузера. Закройте окна браузера и попробуйте Analyze снова, либо используйте cookies Firefox.",
            "friendly.dpapi": "Windows заблокировал расшифровку cookies для этого профиля. Попробуйте другой профиль браузера или установите Cookies browser = none.",
            "friendly.http403": "YouTube заблокировал поток (HTTP 403). Попробуйте выбрать Cookies browser/PO token и снова выполнить Analyze.",
            "friendly.empty_stream": "Выбранный поток вернул пустые фрагменты. Приложение попробует более низкое качество автоматически или повтор с другой авторизацией.",
        })
        self.translations["ru"].update({
            "status.downloading_best": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 \u043b\u0443\u0447\u0448\u0435\u0433\u043e \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0433\u043e \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u0430...",
            "status.done_best": "\u0413\u043e\u0442\u043e\u0432\u043e: \u043b\u0443\u0447\u0448\u0435\u0435 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0435 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u043e ({height}p) \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e \u0432 {path}",
            "progress.starting_best": "\u0421\u0442\u0430\u0440\u0442 \u0441\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u044f \u043b\u0443\u0447\u0448\u0435\u0433\u043e \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u0430...",
            "downloader.best_available": "\u041b\u0443\u0447\u0448\u0435\u0435 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0435: {height}p",
            "button.download_best": "\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u043b\u0443\u0447\u0448\u0435\u0435",
            "dialog.download_complete.best": "\u041b\u0443\u0447\u0448\u0435\u0435 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0435 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u043e ({height}p) \u0441\u043a\u0430\u0447\u0430\u043d\u043e \u0432:\n{path}",
            "dialog.download_failed.best": "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043a\u0430\u0447\u0430\u0442\u044c \u043b\u0443\u0447\u0448\u0435\u0435 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0435 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u043e.\n\n{error}",
        })
        self.translations["ru"].update({
            "tabs.soundcloud": "SoundCloud Downloader",
            "button.download_soundcloud": "\u0421\u043a\u0430\u0447\u0430\u0442\u044c",
            "soundcloud.title": "SoundCloud Downloader",
            "soundcloud.url": "\u0421\u0441\u044b\u043b\u043a\u0430 SoundCloud",
            "soundcloud.format": "\u0410\u0443\u0434\u0438\u043e\u0444\u043e\u0440\u043c\u0430\u0442",
            "soundcloud.output_folder": "\u041f\u0430\u043f\u043a\u0430 \u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u044f",
            "soundcloud.status.default": "\u0412\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0441\u0441\u044b\u043b\u043a\u0443 \u043d\u0430 \u0442\u0440\u0435\u043a \u0438\u043b\u0438 \u043f\u043b\u0435\u0439\u043b\u0438\u0441\u0442 SoundCloud, \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0444\u043e\u0440\u043c\u0430\u0442 \u0438 \u043f\u0430\u043f\u043a\u0443.",
            "soundcloud.status.missing_url": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 \u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c: \u043f\u0443\u0441\u0442\u0430\u044f \u0441\u0441\u044b\u043b\u043a\u0430.",
            "soundcloud.status.missing_folder": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u043e: \u043f\u0430\u043f\u043a\u0430 \u043d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d\u0430.",
            "soundcloud.status.downloading": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 \u0438\u0437 SoundCloud...",
            "soundcloud.status.processing": "\u041a\u043e\u043d\u0432\u0435\u0440\u0442\u0430\u0446\u0438\u044f \u0430\u0443\u0434\u0438\u043e...",
            "soundcloud.status.done": "\u0413\u043e\u0442\u043e\u0432\u043e: \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e \u0432 {path}",
            "soundcloud.status.failed": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 SoundCloud \u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c.",
            "soundcloud.progress.zero": "\u041f\u0440\u043e\u0433\u0440\u0435\u0441\u0441 SoundCloud: 0%",
            "soundcloud.progress.downloading": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435",
            "soundcloud.progress.processing": "\u041e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430...",
            "soundcloud.progress.finalizing": "\u0424\u0438\u043d\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f \u0444\u0430\u0439\u043b\u0430...",
            "soundcloud.progress.done": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 SoundCloud \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e.",
            "soundcloud.progress.failed": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 SoundCloud \u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c.",
            "dialog.folder_required.soundcloud": "\u041f\u0435\u0440\u0435\u0434 \u0441\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435\u043c \u0438\u0437 SoundCloud \u043d\u0443\u0436\u043d\u043e \u0432\u044b\u0431\u0440\u0430\u0442\u044c \u043f\u0430\u043f\u043a\u0443.",
            "dialog.soundcloud_url_required.title": "\u041d\u0443\u0436\u043d\u0430 \u0441\u0441\u044b\u043b\u043a\u0430",
            "dialog.soundcloud_url_required.message": "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0432\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0441\u0441\u044b\u043b\u043a\u0443 SoundCloud.",
            "dialog.soundcloud_format_required.title": "\u041d\u0443\u0436\u0435\u043d \u0444\u043e\u0440\u043c\u0430\u0442",
            "dialog.soundcloud_format_required.message": "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0430\u0443\u0434\u0438\u043e\u0444\u043e\u0440\u043c\u0430\u0442.",
            "dialog.soundcloud_complete.title": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 SoundCloud \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e",
            "dialog.soundcloud_complete.message": "\u0410\u0443\u0434\u0438\u043e \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u0441\u043a\u0430\u0447\u0430\u043d\u043e:\n{path}",
            "dialog.soundcloud_failed.title": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 SoundCloud \u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c",
            "dialog.drag_drop_file_required.title": "\u041d\u0443\u0436\u0435\u043d \u0444\u0430\u0439\u043b",
            "dialog.drag_drop_file_required.message": "\u041f\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u0435 \u0441\u044e\u0434\u0430 \u0444\u0430\u0439\u043b.",
            "dialog.drag_drop_folder_required.title": "\u041d\u0443\u0436\u043d\u0430 \u043f\u0430\u043f\u043a\u0430",
            "dialog.drag_drop_folder_required.message": "\u041f\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u0435 \u0441\u044e\u0434\u0430 \u043f\u0430\u043f\u043a\u0443.",
        })

    def _tr(self, key: str, **kwargs: Any) -> str:
        language_pack = self.translations.get(self.language_code, self.translations["ru"])
        text = language_pack.get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text

    def _open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.focus_set()
            return

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title(self._tr("settings.title"))
        self.settings_window.transient(self.root)
        self.settings_window.resizable(False, False)

        panel = ttk.Frame(self.settings_window, style="Panel.TFrame", padding=(16, 14, 16, 14))
        panel.pack(fill=tk.BOTH, expand=True)
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, text=self._tr("settings.language"), style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.settings_language_options = {
            self._tr("settings.option_ru"): "ru",
            self._tr("settings.option_en"): "en",
        }
        self.settings_language_var.set(
            self._tr("settings.option_ru") if self.language_code == "ru" else self._tr("settings.option_en")
        )
        language_combo = ttk.Combobox(
            panel,
            textvariable=self.settings_language_var,
            values=tuple(self.settings_language_options.keys()),
            state="readonly",
            style="App.TCombobox",
        )
        language_combo.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        action_row = ttk.Frame(panel, style="SubPanel.TFrame")
        action_row.grid(row=2, column=0, sticky="ew")
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=1)

        apply_button = ttk.Button(
            action_row,
            text=self._tr("settings.apply"),
            style="Primary.TButton",
            command=self._apply_settings,
        )
        apply_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        close_button = ttk.Button(
            action_row,
            text=self._tr("settings.close"),
            style="Secondary.TButton",
            command=self._close_settings,
        )
        close_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.settings_window.protocol("WM_DELETE_WINDOW", self._close_settings)

    def _close_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None

    def _apply_settings(self) -> None:
        selected_display = self.settings_language_var.get().strip()
        selected_language = self.settings_language_options.get(selected_display, selected_display.lower())
        self._set_language(selected_language)

    def _set_language(self, language_code: str) -> None:
        if language_code not in self.translations:
            return

        if language_code == self.language_code:
            return

        if self.is_busy or self.converter_is_busy or self.soundcloud_is_busy:
            messagebox.showinfo(self._tr("busy.title"), self._tr("busy.language_change"))
            return

        selected_tab = 0
        if self.tabs is not None and self.tabs.winfo_exists():
            try:
                selected_tab = int(self.tabs.index(self.tabs.select()))
            except (tk.TclError, ValueError):
                selected_tab = 0

        settings_was_open = self.settings_window is not None and self.settings_window.winfo_exists()
        self._close_settings()

        self.language_code = language_code
        self.root.title(self._tr("app.title"))
        self.status_var.set(self._tr("status.paste_url"))
        self.converter_status_var.set(self._tr("converter.status.default"))
        self.converter_progress_var.set(0.0)
        self.converter_progress_text_var.set(self._tr("converter.progress.zero"))
        self.soundcloud_status_var.set(self._tr("soundcloud.status.default"))
        self.soundcloud_progress_var.set(0.0)
        self.soundcloud_progress_text_var.set(self._tr("soundcloud.progress.zero"))

        if self.outer_frame is not None and self.outer_frame.winfo_exists():
            self.outer_frame.destroy()

        self._build_ui()

        if self.tabs is not None and self.tabs.winfo_exists():
            try:
                last_index = int(self.tabs.index("end")) - 1
                if last_index >= 0:
                    self.tabs.select(min(selected_tab, last_index))
            except (tk.TclError, ValueError):
                pass

        if settings_was_open:
            self._open_settings()

    def _pick_font_family(self, preferred: list[str], fallback: str) -> str:
        available = set(tkfont.families(self.root))
        for family in preferred:
            if family in available:
                return family
        return fallback

    def _setup_styles(self) -> None:
        self.colors = {
            "bg": "#eceff1",
            "surface": "#f8f9fa",
            "surface_alt": "#ffffff",
            "text": "#101214",
            "muted": "#5f6870",
            "border": "#c7ced4",
            "accent": "#0f1720",
            "accent_hover": "#1b2631",
            "accent_pressed": "#0a0f15",
            "danger": "#b42318",
        }

        self.root.configure(bg=self.colors["bg"])

        family = self._pick_font_family(
            preferred=["Bahnschrift", "Segoe UI", "Calibri"],
            fallback="TkDefaultFont",
        )
        self.font_main = (family, 10)
        self.font_label = (family, 10)
        self.font_button = (family, 10, "bold")
        self.font_title = (family, 11, "bold")

        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")

        self.style.configure(
            "App.TNotebook",
            background=self.colors["bg"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        self.style.configure(
            "App.TNotebook.Tab",
            font=self.font_button,
            foreground=self.colors["muted"],
            background=self.colors["surface"],
            padding=(14, 8),
            borderwidth=0,
        )
        self.style.map(
            "App.TNotebook.Tab",
            foreground=[("selected", self.colors["text"]), ("active", self.colors["text"])],
            background=[("selected", self.colors["surface_alt"]), ("active", self.colors["surface_alt"])],
        )

        self.style.configure("App.TFrame", background=self.colors["bg"])
        self.style.configure("Panel.TFrame", background=self.colors["surface_alt"], borderwidth=1, relief="flat")
        self.style.configure("SubPanel.TFrame", background=self.colors["surface_alt"])

        self.style.configure(
            "Title.TLabel",
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            font=self.font_title,
        )
        self.style.configure(
            "FieldLabel.TLabel",
            background=self.colors["surface_alt"],
            foreground=self.colors["muted"],
            font=self.font_label,
        )
        self.style.configure(
            "Body.TLabel",
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            font=self.font_main,
        )
        self.style.configure(
            "Status.TLabel",
            background=self.colors["surface_alt"],
            foreground=self.colors["muted"],
            font=self.font_main,
        )

        self.style.configure(
            "App.TEntry",
            foreground=self.colors["text"],
            fieldbackground=self.colors["surface_alt"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            padding=(10, 8),
            relief="flat",
        )
        self.style.map(
            "App.TEntry",
            bordercolor=[("focus", self.colors["accent"])],
            lightcolor=[("focus", self.colors["accent"])],
            darkcolor=[("focus", self.colors["accent"])],
        )

        self.style.configure(
            "App.TCombobox",
            foreground=self.colors["text"],
            fieldbackground=self.colors["surface_alt"],
            background=self.colors["surface_alt"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            arrowcolor=self.colors["text"],
            padding=(10, 7),
            relief="flat",
        )
        self.style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", self.colors["surface_alt"]), ("focus", self.colors["surface_alt"])],
            bordercolor=[("focus", self.colors["accent"])],
            lightcolor=[("focus", self.colors["accent"])],
            darkcolor=[("focus", self.colors["accent"])],
            arrowcolor=[("disabled", self.colors["muted"])],
        )

        self.style.configure(
            "Secondary.TButton",
            font=self.font_button,
            foreground=self.colors["text"],
            background=self.colors["surface_alt"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            focuscolor=self.colors["surface_alt"],
            padding=(14, 8),
            relief="flat",
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", self.colors["surface"]), ("pressed", self.colors["surface"])],
            bordercolor=[("active", self.colors["text"]), ("pressed", self.colors["text"])],
            lightcolor=[("active", self.colors["text"]), ("pressed", self.colors["text"])],
            darkcolor=[("active", self.colors["text"]), ("pressed", self.colors["text"])],
            foreground=[("disabled", self.colors["muted"])],
        )

        self.style.configure(
            "Primary.TButton",
            font=self.font_button,
            foreground="#ffffff",
            background=self.colors["accent"],
            bordercolor=self.colors["accent"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
            focuscolor=self.colors["accent"],
            padding=(14, 8),
            relief="flat",
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", self.colors["accent_hover"]), ("pressed", self.colors["accent_pressed"])],
            bordercolor=[("active", self.colors["accent_hover"]), ("pressed", self.colors["accent_pressed"])],
            lightcolor=[("active", self.colors["accent_hover"]), ("pressed", self.colors["accent_pressed"])],
            darkcolor=[("active", self.colors["accent_hover"]), ("pressed", self.colors["accent_pressed"])],
            foreground=[("disabled", "#c5c8cc")],
        )

        self.style.configure(
            "Icon.TButton",
            font=self.font_button,
            foreground=self.colors["text"],
            background=self.colors["surface_alt"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            focuscolor=self.colors["surface_alt"],
            padding=(8, 8),
            relief="flat",
        )
        self.style.map(
            "Icon.TButton",
            background=[("active", self.colors["surface"]), ("pressed", self.colors["surface"])],
            bordercolor=[("active", self.colors["text"]), ("pressed", self.colors["text"])],
            lightcolor=[("active", self.colors["text"]), ("pressed", self.colors["text"])],
            darkcolor=[("active", self.colors["text"]), ("pressed", self.colors["text"])],
        )

        self.style.configure(
            "Danger.TButton",
            font=self.font_button,
            foreground=self.colors["danger"],
            background=self.colors["surface_alt"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            focuscolor=self.colors["surface_alt"],
            padding=(8, 8),
            relief="flat",
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", self.colors["surface"]), ("pressed", self.colors["surface"])],
            bordercolor=[("active", self.colors["danger"]), ("pressed", self.colors["danger"])],
            lightcolor=[("active", self.colors["danger"]), ("pressed", self.colors["danger"])],
            darkcolor=[("active", self.colors["danger"]), ("pressed", self.colors["danger"])],
        )

        self.style.configure(
            "Minimal.Horizontal.TProgressbar",
            troughcolor=self.colors["surface"],
            background=self.colors["accent"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
            thickness=8,
            relief="flat",
        )

        self.style.configure("App.TSeparator", background=self.colors["border"])

    def _build_ui(self) -> None:
        self.outer_frame = ttk.Frame(self.root, style="App.TFrame", padding=(20, 20, 20, 16))
        self.outer_frame.pack(fill=tk.BOTH, expand=True)
        self.outer_frame.columnconfigure(0, weight=1)
        self.outer_frame.rowconfigure(1, weight=1)

        top_row = ttk.Frame(self.outer_frame, style="App.TFrame")
        top_row.grid(row=0, column=0, sticky="ew")
        top_row.columnconfigure(0, weight=1)

        self.top_title_label = ttk.Label(top_row, text=self._tr("header.app"), style="FieldLabel.TLabel")
        self.top_title_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.settings_button = ttk.Button(
            top_row,
            text=self._tr("button.settings"),
            style="Icon.TButton",
            width=3,
            command=self._open_settings,
        )
        self.settings_button.grid(row=0, column=1, sticky="e", pady=(0, 6))
        self._refresh_settings_button_state()

        self.tabs = ttk.Notebook(self.outer_frame, style="App.TNotebook")
        self.tabs.grid(row=1, column=0, sticky="nsew")

        downloader_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        converter_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=(0, 12, 0, 0))
        soundcloud_tab = ttk.Frame(self.tabs, style="App.TFrame", padding=(0, 12, 0, 0))

        self.tabs.add(downloader_tab, text=self._tr("tabs.downloader"))
        self.tabs.add(converter_tab, text=self._tr("tabs.converter"))
        self.tabs.add(soundcloud_tab, text=self._tr("tabs.soundcloud"))

        self._build_downloader_tab(downloader_tab)
        self._build_converter_tab(converter_tab)
        self._build_soundcloud_tab(soundcloud_tab)

    def _build_downloader_tab(self, parent: ttk.Frame) -> None:
        container = ttk.Frame(parent, style="Panel.TFrame", padding=(18, 16, 18, 14))
        container.pack(fill=tk.BOTH, expand=True)

        container.columnconfigure(1, weight=1)
        container.rowconfigure(8, weight=1)

        title_label = ttk.Label(container, text=self._tr("downloader.title"), style="Title.TLabel")
        title_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(container, text=self._tr("downloader.download_folder"), style="FieldLabel.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.folder_entry = ttk.Entry(container, textvariable=self.output_dir_var, style="App.TEntry")
        self.folder_entry.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self._bind_entry_shortcuts(self.folder_entry)
        self._register_folder_drop(self.folder_entry, self.output_dir_var)
        self.browse_button = ttk.Button(container, text=self._tr("button.browse"), command=self._choose_directory, style="Secondary.TButton")
        self.browse_button.grid(row=1, column=2, sticky="ew", pady=(0, 8), padx=(8, 0))

        ttk.Label(container, text=self._tr("downloader.urls"), style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.urls_frame = ttk.Frame(container, style="SubPanel.TFrame")
        self.urls_frame.grid(row=2, column=1, sticky="ew", pady=(0, 8))
        self.urls_frame.columnconfigure(0, weight=1)
        self.urls_frame.columnconfigure(1, weight=0)

        self.add_url_button = ttk.Button(self.urls_frame, text="+", command=self._add_url_field, style="Icon.TButton")
        self._add_url_field()

        self.analyze_button = ttk.Button(container, text=self._tr("button.analyze"), command=self._start_analysis, style="Primary.TButton")
        self.analyze_button.grid(row=2, column=2, sticky="ew", pady=(0, 8), padx=(8, 0))

        ttk.Label(container, text=self._tr("downloader.cookies_browser"), style="FieldLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.cookies_browser_combo = ttk.Combobox(
            container,
            textvariable=self.cookies_browser_var,
            values=("none", "firefox", "chrome", "edge", "brave", "opera", "vivaldi"),
            state="readonly",
            style="App.TCombobox",
        )
        self.cookies_browser_combo.grid(row=3, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(container, text=self._tr("downloader.cookies_profile"), style="FieldLabel.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.cookies_profile_entry = ttk.Entry(container, textvariable=self.cookies_profile_var, style="App.TEntry")
        self.cookies_profile_entry.grid(row=4, column=1, sticky="ew", pady=(0, 8))
        self._bind_entry_shortcuts(self.cookies_profile_entry)

        ttk.Label(container, text=self._tr("downloader.po_token"), style="FieldLabel.TLabel").grid(row=5, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.po_token_entry = ttk.Entry(container, textvariable=self.po_token_var, style="App.TEntry")
        self.po_token_entry.grid(row=5, column=1, sticky="ew", pady=(0, 8))
        self._bind_entry_shortcuts(self.po_token_entry)

        ttk.Separator(container, orient=tk.HORIZONTAL, style="App.TSeparator").grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        ttk.Label(container, text=self._tr("downloader.available"), style="FieldLabel.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")

        self.options_frame = ttk.Frame(container, style="SubPanel.TFrame")
        self.options_frame.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(8, 12))
        self.options_frame.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(
            container,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
            style="Minimal.Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        self.progress_info_label = ttk.Label(container, textvariable=self.progress_text_var, anchor="w", style="Status.TLabel")
        self.progress_info_label.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(0, 3))

        self.status_label = ttk.Label(container, textvariable=self.status_var, anchor="w", style="Status.TLabel")
        self.status_label.grid(row=11, column=0, columnspan=3, sticky="ew")

        self._show_empty_state(self._tr("downloader.empty"))
        self._set_progress(0.0, self._tr("progress.zero"))

    def _build_converter_tab(self, parent: ttk.Frame) -> None:
        container = ttk.Frame(parent, style="Panel.TFrame", padding=(18, 16, 18, 14))
        container.pack(fill=tk.BOTH, expand=True)

        container.columnconfigure(1, weight=1)
        container.rowconfigure(7, weight=1)

        title_label = ttk.Label(container, text=self._tr("converter.title"), style="Title.TLabel")
        title_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(container, text=self._tr("converter.source_file"), style="FieldLabel.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.converter_source_entry = ttk.Entry(container, textvariable=self.converter_source_var, style="App.TEntry")
        self.converter_source_entry.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self._bind_entry_shortcuts(self.converter_source_entry)
        self.converter_source_entry.bind("<KeyRelease>", self._on_converter_source_changed, add="+")
        self.converter_source_entry.bind("<FocusOut>", self._on_converter_source_changed, add="+")
        self._register_file_drop(self.converter_source_entry, self._handle_converter_source_drop)
        self.converter_source_browse_button = ttk.Button(
            container,
            text=self._tr("button.browse"),
            command=self._choose_converter_source,
            style="Secondary.TButton",
        )
        self.converter_source_browse_button.grid(row=1, column=2, sticky="ew", pady=(0, 8), padx=(8, 0))

        ttk.Label(container, text=self._tr("converter.format"), style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.converter_format_combo = ttk.Combobox(
            container,
            textvariable=self.converter_format_var,
            values=(),
            state="disabled",
            style="App.TCombobox",
        )
        self.converter_format_combo.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(container, text=self._tr("converter.download_folder"), style="FieldLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.converter_folder_entry = ttk.Entry(container, textvariable=self.converter_output_dir_var, style="App.TEntry")
        self.converter_folder_entry.grid(row=3, column=1, sticky="ew", pady=(0, 8))
        self._bind_entry_shortcuts(self.converter_folder_entry)
        self._register_folder_drop(self.converter_folder_entry, self.converter_output_dir_var)
        self.converter_folder_browse_button = ttk.Button(
            container,
            text=self._tr("button.browse"),
            command=self._choose_converter_directory,
            style="Secondary.TButton",
        )
        self.converter_folder_browse_button.grid(row=3, column=2, sticky="ew", pady=(0, 8), padx=(8, 0))

        self.converter_button = ttk.Button(
            container,
            text=self._tr("button.convert"),
            command=self._start_conversion,
            style="Primary.TButton",
        )
        self.converter_button.grid(row=4, column=0, columnspan=3, sticky="ew")

        self.converter_progress_bar = ttk.Progressbar(
            container,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
            variable=self.converter_progress_var,
            style="Minimal.Horizontal.TProgressbar",
        )
        self.converter_progress_bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 6))

        self.converter_progress_label = ttk.Label(
            container,
            textvariable=self.converter_progress_text_var,
            anchor="w",
            style="Status.TLabel",
        )
        self.converter_progress_label.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 3))

        self.converter_status_label = ttk.Label(
            container,
            textvariable=self.converter_status_var,
            anchor="w",
            style="Status.TLabel",
        )
        self.converter_status_label.grid(row=7, column=0, columnspan=3, sticky="ew")

        self._clear_converter_format_options()
        self._set_converter_progress(0.0, self._tr("converter.progress.zero"))

    def _build_soundcloud_tab(self, parent: ttk.Frame) -> None:
        container = ttk.Frame(parent, style="Panel.TFrame", padding=(18, 16, 18, 14))
        container.pack(fill=tk.BOTH, expand=True)

        container.columnconfigure(1, weight=1)
        container.rowconfigure(7, weight=1)

        title_label = ttk.Label(container, text=self._tr("soundcloud.title"), style="Title.TLabel")
        title_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(container, text=self._tr("soundcloud.url"), style="FieldLabel.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.soundcloud_url_entry = ttk.Entry(container, textvariable=self.soundcloud_url_var, style="App.TEntry")
        self.soundcloud_url_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(0, 8))
        self._bind_entry_shortcuts(self.soundcloud_url_entry)

        ttk.Label(container, text=self._tr("soundcloud.format"), style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.soundcloud_format_combo = ttk.Combobox(
            container,
            textvariable=self.soundcloud_format_var,
            values=(),
            state="disabled",
            style="App.TCombobox",
        )
        self.soundcloud_format_combo.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(container, text=self._tr("soundcloud.output_folder"), style="FieldLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 8), padx=(0, 8))
        self.soundcloud_folder_entry = ttk.Entry(container, textvariable=self.soundcloud_output_dir_var, style="App.TEntry")
        self.soundcloud_folder_entry.grid(row=3, column=1, sticky="ew", pady=(0, 8))
        self._bind_entry_shortcuts(self.soundcloud_folder_entry)
        self._register_folder_drop(self.soundcloud_folder_entry, self.soundcloud_output_dir_var)
        self.soundcloud_folder_browse_button = ttk.Button(
            container,
            text=self._tr("button.browse"),
            command=self._choose_soundcloud_directory,
            style="Secondary.TButton",
        )
        self.soundcloud_folder_browse_button.grid(row=3, column=2, sticky="ew", pady=(0, 8), padx=(8, 0))

        self.soundcloud_button = ttk.Button(
            container,
            text=self._tr("button.download_soundcloud"),
            command=self._start_soundcloud_download,
            style="Primary.TButton",
        )
        self.soundcloud_button.grid(row=4, column=0, columnspan=3, sticky="ew")

        self.soundcloud_progress_bar = ttk.Progressbar(
            container,
            orient=tk.HORIZONTAL,
            mode="determinate",
            maximum=100,
            variable=self.soundcloud_progress_var,
            style="Minimal.Horizontal.TProgressbar",
        )
        self.soundcloud_progress_bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 6))

        self.soundcloud_progress_label = ttk.Label(
            container,
            textvariable=self.soundcloud_progress_text_var,
            anchor="w",
            style="Status.TLabel",
        )
        self.soundcloud_progress_label.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 3))

        self.soundcloud_status_label = ttk.Label(
            container,
            textvariable=self.soundcloud_status_var,
            anchor="w",
            style="Status.TLabel",
        )
        self.soundcloud_status_label.grid(row=7, column=0, columnspan=3, sticky="ew")

        self._set_soundcloud_format_options()
        self._set_soundcloud_progress(0.0, self._tr("soundcloud.progress.zero"))

    def _show_empty_state(self, text: str) -> None:
        self._clear_resolution_rows()
        label = ttk.Label(self.options_frame, text=text, style="Body.TLabel")
        label.grid(row=0, column=0, sticky="w")

    def _clear_resolution_rows(self) -> None:
        self.download_buttons.clear()
        for child in self.options_frame.winfo_children():
            child.destroy()

    def _set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        common_state = tk.DISABLED if busy else tk.NORMAL
        self.analyze_button.configure(state=common_state)
        self.browse_button.configure(state=common_state)
        self.add_url_button.configure(state=common_state)
        self.folder_entry.configure(state=common_state)
        self.cookies_profile_entry.configure(state=common_state)
        self.po_token_entry.configure(state=common_state)
        self.cookies_browser_combo.configure(state="disabled" if busy else "readonly")
        for button in self.download_buttons:
            button.configure(state=common_state)

        for entry in self.url_entries:
            entry.configure(state=common_state)

        for remove_button in self.url_remove_buttons:
            remove_button.configure(state=common_state)

        self._refresh_settings_button_state()

    def _set_converter_busy(self, busy: bool) -> None:
        self.converter_is_busy = busy
        common_state = tk.DISABLED if busy else tk.NORMAL
        self.converter_button.configure(state=common_state)
        self.converter_source_entry.configure(state=common_state)
        self.converter_folder_entry.configure(state=common_state)
        self.converter_source_browse_button.configure(state=common_state)
        self.converter_folder_browse_button.configure(state=common_state)
        if busy:
            self.converter_format_combo.configure(state="disabled")
        else:
            self.converter_format_combo.configure(
                state="readonly" if self.converter_format_options else "disabled"
            )

        self._refresh_settings_button_state()

    def _set_soundcloud_busy(self, busy: bool) -> None:
        self.soundcloud_is_busy = busy
        common_state = tk.DISABLED if busy else tk.NORMAL
        self.soundcloud_button.configure(state=common_state)
        self.soundcloud_url_entry.configure(state=common_state)
        self.soundcloud_folder_entry.configure(state=common_state)
        self.soundcloud_folder_browse_button.configure(state=common_state)
        self.soundcloud_format_combo.configure(state="disabled" if busy else "readonly")
        self._refresh_settings_button_state()

    def _on_converter_source_changed(self, _event: tk.Event | None = None) -> None:
        if self.converter_is_busy:
            return
        self._refresh_converter_format_options(show_errors=False)

    def _clear_converter_format_options(self) -> None:
        self.converter_format_options.clear()
        self.converter_format_var.set("")
        self.converter_format_combo.configure(values=(), state="disabled")

    def _set_converter_format_options(self, options: list[tuple[str, str]]) -> None:
        labels: list[str] = []
        self.converter_format_options.clear()
        for target_format, label in options:
            labels.append(label)
            self.converter_format_options[label] = target_format

        self.converter_format_combo.configure(values=tuple(labels))
        current_label = self.converter_format_var.get().strip()
        if current_label not in self.converter_format_options:
            self.converter_format_var.set(labels[0] if labels else "")

        if self.converter_is_busy:
            self.converter_format_combo.configure(state="disabled")
        else:
            self.converter_format_combo.configure(state="readonly" if labels else "disabled")

    def _refresh_converter_format_options(self, show_errors: bool = False) -> bool:
        source_path = self.converter_source_var.get().strip()
        if not source_path:
            self._clear_converter_format_options()
            self.converter_status_var.set(self._tr("converter.status.default"))
            if not self.converter_is_busy:
                self._set_converter_progress(0.0, self._tr("converter.progress.zero"))
            return False

        if not os.path.isfile(source_path):
            self._clear_converter_format_options()
            if show_errors:
                self.converter_status_var.set(self._tr("converter.status.missing_source"))
                messagebox.showerror(
                    self._tr("dialog.invalid_source.title"),
                    self._tr("converter.status.missing_source"),
                )
            else:
                self.converter_status_var.set(self._tr("converter.status.default"))
            if not self.converter_is_busy:
                self._set_converter_progress(0.0, self._tr("converter.progress.zero"))
            return False

        try:
            options = get_available_conversion_targets(source_path)
        except ConversionError as err:
            self._clear_converter_format_options()
            self.converter_status_var.set(self._tr("converter.status.invalid_source"))
            if not self.converter_is_busy:
                self._set_converter_progress(0.0, self._tr("converter.progress.zero"))
            if show_errors:
                messagebox.showerror(self._tr("dialog.invalid_source.title"), str(err))
            return False

        if not options:
            self._clear_converter_format_options()
            self.converter_status_var.set(self._tr("converter.status.no_formats"))
            if not self.converter_is_busy:
                self._set_converter_progress(0.0, self._tr("converter.progress.zero"))
            if show_errors:
                messagebox.showerror(
                    self._tr("dialog.invalid_source.title"),
                    self._tr("dialog.invalid_source.message"),
                )
            return False

        self._set_converter_format_options(options)
        if not self.converter_is_busy:
            self.converter_status_var.set(self._tr("converter.status.default"))
            self._set_converter_progress(0.0, self._tr("converter.progress.zero"))
        return True

    def _selected_converter_target_format(self) -> str | None:
        selected_label = self.converter_format_var.get().strip()
        if not selected_label:
            return None
        return self.converter_format_options.get(selected_label)

    def _set_soundcloud_format_options(self) -> None:
        labels: list[str] = []
        self.soundcloud_format_options.clear()
        for target_format, label in SOUNDCLOUD_AUDIO_FORMATS:
            labels.append(label)
            self.soundcloud_format_options[label] = target_format

        self.soundcloud_format_combo.configure(values=tuple(labels))
        current_label = self.soundcloud_format_var.get().strip()
        if current_label not in self.soundcloud_format_options:
            self.soundcloud_format_var.set(labels[0] if labels else "")
        self.soundcloud_format_combo.configure(state="disabled" if self.soundcloud_is_busy else "readonly")

    def _selected_soundcloud_target_format(self) -> str | None:
        selected_label = self.soundcloud_format_var.get().strip()
        if not selected_label:
            return None
        return self.soundcloud_format_options.get(selected_label)

    def _refresh_settings_button_state(self) -> None:
        if not hasattr(self, "settings_button"):
            return
        state = tk.DISABLED if self.is_busy or self.converter_is_busy or self.soundcloud_is_busy else tk.NORMAL
        self.settings_button.configure(state=state)

    def _refresh_url_rows(self) -> None:
        for index, (entry, remove_button) in enumerate(zip(self.url_entries, self.url_remove_buttons)):
            entry.grid(row=index, column=0, sticky="ew", pady=(0, 4))
            remove_button.grid(row=index, column=1, sticky="e", padx=(6, 0), pady=(0, 4))

        if len(self.url_remove_buttons) <= 1:
            self.url_remove_buttons[0].grid_remove()

        self.add_url_button.grid(row=len(self.url_entries), column=0, columnspan=2, sticky="ew", pady=(2, 0))

    def _add_url_field(self) -> None:
        url_var = tk.StringVar()
        entry = ttk.Entry(self.urls_frame, textvariable=url_var, style="App.TEntry")
        self._bind_entry_shortcuts(entry)
        entry.bind("<KeyRelease>", self._on_url_fields_changed, add="+")

        remove_button = ttk.Button(
            self.urls_frame,
            text="-",
            width=3,
            style="Danger.TButton",
            command=lambda e=entry: self._remove_url_entry(e),
        )

        self.url_vars.append(url_var)
        self.url_entries.append(entry)
        self.url_remove_buttons.append(remove_button)
        self._refresh_url_rows()

        entry.focus_set()

    def _remove_url_entry(self, entry: ttk.Entry) -> None:
        if len(self.url_entries) <= 1:
            self.url_vars[0].set("")
            self.url_entries[0].focus_set()
            self._on_url_fields_changed()
            return

        try:
            index = self.url_entries.index(entry)
        except ValueError:
            return

        self.url_vars.pop(index)
        removed_entry = self.url_entries.pop(index)
        removed_button = self.url_remove_buttons.pop(index)

        removed_entry.destroy()
        removed_button.destroy()

        self._refresh_url_rows()

        if self.url_entries:
            next_index = min(index, len(self.url_entries) - 1)
            self.url_entries[next_index].focus_set()

        self._on_url_fields_changed()

    def _get_filled_urls(self) -> list[str]:
        return [url_var.get().strip() for url_var in self.url_vars if url_var.get().strip()]

    def _on_url_fields_changed(self, _event: tk.Event | None = None) -> None:
        if self.is_busy:
            return

        self.analyzed_url = None
        self.analyzed_auth_signature = None
        self.selector_by_height.clear()

        urls = self._get_filled_urls()
        if len(urls) > 1:
            self._show_batch_ready(len(urls))
            self.status_var.set(self._tr("status.batch_detected"))
            return

        self._show_empty_state(self._tr("downloader.empty"))
        self.status_var.set(self._tr("status.paste_url"))

    def _show_batch_ready(self, url_count: int) -> None:
        self._clear_resolution_rows()

        hint = ttk.Label(
            self.options_frame,
            text=self._tr("downloader.batch_hint", count=url_count),
            style="Body.TLabel",
        )
        hint.grid(row=0, column=0, sticky="w", pady=(0, 6))

        download_all_button = ttk.Button(
            self.options_frame,
            text=self._tr("button.download_all_best"),
            command=self._start_batch_download,
            style="Primary.TButton",
        )
        download_all_button.grid(row=1, column=0, sticky="w")
        self.download_buttons.append(download_all_button)

    def _sanitize_auth_inputs(self, show_warning: bool = True) -> tuple[str | None, str | None, str | None]:
        auth_signature = self._current_auth_signature()
        cookies_browser, cookies_profile, po_token = auth_signature

        if self._normalize_optional_text(self.cookies_profile_var.get()) is None and self.cookies_profile_var.get().strip():
            self.cookies_profile_var.set("")

        if self._normalize_optional_text(self.po_token_var.get()) is None and self.po_token_var.get().strip():
            self.po_token_var.set("")

        if po_token is not None and not self._looks_like_po_token(po_token):
            self.po_token_var.set("")
            po_token = None
            if show_warning:
                messagebox.showwarning(
                    self._tr("dialog.po_ignored.title"),
                    self._tr("dialog.po_ignored.message"),
                )
            self.status_var.set(self._tr("status.invalid_po_ignored"))

        if cookies_browser is None and cookies_profile is not None:
            self.cookies_profile_var.set("")
            cookies_profile = None

        return (cookies_browser, cookies_profile, po_token)

    def _selected_cookies_browser(self) -> str | None:
        value = self.cookies_browser_var.get().strip().lower()
        if not value or value == "none":
            return None
        return value

    @staticmethod
    def _normalize_optional_text(value: str) -> str | None:
        normalized = value.strip()
        if normalized.lower() in {"", "none", "null", "nil", "no", "-"}:
            return None
        return normalized

    @staticmethod
    def _looks_like_po_token(value: str) -> bool:
        token = value.strip()
        if not token:
            return False
        if ".gvs+" in token:
            return True
        return len(token) >= 20 and " " not in token

    def _current_auth_signature(self) -> tuple[str | None, str | None, str | None]:
        cookies_browser = self._selected_cookies_browser()
        cookies_profile = self._normalize_optional_text(self.cookies_profile_var.get())
        po_token = self._normalize_optional_text(self.po_token_var.get())

        if cookies_browser is None:
            cookies_profile = None

        return (cookies_browser, cookies_profile, po_token)

    def _bind_entry_shortcuts(self, entry: ttk.Entry) -> None:
        entry.bind("<Button-3>", self._show_entry_context_menu, add="+")
        entry.bind("<Control-KeyPress>", self._handle_ctrl_keypress, add="+")
        entry.bind("<Shift-Insert>", self._handle_shift_insert, add="+")

    def _register_file_drop(self, widget: tk.Widget, handler: Any) -> None:
        if DND_FILES is None:
            return

        drop_target_register = getattr(widget, "drop_target_register", None)
        dnd_bind = getattr(widget, "dnd_bind", None)
        if not callable(drop_target_register) or not callable(dnd_bind):
            return

        try:
            drop_target_register(DND_FILES)
            dnd_bind("<<Drop>>", handler, add="+")
        except tk.TclError:
            return

    def _register_folder_drop(self, widget: tk.Widget, target_var: tk.StringVar) -> None:
        self._register_file_drop(widget, lambda event, var=target_var: self._handle_folder_drop(event, var))

    def _extract_dropped_paths(self, event: tk.Event) -> list[str]:
        raw_data = str(getattr(event, "data", "")).strip()
        if not raw_data:
            return []

        try:
            raw_paths = self.root.tk.splitlist(raw_data)
        except tk.TclError:
            raw_paths = (raw_data,)

        paths: list[str] = []
        for raw_path in raw_paths:
            normalized = self._normalize_dropped_path(str(raw_path))
            if normalized:
                paths.append(normalized)
        return paths

    @staticmethod
    def _normalize_dropped_path(raw_path: str) -> str:
        path = raw_path.strip().strip("{}")
        if not path:
            return ""

        if path.startswith("file://"):
            parsed = urlparse(path)
            path = unquote(parsed.path)
            if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
                path = path[1:]

        return os.path.abspath(path)

    def _handle_folder_drop(self, event: tk.Event, target_var: tk.StringVar) -> str:
        paths = self._extract_dropped_paths(event)
        path = paths[0] if paths else ""
        if path and os.path.isdir(path):
            target_var.set(path)
            return "break"

        messagebox.showerror(
            self._tr("dialog.drag_drop_folder_required.title"),
            self._tr("dialog.drag_drop_folder_required.message"),
        )
        return "break"

    def _handle_converter_source_drop(self, event: tk.Event) -> str:
        if self.converter_is_busy:
            return "break"

        paths = self._extract_dropped_paths(event)
        path = paths[0] if paths else ""
        if path and os.path.isfile(path):
            self.converter_source_var.set(path)
            self._refresh_converter_format_options(show_errors=True)
            return "break"

        messagebox.showerror(
            self._tr("dialog.drag_drop_file_required.title"),
            self._tr("dialog.drag_drop_file_required.message"),
        )
        return "break"

    def _entry_menu_generate(self, virtual_event: str) -> None:
        if self.entry_menu_target is not None:
            self.entry_menu_target.event_generate(virtual_event)

    def _show_entry_context_menu(self, event: tk.Event) -> str:
        widget = event.widget
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            self.entry_menu_target = widget
            self.entry_context_menu.tk_popup(event.x_root, event.y_root)
            self.entry_context_menu.grab_release()
        return "break"

    def _handle_shift_insert(self, event: tk.Event) -> str:
        widget = event.widget
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.event_generate("<<Paste>>")
        return "break"

    def _handle_ctrl_keypress(self, event: tk.Event) -> str | None:
        widget = event.widget
        if not isinstance(widget, (tk.Entry, ttk.Entry)):
            return None

        keysym = str(event.keysym).lower()
        if keysym == "v" or event.keycode == 86:
            widget.event_generate("<<Paste>>")
            return "break"

        if keysym == "c" or event.keycode == 67:
            widget.event_generate("<<Copy>>")
            return "break"

        if keysym == "x" or event.keycode == 88:
            widget.event_generate("<<Cut>>")
            return "break"

        return None

    def _set_progress(self, percent: float | None, text: str | None = None) -> None:
        if isinstance(percent, (int, float)):
            bounded = max(0.0, min(float(percent), 100.0))
            self.progress_var.set(bounded)
        if text is not None:
            self.progress_text_var.set(text)

    def _set_converter_progress(self, percent: float | None, text: str | None = None) -> None:
        if isinstance(percent, (int, float)):
            bounded = max(0.0, min(float(percent), 100.0))
            self.converter_progress_var.set(bounded)
        if text is not None:
            self.converter_progress_text_var.set(text)

    def _set_soundcloud_progress(self, percent: float | None, text: str | None = None) -> None:
        if isinstance(percent, (int, float)):
            bounded = max(0.0, min(float(percent), 100.0))
            self.soundcloud_progress_var.set(bounded)
        if text is not None:
            self.soundcloud_progress_text_var.set(text)

    def _queue_converter_progress_event(self, event: dict[str, Any]) -> None:
        self.root.after(0, self._on_converter_progress_event, dict(event))

    def _on_converter_progress_event(self, event: dict[str, Any]) -> None:
        stage = str(event.get("stage", "")).strip().lower()
        raw_percent = event.get("percent")
        percent = float(raw_percent) if isinstance(raw_percent, (int, float)) else None

        speed = event.get("speed")
        speed_text = str(speed).strip() if isinstance(speed, str) else ""

        if stage == "preparing":
            self._set_converter_progress(percent if percent is not None else 0.0, self._tr("converter.progress.preparing"))
            return

        if stage == "converting":
            if percent is None:
                text = self._tr("converter.progress.converting")
            else:
                text = self._tr("converter.progress.converting_percent", percent=percent)

            if speed_text and speed_text != "N/A":
                text = f"{text} | {speed_text}"

            self._set_converter_progress(percent, text)
            return

        if stage == "finalizing":
            current = float(self.converter_progress_var.get())
            self._set_converter_progress(max(current, 99.0), self._tr("converter.progress.finalizing"))
            return

        if stage == "done":
            self._set_converter_progress(100.0, self._tr("converter.progress.done"))
            return

    def _queue_soundcloud_progress_event(self, event: dict[str, Any]) -> None:
        self.root.after(0, self._on_soundcloud_progress_event, dict(event))

    def _on_soundcloud_progress_event(self, event: dict[str, Any]) -> None:
        event_name = event.get("event")
        if event_name == "downloading":
            percent = event.get("percent")
            speed_text = self._format_speed(event.get("speed"))
            eta_text = self._format_eta(event.get("eta"))

            status_parts = []
            if isinstance(percent, (int, float)):
                status_parts.append(f"{percent:.1f}%")
            if speed_text:
                status_parts.append(speed_text)
            if eta_text:
                status_parts.append(f"ETA {eta_text}")

            progress_text = self._tr("soundcloud.progress.downloading")
            if status_parts:
                progress_text = f"{self._tr('soundcloud.progress.downloading')} - {' | '.join(status_parts)}"

            self.soundcloud_status_var.set(self._tr("soundcloud.status.downloading"))
            self._set_soundcloud_progress(percent if isinstance(percent, (int, float)) else None, progress_text)
            return

        if event_name == "processing":
            current = float(self.soundcloud_progress_var.get())
            message = str(event.get("message", self._tr("soundcloud.progress.processing")))
            self.soundcloud_status_var.set(self._tr("soundcloud.status.processing"))
            self._set_soundcloud_progress(max(current, 99.0) if current > 0 else current, message)
            return

        if event_name == "item_finished":
            path = event.get("path")
            if isinstance(path, str) and path.strip():
                self.soundcloud_status_var.set(self._tr("soundcloud.status.done", path=path))
            self._set_soundcloud_progress(None, self._tr("soundcloud.progress.finalizing"))
            return

        if event_name == "done":
            self._set_soundcloud_progress(100.0, self._tr("soundcloud.progress.done"))
            return

    @staticmethod
    def _format_speed(speed: Any) -> str:
        if not isinstance(speed, (int, float)) or speed <= 0:
            return ""

        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        value = float(speed)
        unit_index = 0
        while value >= 1024 and unit_index < len(units) - 1:
            value /= 1024
            unit_index += 1
        return f"{value:.1f} {units[unit_index]}"

    @staticmethod
    def _format_eta(eta: Any) -> str:
        if not isinstance(eta, (int, float)) or eta < 0:
            return ""

        total_seconds = int(eta)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"

    def _queue_progress_event(self, event: dict[str, Any]) -> None:
        self.root.after(0, self._on_progress_event, dict(event))

    def _on_progress_event(self, event: dict[str, Any]) -> None:
        event_name = event.get("event")
        if event_name == "downloading":
            percent = event.get("percent")
            speed_text = self._format_speed(event.get("speed"))
            eta_text = self._format_eta(event.get("eta"))

            status_parts = []
            if isinstance(percent, (int, float)):
                status_parts.append(f"{percent:.1f}%")
            if speed_text:
                status_parts.append(speed_text)
            if eta_text:
                status_parts.append(f"ETA {eta_text}")

            progress_text = self._tr("progress.downloading")
            if status_parts:
                progress_text = f"{self._tr('progress.downloading')} - {' | '.join(status_parts)}"

            self._set_progress(percent if isinstance(percent, (int, float)) else None, progress_text)
            return

        if event_name == "processing":
            current = float(self.progress_var.get())
            self._set_progress(max(current, 99.0), str(event.get("message", self._tr("progress.processing"))))
            return

        if event_name == "fallback_height":
            from_height = event.get("from_height")
            to_height = event.get("to_height")
            if isinstance(from_height, int) and isinstance(to_height, int):
                self.status_var.set(self._tr("status.requested_trying", requested=from_height, active=to_height))
                self._set_progress(None, self._tr("progress.switching", from_height=from_height, to_height=to_height))
            return

        if event_name == "retry":
            self._set_progress(None, str(event.get("message", self._tr("progress.retry_stream"))))
            return

        if event_name == "auth_fallback":
            self.status_var.set(self._tr("status.retry_no_cookies"))
            self._set_progress(None, str(event.get("message", self._tr("progress.retry_no_cookies"))))
            return

        if event_name == "trying_resolution":
            requested_height = event.get("requested_height")
            active_height = event.get("active_height")
            if isinstance(requested_height, int) and isinstance(active_height, int):
                if requested_height == active_height:
                    self.status_var.set(self._tr("status.downloading_height", height=active_height))
                else:
                    self.status_var.set(self._tr("status.requested_trying", requested=requested_height, active=active_height))
            return

    def _choose_directory(self) -> str | None:
        selected = filedialog.askdirectory(title=self._tr("dialog.select_folder"))
        if selected:
            self.output_dir_var.set(selected)
            return selected
        return None

    def _require_directory(self) -> str | None:
        current = self.output_dir_var.get().strip()
        if current:
            return current

        while True:
            selected = self._choose_directory()
            if selected:
                return selected

            retry = messagebox.askretrycancel(
                self._tr("dialog.folder_required.title"),
                self._tr("dialog.folder_required.download"),
            )
            if not retry:
                return None

    def _choose_converter_source(self) -> str | None:
        selected = filedialog.askopenfilename(
            title=self._tr("dialog.select_mkv_file"),
            filetypes=((self._tr("dialog.filetype_all"), "*.*"),),
        )
        if selected:
            self.converter_source_var.set(selected)
            self._refresh_converter_format_options(show_errors=True)
            return selected
        return None

    def _choose_converter_directory(self) -> str | None:
        selected = filedialog.askdirectory(title=self._tr("dialog.select_folder"))
        if selected:
            self.converter_output_dir_var.set(selected)
            return selected
        return None

    def _choose_soundcloud_directory(self) -> str | None:
        selected = filedialog.askdirectory(title=self._tr("dialog.select_folder"))
        if selected:
            self.soundcloud_output_dir_var.set(selected)
            return selected
        return None

    def _require_converter_directory(self) -> str | None:
        current = self.converter_output_dir_var.get().strip()
        if current:
            return current

        while True:
            selected = self._choose_converter_directory()
            if selected:
                return selected

            retry = messagebox.askretrycancel(
                self._tr("dialog.folder_required.title"),
                self._tr("dialog.folder_required.convert"),
            )
            if not retry:
                return None

    def _require_soundcloud_directory(self) -> str | None:
        current = self.soundcloud_output_dir_var.get().strip()
        if current:
            return current

        while True:
            selected = self._choose_soundcloud_directory()
            if selected:
                return selected

            retry = messagebox.askretrycancel(
                self._tr("dialog.folder_required.title"),
                self._tr("dialog.folder_required.soundcloud"),
            )
            if not retry:
                return None

    def _start_conversion(self) -> None:
        if self.converter_is_busy:
            return

        source_path = self.converter_source_var.get().strip()
        if not source_path:
            messagebox.showerror(self._tr("dialog.source_required.title"), self._tr("dialog.source_required.message"))
            self.converter_status_var.set(self._tr("converter.status.missing_source"))
            return

        if not self._refresh_converter_format_options(show_errors=True):
            return

        target_format = self._selected_converter_target_format()
        if target_format is None:
            messagebox.showerror(self._tr("dialog.format_required.title"), self._tr("dialog.format_required.message"))
            self.converter_status_var.set(self._tr("converter.status.no_formats"))
            return

        output_dir = self._require_converter_directory()
        if not output_dir:
            self.converter_status_var.set(self._tr("converter.status.canceled_no_folder"))
            return

        self._set_converter_busy(True)
        self._set_converter_progress(0.0, self._tr("converter.progress.preparing"))
        self.converter_status_var.set(self._tr("converter.status.converting"))
        threading.Thread(
            target=self._conversion_worker,
            args=(source_path, output_dir, target_format),
            daemon=True,
        ).start()

    def _conversion_worker(self, source_path: str, output_dir: str, target_format: str) -> None:
        try:
            output_paths = convert_media(
                source_path,
                output_dir,
                target_format=target_format,
                mp3_quality_preset="balanced",
                progress_callback=self._queue_converter_progress_event,
            )
        except ConversionError as err:
            self.root.after(0, self._on_conversion_failed, str(err))
            return
        except Exception as err:
            self.root.after(0, self._on_conversion_failed, str(err))
            return

        self.root.after(0, self._on_conversion_success, output_paths)

    def _on_conversion_success(self, output_paths: str | list[str]) -> None:
        if isinstance(output_paths, str):
            normalized_paths = [output_paths]
        else:
            normalized_paths = [path for path in output_paths if isinstance(path, str) and path.strip()]

        if not normalized_paths:
            self._on_conversion_failed("Conversion finished, but no output files were created.")
            return

        if len(normalized_paths) == 1:
            summary_path = normalized_paths[0]
            details_text = self._tr("dialog.conversion_complete.message", path=summary_path)
        else:
            output_dir = os.path.dirname(normalized_paths[0])
            if self.language_code == "ru":
                summary_path = f"{len(normalized_paths)} файлов в {output_dir}"
                details_header = f"Файлы созданы: {len(normalized_paths)}"
            else:
                summary_path = f"{len(normalized_paths)} files in {output_dir}"
                details_header = f"Files created: {len(normalized_paths)}"

            preview_count = 10
            listed_paths = normalized_paths[:preview_count]
            details_lines = [details_header, *listed_paths]
            remaining = len(normalized_paths) - preview_count
            if remaining > 0:
                details_lines.append(f"... (+{remaining})")
            details_text = "\n".join(details_lines)

        self._set_converter_busy(False)
        self._set_converter_progress(100.0, self._tr("converter.progress.done"))
        self.converter_status_var.set(self._tr("converter.status.done", path=summary_path))
        messagebox.showinfo(
            self._tr("dialog.conversion_complete.title"),
            details_text,
        )

    def _on_conversion_failed(self, error_text: str) -> None:
        self._set_converter_busy(False)
        current = float(self.converter_progress_var.get())
        self._set_converter_progress(current, self._tr("converter.progress.failed"))
        self.converter_status_var.set(self._tr("converter.status.failed"))
        messagebox.showerror(self._tr("dialog.conversion_failed.title"), error_text)

    def _start_soundcloud_download(self) -> None:
        if self.soundcloud_is_busy:
            return

        url = self.soundcloud_url_var.get().strip()
        if not url:
            messagebox.showerror(
                self._tr("dialog.soundcloud_url_required.title"),
                self._tr("dialog.soundcloud_url_required.message"),
            )
            self.soundcloud_status_var.set(self._tr("soundcloud.status.missing_url"))
            return

        target_format = self._selected_soundcloud_target_format()
        if target_format is None:
            messagebox.showerror(
                self._tr("dialog.soundcloud_format_required.title"),
                self._tr("dialog.soundcloud_format_required.message"),
            )
            self.soundcloud_status_var.set(self._tr("soundcloud.status.failed"))
            return

        output_dir = self._require_soundcloud_directory()
        if not output_dir:
            self.soundcloud_status_var.set(self._tr("soundcloud.status.missing_folder"))
            return

        self._set_soundcloud_busy(True)
        self._set_soundcloud_progress(0.0, self._tr("soundcloud.progress.processing"))
        self.soundcloud_status_var.set(self._tr("soundcloud.status.downloading"))
        threading.Thread(
            target=self._soundcloud_download_worker,
            args=(url, output_dir, target_format),
            daemon=True,
        ).start()

    def _soundcloud_download_worker(self, url: str, output_dir: str, target_format: str) -> None:
        try:
            output_paths = download_soundcloud_audio(
                url=url,
                out_dir=output_dir,
                target_format=target_format,
                progress_callback=self._queue_soundcloud_progress_event,
            )
        except DownloadError as err:
            self.root.after(0, self._on_soundcloud_download_failed, str(err))
            return
        except Exception as err:
            self.root.after(0, self._on_soundcloud_download_failed, str(err))
            return

        self.root.after(0, self._on_soundcloud_download_success, output_paths)

    def _on_soundcloud_download_success(self, output_paths: list[str]) -> None:
        normalized_paths = [path for path in output_paths if isinstance(path, str) and path.strip()]
        if not normalized_paths:
            self._on_soundcloud_download_failed("Download finished, but no output files were created.")
            return

        if len(normalized_paths) == 1:
            summary_path = normalized_paths[0]
            details_text = self._tr("dialog.soundcloud_complete.message", path=summary_path)
        else:
            output_dir = os.path.dirname(normalized_paths[0])
            if self.language_code == "ru":
                summary_path = f"{len(normalized_paths)} \u0444\u0430\u0439\u043b\u043e\u0432 \u0432 {output_dir}"
                details_header = f"\u0424\u0430\u0439\u043b\u044b \u0441\u043e\u0437\u0434\u0430\u043d\u044b: {len(normalized_paths)}"
            else:
                summary_path = f"{len(normalized_paths)} files in {output_dir}"
                details_header = f"Files created: {len(normalized_paths)}"

            preview_count = 10
            listed_paths = normalized_paths[:preview_count]
            details_lines = [details_header, *listed_paths]
            remaining = len(normalized_paths) - preview_count
            if remaining > 0:
                details_lines.append(f"... (+{remaining})")
            details_text = "\n".join(details_lines)

        self._set_soundcloud_busy(False)
        self._set_soundcloud_progress(100.0, self._tr("soundcloud.progress.done"))
        self.soundcloud_status_var.set(self._tr("soundcloud.status.done", path=summary_path))
        messagebox.showinfo(self._tr("dialog.soundcloud_complete.title"), details_text)

    def _on_soundcloud_download_failed(self, error_text: str) -> None:
        self._set_soundcloud_busy(False)
        current = float(self.soundcloud_progress_var.get())
        self._set_soundcloud_progress(current, self._tr("soundcloud.progress.failed"))
        self.soundcloud_status_var.set(self._tr("soundcloud.status.failed"))
        messagebox.showerror(self._tr("dialog.soundcloud_failed.title"), self._friendly_error_text(error_text))

    def _start_analysis(self) -> None:
        if self.is_busy:
            return

        urls = self._get_filled_urls()
        if not urls:
            messagebox.showerror(self._tr("dialog.url_required.title"), self._tr("dialog.url_required.message"))
            return

        auth_signature = self._sanitize_auth_inputs(show_warning=True)

        if len(urls) > 1:
            self.analyzed_url = None
            self.analyzed_auth_signature = auth_signature
            self.selector_by_height.clear()
            self._set_progress(0.0, self._tr("progress.zero"))
            self._show_batch_ready(len(urls))
            self.status_var.set(self._tr("status.batch_ready"))
            return

        url = urls[0]

        self.analyzed_url = None
        self.analyzed_auth_signature = None
        self.selector_by_height.clear()
        self._show_empty_state(self._tr("status.analyzing"))
        self._set_progress(0.0, self._tr("progress.zero"))
        self.status_var.set(self._tr("status.analyzing"))
        self._set_busy(True)

        threading.Thread(target=self._analyze_worker, args=(url, auth_signature), daemon=True).start()

    def _analyze_worker(self, url: str, auth_signature: tuple[str | None, str | None, str | None]) -> None:
        cookies_browser, cookies_profile, po_token = auth_signature
        try:
            options = get_downloadable_resolutions(
                url,
                cookies_browser=cookies_browser,
                cookies_profile=cookies_profile,
                po_token=po_token,
                verify_streams=False,
            )
        except Exception as err:
            self.root.after(0, self._on_analyze_failed, str(err))
            return

        best_height: int | None = None
        try:
            best_height = get_best_available_resolution(
                url,
                cookies_browser=cookies_browser,
                cookies_profile=cookies_profile,
                po_token=po_token,
            )
        except Exception:
            best_height = None

        self.root.after(0, self._on_analyze_success, url, auth_signature, options, best_height)

    def _on_analyze_success(
        self,
        url: str,
        auth_signature: tuple[str | None, str | None, str | None],
        options: list[tuple[int, str]],
        best_height: int | None,
    ) -> None:
        self._set_busy(False)

        sorted_options = sorted(options, key=lambda item: item[0], reverse=True)
        display_best_height = best_height
        if display_best_height is None and sorted_options:
            display_best_height = sorted_options[0][0]

        if display_best_height is None and not sorted_options:
            self.selector_by_height.clear()
            self.analyzed_auth_signature = None
            self._show_empty_state(self._tr("status.no_resolutions"))
            self.status_var.set(self._tr("status.no_resolutions"))
            return

        self.analyzed_url = url
        self.analyzed_auth_signature = auth_signature
        self.selector_by_height = {height: selector for height, selector in sorted_options}
        self._clear_resolution_rows()

        best_row = ttk.Frame(self.options_frame, style="SubPanel.TFrame")
        best_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        best_row.columnconfigure(0, weight=1)

        best_label = ttk.Label(best_row, text=self._tr("downloader.best_available", height=display_best_height), style="Body.TLabel")
        best_label.grid(row=0, column=0, sticky="w")

        best_button = ttk.Button(best_row, text=self._tr("button.download_best"), command=self._start_best_download, style="Primary.TButton")
        best_button.grid(row=0, column=1, sticky="e")
        self.download_buttons.append(best_button)

        for index, (height, _selector) in enumerate(sorted_options, start=1):
            row = ttk.Frame(self.options_frame, style="SubPanel.TFrame")
            row.grid(row=index, column=0, sticky="ew", pady=2)
            row.columnconfigure(0, weight=1)

            label = ttk.Label(row, text=f"{height}p", style="Body.TLabel")
            label.grid(row=0, column=0, sticky="w")

            button = ttk.Button(row, text=self._tr("button.download"), command=lambda h=height: self._start_download(h), style="Secondary.TButton")
            button.grid(row=0, column=1, sticky="e")
            self.download_buttons.append(button)

        self.status_var.set(self._tr("status.select_resolution"))

    def _friendly_error_text(self, error_text: str) -> str:
        cleaned = re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", error_text)
        cleaned = cleaned.replace("\r", "").strip()
        lowered = cleaned.lower()

        if "could not find firefox cookies database" in lowered:
            return self._tr("friendly.firefox_cookies")

        if "could not copy chrome cookie database" in lowered:
            return self._tr("friendly.browser_cookies")

        if "failed to decrypt with dpapi" in lowered:
            return self._tr("friendly.dpapi")

        if "http error 403: forbidden" in lowered:
            return self._tr("friendly.http403")

        if "downloaded file is empty" in lowered or "fragment not found" in lowered:
            return self._tr("friendly.empty_stream")

        return cleaned

    def _on_analyze_failed(self, error_text: str) -> None:
        self._set_busy(False)
        self._show_empty_state(self._tr("status.analyze_failed"))
        self.status_var.set(self._tr("status.analyze_failed"))
        messagebox.showerror(self._tr("dialog.analyze_failed.title"), self._friendly_error_text(error_text))

    def _start_batch_download(self) -> None:
        if self.is_busy:
            return

        urls = self._get_filled_urls()
        if len(urls) < 2:
            messagebox.showinfo(self._tr("dialog.batch_mode.title"), self._tr("dialog.batch_mode.need_two"))
            return

        output_dir = self._require_directory()
        if not output_dir:
            self.status_var.set(self._tr("status.download_canceled_no_folder"))
            return

        cookies_browser, cookies_profile, po_token = self._sanitize_auth_inputs(show_warning=True)

        self._set_busy(True)
        self._set_progress(0.0, self._tr("progress.batch_start", total=len(urls)))
        self.status_var.set(self._tr("status.batch_started", total=len(urls)))
        threading.Thread(
            target=self._batch_download_worker,
            args=(urls, output_dir, cookies_browser, cookies_profile, po_token),
            daemon=True,
        ).start()

    def _batch_download_worker(
        self,
        urls: list[str],
        output_dir: str,
        cookies_browser: str | None,
        cookies_profile: str | None,
        po_token: str | None,
    ) -> None:
        results: list[tuple[str, bool, int | None, str | None]] = []
        total = len(urls)

        for index, url in enumerate(urls, start=1):
            self.root.after(0, self._on_batch_item_start, index, total)
            try:
                used_height = download_best_available(
                    url=url,
                    out_dir=output_dir,
                    cookies_browser=cookies_browser,
                    cookies_profile=cookies_profile,
                    po_token=po_token,
                    progress_callback=self._queue_progress_event,
                )
                results.append((url, True, used_height, None))
            except Exception as err:
                results.append((url, False, None, str(err)))
                self.root.after(0, self._on_batch_item_failed, index, total, str(err))

        self.root.after(0, self._on_batch_download_complete, total, output_dir, results)

    def _on_batch_item_start(self, index: int, total: int) -> None:
        self._set_progress(0.0, self._tr("progress.batch_downloading", index=index, total=total))
        self.status_var.set(self._tr("status.batch_downloading_video", index=index, total=total))

    def _on_batch_item_failed(self, index: int, total: int, error_text: str) -> None:
        self._set_progress(float(self.progress_var.get()), self._tr("status.batch_video_failed", index=index, total=total))
        self.status_var.set(self._tr("status.batch_video_failed", index=index, total=total))
        _ = self._friendly_error_text(error_text)

    def _on_batch_download_complete(
        self,
        total: int,
        output_dir: str,
        results: list[tuple[str, bool, int | None, str | None]],
    ) -> None:
        self._set_busy(False)
        success_count = sum(1 for _url, ok, _height, _err in results if ok)
        failed_count = total - success_count

        if success_count > 0:
            self._set_progress(100.0, self._tr("progress.batch_complete"))
        else:
            self._set_progress(float(self.progress_var.get()), self._tr("progress.batch_failed"))

        self.status_var.set(self._tr("status.batch_complete", done=success_count, total=total))

        if failed_count == 0:
            messagebox.showinfo(
                self._tr("dialog.batch_complete.title"),
                self._tr("dialog.batch_complete.message", count=success_count, path=output_dir),
            )
            return

        failed_examples = [
            self._friendly_error_text(err or "Unknown error")
            for _url, ok, _height, err in results
            if not ok
        ]
        preview = "\n".join(f"- {text}" for text in failed_examples[:3])
        messagebox.showwarning(
            self._tr("dialog.batch_complete_with_errors.title"),
            self._tr(
                "dialog.batch_complete_with_errors.message",
                done=success_count,
                total=total,
                failed=failed_count,
                preview=preview,
            ),
        )

    def _start_best_download(self) -> None:
        if self.is_busy:
            return

        output_dir = self._require_directory()
        if not output_dir:
            self.status_var.set(self._tr("status.download_canceled_no_folder"))
            return

        urls = self._get_filled_urls()
        if not urls:
            messagebox.showerror(self._tr("dialog.url_required.title"), self._tr("dialog.url_required.message"))
            self.status_var.set(self._tr("status.download_failed_empty_url"))
            return

        if len(urls) > 1:
            messagebox.showinfo(self._tr("dialog.batch_mode.title"), self._tr("dialog.batch_mode.use_button"))
            self.status_var.set(self._tr("status.batch_mode_active"))
            return

        url = urls[0]
        current_auth_signature = self._sanitize_auth_inputs(show_warning=False)

        if self.analyzed_url != url:
            messagebox.showinfo(self._tr("dialog.analyze_required.title"), self._tr("dialog.analyze_required.url_changed"))
            self.status_var.set(self._tr("status.analyze_current_url"))
            return

        if self.analyzed_auth_signature != current_auth_signature:
            messagebox.showinfo(self._tr("dialog.analyze_required.title"), self._tr("dialog.analyze_required.auth_changed"))
            self.status_var.set(self._tr("status.analyze_current_url"))
            return

        if self.analyzed_auth_signature is None:
            messagebox.showinfo(self._tr("dialog.analyze_required.title"), self._tr("dialog.analyze_required.auth_missing"))
            self.status_var.set(self._tr("status.analyze_current_url"))
            return

        cookies_browser, cookies_profile, po_token = self.analyzed_auth_signature

        self._set_busy(True)
        self._set_progress(0.0, self._tr("progress.starting_best"))
        self.status_var.set(self._tr("status.downloading_best"))
        threading.Thread(
            target=self._best_download_worker,
            args=(url, output_dir, cookies_browser, cookies_profile, po_token),
            daemon=True,
        ).start()

    def _best_download_worker(
        self,
        url: str,
        output_dir: str,
        cookies_browser: str | None,
        cookies_profile: str | None,
        po_token: str | None,
    ) -> None:
        try:
            actual_height = download_best_available(
                url=url,
                out_dir=output_dir,
                cookies_browser=cookies_browser,
                cookies_profile=cookies_profile,
                po_token=po_token,
                progress_callback=self._queue_progress_event,
            )
        except DownloadError as err:
            self.root.after(0, self._on_best_download_failed, str(err))
            return
        except Exception as err:
            self.root.after(0, self._on_best_download_failed, str(err))
            return

        self.root.after(0, self._on_best_download_success, actual_height, output_dir)

    def _on_best_download_success(self, actual_height: int, output_dir: str) -> None:
        self._set_busy(False)
        self._set_progress(100.0, self._tr("progress.download_complete"))
        self.status_var.set(self._tr("status.done_best", height=actual_height, path=output_dir))
        messagebox.showinfo(
            self._tr("dialog.download_complete.title"),
            self._tr("dialog.download_complete.best", height=actual_height, path=output_dir),
        )

    def _on_best_download_failed(self, error_text: str) -> None:
        self._set_busy(False)
        current = float(self.progress_var.get())
        self._set_progress(current, self._tr("progress.download_failed"))
        self.status_var.set(self._tr("status.download_failed"))
        friendly_error = self._friendly_error_text(error_text)
        messagebox.showerror(
            self._tr("dialog.download_failed.title"),
            self._tr("dialog.download_failed.best", error=friendly_error),
        )

    def _start_download(self, height: int) -> None:
        if self.is_busy:
            return

        output_dir = self._require_directory()
        if not output_dir:
            self.status_var.set(self._tr("status.download_canceled_no_folder"))
            return

        urls = self._get_filled_urls()
        if not urls:
            messagebox.showerror(self._tr("dialog.url_required.title"), self._tr("dialog.url_required.message"))
            self.status_var.set(self._tr("status.download_failed_empty_url"))
            return

        if len(urls) > 1:
            messagebox.showinfo(self._tr("dialog.batch_mode.title"), self._tr("dialog.batch_mode.use_button"))
            self.status_var.set(self._tr("status.batch_mode_active"))
            return

        url = urls[0]

        current_auth_signature = self._sanitize_auth_inputs(show_warning=False)

        if self.analyzed_url != url:
            messagebox.showinfo(self._tr("dialog.analyze_required.title"), self._tr("dialog.analyze_required.url_changed"))
            self.status_var.set(self._tr("status.analyze_current_url"))
            return

        if self.analyzed_auth_signature != current_auth_signature:
            messagebox.showinfo(self._tr("dialog.analyze_required.title"), self._tr("dialog.analyze_required.auth_changed"))
            self.status_var.set(self._tr("status.analyze_current_url"))
            return

        if self.analyzed_auth_signature is None:
            messagebox.showinfo(self._tr("dialog.analyze_required.title"), self._tr("dialog.analyze_required.auth_missing"))
            self.status_var.set(self._tr("status.analyze_current_url"))
            return

        cookies_browser, cookies_profile, po_token = self.analyzed_auth_signature

        selector = self.selector_by_height.get(height)
        if not selector:
            messagebox.showinfo(self._tr("dialog.analyze_required.title"), self._tr("dialog.analyze_required.stream_missing"))
            self.status_var.set(self._tr("status.analyze_current_url"))
            return

        self._set_busy(True)
        self._set_progress(0.0, self._tr("progress.starting_height", height=height))
        self.status_var.set(self._tr("status.downloading_height", height=height))
        threading.Thread(
            target=self._download_worker,
            args=(url, output_dir, height, selector, cookies_browser, cookies_profile, po_token),
            daemon=True,
        ).start()

    def _download_worker(
        self,
        url: str,
        output_dir: str,
        height: int,
        selector: str,
        cookies_browser: str | None,
        cookies_profile: str | None,
        po_token: str | None,
    ) -> None:
        try:
            actual_height = download_resolution(
                url=url,
                out_dir=output_dir,
                height=height,
                format_selector=selector,
                cookies_browser=cookies_browser,
                cookies_profile=cookies_profile,
                po_token=po_token,
                progress_callback=self._queue_progress_event,
            )
        except DownloadError as err:
            self.root.after(0, self._on_download_failed, height, str(err))
            return
        except Exception as err:
            self.root.after(0, self._on_download_failed, height, str(err))
            return

        self.root.after(0, self._on_download_success, height, actual_height, output_dir)

    def _on_download_success(self, requested_height: int, actual_height: int, output_dir: str) -> None:
        self._set_busy(False)
        self._set_progress(100.0, self._tr("progress.download_complete"))

        if requested_height == actual_height:
            self.status_var.set(self._tr("status.done_exact", height=actual_height, path=output_dir))
            messagebox.showinfo(
                self._tr("dialog.download_complete.title"),
                self._tr("dialog.download_complete.exact", height=actual_height, path=output_dir),
            )
            return

        self.status_var.set(self._tr("status.done_fallback", requested=requested_height, actual=actual_height, path=output_dir))
        messagebox.showinfo(
            self._tr("dialog.download_complete.title"),
            self._tr("dialog.download_complete.fallback", requested=requested_height, actual=actual_height, path=output_dir),
        )

    def _on_download_failed(self, height: int, error_text: str) -> None:
        self._set_busy(False)
        current = float(self.progress_var.get())
        self._set_progress(current, self._tr("progress.download_failed"))
        self.status_var.set(self._tr("status.download_failed"))
        friendly_error = self._friendly_error_text(error_text)
        messagebox.showerror(
            self._tr("dialog.download_failed.title"),
            self._tr("dialog.download_failed.message", height=height, error=friendly_error),
        )


def main() -> None:
    if TkinterDnD is not None:
        try:
            root = TkinterDnD.Tk()
        except tk.TclError:
            root = tk.Tk()
    else:
        root = tk.Tk()
    app = YouTubeDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
