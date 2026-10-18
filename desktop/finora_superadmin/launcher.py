"""Finora Superadmin desktop client for Windows."""

from __future__ import annotations

import ctypes
import base64
import json
import os
import sys
import traceback
from pathlib import Path

import webview


APP_NAME = "Finora Superadmin"
APP_ID = "Finora.Superadmin.Desktop.1"
DEFAULT_URL = "https://finora.company/superadmin/"
BACKGROUND = "#0b1220"


def _local_app_data() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Finora" / "Superadmin"


def _resource_path(filename: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / filename


def _message(text: str, title: str = APP_NAME, error: bool = False) -> None:
    flags = 0x10 if error else 0x40
    ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def _acquire_single_instance():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\FinoraSuperadminDesktop")
    if ctypes.windll.kernel32.GetLastError() == 183:
        _message("تطبيق Finora Superadmin مفتوح مسبقاً.")
        return None
    return mutex


def _write_crash_log() -> None:
    try:
        log_dir = _local_app_data()
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "crash.log").write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    if sys.platform != "win32":
        raise RuntimeError("This desktop package is intended for Windows.")

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    mutex = _acquire_single_instance()
    if not mutex:
        return 0

    storage_dir = _local_app_data() / "WebViewProfile"
    storage_dir.mkdir(parents=True, exist_ok=True)
    app_url = os.environ.get("FINORA_SUPERADMIN_URL", DEFAULT_URL).strip() or DEFAULT_URL
    logo_data_uri = "data:image/x-icon;base64," + base64.b64encode(
        _resource_path("finora-superadmin.ico").read_bytes()
    ).decode("ascii")

    try:
        window = webview.create_window(
            APP_NAME,
            url=app_url,
            width=1440,
            height=920,
            min_size=(390, 680),
            resizable=True,
            maximized=True,
            background_color=BACKGROUND,
            text_select=True,
            zoomable=False,
        )

        def mark_desktop_client() -> None:
            try:
                window.evaluate_js(
                    "document.documentElement.classList.add('finora-desktop-app');"
                    "document.documentElement.dataset.finoraClient='desktop';"
                    f"const finoraDesktopLogo={json.dumps(logo_data_uri)};"
                    "document.querySelectorAll('.sa-login-icon,.sa-brand-icon').forEach((box)=>{"
                    "box.innerHTML='';box.style.background='#071a42';box.style.overflow='hidden';"
                    "const img=document.createElement('img');img.src=finoraDesktopLogo;img.alt='Finora';"
                    "img.style.cssText='width:94%;height:94%;display:block;object-fit:contain';box.appendChild(img);"
                    "});"
                    "document.querySelectorAll('link[rel~=icon]').forEach((link)=>link.href=finoraDesktopLogo);"
                )
            except Exception:
                pass

        window.events.loaded += mark_desktop_client
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(storage_dir),
            user_agent="FinoraSuperadminDesktop/1.0 Windows",
            icon=str(_resource_path("finora-superadmin.ico")),
        )
        return 0
    except Exception:
        _write_crash_log()
        _message(
            "تعذّر تشغيل Finora Superadmin.\n"
            "تأكد من اتصال الإنترنت وأعد فتح التطبيق.",
            error=True,
        )
        return 1
    finally:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
