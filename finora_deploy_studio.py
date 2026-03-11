import json
import os
import subprocess
import threading
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
        # Top frame: config + buttons
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=10)

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

        # Buttons frame
        btns = ttk.Frame(top)
        btns.pack(side=tk.RIGHT, fill=tk.Y)

        self.push_btn = ttk.Button(btns, text="Push to GitHub", width=18, command=self.on_push_clicked)
        self.push_btn.grid(row=0, column=0, padx=4, pady=4)

        self.deploy_btn = ttk.Button(btns, text="Deploy to Server", width=18, command=self.on_deploy_clicked)
        self.deploy_btn.grid(row=1, column=0, padx=4, pady=4)

        self.restart_btn = ttk.Button(btns, text="Restart Server", width=18, command=self.on_restart_clicked)
        self.restart_btn.grid(row=2, column=0, padx=4, pady=4)

        self.logs_btn = ttk.Button(btns, text="View Server Logs", width=18, command=self.on_view_logs_clicked)
        self.logs_btn.grid(row=3, column=0, padx=4, pady=4)

        self.build_btn = ttk.Button(btns, text="Build Frontend", width=18, command=self.on_build_frontend_clicked)
        self.build_btn.grid(row=4, column=0, padx=4, pady=4)

        # Progress + status
        status_frame = ttk.Frame(self)
        status_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 4))

        self.progress = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.status_var = tk.StringVar(value="Ready.")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, anchor="e")
        status_label.pack(side=tk.RIGHT)

        # Log output + command input
        log_frame = ttk.LabelFrame(self, text="Terminal / Log Output")
        log_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        self.log_text = tk.Text(
            log_frame,
            bg="#020617",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            wrap="word",
            state="disabled",
        )
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scroll.set)

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

        self.append_log("Finora Deploy Studio started.\n")

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
        self.log_text.insert(tk.END, text)
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
        try:
            local_path = Path(self.local_path_var.get().strip() or ".")
            if not local_path.exists():
                self.append_log(f"[ERROR] Local path does not exist: {local_path}\n")
                return

            parts = cmd_str.split()
            if not parts:
                return

            self.append_log(f"$ {cmd_str}\n")
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
                if rc != 0:
                    self.append_log(f"[ERROR] Command exited with code {rc}\n")
                else:
                    self.append_log("[INFO] Command finished successfully.\n")
            except FileNotFoundError:
                self.append_log(f"[ERROR] Command not found: {parts[0]}\n")
        finally:
            self.set_busy(False)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def set_busy(self, busy: bool) -> None:
        widgets = [self.push_btn, self.deploy_btn, self.restart_btn, self.logs_btn, self.build_btn]
        if busy:
            for w in widgets:
                w.config(state="disabled")
            self.progress.start(80)
        else:
            for w in widgets:
                w.config(state="normal")
            self.progress.stop()

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
            self.set_status("Deploying to server…")

            server_path = self.server_path_var.get().strip()
            bind = self.gunicorn_bind_var.get().strip()
            workers = self.gunicorn_workers_var.get().strip() or "3"
            nginx_service = self.nginx_service_var.get().strip() or "nginx"

            # سكربت الدبلوي عن بعد (يُنفّذ داخل الشيل على السيرفر)
            script = (
                f"cd {server_path} && "
                "git pull && "
                "pkill -f gunicorn || true && "
                "source venv/bin/activate && "
                f"gunicorn app:app -b {bind} -w {workers} --daemon && "
                f"systemctl restart {nginx_service}"
            )

            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Deploy completed successfully.\n")
                self.set_status("Deploy completed.")
            else:
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
            bind = self.gunicorn_bind_var.get().strip()
            workers = self.gunicorn_workers_var.get().strip() or "3"

            script = (
                f"cd {server_path} && "
                "pkill -f gunicorn || true && "
                "source venv/bin/activate && "
                f"gunicorn app:app -b {bind} -w {workers} --daemon && "
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

    def on_build_frontend_clicked(self) -> None:
        self.save_config()
        thread = threading.Thread(target=self._build_frontend_thread, daemon=True)
        self.set_busy(True)
        thread.start()

    def _build_frontend_thread(self) -> None:
        try:
            self.set_status("Building frontend on server…")
            server_path = self.server_path_var.get().strip()
            script = (
                f"cd {server_path}/static/ai_agent_frontend && "
                "npm install && "
                "npm run build"
            )
            rc = self.run_ssh_script(script)
            if rc == 0:
                self.append_log("[INFO] Frontend build completed.\n")
                self.set_status("Frontend build completed.")
            else:
                self.set_status("Frontend build failed (see log).")
        finally:
            self.set_busy(False)


if __name__ == "__main__":
    app = FinoraDeployStudio()
    app.mainloop()