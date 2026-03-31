import json
import os
import subprocess
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime

CONFIG_FILE = Path("finora_deploy_config.json")


DEFAULT_CONFIG = {
    "local_project_path": str(Path.cwd()),
    "server_ssh": "root@187.124.29.5",
    "server_project_path": "/var/www/finora/supermaxi",
    "nginx_service": "nginx",
    "gunicorn_bind": "127.0.0.1:8000",
    "gunicorn_workers": 3,
    "logs_command": "journalctl -u nginx -n 100 --no-pager",
    # كلمة السر لا نحفظها في الملف لأسباب أمان، تبقى فارغة في كل تشغيل
}


class FinoraDeployStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Finora Deploy Studio")
        self.geometry("980x620")
        self.minsize(900, 550)

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

        # Top frame: configuration only
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))

        # Config frame
        cfg = ttk.LabelFrame(top, text="Configuration")
        cfg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

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

        # Buttons bar (horizontal)
        btns = ttk.Frame(self)
        btns.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 4))

        self.push_btn = ttk.Button(btns, text="Push to GitHub", width=18, command=self.on_push_clicked)
        self.push_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.deploy_btn = ttk.Button(btns, text="Deploy to Server", width=18, command=self.on_deploy_clicked)
        self.deploy_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.restart_btn = ttk.Button(btns, text="Restart Server", width=18, command=self.on_restart_clicked)
        self.restart_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.logs_btn = ttk.Button(btns, text="View Server Logs", width=18, command=self.on_view_logs_clicked)
        self.logs_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.build_btn = ttk.Button(btns, text="Build Frontends", width=18, command=self.on_build_frontend_clicked)
        self.build_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.build_social_ai_btn = ttk.Button(
            btns,
            text="Build Social AI",
            width=18,
            command=self.on_build_social_ai_clicked,
        )
        self.build_social_ai_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.fix_all_btn = ttk.Button(btns, text="Fix All", width=18, command=self.on_fix_all_clicked)
        self.fix_all_btn.pack(side=tk.LEFT, padx=4, pady=4)

        # Quick maintenance / schedulers
        self.fix_nginx_btn = ttk.Button(
            btns,
            text="Fix Nginx / Proxy",
            width=18,
            command=self.on_fix_nginx_proxy_clicked,
        )
        self.fix_nginx_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.run_migrations_btn = ttk.Button(
            btns,
            text="Run DB create_all",
            width=18,
            command=self.on_run_db_create_all_clicked,
        )
        self.run_migrations_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.telegram_inbox_db_btn = ttk.Button(
            btns,
            text="Inbox DB (TG+WA)",
            width=18,
            command=self.on_ensure_telegram_inbox_table_clicked,
        )
        self.telegram_inbox_db_btn.pack(side=tk.LEFT, padx=4, pady=4)

        # Self Healing Monitor control
        self.start_monitor_btn = ttk.Button(
            btns, text="Start Monitor", width=18, command=self.on_start_monitor_clicked
        )
        self.start_monitor_btn.pack(side=tk.LEFT, padx=4, pady=4)

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
                    text=True,
                    bufsize=1,
                    shell=False,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.append_log(line)
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
            self.restart_btn,
            self.logs_btn,
            self.build_btn,
            self.fix_all_btn,
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
                    text=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.append_log(line)
                proc.wait()
                rc = proc.returncode
                if rc != 0:
                    self.append_log(f"[ERROR] Command failed with code {rc}: {cmd_str}\n")
                    # لا نوقف مباشرة لـ git commit الفارغ، نترك caller يقرّر
            except FileNotFoundError:
                self.append_log(f"[ERROR] Command not found: {cmd[0]}\n")
                return 1
        return rc

    def run_ssh_script(self, script: str) -> int:
        server = self.server_ssh_var.get().strip()
        if not server:
            self.append_log("[ERROR] Server SSH address is empty.\n")
            return 1
        password = self.server_password_var.get()

        # إذا ماكو باسورد: نستخدم ssh العادي (يتطلب مفاتيح أو جلسة بدون تفاعل)
        if not password:
            full_cmd = ["ssh", "-o", "BatchMode=yes", server, script]
            self.append_log(f"$ ssh {server} '{script}'\n")
            try:
                proc = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.append_log(line)
                proc.wait()
                rc = proc.returncode
                if rc != 0:
                    self.append_log(f"[ERROR] SSH command failed with code {rc}\n")
                return rc
            except FileNotFoundError:
                self.append_log("[ERROR] ssh command not found. Make sure OpenSSH is installed and in PATH.\n")
                return 1

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
                password=password,
                look_for_keys=False,
                allow_agent=False,
            )
            stdin, stdout, stderr = client.exec_command(script)
            for line in stdout:
                self.append_log(line)
            for line in stderr:
                if line.strip():
                    self.append_log(line)
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
            cmds = [
                ["git", "status"],
                ["git", "add", "."],
                ["git", "commit", "-m", "update"],
                ["git", "push"],
            ]
            rc = self.run_local_commands(cmds, cwd=local_path)
            if rc == 0:
                self.append_log("[INFO] Push to GitHub completed.\n")
                self.set_status("Push completed.")
            else:
                self.set_status("Push finished with errors (see log).")
        finally:
            self.set_busy(False)

    def on_deploy_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._deploy_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _deploy_thread(self) -> None:
        try:
            self.set_status("Deploying to server (upload script)…")

            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("Deploy failed (server path empty).")
                return

            nginx_service = self.nginx_service_var.get().strip() or "nginx"
            # خدمة التطبيق في هذا السكربت اسمها finora كما في المواصفة
            service_name = "finora"

            # استخراج المنفذ من bind (مثال 127.0.0.1:8000)
            bind = self.gunicorn_bind_var.get().strip() or "127.0.0.1:8000"
            port = "8000"
            if ":" in bind:
                port = bind.split(":")[-1] or "8000"

            # سكربت الدبلوي كما في الملف الذي أرسلته (upload script)
            script = f"""#!/bin/bash
echo "=============================="
echo "FINORA DEPLOY SCRIPT STARTING"
echo "=============================="

PROJECT_DIR="{server_path}"
SERVICE_NAME="{service_name}"
NGINX_SERVICE="{nginx_service}"
PORT="{port}"

cd "$PROJECT_DIR" || exit

echo ""
echo "[1] Fix git safe directory..."
git config --global --add safe.directory "$PROJECT_DIR"

echo ""
echo "[2] Updating code from GitHub..."
git fetch origin
git reset --hard origin/main

echo ""
echo "[3] Activating virtual environment..."
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "No virtual environment found"
fi

echo ""
echo "[4] Installing dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

echo ""
echo "[5] Cleaning python cache..."
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {{}} +

echo ""
echo "[6] Cleaning static build..."
rm -rf static/build 2>/dev/null

echo ""
echo "[6b] Building Social AI frontend (so /social-ai/ loads correctly)..."
if [ -d "static/ai_agent_frontend" ]; then
  (cd static/ai_agent_frontend && npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund) && (cd static/ai_agent_frontend && npm run build) || echo "[WARN] Social AI frontend build failed; /social-ai/ may show white page until you run: cd static/ai_agent_frontend && npm run build"
else
  echo "[SKIP] static/ai_agent_frontend not found"
fi

echo ""
echo "[7] Killing old gunicorn processes and freeing port..."
sudo pkill -9 gunicorn 2>/dev/null || true
sudo fuser -k "$PORT"/tcp 2>/dev/null || true
sleep 2
# تأكد أن المنفذ حر قبل إعادة التشغيل
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -t -i :"$PORT" 2>/dev/null)
  if [ -n "$PIDS" ]; then
    echo "[7b] Force killing remaining process(es) on port $PORT: $PIDS"
    echo "$PIDS" | xargs -r sudo kill -9 2>/dev/null || true
    sleep 1
  fi
fi

echo ""
echo "[8] Restarting application service..."
systemctl restart "$SERVICE_NAME"

echo ""
echo "[9] Restarting nginx..."
systemctl restart "$NGINX_SERVICE"

echo ""
echo "[10] Checking service status..."
systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "[11] Checking open ports..."
lsof -i :"$PORT"

echo ""
# التحقق من أن الخدمة تستمع على المنفذ (تفادي رسالة نجاح كاذبة)
LISTEN_CHECK=$(lsof -i :"$PORT" 2>/dev/null | grep -c LISTEN || true)
if [ "$LISTEN_CHECK" -lt 1 ]; then
  echo "[WARN] No process is listening on port $PORT. Gunicorn may have failed to start (e.g. Address already in use or app crash)."
  echo ""
  echo "[12] Last 30 lines of service log (to see gunicorn error):"
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager 2>/dev/null || true
  echo ""
  echo "Tip: On server run: sudo journalctl -u $SERVICE_NAME -f   to watch logs. Use http:// (not https://) if SSL is not configured."
  exit 1
fi

echo "=============================="
echo "DEPLOYMENT COMPLETE"
echo "=============================="
"""

            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Deploy completed successfully.\n")
                self.set_status("Deploy completed.")
            else:
                self.append_log("[WARN] Deploy script exited with code %s. Check log above: port in use or gunicorn crash. Try http:// (not https://) if you see ERR_SSL_PROTOCOL_ERROR.\n" % rc)
                self.set_status("Deploy finished with errors (see log).")
        finally:
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
        """تشغيل db.create_all() على السيرفر داخل app context."""
        self.save_config()
        thread = threading.Thread(target=self._run_db_create_all_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _run_db_create_all_thread(self) -> None:
        try:
            self.set_status("Running db.create_all() on server…")
            server_path = self.server_path_var.get().strip()
            if not server_path:
                self.append_log("[ERROR] Server project path is empty.\n")
                self.set_status("DB create_all failed (server path empty).")
                return

            script = f"""
cd {server_path} || {{ echo '[ERROR] Cannot cd to {server_path}'; exit 1; }}
if [ -d "venv" ]; then
  source venv/bin/activate
fi
python - << 'PY'
from app import app, db
with app.app_context():
    # يجب استيراد النماذج قبل create_all() وإلا لا يُنشأ الجدول في Metadata
    from models.telegram_inbox_message import TelegramInboxMessage  # noqa: F401
    db.create_all()
    print("db.create_all() completed successfully.")
    try:
        from sqlalchemy import inspect
        if inspect(db.engine).has_table("telegram_inbox_messages"):
            print("telegram_inbox_messages: OK")
        else:
            print("WARNING: telegram_inbox_messages table not listed after create_all")
    except Exception as _e:
        print("inspect:", _e)
PY
"""
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] db.create_all() executed successfully.\n")
                self.set_status("DB create_all completed.")
            else:
                self.set_status("DB create_all finished with errors (see log).")
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
    with engine.connect() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(telegram_inbox_messages)").fetchall()]
        if "channel" not in cols:
            conn.exec_driver_sql("ALTER TABLE telegram_inbox_messages ADD COLUMN channel VARCHAR(20) DEFAULT 'telegram'")
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
            full_cmd = ["ssh", "-o", "BatchMode=yes", self.server, script]
            try:
                proc = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    output_lines.append(line.rstrip())
                proc.wait()
                return proc.returncode, "\n".join(output_lines)
            except FileNotFoundError:
                return 1, "ssh command not found on local machine."

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
                password=self.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=15,
            )
            stdin, stdout, stderr = client.exec_command(script)
            for line in stdout:
                output_lines.append(line.rstrip())
            for line in stderr:
                if line.strip():
                    output_lines.append(line.rstrip())
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