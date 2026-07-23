import json
import os
import posixpath
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
import queue
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime

CONFIG_FILE = Path("finora_deploy_config.json")

SSH_CONNECT_OPTIONS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ConnectionAttempts=1",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=4",
]


def _resolve_command(command_name: str) -> str:
    """Return a runnable command path, including Windows' built-in OpenSSH path."""
    found = shutil.which(command_name)
    if found:
        return found
    if os.name == "nt" and command_name.lower() in {"ssh", "sftp"}:
        exe_name = f"{command_name}.exe"
        candidates = [
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "OpenSSH" / exe_name,
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Sysnative" / "OpenSSH" / exe_name,
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
    return command_name


def _format_file_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"

# Windows may ignore subprocess encoding= and still use cp1252 — read bytes, decode as UTF-8.
def _decode_output_chunk(chunk) -> str:
    if chunk is None:
        return ""
    if isinstance(chunk, str):
        return chunk
    return chunk.decode("utf-8", errors="replace")


def _stream_pipe_lines(pipe, on_line) -> None:
    if pipe is None:
        return
    while True:
        raw = pipe.readline()
        if not raw:
            break
        line = _decode_output_chunk(raw)
        if not line.endswith("\n"):
            line += "\n"
        on_line(line)


def _decode_paramiko_line(line) -> str:
    text = _decode_output_chunk(line)
    return text if text.endswith("\n") else text + "\n"

SAFE_PUSH_EXCLUDED_PARTS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "logs",
    "instance",
    "tenants",
    "uploads",
    "outputs",
    "playwright-report",
    "test-results",
    ".pytest_cache",
    ".dart_tool",
    ".gradle",
    ".idea",
    "artifacts",
    "backups",
    "build",
    "coverage",
    "dist",
    "downloads",
    "mobile",
}

SAFE_PUSH_EXCLUDED_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".err",
    ".out",
    ".tmp",
    ".pyc",
    ".apk",
    ".aab",
    ".ipa",
    ".tgz",
    ".zip",
}

SAFE_PUSH_EXCLUDED_NAME_ENDINGS = (
    ".db-wal",
    ".db-shm",
    ".sqlite-wal",
    ".sqlite-shm",
    ".sqlite3-wal",
    ".sqlite3-shm",
)

SMART_DEPLOY_MAX_BYTES = 50 * 1024 * 1024
REMOTE_DEPLOY_MANIFEST = ".finora-smart-deploy-manifest.tsv"

SAFE_PUSH_EXCLUDED_FILES = {
    ".env",
    ".env.local",
    "database.db",
    "debug-180817.log",
    "finora_deploy_config.json",
    # Desktop-only deployment UI; never copy it into the Linux application.
    "finora_deploy_studio.py",
    "nexus-execution.log",
    "nexus-workflows.json",
    "supermaxi",
    "t",
    # Runtime learning memory is written by the live application. It must not
    # be uploaded from a developer machine or treated as deployable source.
    "learned_areas.json",
    "learned_cities.json",
}

REMOTE_RUNTIME_MUTABLE_TRACKED_FILES = (
    "ai/learned_areas.json",
    "ai/learned_cities.json",
)


DEFAULT_CONFIG = {
    "local_project_path": str(Path.cwd()),
    "server_ssh": "root@187.124.29.5",
    "server_project_path": "/var/www/finora/supermaxi",
    "nginx_service": "nginx",
    "gunicorn_bind": "127.0.0.1:8000",
    "gunicorn_workers": 3,
    "logs_command": "journalctl -u nginx -n 100 --no-pager",
    "last_deployed_commit": "",
    "adb_path": "adb",
    "flutter_path": "",
    "android_apk_path": "",
    "android_app_target": "Social (finora_social)",
    "social_api_base_url": "https://www.finora.company",
    "social_tenant_slug": "super",
    # كلمة السر لا نحفظها في الملف لأسباب أمان، تبقى فارغة في كل تشغيل
}


class FinoraDeployStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Finora Deploy Studio")
        self.geometry("1040x720")
        self.minsize(960, 620)

        self.config_data = self.load_config()

        # Self Healing Monitor state
        self.monitor_thread: "ServerMonitorThread | None" = None
        self.monitor_queue: "queue.Queue[dict]" = queue.Queue()
        self.monitor_running = False
        self.monitor_last_status: dict[str, str] = {}

        self.configure(bg="#0f172a")
        self.style = ttk.Style(self)
        self._setup_theme()

        self._build_ui()

    # ---------- Theme / UI ----------

    def _setup_theme(self) -> None:
        # Dark theme
        self.style.theme_use("clam")
        self.style.configure(
            "TLabel",
            background="#0f172a",
            foreground="#e5e7eb",
        )
        self.style.configure(
            "TEntry",
            fieldbackground="#020617",
            foreground="#e5e7eb",
            bordercolor="#1e293b",
        )
        self.style.configure(
            "TButton",
            background="#1e293b",
            foreground="#e5e7eb",
            padding=6,
        )
        self.style.map(
            "TButton",
            background=[("active", "#2563eb"), ("disabled", "#1e293b")],
            foreground=[("active", "#f9fafb"), ("disabled", "#64748b")],
        )

    def _build_ui(self) -> None:
        # Header
        header = ttk.Frame(self)
        header.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(8, 4))
        title_label = ttk.Label(header, text="Finora Deploy Studio", font=("Segoe UI", 11, "bold"))
        title_label.pack(side=tk.LEFT)
        self.current_config_label = ttk.Label(
            header,
            text=f"Project: {self.config_data['local_project_path']}",
            font=("Segoe UI", 8),
        )
        self.current_config_label.pack(side=tk.RIGHT)

        # Top frame: server + android configuration
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)

        # Server config
        cfg = ttk.LabelFrame(top, text="Server Configuration")
        cfg.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # Local project path
        self.local_path_var = tk.StringVar(value=self.config_data["local_project_path"])
        ttk.Label(cfg, text="Local project path:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        local_entry = ttk.Entry(cfg, textvariable=self.local_path_var, width=60, justify="center")
        local_entry.grid(row=0, column=1, sticky="we", padx=(0, 4), pady=4)
        browse_btn = ttk.Button(cfg, text="Browse…", command=self.browse_local_path)
        browse_btn.grid(row=0, column=2, sticky="e", padx=(0, 6), pady=4)

        # Server SSH
        self.server_ssh_var = tk.StringVar(value=self.config_data["server_ssh"])
        ttk.Label(cfg, text="Server SSH (user@host):").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(cfg, textvariable=self.server_ssh_var, justify="center").grid(
            row=1, column=1, columnspan=2, sticky="we", padx=(0, 6), pady=4
        )

        # Server password (اختياري – لا يُحفظ في ملف الإعدادات)
        self.server_password_var = tk.StringVar(value="")
        ttk.Label(cfg, text="Server password (optional):").grid(
            row=2, column=0, sticky="w", padx=6, pady=4
        )
        pwd_entry = ttk.Entry(cfg, textvariable=self.server_password_var, show="*", justify="center")
        pwd_entry.grid(row=2, column=1, sticky="we", padx=(0, 4), pady=4)
        paste_btn = ttk.Button(cfg, text="Paste", width=6, command=lambda e=pwd_entry: self.paste_into(e))
        paste_btn.grid(row=2, column=2, sticky="e", padx=(0, 6), pady=4)

        # Server project path
        self.server_path_var = tk.StringVar(value=self.config_data["server_project_path"])
        ttk.Label(cfg, text="Server project path:").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(cfg, textvariable=self.server_path_var, justify="center").grid(
            row=3, column=1, columnspan=2, sticky="we", padx=(0, 6), pady=4
        )

        # Nginx service
        self.nginx_service_var = tk.StringVar(value=self.config_data["nginx_service"])
        ttk.Label(cfg, text="Nginx service name:").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(cfg, textvariable=self.nginx_service_var, justify="center").grid(
            row=4, column=1, columnspan=2, sticky="we", padx=(0, 6), pady=4
        )

        # Gunicorn workers/bind (optional tuning)
        self.gunicorn_bind_var = tk.StringVar(value=self.config_data["gunicorn_bind"])
        self.gunicorn_workers_var = tk.StringVar(value=str(self.config_data["gunicorn_workers"]))
        ttk.Label(cfg, text="Gunicorn bind:").grid(row=5, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(cfg, textvariable=self.gunicorn_bind_var, justify="center").grid(
            row=5, column=1, sticky="we", padx=(0, 6), pady=4
        )
        ttk.Label(cfg, text="Workers:").grid(row=5, column=2, sticky="e", padx=(0, 6), pady=4)
        ttk.Entry(cfg, width=5, textvariable=self.gunicorn_workers_var, justify="center").grid(
            row=5, column=3, sticky="e", padx=(0, 6), pady=4
        )

        cfg.columnconfigure(1, weight=1)

        # Android config (separate panel)
        android_cfg = ttk.LabelFrame(top, text="Android / USB")
        android_cfg.grid(row=0, column=1, sticky="nsew")

        self.adb_path_var = tk.StringVar(value=(self.config_data.get("adb_path") or "adb"))
        ttk.Label(android_cfg, text="ADB path:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(android_cfg, textvariable=self.adb_path_var, justify="center").grid(
            row=0, column=1, columnspan=2, sticky="we", padx=(0, 6), pady=4
        )

        self.flutter_path_var = tk.StringVar(value=(self.config_data.get("flutter_path") or ""))
        ttk.Label(android_cfg, text="Flutter path:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(android_cfg, textvariable=self.flutter_path_var, justify="center").grid(
            row=1, column=1, columnspan=2, sticky="we", padx=(0, 6), pady=4
        )

        self.android_app_var = tk.StringVar(
            value=(self.config_data.get("android_app_target") or "Social (finora_social)")
        )
        ttk.Label(android_cfg, text="App target:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        app_combo = ttk.Combobox(
            android_cfg,
            textvariable=self.android_app_var,
            values=[
                "Social (finora_social)",
                "Delivery Agent",
                "POS (finora_pos)",
                "Custom path",
            ],
            state="readonly",
            justify="center",
        )
        app_combo.grid(row=2, column=1, sticky="we", padx=(0, 6), pady=4)

        self.android_apk_var = tk.StringVar(value=(self.config_data.get("android_apk_path") or ""))
        ttk.Label(android_cfg, text="APK path:").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(android_cfg, textvariable=self.android_apk_var, justify="center").grid(
            row=3, column=1, sticky="we", padx=(0, 4), pady=4
        )
        ttk.Button(android_cfg, text="Browse…", command=self.browse_apk_path).grid(
            row=3, column=2, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Label(
            android_cfg,
            text="الافتراضي: finora_social — Install APK يبني تلقائياً إذا لم يوجد APK",
            font=("Segoe UI", 8),
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 2))

        self.social_api_url_var = tk.StringVar(
            value=(
                self.config_data.get("social_api_base_url")
                or os.environ.get("FINORA_SOCIAL_API_BASE_URL")
                or "https://www.finora.company"
            )
        )
        ttk.Label(android_cfg, text="Social API URL:").grid(
            row=5, column=0, sticky="w", padx=6, pady=4
        )
        ttk.Entry(android_cfg, textvariable=self.social_api_url_var, justify="center").grid(
            row=5, column=1, columnspan=2, sticky="we", padx=(0, 6), pady=4
        )

        self.social_tenant_var = tk.StringVar(
            value=(
                self.config_data.get("social_tenant_slug")
                or os.environ.get("FINORA_SOCIAL_TENANT_SLUG")
                or "super"
            )
        )
        ttk.Label(android_cfg, text="Tenant slug:").grid(
            row=6, column=0, sticky="w", padx=6, pady=4
        )
        ttk.Entry(android_cfg, textvariable=self.social_tenant_var, justify="center").grid(
            row=6, column=1, columnspan=2, sticky="we", padx=(0, 6), pady=4
        )

        android_cfg.columnconfigure(1, weight=1)

        # Action buttons — grouped rows
        actions = ttk.Frame(self)
        actions.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 4))

        def _btn_row(parent: ttk.Frame, title: str) -> ttk.Frame:
            frame = ttk.LabelFrame(parent, text=title)
            frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
            inner = ttk.Frame(frame)
            inner.pack(fill=tk.X, padx=4, pady=4)
            return inner

        deploy_row = _btn_row(actions, "Deploy")
        self.push_btn = ttk.Button(deploy_row, text="Push to GitHub", command=self.on_push_clicked)
        self.push_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.deploy_btn = ttk.Button(deploy_row, text="Smart Deploy", command=self.on_deploy_clicked)
        self.deploy_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.publish_apk_btn = ttk.Button(
            deploy_row, text="Publish APK", command=self.on_publish_apk_clicked
        )
        self.publish_apk_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.restart_btn = ttk.Button(deploy_row, text="Restart Server", command=self.on_restart_clicked)
        self.restart_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.logs_btn = ttk.Button(deploy_row, text="View Server Logs", command=self.on_view_logs_clicked)
        self.logs_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.start_monitor_btn = ttk.Button(
            deploy_row, text="Start Monitor", command=self.on_start_monitor_clicked
        )
        self.start_monitor_btn.pack(side=tk.LEFT, padx=3, pady=2)

        build_row = _btn_row(actions, "Build")
        self.build_btn = ttk.Button(build_row, text="Build Frontends", command=self.on_build_frontend_clicked)
        self.build_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.build_social_ai_btn = ttk.Button(
            build_row, text="Build Social AI", command=self.on_build_social_ai_clicked
        )
        self.build_social_ai_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.build_apk_btn = ttk.Button(build_row, text="Build APK", command=self.on_build_apk_clicked)
        self.build_apk_btn.pack(side=tk.LEFT, padx=3, pady=2)

        maint_row = _btn_row(actions, "Maintenance")
        self.fix_all_btn = ttk.Button(maint_row, text="Fix All", command=self.on_fix_all_clicked)
        self.fix_all_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.fix_nginx_btn = ttk.Button(
            maint_row, text="Fix Nginx / Proxy", command=self.on_fix_nginx_proxy_clicked
        )
        self.fix_nginx_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.run_migrations_btn = ttk.Button(
            maint_row, text="Add DB Columns", command=self.on_run_db_create_all_clicked
        )
        self.run_migrations_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.telegram_inbox_db_btn = ttk.Button(
            maint_row, text="Inbox DB (TG+WA)", command=self.on_ensure_telegram_inbox_table_clicked
        )
        self.telegram_inbox_db_btn.pack(side=tk.LEFT, padx=3, pady=2)

        android_row = _btn_row(actions, "Android USB")
        self.install_usb_btn = ttk.Button(
            android_row, text="Install APK", command=self.on_install_usb_clicked
        )
        self.install_usb_btn.pack(side=tk.LEFT, padx=3, pady=2)
        self.launch_app_btn = ttk.Button(
            android_row, text="Open App on Phone", command=self.on_launch_app_clicked
        )
        self.launch_app_btn.pack(side=tk.LEFT, padx=3, pady=2)

        # Progress + status + small indicators
        status_frame = ttk.Frame(self)
        status_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 4))

        self.progress = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.status_var = tk.StringVar(value="Ready.")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, anchor="w")
        status_label.pack(side=tk.LEFT)

        # Small live status indicators for monitor
        self.nginx_status_var = tk.StringVar(value="NGINX: -")
        self.gunicorn_status_var = tk.StringVar(value="GUNICORN: -")
        self.https_status_var = tk.StringVar(value="HTTPS: -")
        self.cpu_status_var = tk.StringVar(value="CPU: -")
        self.ram_status_var = tk.StringVar(value="RAM: -")
        self.disk_status_var = tk.StringVar(value="DISK: -")

        indicators_frame = ttk.Frame(status_frame)
        indicators_frame.pack(side=tk.RIGHT)
        for var in (
            self.disk_status_var,
            self.ram_status_var,
            self.cpu_status_var,
            self.https_status_var,
            self.gunicorn_status_var,
            self.nginx_status_var,
        ):
            ttk.Label(indicators_frame, textvariable=var).pack(side=tk.RIGHT, padx=(4, 0))

        # Notebook: Terminal + Error Explorer
        notebook = ttk.Notebook(self)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        terminal_frame = ttk.Frame(notebook)
        errors_frame = ttk.Frame(notebook)
        notebook.add(terminal_frame, text="Terminal")
        notebook.add(errors_frame, text="Error Explorer")

        # Log output + command input (Terminal tab)
        log_frame = ttk.LabelFrame(terminal_frame, text="Terminal / Log Output")
        log_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(4, 8))

        self.log_text = tk.Text(
            log_frame,
            bg="#020617",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
        )
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scroll.set)

        # تلوين الأنواع المختلفة من الرسائل
        self.log_text.tag_config("error", foreground="#f87171")
        self.log_text.tag_config("info", foreground="#4ade80")
        self.log_text.tag_config("cmd", foreground="#60a5fa")

        # Local command input (مثل ترمنال بسيط لتنفيذ أوامر محلية مثل pip install paramiko)
        cmd_frame = ttk.Frame(log_frame)
        cmd_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        ttk.Label(cmd_frame, text="Local command:").pack(side=tk.LEFT, padx=(0, 4))
        self.local_cmd_var = tk.StringVar(value="")
        cmd_entry = ttk.Entry(cmd_frame, textvariable=self.local_cmd_var)
        cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        cmd_entry.bind("<Return>", lambda _e: self.on_run_local_cmd_clicked())
        ttk.Button(
            cmd_frame,
            text="Run",
            command=self.on_run_local_cmd_clicked,
            width=8,
        ).pack(side=tk.RIGHT)

        # شريط حالة أسفل الترمنال
        status_bar = ttk.Frame(terminal_frame)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
        self.last_command_var = tk.StringVar(value="Last: -")
        self.last_exit_code_var = tk.StringVar(value="Exit: -")
        self.last_duration_var = tk.StringVar(value="Duration: -")
        ttk.Label(status_bar, textvariable=self.last_command_var).pack(side=tk.LEFT, padx=4)
        ttk.Label(status_bar, textvariable=self.last_exit_code_var).pack(side=tk.LEFT, padx=4)
        ttk.Label(status_bar, textvariable=self.last_duration_var).pack(side=tk.LEFT, padx=4)

        # Error Explorer tab
        self.error_entries: list[dict] = []
        self.errors_list = tk.Listbox(
            errors_frame,
            bg="#020617",
            fg="#fca5a5",
        )
        self.errors_list.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(4, 2))

        error_detail_frame = ttk.Frame(errors_frame)
        error_detail_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
        self.error_detail_var = tk.StringVar(value="")
        ttk.Label(error_detail_frame, textvariable=self.error_detail_var, wraplength=700).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(
            error_detail_frame,
            text="Copy last error",
            command=self.copy_last_error,
            width=14,
        ).pack(side=tk.RIGHT, padx=4)

        self.errors_list.bind("<<ListboxSelect>>", self.on_error_select)

        self.append_log("Finora Deploy Studio started.\n")

        # Start polling monitor queue for UI updates
        self.after(500, self.poll_monitor_queue)

    # ---------- Config ----------

    def load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with CONFIG_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                return {**DEFAULT_CONFIG, **data}
            except Exception:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self) -> None:
        self.config_data.update(
            {
                "local_project_path": self.local_path_var.get().strip(),
                "server_ssh": self.server_ssh_var.get().strip(),
                "server_project_path": self.server_path_var.get().strip(),
                "nginx_service": self.nginx_service_var.get().strip(),
                "gunicorn_bind": self.gunicorn_bind_var.get().strip(),
                "gunicorn_workers": int(self.gunicorn_workers_var.get() or "3"),
                "adb_path": (getattr(self, "adb_path_var", tk.StringVar(value="adb")).get().strip() or "adb"),
                "flutter_path": (
                    getattr(self, "flutter_path_var", tk.StringVar(value="")).get().strip()
                ),
                "android_apk_path": (getattr(self, "android_apk_var", tk.StringVar(value="")).get().strip()),
                "android_app_target": (
                    getattr(self, "android_app_var", tk.StringVar(value="Social (finora_social)")).get().strip()
                    or "Social (finora_social)"
                ),
                "social_api_base_url": (
                    getattr(
                        self,
                        "social_api_url_var",
                        tk.StringVar(value="https://www.finora.company"),
                    ).get().strip()
                    or "https://www.finora.company"
                ),
                "social_tenant_slug": (
                    getattr(self, "social_tenant_var", tk.StringVar(value="super")).get().strip()
                    or "super"
                ),
            }
        )
        try:
            with CONFIG_FILE.open("w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            self.append_log(f"[WARN] Failed to save config: {e}\n")

    # ---------- Helpers ----------

    def browse_local_path(self) -> None:
        path = filedialog.askdirectory(initialdir=self.local_path_var.get() or str(Path.cwd()))
        if path:
            self.local_path_var.set(path)

    def browse_apk_path(self) -> None:
        local_path = Path(self.local_path_var.get().strip() or ".")
        initial = str(local_path if local_path.exists() else Path.cwd())
        chosen = filedialog.askopenfilename(
            title="Select APK file",
            initialdir=initial,
            filetypes=[("Android APK", "*.apk"), ("All files", "*.*")],
        )
        if chosen:
            # Store relative path when possible (more portable)
            try:
                rel = str(Path(chosen).resolve().relative_to(local_path.resolve()))
                self.android_apk_var.set(rel)
            except Exception:
                self.android_apk_var.set(chosen)

    def append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        tag = None
        if text.startswith("[ERROR]"):
            tag = "error"
            # حفظ في Error Explorer
            self.error_entries.append(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "message": text.strip(),
                }
            )
            self.refresh_error_explorer()
        elif text.startswith("[INFO]"):
            tag = "info"
        elif text.startswith("$ "):
            tag = "cmd"

        self.log_text.insert(tk.END, text, tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def paste_into(self, entry: ttk.Entry) -> None:
        """لصق النص من الـ Clipboard داخل حقل معيّن."""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        entry.delete(0, tk.END)
        entry.insert(0, text)

    # ---------- Error Explorer helpers ----------

    def refresh_error_explorer(self) -> None:
        """تحديث قائمة الأخطاء في تبويب Error Explorer."""
        if not hasattr(self, "errors_list"):
            return
        self.errors_list.delete(0, tk.END)
        for e in self.error_entries:
            self.errors_list.insert(tk.END, f"[{e['time']}] {e['message']}")

    def on_error_select(self, _event: tk.Event) -> None:
        idx = self.errors_list.curselection()
        if not idx:
            return
        entry = self.error_entries[idx[0]]
        self.error_detail_var.set(entry["message"])

    def copy_last_error(self) -> None:
        if not self.error_entries:
            return
        last = self.error_entries[-1]["message"]
        try:
            self.clipboard_clear()
            self.clipboard_append(last)
        except tk.TclError:
            pass

    # ---------- Local command from terminal ----------

    def on_run_local_cmd_clicked(self) -> None:
        cmd_str = self.local_cmd_var.get().strip()
        if not cmd_str:
            return
        # نحفظ إعدادات المشروع أولاً حتى ننفّذ الأوامر داخل المسار الصحيح
        self.save_config()
        thread = threading.Thread(target=self._run_local_cmd_thread, args=(cmd_str,), daemon=True)
        self.set_busy(True)
        thread.start()

    def _run_local_cmd_thread(self, cmd_str: str) -> None:
        import time

        start = time.perf_counter()
        try:
            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                return

            parts = cmd_str.split()
            if not parts:
                return

            self.append_log(f"$ {cmd_str}\n")
            self.last_command_var.set(f"Last: {cmd_str}")
            try:
                proc = subprocess.Popen(
                    parts,
                    cwd=str(local_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                    shell=False,
                )
                assert proc.stdout is not None
                _stream_pipe_lines(proc.stdout, self.append_log)
                proc.wait()
                rc = proc.returncode
                self.last_exit_code_var.set(f"Exit: {rc}")
                if rc != 0:
                    self.append_log(f"[ERROR] Command exited with code {rc}\n")
                else:
                    self.append_log("[INFO] Command finished successfully.\n")
            except FileNotFoundError:
                self.append_log(f"[ERROR] Command not found: {parts[0]}\n")
        finally:
            import time as _t

            duration = _t.perf_counter() - start
            self.last_duration_var.set(f"Duration: {duration:.2f}s")
            self.set_busy(False)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def set_busy(self, busy: bool) -> None:
        widgets = [
            self.push_btn,
            self.deploy_btn,
            self.publish_apk_btn,
            self.restart_btn,
            self.logs_btn,
            self.build_btn,
            self.build_social_ai_btn,
            self.build_apk_btn,
            self.fix_all_btn,
            self.fix_nginx_btn,
            self.run_migrations_btn,
            self.telegram_inbox_db_btn,
            self.install_usb_btn,
            self.launch_app_btn,
            self.start_monitor_btn,
        ]
        if busy:
            for w in widgets:
                w.config(state="disabled")
            self.progress.start(80)
        else:
            for w in widgets:
                w.config(state="normal")
            self.progress.stop()

    # ---------- Self Healing Server Monitor ----------

    def on_start_monitor_clicked(self) -> None:
        """Start the background Self Healing Server Monitor once per session."""
        if self.monitor_running:
            messagebox.showinfo("Monitor", "Server monitor is already running.")
            return

        server = self.server_ssh_var.get().strip()
        if not server:
            messagebox.showerror("Monitor", "Please configure Server SSH before starting the monitor.")
            return

        self.save_config()

        self.monitor_running = True
        self.start_monitor_btn.config(state="disabled")
        self.append_log("[INFO] Starting Self Healing Server Monitor…\n")

        # Snapshot current config for the monitor thread
        server_password = self.server_password_var.get()
        nginx_service = self.nginx_service_var.get().strip() or "nginx"
        bind = self.gunicorn_bind_var.get().strip() or "127.0.0.1:8000"
        port = "8000"
        if ":" in bind:
            port = bind.split(":")[-1] or "8000"

        self.monitor_thread = ServerMonitorThread(
            server=server,
            password=server_password,
            nginx_service=nginx_service,
            app_port=port,
            queue_out=self.monitor_queue,
        )
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def poll_monitor_queue(self) -> None:
        """Pull messages from monitor thread and update UI safely in Tk thread."""
        try:
            while True:
                item = self.monitor_queue.get_nowait()
                kind = item.get("kind")
                msg = item.get("message", "")
                if kind == "log" and msg:
                    # Already formatted with [MONITOR] / [AUTO FIX] prefixes, etc.
                    if not msg.endswith("\n"):
                        msg += "\n"
                    self.append_log(msg)
                elif kind == "status":
                    data = item.get("data") or {}
                    # Update small indicators
                    nginx = data.get("nginx")
                    gunicorn = data.get("gunicorn")
                    https = data.get("https")
                    cpu = data.get("cpu")
                    ram = data.get("ram")
                    disk = data.get("disk")
                    if nginx is not None:
                        self.nginx_status_var.set(f"NGINX: {nginx}")
                    if gunicorn is not None:
                        self.gunicorn_status_var.set(f"GUNICORN: {gunicorn}")
                    if https is not None:
                        self.https_status_var.set(f"HTTPS: {https}")
                    if cpu is not None:
                        self.cpu_status_var.set(f"CPU: {cpu}")
                    if ram is not None:
                        self.ram_status_var.set(f"RAM: {ram}")
                    if disk is not None:
                        self.disk_status_var.set(f"DISK: {disk}")
                elif kind == "stopped":
                    self.monitor_running = False
                    self.start_monitor_btn.config(state="normal")
                    self.append_log("[INFO] Server monitor stopped.\n")
        except queue.Empty:
            pass
        finally:
            # Poll again
            self.after(1000, self.poll_monitor_queue)

    # ---------- Command Runners ----------

    def run_local_commands(self, commands, cwd: Path) -> int:
        """
        commands: list[list[str]]
        returns last returncode
        """
        rc = 0
        for cmd in commands:
            cmd_str = " ".join(cmd)
            self.append_log(f"$ {cmd_str}\n")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                )
                assert proc.stdout is not None
                _stream_pipe_lines(proc.stdout, self.append_log)
                proc.wait()
                rc = proc.returncode
                if rc != 0:
                    self.append_log(f"[ERROR] Command failed with code {rc}: {cmd_str}\n")
                    # لا نوقف مباشرة لـ git commit الفارغ، نترك caller يقرّر
            except FileNotFoundError:
                self.append_log(f"[ERROR] Command not found: {cmd[0]}\n")
                return 1
        return rc

    def git_capture(self, args: list[str], cwd: Path) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            stderr = _decode_output_chunk(proc.stderr)
            if stderr.strip():
                self.append_log(stderr)
            return proc.returncode, _decode_output_chunk(proc.stdout)
        except FileNotFoundError:
            return 1, "[ERROR] git command not found.\n"

    def git_capture_bytes(self, args: list[str], cwd: Path) -> tuple[int, bytes]:
        """Run git and return raw stdout (for -z / NUL-delimited output)."""
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            stderr = proc.stderr or b""
            if stderr.strip():
                self.append_log(stderr.decode("utf-8", errors="replace"))
            return proc.returncode, proc.stdout or b""
        except FileNotFoundError:
            return 1, b""

    @staticmethod
    def parse_git_z_paths(data: bytes) -> list[str]:
        """Parse NUL-delimited paths from git -z output."""
        paths: list[str] = []
        for part in data.split(b"\x00"):
            if not part:
                continue
            paths.append(part.decode("utf-8", errors="surrogateescape"))
        return paths

    def git_add_paths(self, paths: list[str], cwd: Path) -> int:
        """Stage paths via stdin to handle Unicode filenames on Windows."""
        if not paths:
            return 0
        valid_paths: list[str] = []
        for p in paths:
            rel = p.strip().replace("\\", "/")
            if not rel:
                continue
            local_file = cwd / Path(rel)
            if not local_file.is_file():
                self.append_log(f"[WARN] Skip missing path for git add: {rel}\n")
                continue
            valid_paths.append(rel)
        if not valid_paths:
            self.append_log("[WARN] No existing files to stage after path validation.\n")
            return 0
        if len(valid_paths) < len(paths):
            self.append_log(
                f"[WARN] Skipped {len(paths) - len(valid_paths)} missing/invalid paths before git add.\n"
            )
        payload = "\x00".join(valid_paths).encode("utf-8") + b"\x00"
        self.append_log(f"$ git add --pathspec-from-file=- ({len(valid_paths)} paths)\n")
        try:
            proc = subprocess.run(
                ["git", "add", "--pathspec-from-file=-", "--pathspec-file-nul"],
                cwd=str(cwd),
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
            if stdout.strip():
                self.append_log(stdout)
            if stderr.strip():
                self.append_log(stderr)
            if proc.returncode != 0:
                self.append_log(f"[ERROR] git add failed with code {proc.returncode}\n")
            return proc.returncode
        except FileNotFoundError:
            self.append_log("[ERROR] git command not found.\n")
            return 1

    def current_git_commit(self, cwd: Path) -> str:
        rc, out = self.git_capture(["rev-parse", "HEAD"], cwd)
        if rc != 0:
            return ""
        return (out or "").strip()

    def is_safe_push_path(self, path_text: str) -> bool:
        cleaned = path_text.strip().replace("\\", "/")
        if not cleaned:
            return False
        path = Path(cleaned)
        if path.is_absolute():
            return False
        if path.name in SAFE_PUSH_EXCLUDED_FILES:
            return False
        if path.name.lower().endswith(SAFE_PUSH_EXCLUDED_NAME_ENDINGS):
            return False
        if path.suffix.lower() in SAFE_PUSH_EXCLUDED_SUFFIXES:
            return False
        parts = set(path.parts)
        return not bool(parts.intersection(SAFE_PUSH_EXCLUDED_PARTS))

    def collect_safe_push_paths(self, cwd: Path) -> tuple[list[str], list[str]]:
        rc_mod, modified_out = self.git_capture_bytes(["diff", "-z", "--name-only", "--diff-filter=AM"], cwd)
        rc_untracked, untracked_out = self.git_capture_bytes(["ls-files", "-z", "-o", "--exclude-standard"], cwd)
        rc_deleted, deleted_out = self.git_capture_bytes(["ls-files", "-z", "-d"], cwd)

        if rc_mod != 0:
            self.append_log((modified_out or b"").decode("utf-8", errors="replace"))
        if rc_untracked != 0:
            self.append_log((untracked_out or b"").decode("utf-8", errors="replace"))
        if rc_deleted != 0:
            self.append_log((deleted_out or b"").decode("utf-8", errors="replace"))

        candidates: list[str] = []
        for output in (modified_out, untracked_out):
            candidates.extend(self.parse_git_z_paths(output))

        safe_paths: list[str] = []
        skipped_paths: list[str] = []
        seen: set[str] = set()
        for p in candidates:
            if p in seen:
                continue
            seen.add(p)
            if self.is_safe_push_path(p):
                safe_paths.append(p)
            else:
                skipped_paths.append(p)

        deleted = self.parse_git_z_paths(deleted_out)
        if deleted:
            self.append_log(
                f"[WARN] Ignoring {len(deleted)} deleted tracked files. "
                "Safe Push will not stage deletions. Restore or stage deletions manually if intentional.\n"
            )

        if skipped_paths:
            self.append_log(f"[WARN] Skipped {len(skipped_paths)} unsafe/local paths.\n")
            for p in skipped_paths[:30]:
                self.append_log(f"  - {p}\n")
            if len(skipped_paths) > 30:
                self.append_log(f"  ... and {len(skipped_paths) - 30} more\n")

        return safe_paths, deleted

    def collect_safe_changed_paths(
        self,
        cwd: Path,
        since_commit: str = "",
    ) -> tuple[list[str], list[str], list[str]]:
        """Collect modified/added/untracked files for Smart Deploy; deletions are reported only."""
        commands = [
            ["diff", "-z", "--name-only", "--diff-filter=AM"],
            ["diff", "-z", "--cached", "--name-only", "--diff-filter=AM"],
            ["ls-files", "-z", "-o", "--exclude-standard"],
        ]
        if since_commit:
            commands.append(["diff", "-z", "--name-only", "--diff-filter=AM", f"{since_commit}..HEAD"])
        else:
            commands.append(["diff-tree", "-z", "--no-commit-id", "--name-only", "--diff-filter=AM", "-r", "HEAD"])

        candidates: list[str] = []
        errors: list[str] = []
        for args in commands:
            rc, out = self.git_capture_bytes(args, cwd)
            if rc != 0:
                errors.append((out or b"").decode("utf-8", errors="replace"))
                continue
            candidates.extend(self.parse_git_z_paths(out))

        rc_deleted, deleted_out = self.git_capture_bytes(["ls-files", "-z", "-d"], cwd)
        if rc_deleted != 0:
            errors.append((deleted_out or b"").decode("utf-8", errors="replace"))
        deleted = self.parse_git_z_paths(deleted_out)

        safe_paths: list[str] = []
        skipped_paths: list[str] = []
        seen: set[str] = set()
        for p in candidates:
            p = p.replace("\\", "/")
            if p in seen:
                continue
            seen.add(p)
            local_file = cwd / Path(p)
            if not local_file.is_file():
                skipped_paths.append(p)
                continue
            if self.is_safe_push_path(p):
                safe_paths.append(p)
            else:
                skipped_paths.append(p)

        if errors:
            for err in errors:
                self.append_log(err)
        if deleted:
            self.append_log(
                f"[WARN] Smart Deploy ignored {len(deleted)} deleted tracked files. "
                "It uploads changed/new files only and never deletes server files automatically.\n"
            )
        if skipped_paths:
            self.append_log(f"[WARN] Smart Deploy skipped {len(skipped_paths)} unsafe/local paths.\n")
            for p in skipped_paths[:30]:
                self.append_log(f"  - {p}\n")
            if len(skipped_paths) > 30:
                self.append_log(f"  ... and {len(skipped_paths) - 30} more\n")

        return safe_paths, skipped_paths, deleted

    def make_changed_files_archive(self, cwd: Path, paths: list[str]) -> Path:
        """Create a tar.gz with only selected safe relative paths."""
        tmp = tempfile.NamedTemporaryFile(prefix="finora-smart-deploy-", suffix=".tar.gz", delete=False)
        archive_path = Path(tmp.name)
        tmp.close()
        with tarfile.open(archive_path, "w:gz") as tar:
            for rel in paths:
                safe_rel = rel.replace("\\", "/").lstrip("/")
                tar.add(cwd / Path(safe_rel), arcname=safe_rel, recursive=False)
        return archive_path

    def upload_file_to_server(self, local_file: Path, remote_file: str) -> int:
        server = self.server_ssh_var.get().strip()
        if not server:
            self.append_log("[ERROR] Server SSH address is empty.\n")
            return 1
        password = self.server_password_var.get()

        if not password:
            total_bytes = local_file.stat().st_size
            batch_path: Path | None = None
            ssh_cmd = _resolve_command("ssh")
            sftp_cmd = _resolve_command("sftp")
            self.append_log(
                f"[INFO] Upload size: {_format_file_size(total_bytes)}. "
                "Using resumable SFTP with SSH-key authentication.\n"
            )
            try:
                batch = tempfile.NamedTemporaryFile(
                    mode="w",
                    prefix="finora-sftp-",
                    suffix=".txt",
                    delete=False,
                    encoding="utf-8",
                    newline="\n",
                )
                batch_path = Path(batch.name)
                local_sftp_path = str(local_file).replace("\\", "/").replace('"', '\\"')
                remote_sftp_path = remote_file.replace('"', '\\"')
                with batch:
                    batch.write(f'put "{local_sftp_path}" "{remote_sftp_path}"\n')

                started = time.monotonic()
                max_attempts = 8
                for attempt in range(1, max_attempts + 1):
                    resume_args: list[str] = []
                    upload_mode = "starting"
                    if attempt > 1:
                        try:
                            remote_check = subprocess.run(
                                [
                                    ssh_cmd,
                                    *SSH_CONNECT_OPTIONS,
                                    server,
                                    f"test -f {shlex.quote(remote_file)}",
                                ],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=25,
                                check=False,
                            )
                        except (OSError, subprocess.SubprocessError):
                            remote_check = None
                        if remote_check is not None and remote_check.returncode == 0:
                            resume_args = ["-a"]
                            upload_mode = "resuming"

                    full_cmd = [
                        sftp_cmd,
                        *resume_args,
                        "-q",
                        "-b",
                        str(batch_path),
                        *SSH_CONNECT_OPTIONS,
                        server,
                    ]
                    self.append_log(
                        f"$ sftp {upload_mode} upload (attempt {attempt}/{max_attempts})\n"
                    )
                    proc = subprocess.Popen(
                        full_cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        bufsize=0,
                    )
                    assert proc.stdout is not None
                    attempt_started = time.monotonic()
                    last_notice = attempt_started
                    while proc.poll() is None:
                        now = time.monotonic()
                        if now - last_notice >= 15:
                            elapsed = int(now - started)
                            self.append_log(
                                f"[INFO] Resumable upload active: {_format_file_size(total_bytes)} "
                                f"archive, {elapsed}s total elapsed.\n"
                            )
                            last_notice = now
                        time.sleep(1)
                    _stream_pipe_lines(proc.stdout, self.append_log)
                    if proc.returncode == 0:
                        elapsed = max(1, int(time.monotonic() - started))
                        self.append_log(
                            f"[INFO] Upload completed: {_format_file_size(total_bytes)} in {elapsed}s.\n"
                        )
                        return 0

                    if attempt < max_attempts:
                        self.append_log(
                            f"[WARN] SFTP connection ended with code {proc.returncode}; "
                            "retrying in 3s and resuming the remote partial file.\n"
                        )
                        time.sleep(3)
                        continue

                    self.append_log(
                        f"[ERROR] Resumable SFTP failed after {max_attempts} attempts "
                        f"(last code {proc.returncode}). Verify the network connection.\n"
                    )
                    return proc.returncode or 1
            except FileNotFoundError:
                self.append_log(
                    "[WARN] sftp command not found. Falling back to Paramiko SFTP.\n"
                )
            finally:
                if batch_path:
                    batch_path.unlink(missing_ok=True)

        try:
            import paramiko  # type: ignore[import]
        except ImportError:
            self.append_log("[ERROR] paramiko غير مثبت. ثبّته بأمر: pip install paramiko\n")
            return 1

        host = server
        username = None
        if "@" in server:
            username, host = server.split("@", 1)

        self.append_log(f"[INFO] Uploading archive via SFTP to {server}…\n")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host,
                username=username,
                password=password or None,
                look_for_keys=not bool(password),
                allow_agent=not bool(password),
            )
            sftp = client.open_sftp()
            try:
                total_bytes = local_file.stat().st_size
                last_percent = -10

                def report_progress(transferred: int, total: int) -> None:
                    nonlocal last_percent
                    percent = int((transferred * 100) / max(1, total))
                    if percent >= last_percent + 10 or percent == 100:
                        last_percent = percent
                        self.append_log(
                            f"[INFO] Upload progress: {percent}% "
                            f"({_format_file_size(transferred)} / {_format_file_size(total)})\n"
                        )

                self.append_log(f"[INFO] Upload size: {_format_file_size(total_bytes)}.\n")
                sftp.put(str(local_file), remote_file, callback=report_progress)
            finally:
                sftp.close()
            return 0
        except Exception as e:
            self.append_log(f"[ERROR] SFTP upload failed: {e}\n")
            return 1
        finally:
            try:
                client.close()
            except Exception:
                pass

    def run_ssh_script(self, script: str) -> int:
        server = self.server_ssh_var.get().strip()
        if not server:
            self.append_log("[ERROR] Server SSH address is empty.\n")
            return 1
        password = self.server_password_var.get()

        # إذا ماكو باسورد: نستخدم ssh العادي (يتطلب مفاتيح أو جلسة بدون تفاعل)
        if not password:
            ssh_cmd = _resolve_command("ssh")
            full_cmd = [ssh_cmd, *SSH_CONNECT_OPTIONS, server, script]
            self.append_log(f"$ ssh {server} '{script}'\n")
            try:
                proc = subprocess.Popen(
                    full_cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                )
                assert proc.stdout is not None
                _stream_pipe_lines(proc.stdout, self.append_log)
                proc.wait()
                rc = proc.returncode
                if rc != 0:
                    self.append_log(f"[ERROR] SSH command failed with code {rc}\n")
                return rc
            except UnicodeDecodeError as exc:
                self.append_log(f"[ERROR] SSH output decode failed: {exc}\n")
                return 1
            except FileNotFoundError:
                self.append_log("[WARN] ssh command not found. Falling back to Paramiko SSH.\n")

        # في حالة وجود باسورد: نستخدم paramiko (يتطلب pip install paramiko)
        try:
            import paramiko  # type: ignore[import]
        except ImportError:
            self.append_log(
                "[ERROR] paramiko غير مثبت. ثبّته بأمر: pip install paramiko\n"
            )
            return 1

        self.append_log(f"[INFO] Connecting via SSH (paramiko) to {server}…\n")
        host, _, user = server, None, None
        # الصيغة المعتادة user@host
        if "@" in server:
            user, host = server.split("@", 1)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=host,
                username=user,
                password=password or None,
                look_for_keys=not bool(password),
                allow_agent=not bool(password),
            )
            stdin, stdout, stderr = client.exec_command(script)
            while True:
                line = stdout.readline()
                if not line:
                    break
                self.append_log(_decode_paramiko_line(line))
            while True:
                line = stderr.readline()
                if not line:
                    break
                decoded = _decode_output_chunk(line).strip()
                if decoded:
                    self.append_log(decoded + "\n")
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                self.append_log(f"[ERROR] SSH command failed with code {exit_status}\n")
            return exit_status
        except Exception as e:
            self.append_log(f"[ERROR] SSH connection failed: {e}\n")
            return 1
        finally:
            try:
                client.close()
            except Exception:
                pass

    # ---------- Button handlers ----------

    def on_push_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._push_to_github_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _push_to_github_thread(self) -> None:
        try:
            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                return

            self.set_status("Pushing to GitHub…")
            self.append_log("[INFO] Safe Push mode: staging modified/new safe files only; deletions are ignored.\n")

            self.run_local_commands([["git", "restore", "--staged", "."]], cwd=local_path)
            self.run_local_commands([["git", "status", "--short"]], cwd=local_path)

            safe_paths, deleted_paths = self.collect_safe_push_paths(local_path)
            if not safe_paths:
                self.append_log("[INFO] No safe files to stage. Nothing was pushed.\n")
                if deleted_paths:
                    self.append_log("[INFO] There are deleted files in the working tree, but Safe Push did not stage them.\n")
                self.set_status("Nothing safe to push.")
                return

            self.append_log(f"[INFO] Staging {len(safe_paths)} safe files.\n")
            rc = self.git_add_paths(safe_paths, local_path)
            if rc != 0:
                self.set_status("Push failed while staging files.")
                return

            rc, staged_out = self.git_capture(["diff", "--cached", "--stat"], local_path)
            self.append_log(staged_out or "[INFO] No staged diff.\n")
            if rc != 0:
                self.set_status("Push failed while reading staged diff.")
                return

            if not staged_out.strip():
                self.append_log("[INFO] Nothing staged after safety filters. Nothing was pushed.\n")
                self.set_status("Nothing to push.")
                return

            commit_message = f"update {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            rc = self.run_local_commands(
                [["git", "commit", "-m", commit_message], ["git", "push"]],
                cwd=local_path,
            )
            if rc == 0:
                self.append_log("[INFO] Push to GitHub completed.\n")
                self.set_status("Push completed.")
            else:
                self.set_status("Push finished with errors (see log).")
        finally:
            self.set_busy(False)

    # ---------- Android USB install ----------

    def on_install_usb_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._install_usb_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _get_adb_path(self) -> str:
        # Prefer current UI value if present (user may edit without saving yet)
        if hasattr(self, "adb_path_var"):
            return (self.adb_path_var.get() or "adb").strip() or "adb"
        return (self.config_data.get("adb_path") or "adb").strip() or "adb"

    def _choose_usb_device(self, serials: list[str]) -> str | None:
        if not serials:
            return None
        if len(serials) == 1:
            return serials[0]

        selected: dict[str, str | None] = {"value": None}
        win = tk.Toplevel(self)
        win.title("Select USB device")
        win.geometry("420x260")
        win.configure(bg="#0f172a")
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text="Multiple devices detected. Choose one:").pack(
            side=tk.TOP, anchor="w", padx=12, pady=(12, 6)
        )
        lb = tk.Listbox(win, bg="#020617", fg="#e5e7eb", selectmode=tk.SINGLE, height=8)
        lb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        for s in serials:
            lb.insert(tk.END, s)
        lb.selection_set(0)

        btn_row = ttk.Frame(win)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=12)

        def _ok() -> None:
            idx = lb.curselection()
            if not idx:
                return
            selected["value"] = lb.get(idx[0])
            win.destroy()

        def _cancel() -> None:
            selected["value"] = None
            win.destroy()

        ttk.Button(btn_row, text="Cancel", command=_cancel, width=10).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn_row, text="OK", command=_ok, width=10).pack(side=tk.RIGHT)
        win.bind("<Return>", lambda _e: _ok())
        win.bind("<Escape>", lambda _e: _cancel())

        self.wait_window(win)
        return selected["value"]

    def _android_project_roots(self, local_path: Path) -> dict[str, Path]:
        return {
            "Social (finora_social)": local_path / "mobile" / "finora_social",
            "POS (finora_pos)": local_path / "mobile" / "finora_pos_android",
            "Delivery Agent": local_path / "mobile" / "finora_delivery_agent_android",
        }

    def _normalize_android_app_target(self, target: str) -> str:
        legacy = {
            "Auto (latest)": "Social (finora_social)",
            "Social": "Social (finora_social)",
        }
        return legacy.get(target.strip(), target.strip())

    def _effective_android_app(self, local_path: Path) -> str:
        raw = ""
        if hasattr(self, "android_app_var"):
            raw = (self.android_app_var.get() or "").strip()
        if not raw:
            raw = (self.config_data.get("android_app_target") or "Social (finora_social)").strip()
        target = self._normalize_android_app_target(raw)
        if target == "Custom path":
            return target
        roots = self._android_project_roots(local_path)
        if target in roots:
            return target
        return "Social (finora_social)"

    def _is_flutter_app(self, app_target: str) -> bool:
        return app_target == "Social (finora_social)"

    def _list_apk_candidates(self, root: Path) -> list[Path]:
        skip_parts = {"intermediates", ".gradle", ".pub-cache"}
        candidates: list[Path] = []
        if not root.exists():
            return candidates
        for apk in root.rglob("*.apk"):
            parts = {s.lower() for s in apk.parts}
            if parts & skip_parts:
                continue
            if apk.is_file():
                candidates.append(apk)
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates

    def _preferred_apk_browse_dir(self, local_path: Path, app_target: str) -> Path:
        project_roots = self._android_project_roots(local_path)
        root = project_roots.get(app_target)
        if not root:
            return local_path
        if self._is_flutter_app(app_target):
            flutter_out = root / "build" / "app" / "outputs" / "flutter-apk"
            if flutter_out.exists():
                return flutter_out
        android_out = root / "app" / "build" / "outputs" / "apk" / "debug"
        if android_out.exists():
            return android_out
        return root

    def _set_apk_var_from_path(self, apk: Path, local_path: Path) -> None:
        try:
            rel = str(apk.resolve().relative_to(local_path.resolve()))
            self.android_apk_var.set(rel)
        except Exception:
            self.android_apk_var.set(str(apk))

    def _find_latest_apk(self, local_path: Path) -> Path | None:
        configured = (self.android_apk_var.get() if hasattr(self, "android_apk_var") else "").strip()
        if not configured:
            configured = (self.config_data.get("android_apk_path") or "").strip()
        if configured:
            p = Path(configured)
            if not p.is_absolute():
                p = (local_path / p).resolve()
            if p.is_file() and p.suffix.lower() == ".apk":
                return p

        app_target = self._effective_android_app(local_path)
        if app_target == "Custom path":
            return None

        project_roots = self._android_project_roots(local_path)
        root = project_roots.get(app_target)
        if not root:
            return None

        if app_target == "Social (finora_social)":
            artifact_apk = local_path / "artifacts" / "finora-social-debug.apk"
            if artifact_apk.is_file():
                return artifact_apk

        candidates = self._list_apk_candidates(root)
        return candidates[0] if candidates else None

    def _package_for_apk(self, apk: Path) -> str | None:
        path_lower = str(apk).lower().replace("\\", "/")
        if "finora_pos" in path_lower:
            return "iq.finora.pos"
        if "delivery_agent" in path_lower or "deliveryagent" in path_lower:
            return "iq.finora.deliveryagent"
        if "finora_social" in path_lower:
            return "iq.finora.finora_social"
        return None

    def _launch_app_on_device(self, adb_path: str, serial: str, package: str, cwd: Path) -> int:
        cmd = [
            adb_path,
            "-s",
            serial,
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ]
        self.append_log(f"$ {' '.join(cmd)}\n")
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        out = _decode_output_chunk(proc.stdout)
        if out:
            self.append_log(out if out.endswith("\n") else out + "\n")
        return proc.returncode

    def _resolve_usb_device(self, adb_path: str, cwd: Path) -> str | None:
        devices = self._adb_list_devices(adb_path=adb_path, cwd=cwd)
        if not devices:
            self.append_log(
                "[ERROR] No USB device found. Enable USB debugging and accept RSA prompt, then retry.\n"
            )
            return None
        return self._choose_usb_device(devices)

    def _adb_list_devices(self, adb_path: str, cwd: Path) -> list[str]:
        try:
            proc = subprocess.run(
                [adb_path, "devices"],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except FileNotFoundError:
            self.append_log(f"[ERROR] adb not found: {adb_path}. Install Android platform-tools or add adb to PATH.\n")
            return []

        out = _decode_output_chunk(proc.stdout)
        if out:
            self.append_log(out if out.endswith("\n") else out + "\n")

        serials: list[str] = []
        for line in (out or "").splitlines():
            line = line.strip()
            if not line or line.lower().startswith("list of devices"):
                continue
            # serial \t state
            parts = line.split()
            if len(parts) >= 2 and parts[1].strip().lower() == "device":
                serials.append(parts[0].strip())
        return serials

    def on_launch_app_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._launch_app_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _launch_app_thread(self) -> None:
        start = time.perf_counter()
        try:
            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                return

            adb_path = self._get_adb_path()
            self.set_status("Launching app on device…")
            serial = self._resolve_usb_device(adb_path, local_path)
            if not serial:
                self.set_status("Launch failed (no devices).")
                return

            app_target = self._effective_android_app(local_path)
            self.append_log(f"[INFO] App target: {app_target}\n")

            apk = self._find_latest_apk(local_path)
            package = self._package_for_apk(apk) if apk else None
            if not package:
                self.append_log("[ERROR] Could not detect package name. Choose a known APK or install first.\n")
                self.set_status("Launch failed (unknown package).")
                return

            self.append_log(f"[INFO] Opening {package} on {serial}…\n")
            rc = self._launch_app_on_device(adb_path, serial, package, local_path)
            if rc != 0:
                self.append_log(f"[ERROR] Launch failed with code {rc}\n")
                self.set_status("Launch failed (see log).")
                return

            self.append_log("[INFO] App launched on device.\n")
            self.set_status("App opened on phone.")
        finally:
            duration = time.perf_counter() - start
            self.last_duration_var.set(f"Duration: {duration:.2f}s")
            self.set_busy(False)

    def _resolve_flutter_cmd(self) -> str | None:
        configured = ""
        if hasattr(self, "flutter_path_var"):
            configured = (self.flutter_path_var.get() or "").strip()
        if not configured:
            configured = (self.config_data.get("flutter_path") or "").strip()
        if configured and Path(configured).is_file():
            return configured

        for candidate in (
            shutil.which("flutter"),
            shutil.which("flutter.bat"),
            r"C:\flutter\bin\flutter.bat",
            os.path.expandvars(r"%LOCALAPPDATA%\flutter\bin\flutter.bat"),
        ):
            if candidate and Path(candidate).is_file():
                return candidate
        return None

    def _is_ascii_path(self, path: Path) -> bool:
        return all(ord(ch) < 128 for ch in str(path))

    def _resolve_social_build_settings(self, local_path: Path) -> tuple[str, str]:
        """Resolve Social API URL + tenant from UI, env, .env, then defaults."""
        env_file_vals: dict[str, str] = {}
        env_path = local_path / ".env"
        if env_path.is_file():
            try:
                for raw in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    env_file_vals[key.strip()] = value.strip().strip("'\"")
            except OSError:
                pass

        api = (
            getattr(self, "social_api_url_var", tk.StringVar(value="")).get().strip()
            or (self.config_data.get("social_api_base_url") or "").strip()
            or (os.environ.get("FINORA_SOCIAL_API_BASE_URL") or "").strip()
            or (env_file_vals.get("FINORA_SOCIAL_API_BASE_URL") or "").strip()
            or "https://www.finora.company"
        )
        tenant = (
            getattr(self, "social_tenant_var", tk.StringVar(value="")).get().strip()
            or (self.config_data.get("social_tenant_slug") or "").strip()
            or (os.environ.get("FINORA_SOCIAL_TENANT_SLUG") or "").strip()
            or (env_file_vals.get("FINORA_SOCIAL_TENANT_SLUG") or "").strip()
            or "super"
        )
        # Normalize common mistakes like missing scheme.
        if api and "://" not in api:
            api = "https://" + api
        return api.rstrip("/"), tenant

    def _prepare_flutter_build_cwd(self, project_dir: Path) -> Path:
        if self._is_ascii_path(project_dir):
            return project_dir

        build_root = Path(tempfile.gettempdir()) / "finora_social_build"
        self.append_log(f"[INFO] Non-ASCII path detected — copying project to: {build_root}\n")
        if build_root.exists():
            shutil.rmtree(build_root, ignore_errors=True)
        build_root.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                "robocopy",
                str(project_dir),
                str(build_root),
                "/E",
                "/XD",
                "build",
                ".dart_tool",
                ".gradle",
                "android\\.gradle",
                "android\\app\\build",
                "/NFL",
                "/NDL",
                "/NJH",
                "/NJS",
                "/nc",
                "/ns",
                "/np",
            ],
            check=False,
        )
        if proc.returncode >= 8:
            raise RuntimeError(f"robocopy failed (code {proc.returncode})")
        return build_root

    def _run_logged_command(self, cmd: list[str], cwd: Path) -> int:
        self.append_log(f"$ {' '.join(cmd)}\n")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                shell=False,
            )
        except FileNotFoundError:
            self.append_log(f"[ERROR] Command not found: {cmd[0]}\n")
            return 127

        assert proc.stdout is not None
        _stream_pipe_lines(proc.stdout, self.append_log)
        proc.wait()
        return proc.returncode

    def _copy_built_apk_to_artifacts(self, apk: Path, local_path: Path, app_target: str) -> Path:
        artifacts_dir = local_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        if app_target == "Social (finora_social)":
            dest = artifacts_dir / "finora-social-release.apk"
        elif app_target == "Delivery Agent":
            dest = artifacts_dir / "finora-delivery-agent-debug.apk"
        else:
            dest = artifacts_dir / f"{apk.stem}.apk"
        shutil.copy2(apk, dest)
        return dest

    def _build_apk_internal(self, local_path: Path, app_target: str) -> Path | None:
        project_roots = self._android_project_roots(local_path)
        project_dir = project_roots.get(app_target)
        if not project_dir or not project_dir.exists():
            self.append_log(f"[ERROR] Android project not found for: {app_target}\n")
            return None

        if self._is_flutter_app(app_target):
            flutter_cmd = self._resolve_flutter_cmd()
            if not flutter_cmd:
                self.append_log(
                    "[ERROR] Flutter not found. Install Flutter SDK or set Flutter path to flutter.bat\n"
                    "Example: C:\\flutter\\bin\\flutter.bat\n"
                )
                return None

            pubspec = project_dir / "pubspec.yaml"
            if not pubspec.is_file():
                self.append_log(f"[ERROR] Flutter project not found: {project_dir}\n")
                return None

            try:
                build_cwd = self._prepare_flutter_build_cwd(project_dir)
            except Exception as exc:
                self.append_log(f"[ERROR] Failed to prepare Flutter build folder: {exc}\n")
                return None

            free_bytes = shutil.disk_usage(build_cwd).free
            if free_bytes < 5 * 1024 * 1024 * 1024:
                self.append_log(
                    "[ERROR] Flutter release build requires at least 5 GB free disk space. "
                    f"Available: {free_bytes / (1024 ** 3):.2f} GB.\n"
                )
                return None

            self.append_log(f"[INFO] Building Flutter APK for {app_target} in {build_cwd}\n")
            build_command = [flutter_cmd, "build", "apk", "--debug"]
            if app_target == "Social (finora_social)":
                api_base_url, tenant_slug = self._resolve_social_build_settings(local_path)
                key_properties = project_dir / "android" / "key.properties"
                if not api_base_url.lower().startswith("https://"):
                    self.append_log(
                        "[ERROR] Social API URL must be HTTPS "
                        f"(got: {api_base_url or '(empty)'}).\n"
                        "[INFO] Set it in Android panel → Social API URL, "
                        "or FINORA_SOCIAL_API_BASE_URL, then restart Deploy Studio.\n"
                    )
                    return None
                if not tenant_slug:
                    self.append_log("[ERROR] Social tenant slug is required.\n")
                    return None
                self.append_log(
                    f"[INFO] Social build API={api_base_url} tenant={tenant_slug}\n"
                )
                if key_properties.is_file():
                    build_command = [
                        flutter_cmd,
                        "build",
                        "apk",
                        "--release",
                        # Include 32-bit + 64-bit for Galaxy A13 (armeabi-v7a) and modern phones.
                        "--target-platform=android-arm,android-arm64",
                        f"--dart-define=API_BASE_URL={api_base_url}",
                        f"--dart-define=TENANT_SLUG={tenant_slug}",
                    ]
                else:
                    self.append_log(
                        "[WARN] key.properties missing — building Social DEBUG APK "
                        "(in-app updates still work for devices on this build lineage).\n"
                    )
                    build_command = [
                        flutter_cmd,
                        "build",
                        "apk",
                        "--debug",
                        "--target-platform=android-arm,android-arm64",
                        f"--dart-define=API_BASE_URL={api_base_url}",
                        f"--dart-define=TENANT_SLUG={tenant_slug}",
                    ]

            for step_cmd in ([flutter_cmd, "pub", "get"], build_command):
                rc = self._run_logged_command(step_cmd, build_cwd)
                if rc != 0:
                    self.append_log(f"[ERROR] Flutter command failed with code {rc}\n")
                    return None

            apks = self._list_apk_candidates(build_cwd)
            if not apks:
                self.append_log("[ERROR] Flutter build finished but APK output was not found.\n")
                return None

            apk = self._copy_built_apk_to_artifacts(apks[0], local_path, app_target)
            self.after(0, lambda p=apk, lp=local_path: self._set_apk_var_from_path(p, lp))
            return apk

        if app_target == "Delivery Agent" and (project_dir / "build_apk.ps1").is_file():
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(project_dir / "build_apk.ps1"),
                "-Variant",
                "debug",
            ]
            build_cwd = project_dir
        else:
            gradlew = project_dir / "gradlew.bat"
            if not gradlew.is_file():
                self.append_log(f"[ERROR] gradlew.bat not found in {project_dir}\n")
                return None
            cmd = [str(gradlew), "--no-daemon", "assembleDebug"]
            build_cwd = project_dir

        self.append_log(f"[INFO] Building APK for {app_target} in {build_cwd}\n")
        rc = self._run_logged_command(cmd, build_cwd)
        if rc != 0:
            self.append_log(f"[ERROR] APK build failed with code {rc}\n")
            return None

        apks = self._list_apk_candidates(project_dir)
        if not apks:
            self.append_log("[ERROR] Build finished but APK output was not found.\n")
            return None

        apk = apks[0]
        self.after(0, lambda p=apk, lp=local_path: self._set_apk_var_from_path(p, lp))
        return apk

    def on_build_apk_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._build_apk_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def on_publish_apk_clicked(self) -> None:
        """Publish only the selected APK without packaging the source tree."""
        self.save_config()
        thread = threading.Thread(target=self._publish_apk_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    @staticmethod
    def _published_apk_name(app_target: str) -> str:
        if app_target == "Social (finora_social)":
            return "finora-social.apk"
        if app_target == "Delivery Agent":
            return "finora-delivery-agent.apk"
        if app_target == "POS (finora_pos)":
            return "finora-pos.apk"
        return "finora-app.apk"

    @staticmethod
    def _parse_flutter_pubspec_version(pubspec: Path) -> tuple[str, int]:
        """Return (versionName, versionCode) from a Flutter pubspec.yaml."""
        try:
            text = pubspec.read_text(encoding="utf-8")
        except OSError:
            return "0.0.0", 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("version:"):
                continue
            raw = stripped.split(":", 1)[1].strip().strip("'\"")
            if "+" in raw:
                name, build = raw.split("+", 1)
                try:
                    return name.strip() or "0.0.0", int(build.strip() or "0")
                except ValueError:
                    return name.strip() or "0.0.0", 0
            return raw or "0.0.0", 0
        return "0.0.0", 0

    def _social_version_payload(self, local_path: Path, apk_name: str) -> dict:
        pubspec = local_path / "mobile" / "finora_social" / "pubspec.yaml"
        version_name, version_code = self._parse_flutter_pubspec_version(pubspec)
        return {
            "latest_version": version_name,
            "latest_build": version_code,
            "min_version": os.environ.get("APP_SOCIAL_APK_MIN_VERSION", "1.0.0").strip()
            or "1.0.0",
            "min_build": int(
                (os.environ.get("APP_SOCIAL_APK_MIN_BUILD") or "1").strip() or "1"
            ),
            "apk_url": f"/static/downloads/{apk_name}",
            "force": (os.environ.get("APP_SOCIAL_APK_FORCE") or "").strip().lower()
            in {"1", "true", "yes", "on"},
            "message": (
                os.environ.get("APP_SOCIAL_APK_UPDATE_MESSAGE")
                or "يتوفر تحديث جديد لتطبيق Finora. حدّث الآن لتحسين الأداء والحماية."
            ).strip(),
        }

    def _publish_apk_thread(self) -> None:
        start = time.perf_counter()
        try:
            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                self.set_status("APK publish failed (local path missing).")
                return

            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("APK publish failed (server path missing).")
                return

            app_target = self._effective_android_app(local_path)
            apk = self._find_latest_apk(local_path)
            if apk is None:
                self.append_log(
                    "[ERROR] No APK found. Build it first or choose it in APK path.\n"
                )
                self.set_status("APK publish failed (APK missing).")
                return

            remote_name = self._published_apk_name(app_target)
            remote_tmp = f"/tmp/{remote_name}.uploading"
            remote_dir = posixpath.join(server_path, "static", "downloads")
            remote_file = posixpath.join(remote_dir, remote_name)
            size = apk.stat().st_size
            self.append_log(
                f"[INFO] Publishing APK only: {apk.name} ({_format_file_size(size)}).\n"
            )
            self.append_log("[INFO] Source files and build folders are not included.\n")
            self.set_status("Publishing APK only…")

            if self.upload_file_to_server(apk, remote_tmp) != 0:
                self.set_status("APK publish failed while uploading.")
                return

            version_tmp = ""
            version_file = ""
            version_install = ""
            if app_target == "Social (finora_social)":
                version_payload = self._social_version_payload(local_path, remote_name)
                version_local = local_path / "artifacts" / "finora-social-version.json"
                version_local.parent.mkdir(parents=True, exist_ok=True)
                version_local.write_text(
                    json.dumps(version_payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                version_tmp = "/tmp/finora-social-version.json.uploading"
                version_file = posixpath.join(remote_dir, "finora-social-version.json")
                if self.upload_file_to_server(version_local, version_tmp) != 0:
                    self.set_status("APK publish failed while uploading version metadata.")
                    return
                version_install = f"""
install -m 0644 {shlex.quote(version_tmp)} {shlex.quote(version_file)}
rm -f {shlex.quote(version_tmp)}
echo "[OK] Version metadata published: {version_file}"
"""
                self.append_log(
                    "[INFO] Social version metadata: "
                    f"{version_payload['latest_version']}+{version_payload['latest_build']}\n"
                )

            install_script = f"""
set -e
install -d -m 0755 {shlex.quote(remote_dir)}
install -m 0644 {shlex.quote(remote_tmp)} {shlex.quote(remote_file)}
rm -f {shlex.quote(remote_tmp)}
echo "[OK] APK published: {remote_file}"
{version_install}
"""
            if self.run_ssh_script(install_script) != 0:
                self.append_log("[ERROR] APK uploaded but could not be installed on server.\n")
                self.set_status("APK publish failed while installing.")
                return

            self.append_log(f"[INFO] APK publish completed: {remote_file}\n")
            self.set_status("APK published successfully.")
        except Exception as exc:
            self.append_log(f"[ERROR] APK publish crashed: {exc}\n")
            self.set_status("APK publish failed (see log).")
        finally:
            duration = time.perf_counter() - start
            self.last_duration_var.set(f"Duration: {duration:.2f}s")
            self.set_busy(False)

    def _build_apk_thread(self) -> None:
        start = time.perf_counter()
        try:
            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                return

            app_target = self._effective_android_app(local_path)
            self.set_status(f"Building APK ({app_target})…")
            apk = self._build_apk_internal(local_path, app_target)
            if apk:
                self.append_log(f"[INFO] APK ready: {apk}\n")
                self.set_status("APK build completed.")
            else:
                self.set_status("Build APK failed (see log).")
        except Exception as exc:
            self.append_log(f"[ERROR] Build APK crashed: {exc}\n")
            self.set_status("Build APK failed (see log).")
        finally:
            duration = time.perf_counter() - start
            self.last_duration_var.set(f"Duration: {duration:.2f}s")
            self.set_busy(False)

    def _install_usb_thread(self) -> None:
        start = time.perf_counter()
        try:
            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                return

            adb_path = self._get_adb_path()
            self.set_status("USB install: detecting devices…")
            self.append_log("[INFO] Detecting Android devices via adb…\n")

            serial = self._resolve_usb_device(adb_path, local_path)
            if not serial:
                self.set_status("USB install failed (no devices).")
                return

            app_target = self._effective_android_app(local_path)
            self.append_log(f"[INFO] App target: {app_target}\n")

            apk = self._find_latest_apk(local_path)
            if apk is None:
                self.append_log(
                    f"[WARN] No APK found for {app_target}. Building automatically before install…\n"
                )
                self.set_status("Building APK before install…")
                apk = self._build_apk_internal(local_path, app_target)
                if apk is None:
                    self.append_log("[ERROR] Auto-build failed. Set Flutter path or build manually.\n")
                    initial_dir = self._preferred_apk_browse_dir(local_path, app_target)
                    chosen = filedialog.askopenfilename(
                        title="Select APK to install",
                        initialdir=str(initial_dir),
                        filetypes=[("Android APK", "*.apk"), ("All files", "*.*")],
                    )
                    if not chosen:
                        self.append_log("[INFO] APK selection cancelled.\n")
                        self.set_status("USB install cancelled.")
                        return
                    apk = Path(chosen)

            self.after(0, lambda p=apk, lp=local_path: self._set_apk_var_from_path(p, lp))
            self.append_log(f"[INFO] Using device: {serial}\n")
            self.append_log(f"[INFO] Installing APK: {apk}\n")
            self.set_status("USB install: installing APK…")

            cmd = [adb_path, "-s", serial, "install", "-r", str(apk)]
            self.append_log(f"$ {' '.join(cmd)}\n")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(local_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                    shell=False,
                )
            except FileNotFoundError:
                self.append_log(f"[ERROR] adb not found: {adb_path}\n")
                self.set_status("USB install failed (adb missing).")
                return

            assert proc.stdout is not None
            _stream_pipe_lines(proc.stdout, self.append_log)
            proc.wait()
            rc = proc.returncode
            self.last_command_var.set(f"Last: adb install -r {apk.name}")
            self.last_exit_code_var.set(f"Exit: {rc}")
            if rc != 0:
                self.append_log(f"[ERROR] APK install failed with code {rc}\n")
                self.set_status("USB install failed (see log).")
                return

            self.append_log("[INFO] APK installed successfully.\n")
            package = self._package_for_apk(apk)
            if package:
                self.append_log(f"[INFO] Launching {package} on device…\n")
                launch_rc = self._launch_app_on_device(adb_path, serial, package, local_path)
                if launch_rc == 0:
                    self.append_log("[INFO] App opened on phone.\n")
                else:
                    self.append_log(
                        "[WARN] Install OK but auto-launch failed. Tap the app icon on your phone.\n"
                    )
            else:
                self.append_log("[WARN] Install OK. Open the app manually from your phone.\n")

            self.set_status("USB install completed — check your phone.")
            self.after(
                0,
                lambda name=apk.name: messagebox.showinfo(
                    "تم التثبيت",
                    f"تم تثبيت التطبيق بنجاح:\n{name}\n\n"
                    "تحقق من شاشة هاتفك — يجب أن يفتح التطبيق تلقائياً.\n"
                    "إذا لم يفتح، ابحث عن أيقونة التطبيق في قائمة التطبيقات.",
                ),
            )
        finally:
            duration = time.perf_counter() - start
            self.last_duration_var.set(f"Duration: {duration:.2f}s")
            self.set_busy(False)

    def on_deploy_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._deploy_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _deploy_thread(self) -> None:
        archive_path: Path | None = None
        try:
            self.set_status("Smart Deploy: collecting changed files…")

            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                self.set_status("Deploy failed (local path missing).")
                return

            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("Deploy failed (server path empty).")
                return

            current_commit = self.current_git_commit(local_path)
            last_deployed_commit = (self.config_data.get("last_deployed_commit") or "").strip()
            if last_deployed_commit and current_commit:
                self.append_log(
                    f"[INFO] Smart Deploy diff range: {last_deployed_commit[:8]}..{current_commit[:8]}\n"
                )
            elif current_commit:
                self.append_log("[INFO] No previous deploy commit recorded; including latest commit changes once.\n")

            changed_paths, _skipped, deleted = self.collect_safe_changed_paths(
                local_path,
                since_commit=last_deployed_commit if current_commit else "",
            )
            if not changed_paths:
                self.append_log("[INFO] Smart Deploy found no safe modified/new files to upload.\n")
                if deleted:
                    self.append_log("[INFO] Deleted files were ignored; Smart Deploy does not delete server files.\n")
                self.set_status("Nothing changed to deploy.")
                return

            safe_server_path = shlex.quote(server_path)
            self.set_status("Smart Deploy: checking remote safety…")
            # Check only files this deployment will replace. If a target has
            # unknown live edits, back it up on the server before overwriting.
            manifest_file = shlex.quote(REMOTE_DEPLOY_MANIFEST)
            deploy_array = " ".join(shlex.quote(path) for path in changed_paths)
            preflight_script = f"""
cd {safe_server_path} || exit 41
DEPLOY_FILES=({deploy_array})
INVALID_DIRTY=0
BACKUP_ROOT=".finora-remote-backups/$(date +%Y%m%d-%H%M%S)"
for DIRTY_PATH in "${{DEPLOY_FILES[@]}}"; do
  STATUS_LINE="$(git -c core.quotepath=false status --porcelain -uno -- "$DIRTY_PATH")"
  [ -z "$STATUS_LINE" ] && continue
  EXPECTED_HASH=""
  if [ -f {manifest_file} ]; then
    EXPECTED_HASH="$(awk -F '\t' -v p="$DIRTY_PATH" '$2 == p {{ print $1; exit }}' {manifest_file})"
  fi
  if [ -f "$DIRTY_PATH" ]; then
    ACTUAL_HASH="$(sha256sum -- "$DIRTY_PATH" | cut -d' ' -f1)"
  else
    ACTUAL_HASH=""
  fi
  if [ -z "$EXPECTED_HASH" ] || [ "$ACTUAL_HASH" != "$EXPECTED_HASH" ]; then
    INVALID_DIRTY=1
    if [ -e "$DIRTY_PATH" ]; then
      BACKUP_PATH="$BACKUP_ROOT/$DIRTY_PATH"
      mkdir -p "$(dirname "$BACKUP_PATH")"
      cp -a -- "$DIRTY_PATH" "$BACKUP_PATH"
      echo "[BACKUP] Remote change saved before overwrite: $DIRTY_PATH -> $BACKUP_PATH"
    else
      echo "[WARN] Target changed remotely but no file exists to back up: $DIRTY_PATH"
    fi
  fi
done
if [ "$INVALID_DIRTY" -ne 0 ]; then
  echo "[OK] Unknown remote target edits were backed up under $BACKUP_ROOT; deploy can continue."
else
  echo "[OK] ${{#DEPLOY_FILES[@]}} deployment targets are safe; unrelated remote edits are preserved."
fi
"""
            rc_preflight = self.run_ssh_script(preflight_script)
            if rc_preflight != 0:
                self.append_log(
                    "[ERROR] Remote safety preflight failed; no files were uploaded.\n"
                )
                if rc_preflight == 127:
                    self.set_status("Deploy blocked (local SSH command missing).")
                else:
                    self.set_status("Deploy blocked (remote safety check failed).")
                return

            nginx_service = self.nginx_service_var.get().strip() or "nginx"
            # خدمة التطبيق في هذا السكربت اسمها finora كما في المواصفة
            service_name = "finora"

            # استخراج المنفذ من bind (مثال 127.0.0.1:8000)
            bind = self.gunicorn_bind_var.get().strip() or "127.0.0.1:8000"
            port = "8000"
            if ":" in bind:
                port = bind.split(":")[-1] or "8000"

            self.append_log(f"[INFO] Smart Deploy will upload {len(changed_paths)} changed file(s):\n")
            for p in changed_paths[:80]:
                self.append_log(f"  + {p}\n")
            if len(changed_paths) > 80:
                self.append_log(f"  ... and {len(changed_paths) - 80} more\n")

            deploy_sizes = [
                ((local_path / Path(path)).stat().st_size, path)
                for path in changed_paths
            ]
            total_deploy_bytes = sum(size for size, _ in deploy_sizes)
            self.append_log(
                f"[INFO] Code payload before compression: {_format_file_size(total_deploy_bytes)}.\n"
            )
            if total_deploy_bytes > SMART_DEPLOY_MAX_BYTES:
                self.append_log(
                    "[BLOCKED] Smart Deploy payload is unexpectedly large. "
                    "APK/build/artifact files must use their dedicated action.\n"
                )
                self.append_log("[INFO] Largest selected files:\n")
                for size, path in sorted(deploy_sizes, reverse=True)[:15]:
                    self.append_log(f"  - {_format_file_size(size):>9}  {path}\n")
                self.set_status("Deploy blocked (payload is too large).")
                return

            archive_path = self.make_changed_files_archive(local_path, changed_paths)
            remote_archive = posixpath.join("/tmp", archive_path.name)

            self.set_status("Smart Deploy: uploading changed files…")
            rc_upload = self.upload_file_to_server(archive_path, remote_archive)
            if rc_upload != 0:
                self.set_status("Deploy failed while uploading archive.")
                return

            needs_python_deps = any(p == "requirements.txt" for p in changed_paths)
            needs_social_build = any(
                p.startswith("static/ai_agent_frontend/")
                and (
                    p.endswith(".tsx")
                    or p.endswith(".ts")
                    or p.endswith(".js")
                    or p.endswith(".css")
                    or p.endswith("package.json")
                    or p.endswith("package-lock.json")
                    or p.endswith("vite.config.ts")
                )
                for p in changed_paths
            )
            needs_publisher_build = any(
                p.startswith("static/publisher_frontend/")
                and (
                    p.endswith(".tsx")
                    or p.endswith(".ts")
                    or p.endswith(".js")
                    or p.endswith(".css")
                    or p.endswith("package.json")
                    or p.endswith("package-lock.json")
                    or p.endswith("vite.config.ts")
                )
                for p in changed_paths
            )

            safe_archive = shlex.quote(remote_archive)
            pip_step = (
                "if [ -f requirements.txt ]; then pip install -r requirements.txt; fi"
                if needs_python_deps
                else "echo '[SKIP] requirements.txt unchanged'"
            )
            social_build_step = (
                "(cd static/ai_agent_frontend && npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund) && "
                "(cd static/ai_agent_frontend && npm run build)"
                if needs_social_build
                else "echo '[SKIP] Social AI frontend unchanged'"
            )
            publisher_build_step = (
                "(cd static/publisher_frontend && npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund) && "
                "(cd static/publisher_frontend && npm run build)"
                if needs_publisher_build
                else "echo '[SKIP] Publisher frontend unchanged'"
            )

            script = f"""#!/bin/bash
echo "=============================="
echo "FINORA SMART DEPLOY STARTING"
echo "=============================="

PROJECT_DIR={safe_server_path}
ARCHIVE={safe_archive}
SERVICE_NAME={shlex.quote(service_name)}
NGINX_SERVICE={shlex.quote(nginx_service)}
PORT={shlex.quote(port)}

cd "$PROJECT_DIR" || exit

echo ""
echo "[1] Extracting changed files only..."
tar -xzf "$ARCHIVE" -C "$PROJECT_DIR"
rm -f "$ARCHIVE"

echo "[1b] Recording deployed tracked-file fingerprints..."
MANIFEST={manifest_file}
MANIFEST_TMP="$MANIFEST.tmp"
DEPLOY_FILES=({deploy_array})
if [ -f "$MANIFEST" ]; then
    cp -f "$MANIFEST" "$MANIFEST_TMP"
else
    : > "$MANIFEST_TMP"
fi
for DEPLOY_PATH in "${{DEPLOY_FILES[@]}}"; do
    FILTERED="$MANIFEST_TMP.filtered"
    awk -F '\t' -v p="$DEPLOY_PATH" '$2 != p' "$MANIFEST_TMP" > "$FILTERED"
    mv -f "$FILTERED" "$MANIFEST_TMP"
    if [ -f "$DEPLOY_PATH" ]; then
        FILE_HASH="$(sha256sum -- "$DEPLOY_PATH" | cut -d' ' -f1)"
        printf '%s\t%s\n' "$FILE_HASH" "$DEPLOY_PATH" >> "$MANIFEST_TMP"
    fi
done
mv -f "$MANIFEST_TMP" "$MANIFEST"

echo ""
echo "[2] Activating virtual environment..."
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "No virtual environment found"
fi

echo ""
echo "[3] Python dependencies..."
{pip_step}

echo ""
echo "[4] Cleaning python cache..."
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {{}} +

echo ""
echo "[5] Frontend builds if relevant..."
{social_build_step}
{publisher_build_step}

echo ""
echo "[6] Restarting application safely..."
echo "Using service manager; no process-wide kill commands will be run."
# تأكد أن المنفذ حر قبل إعادة التشغيل
echo ""
systemctl restart "$SERVICE_NAME"

echo ""
echo "[7] Validating and reloading nginx..."
nginx -t
systemctl reload "$NGINX_SERVICE"

echo ""
echo "[8] Checking service status..."
systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "[9] Checking open ports..."
ss -ltnp 2>/dev/null | grep -E "[:.]$PORT[[:space:]]" || true

echo ""
# Give Gunicorn workers time to import the application, then validate both the
# systemd state and the TCP listening socket. `lsof -i` does not consistently
# print the word LISTEN across server versions, which caused false failures.
READY=0
for ATTEMPT in $(seq 1 45); do
  SERVICE_OK=0
  PORT_OK=0
  systemctl is-active --quiet "$SERVICE_NAME" && SERVICE_OK=1
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk '{{print $4}}' | grep -Eq "[:.]$PORT$" && PORT_OK=1
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q . && PORT_OK=1
  fi
  if [ "$SERVICE_OK" -eq 1 ] && [ "$PORT_OK" -eq 1 ]; then
    READY=1
    echo "[OK] $SERVICE_NAME is active and listening on port $PORT."
    break
  fi
  if [ "$ATTEMPT" -eq 1 ]; then
    echo "Waiting for Gunicorn workers to become ready..."
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  echo "[WARN] Service did not become ready on port $PORT within 90 seconds."
  echo ""
  echo "[10] Last 30 lines of service log (to see gunicorn error):"
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager 2>/dev/null || true
  echo ""
  echo "Tip: On server run: sudo journalctl -u $SERVICE_NAME -f   to watch logs. Use http:// (not https://) if SSL is not configured."
  exit 1
fi

echo "=============================="
echo "SMART DEPLOY COMPLETE"
echo "=============================="
"""

            self.set_status("Smart Deploy: applying files on server…")
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Smart Deploy completed successfully.\n")
                if current_commit:
                    self.config_data["last_deployed_commit"] = current_commit
                    self.save_config()
                self.set_status(f"Smart Deploy completed ({len(changed_paths)} files).")
            else:
                self.append_log("[WARN] Smart Deploy script exited with code %s. Check log above: port in use or gunicorn crash.\n" % rc)
                self.set_status("Smart Deploy finished with errors (see log).")
        finally:
            if archive_path:
                try:
                    archive_path.unlink(missing_ok=True)
                except Exception:
                    pass
            self.set_busy(False)

    def on_restart_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._restart_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _restart_thread(self) -> None:
        try:
            self.set_status("Restarting server services…")
            nginx_service = self.nginx_service_var.get().strip() or "nginx"
            server_path = self.server_path_var.get().strip()
            # اسم خدمة التطبيق في systemd يجب أن يتوافق مع server_tool.py
            app_service = "supermaxi.service"

            # إعادة تشغيل خدمة التطبيق + Nginx عبر systemd (أكثر ثباتاً من pkill / gunicorn اليدوي)
            script = (
                f"cd {server_path} && "
                f"systemctl restart {app_service} && "
                f"systemctl restart {nginx_service}"
            )
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Restart completed.\n")
                self.set_status("Restart completed.")
            else:
                self.set_status("Restart finished with errors (see log).")
        finally:
            self.set_busy(False)

    def on_view_logs_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._view_logs_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _view_logs_thread(self) -> None:
        try:
            self.set_status("Fetching server logs…")
            logs_cmd = self.config_data.get("logs_command") or DEFAULT_CONFIG["logs_command"]
            rc = self.run_ssh_script(logs_cmd)
            if rc == 0:
                self.set_status("Logs fetched.")
            else:
                self.set_status("Failed to fetch logs (see log).")
        finally:
            self.set_busy(False)

    def on_fix_nginx_proxy_clicked(self) -> None:
        """زر سريع لمحاولة إصلاح إعدادات Nginx / proxy للمشروع."""
        self.save_config()
        thread = threading.Thread(target=self._fix_nginx_proxy_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _fix_nginx_proxy_thread(self) -> None:
        try:
            self.set_status("Fixing Nginx proxy configuration…")
            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("Fix Nginx failed (server path empty).")
                return

            nginx_service = self.nginx_service_var.get().strip() or "nginx"

            script = f"""
cd {server_path} || {{ echo '[ERROR] Cannot cd to {server_path}'; exit 1; }}

CONF="/etc/nginx/sites-available/finora"
if [ ! -f "$CONF" ]; then
  echo "[ERROR] Nginx config $CONF not found."
else
  echo "=== Current finora.conf (head) ==="
  head -n 40 "$CONF" || true
fi

echo ""
echo "=== Testing Nginx configuration ==="
nginx -t || exit 1

echo ""
echo "=== Reloading Nginx service ({nginx_service}) ==="
systemctl reload {nginx_service}
"""
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Nginx proxy check completed.\n")
                self.set_status("Nginx proxy check completed (see log).")
            else:
                self.set_status("Fix Nginx finished with errors (see log).")
        finally:
            self.set_busy(False)

    def on_run_db_create_all_clicked(self) -> None:
        """إضافة الأعمدة الناقصة مباشرة من موديلات SQLAlchemy على السيرفر."""
        self.save_config()
        thread = threading.Thread(target=self._run_db_create_all_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _run_db_create_all_thread(self) -> None:
        try:
            self.set_status("Adding missing DB columns on server…")
            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("Add DB columns failed (server path empty).")
                return

            script = f"""
cd {server_path} || {{ echo '[ERROR] Cannot cd to {server_path}'; exit 1; }}
if [ -d "venv" ]; then
  source venv/bin/activate
fi
python - << 'PY'
import importlib
import pkgutil
from pathlib import Path

from flask import Flask, g
from sqlalchemy import create_engine, inspect
from sqlalchemy.schema import CreateColumn

from config import Config
from extensions import db

app = Flask(__name__, root_path=str(Path.cwd()))
app.config.from_object(Config)
db.init_app(app)


def load_all_models():
    import models

    for mod in pkgutil.iter_modules(models.__path__):
        if not mod.ispkg and mod.name != "__init__":
            try:
                importlib.import_module("models." + mod.name)
            except Exception as exc:
                print(f"[WARN] model import skipped: models.{{mod.name}}: {{exc}}")
    try:
        import models.core  # noqa: F401
        for mod in pkgutil.iter_modules(models.core.__path__):
            if not mod.ispkg and mod.name != "__init__":
                try:
                    importlib.import_module("models.core." + mod.name)
                except Exception as exc:
                    print(f"[WARN] model import skipped: models.core.{{mod.name}}: {{exc}}")
    except Exception as exc:
        print("[WARN] core model import skipped:", exc)


def column_sql(column, dialect):
    raw = str(CreateColumn(column).compile(dialect=dialect)).strip()
    # Keep ADD COLUMN safe for existing data. Database defaults/nullable columns
    # are fine; hard NOT NULL can fail when rows already exist.
    if not column.primary_key and not column.server_default and not column.default:
        raw = raw.replace(" NOT NULL", "")
    return raw


def add_missing_columns(engine, label):
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = 0
    skipped = 0
    errors = 0

    for table in sorted(db.Model.metadata.sorted_tables, key=lambda t: t.name):
        if table.name not in existing_tables:
            print(f"[SKIP] {{label}}.{{table.name}}: table missing; use app startup/create_all for new table")
            skipped += 1
            continue

        existing_cols = {{col["name"] for col in inspector.get_columns(table.name)}}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            if column.primary_key:
                print(f"[SKIP] {{label}}.{{table.name}}.{{column.name}}: primary key column")
                skipped += 1
                continue
            table_name = engine.dialect.identifier_preparer.quote(table.name)
            ddl = f"ALTER TABLE {{table_name}} ADD COLUMN {{column_sql(column, engine.dialect)}}"
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(ddl)
                print(f"[ADD] {{label}}.{{table.name}}.{{column.name}}")
                added += 1
            except Exception as exc:
                msg = str(exc)
                if "duplicate column" in msg.lower() or "already exists" in msg.lower():
                    print(f"[OK] {{label}}.{{table.name}}.{{column.name}} already exists")
                else:
                    print(f"[ERROR] {{label}}.{{table.name}}.{{column.name}}: {{exc}}")
                    errors += 1

    print(f"[SUMMARY] {{label}}: added={{added}}, skipped={{skipped}}, errors={{errors}}")
    return errors


def run_explicit_guards():
    # Keep local hand-written guards available for columns that are not fully
    # represented by model metadata yet.
    from utils.product_schema_guard import ensure_product_schema, ensure_customer_blacklist_columns
    from utils.branch_migration import ensure_branch_schema
    from utils.treasury_schema_guard import ensure_treasury_schema
    from utils.beauty_schema_guard import ensure_beauty_schema

    for guard in (
        ensure_product_schema,
        ensure_customer_blacklist_columns,
        ensure_branch_schema,
        ensure_treasury_schema,
        ensure_beauty_schema,
    ):
        try:
            guard()
            print(f"[GUARD] {{guard.__name__}} OK")
        except Exception as exc:
            db.session.rollback()
            print(f"[WARN] {{guard.__name__}} failed: {{exc}}")


with app.app_context():
    load_all_models()
    core_errors = add_missing_columns(db.engine, "core")
    run_explicit_guards()

    tenants_dir = Path(app.root_path) / "tenants"
    tenant_errors = 0
    if tenants_dir.is_dir():
        for dbf in sorted(tenants_dir.glob("*.db")):
            engine = create_engine("sqlite:///" + str(dbf.resolve()))
            tenant_errors += add_missing_columns(engine, "tenant:" + dbf.stem)
            old_tenant = getattr(g, "tenant", None)
            g.tenant = dbf.stem
            try:
                run_explicit_guards()
            finally:
                g.tenant = old_tenant
            engine.dispose()

    total_errors = core_errors + tenant_errors
    if total_errors:
        print(f"[WARN] DB column sync completed with {{total_errors}} non-fatal column error(s).")
        print("[WARN] Columns that could be added were applied. Review [ERROR] lines above for unsupported columns.")
    else:
        print("DB column sync completed successfully.")
PY
"""
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Missing DB columns sync finished.\n")
                self.set_status("DB columns synced.")
            else:
                self.set_status("DB column sync finished with errors (see log).")
        finally:
            self.set_busy(False)

    def on_ensure_telegram_inbox_table_clicked(self) -> None:
        """إنشاء/ترقية جدول inbox (Telegram + WhatsApp) على السيرفر."""
        self.save_config()
        thread = threading.Thread(target=self._ensure_telegram_inbox_table_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _ensure_telegram_inbox_table_thread(self) -> None:
        try:
            self.set_status("Creating/upgrading inbox table (TG+WA) on server…")
            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("Inbox DB failed (server path empty).")
                return

            script = f"""
cd {server_path} || {{ echo '[ERROR] Cannot cd to {server_path}'; exit 1; }}
if [ -d "venv" ]; then
  source venv/bin/activate
fi
python - << 'PY'
from pathlib import Path
from sqlalchemy import create_engine
from app import app, db
from models.telegram_inbox_message import TelegramInboxMessage

def ensure_channel_column(engine):
    from sqlalchemy import inspect
    insp = inspect(engine)
    cols = set([c.get("name") for c in insp.get_columns("telegram_inbox_messages")])
    if "channel" not in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE telegram_inbox_messages ADD COLUMN channel VARCHAR(20) DEFAULT 'telegram'"
            )
        print("channel column added")
    else:
        print("channel column already exists")

with app.app_context():
    TelegramInboxMessage.__table__.create(db.engine, checkfirst=True)
    ensure_channel_column(db.engine)
    print("main DB: telegram_inbox_messages OK (checkfirst + channel)")
    tenants_dir = Path(app.root_path) / "tenants"
    if tenants_dir.is_dir():
        for dbf in sorted(tenants_dir.glob("*.db")):
            eng = create_engine("sqlite:///" + str(dbf.resolve()))
            TelegramInboxMessage.__table__.create(bind=eng, checkfirst=True)
            ensure_channel_column(eng)
            print("tenant", dbf.stem + ": telegram_inbox_messages OK (checkfirst + channel)")
PY
"""
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Inbox table (Telegram + WhatsApp) ensured on server.\n")
                self.set_status("Inbox DB (TG+WA) OK.")
            else:
                self.set_status("Inbox DB (TG+WA) finished with errors (see log).")
        finally:
            self.set_busy(False)

    def on_fix_all_clicked(self) -> None:
        """زر Fix All: فحص أساسي للبيئة المحلية والسيرفر ومحاولة إصلاح سريع."""
        self.save_config()
        thread = threading.Thread(target=self._fix_all_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _fix_all_thread(self) -> None:
        import time

        start = time.perf_counter()
        try:
            self.set_status("Running Fix All on server…")
            self.append_log("[INFO] Starting full Fix All pipeline on server…\n")

            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("Fix All failed (server path empty).")
                return

            nginx_service = self.nginx_service_var.get().strip() or "nginx"
            # استخراج المنفذ من إعداد bind (مثال 127.0.0.1:8000)
            bind = self.gunicorn_bind_var.get().strip() or "127.0.0.1:8000"
            port = "8000"
            if ":" in bind:
                port = bind.split(":")[-1] or "8000"

            # نبني سكربت bash يطبق بالضبط خطوات المواصفات مع إعادة محاولة لكل أمر
            script = f"""
cd {server_path} || {{ echo '[ERROR] Cannot cd to {server_path}'; exit 1; }}

run_cmd() {{
  desc="$1"; shift
  echo ""
  echo "=== $desc ==="
  attempt=1
  max=2
  while [ $attempt -le $max ]; do
    "$@"
    status=$?
    if [ $status -eq 0 ]; then
      echo "--- OK"
      break
    else
      echo "--- Failed with code $status (attempt $attempt/$max)"
      if [ $attempt -lt $max ]; then
        echo '--- Retrying…'
      fi
    fi
    attempt=$((attempt+1))
  done
}};

run_cmd 'Mark repo as safe directory' git config --global --add safe.directory {server_path}
run_cmd 'Git fetch origin' git fetch origin
run_cmd 'Git reset --hard origin/main' git reset --hard origin/main

run_cmd 'Activate venv if exists' bash -lc 'if [ -d "venv" ]; then source venv/bin/activate; fi'
run_cmd 'Install Python dependencies' bash -lc 'if [ -f "requirements.txt" ]; then pip install -r requirements.txt; fi'

run_cmd 'Clean Python cache' bash -lc 'find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -exec rm -rf {{}} +'
run_cmd 'Clean static cache' bash -lc 'rm -rf static/build || true'

run_cmd 'Kill old gunicorn processes' bash -lc 'pkill -9 gunicorn || true'
run_cmd 'Free port {port}' bash -lc 'fuser -k {port}/tcp || true'

run_cmd 'Restart finora service' systemctl restart finora
run_cmd 'Restart nginx' systemctl restart {nginx_service}
run_cmd 'Check finora status' bash -lc 'systemctl status finora --no-pager || true'
run_cmd 'Verify gunicorn port {port}' bash -lc 'lsof -i :{port} || true'

echo ""
echo "System repaired and deployment completed successfully."
"""
            rc = self.run_ssh_script(script)
            duration = time.perf_counter() - start
            if rc == 0:
                self.append_log("[INFO] Fix All pipeline finished.\n")
                self.set_status(f"Fix All completed in {duration:.1f}s (see log).")
            else:
                self.append_log(f"[ERROR] Fix All script exited with code {rc}\n")
                self.set_status(f"Fix All finished with errors in {duration:.1f}s (see log).")
        finally:
            self.set_busy(False)

    def on_build_frontend_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._build_frontend_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _build_frontend_thread(self) -> None:
        try:
            self.set_status("Building frontends on server…")
            server_path = self.server_path_var.get().strip()
            script = (
                f"if [ -d {server_path}/static/ai_agent_frontend ]; then "
                f"cd {server_path}/static/ai_agent_frontend && npm install && npm run build; "
                "fi && "
                f"if [ -d {server_path}/static/publisher_frontend ]; then "
                f"cd {server_path}/static/publisher_frontend && npm install && npm run build; "
                "fi"
            )
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Frontends build completed.\n")
                self.set_status("Frontends build completed.")
            else:
                self.set_status("Frontends build failed (see log).")
        finally:
            self.set_busy(False)

    def on_build_social_ai_clicked(self) -> None:
        """زر: cd ai_agent_frontend → git pull → chmod .bin → npm run build"""
        self.save_config()
        thread = threading.Thread(target=self._build_social_ai_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _build_social_ai_thread(self) -> None:
        try:
            self.set_status("Building Social AI frontend on server…")
            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("Build Social AI failed (server path empty).")
                return
            script = (
                f"cd '{server_path}/static/ai_agent_frontend' || {{ echo '[ERROR] Directory not found'; exit 1; }} && "
                "git pull && "
                "chmod -R u+x node_modules/.bin 2>/dev/null || true && "
                "npm run build"
            )
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Social AI frontend build completed.\n")
                self.set_status("Social AI build completed.")
            else:
                self.set_status("Social AI build failed (see log).")
        finally:
            self.set_busy(False)


class ServerMonitorThread(threading.Thread):
    """
    Background thread that runs continuous health checks on the remote server
    via SSH every 10 seconds and attempts simple self-healing actions.

    All human-readable output is sent back to the main Tk thread using a queue.
    """

    def __init__(
        self,
        server: str,
        password: str,
        nginx_service: str,
        app_port: str,
        queue_out: "queue.Queue[dict]",
        interval_seconds: int = 10,
    ) -> None:
        super().__init__()
        self.server = server
        self.password = password or ""
        self.nginx_service = nginx_service or "nginx"
        self.app_port = app_port or "8000"
        self.queue_out = queue_out
        self.interval_seconds = max(5, interval_seconds)
        self._stop_flag = False
        self._restart_counters: dict[str, int] = {}

    def stop(self) -> None:
        self._stop_flag = True

    def _put_log(self, message: str) -> None:
        self.queue_out.put({"kind": "log", "message": message})

    def _put_status(self, data: dict) -> None:
        self.queue_out.put({"kind": "status", "data": data})

    def _safe_ssh_exec(self, script: str) -> tuple[int, str]:
        """
        Execute a small script on the remote server and return (exit_code, combined_output).
        Uses paramiko when a password is provided, otherwise falls back to system ssh.
        """
        output_lines: list[str] = []

        # Passwordless: use system ssh (keys / agent)
        if not self.password:
            full_cmd = [_resolve_command("ssh"), *SSH_CONNECT_OPTIONS, self.server, script]
            try:
                proc = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                )
                assert proc.stdout is not None
                collected: list[str] = []
                def _collect(line: str) -> None:
                    collected.append(line.rstrip("\n"))
                _stream_pipe_lines(proc.stdout, _collect)
                proc.wait()
                return proc.returncode, "\n".join(collected)
            except FileNotFoundError:
                output_lines.append("ssh command not found on local machine; falling back to Paramiko.")

        # With password: use paramiko (preferred for non-interactive monitoring)
        try:
            import paramiko  # type: ignore[import]
        except ImportError:
            return 1, "paramiko is not installed. Install with: pip install paramiko"

        host = self.server
        username = None
        if "@" in self.server:
            username, host = self.server.split("@", 1)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host,
                username=username,
                password=self.password or None,
                look_for_keys=not bool(self.password),
                allow_agent=not bool(self.password),
                timeout=15,
            )
            stdin, stdout, stderr = client.exec_command(script)
            while True:
                line = stdout.readline()
                if not line:
                    break
                output_lines.append(_decode_output_chunk(line).rstrip())
            while True:
                line = stderr.readline()
                if not line:
                    break
                decoded = _decode_output_chunk(line).strip()
                if decoded:
                    output_lines.append(decoded)
            exit_status = stdout.channel.recv_exit_status()
            return exit_status, "\n".join(output_lines)
        except Exception as e:  # noqa: BLE001
            return 1, f"SSH error: {e}"
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def _should_attempt_fix(self, key: str, max_attempts: int = 3) -> bool:
        current = self._restart_counters.get(key, 0)
        if current >= max_attempts:
            return False
        self._restart_counters[key] = current + 1
        return True

    def run(self) -> None:  # noqa: D401
        """
        Main monitoring loop.
        """
        self._put_log("[MONITOR] Self Healing Server Monitor thread started.")

        # Determine domain/host for HTTP / HTTPS checks (strip user part if any)
        host_for_http = self.server
        if "@" in host_for_http:
            _, host_for_http = host_for_http.split("@", 1)

        while not self._stop_flag:
            start_ts = datetime.now().strftime("%H:%M:%S")

            # One health check pass implemented as a single bash script to also persist /var/log/finora_monitor.log
            script = f"""
LOG_FILE="/var/log/finora_monitor.log"
NOW="{start_ts}"

log() {{
  msg="$1"
  echo "[$NOW] $msg"
  echo "[$NOW] $msg" >> "$LOG_FILE" 2>/dev/null || true
}}

nginx_status="unknown"
gunicorn_status="unknown"
https_status="unknown"
cpu_status="unknown"
ram_status="unknown"
disk_status="unknown"

log "[MONITOR] Checking nginx..."
if systemctl is-active --quiet {self.nginx_service}; then
  log "[OK] nginx running"
  nginx_status="OK"
else
  log "[ERROR DETECTED] nginx is down"
  nginx_status="DOWN"
fi

log "[MONITOR] Checking gunicorn/app service..."
if systemctl is-active --quiet finora || systemctl is-active --quiet supermaxi; then
  log "[OK] application service running"
  gunicorn_status="OK"
else
  log "[ERROR DETECTED] application service is down"
  gunicorn_status="DOWN"
fi

log "[MONITOR] Checking HTTPS response..."
if command -v curl >/dev/null 2>&1; then
  if curl -k -s -o /dev/null -w "%{{http_code}}" "https://{host_for_http}" | grep -q "^200$"; then
    log "[OK] HTTPS 200 from https://{host_for_http}"
    https_status="OK"
  else
    log "[ERROR DETECTED] HTTPS not returning 200"
    https_status="FAIL"
  fi
else
  log "[WARN] curl not installed on server."
fi

log "[MONITOR] Checking port {self.app_port}..."
if ss -tuln 2>/dev/null | grep -q ":{self.app_port} "; then
  log "[OK] Port {self.app_port} is listening"
else
  log "[ERROR DETECTED] Port {self.app_port} is not listening"
fi

log "[MONITOR] Checking disk usage..."
disk_line=$(df -h / | tail -n 1)
disk_pct=$(echo "$disk_line" | awk '{{print $5}}')
disk_status="$disk_pct"
log "[INFO] Disk usage: $disk_pct"

log "[MONITOR] Checking RAM usage..."
if command -v free >/dev/null 2>&1; then
  ram_pct=$(free | awk '/Mem:/ {{printf "%.0f%%", $3/$2*100}}')
  ram_status="$ram_pct"
  log "[INFO] RAM usage: $ram_pct"
fi

log "[MONITOR] Checking CPU load..."
if command -v uptime >/dev/null 2>&1; then
  cpu_load=$(uptime | awk -F'load average:' '{{print $2}}' | sed 's/^ //')
  cpu_status="$cpu_load"
  log "[INFO] CPU load: $cpu_load"
fi

echo ""
echo "NGINX_STATUS=$nginx_status"
echo "GUNICORN_STATUS=$gunicorn_status"
echo "HTTPS_STATUS=$https_status"
echo "CPU_STATUS=$cpu_status"
echo "RAM_STATUS=$ram_status"
echo "DISK_STATUS=$disk_status"
"""

            rc, out = self._safe_ssh_exec(script)
            if out:
                for line in out.splitlines():
                    if line.startswith("NGINX_STATUS=") or line.startswith("GUNICORN_STATUS="):
                        # handled below
                        continue
                    if line.startswith("HTTPS_STATUS=") or line.startswith("CPU_STATUS="):
                        continue
                    if line.startswith("RAM_STATUS=") or line.startswith("DISK_STATUS="):
                        continue
                    self._put_log(line)

            # Parse summarized status lines
            status_payload: dict[str, str] = {}
            for line in out.splitlines():
                if line.startswith("NGINX_STATUS="):
                    status_payload["nginx"] = line.split("=", 1)[1] or "-"
                elif line.startswith("GUNICORN_STATUS="):
                    status_payload["gunicorn"] = line.split("=", 1)[1] or "-"
                elif line.startswith("HTTPS_STATUS="):
                    status_payload["https"] = line.split("=", 1)[1] or "-"
                elif line.startswith("CPU_STATUS="):
                    status_payload["cpu"] = line.split("=", 1)[1] or "-"
                elif line.startswith("RAM_STATUS="):
                    status_payload["ram"] = line.split("=", 1)[1] or "-"
                elif line.startswith("DISK_STATUS="):
                    status_payload["disk"] = line.split("=", 1)[1] or "-"

            if status_payload:
                self._put_status(status_payload)

            # Simple self-healing decisions with limited retry counts
            if "nginx" in status_payload and status_payload["nginx"] == "DOWN":
                if self._should_attempt_fix("nginx"):
                    self._put_log("[AUTO FIX] Attempting to restart nginx…")
                    fix_script = f"""
LOG_FILE="/var/log/finora_monitor.log"
NOW="{start_ts}"
echo "[$NOW] [AUTO FIX] restarting nginx..." | tee -a "$LOG_FILE" 2>/dev/null || true
systemctl restart {self.nginx_service}
"""
                    _, out_fix = self._safe_ssh_exec(fix_script)
                    if out_fix:
                        for line in out_fix.splitlines():
                            self._put_log(line)
            if "gunicorn" in status_payload and status_payload["gunicorn"] == "DOWN":
                if self._should_attempt_fix("gunicorn"):
                    self._put_log("[AUTO FIX] Attempting to restart application service (gunicorn)…")
                    fix_script = f"""
LOG_FILE="/var/log/finora_monitor.log"
NOW="{start_ts}"
echo "[$NOW] [AUTO FIX] restarting finora/supermaxi service..." | tee -a "$LOG_FILE" 2>/dev/null || true
systemctl restart finora || systemctl restart supermaxi || true
"""
                    _, out_fix = self._safe_ssh_exec(fix_script)
                    if out_fix:
                        for line in out_fix.splitlines():
                            self._put_log(line)

            # Auto-clean logs if disk above 90%
            disk_val = status_payload.get("disk") or ""
            if disk_val.endswith("%"):
                try:
                    pct = int(disk_val.rstrip("%"))
                    if pct >= 90 and self._should_attempt_fix("disk_cleanup", max_attempts=2):
                        self._put_log("[AUTO FIX] Disk usage high, cleaning old journal logs…")
                        clean_script = f"""
LOG_FILE="/var/log/finora_monitor.log"
NOW="{start_ts}"
echo "[$NOW] [AUTO FIX] running journalctl vacuum..." | tee -a "$LOG_FILE" 2>/dev/null || true
journalctl --vacuum-time=3d || true
"""
                        _, out_clean = self._safe_ssh_exec(clean_script)
                        if out_clean:
                            for line in out_clean.splitlines():
                                self._put_log(line)
                except ValueError:
                    pass

            if rc != 0:
                self._put_log("[MONITOR] Monitoring script exited with non‑zero status; will retry.")

            # Sleep before next iteration, but break early if asked to stop
            for _ in range(self.interval_seconds):
                if self._stop_flag:
                    break
                time.sleep(1)

        self.queue_out.put({"kind": "stopped"})


if __name__ == "__main__":
    app = FinoraDeployStudio()
    app.mainloop()
