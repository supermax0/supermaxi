import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from finora_deploy_studio import (
    FinoraDeployStudio,
    SSH_CONNECT_OPTIONS,
    SMART_UPLOAD_STALL_TIMEOUT_SECONDS,
    _format_file_size,
)


class _Var:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def test_format_file_size() -> None:
    assert _format_file_size(0) == "0.0 B"
    assert _format_file_size(1024) == "1.0 KB"
    assert _format_file_size(5 * 1024 * 1024) == "5.0 MB"


def test_key_based_sftp_is_resumable_and_non_interactive(tmp_path: Path) -> None:
    source = tmp_path / "deploy.tar.gz"
    source.write_bytes(b"archive")

    studio = object.__new__(FinoraDeployStudio)
    studio.server_ssh_var = _Var("root@example.test")
    studio.server_password_var = _Var("")
    studio.append_log = Mock()

    process = Mock()
    process.stdout = Mock()
    process.stdout.readline.return_value = b""
    process.poll.return_value = 0
    process.returncode = 0

    with (
        patch("finora_deploy_studio._resolve_command", side_effect=lambda name: name),
        patch("finora_deploy_studio.subprocess.Popen", return_value=process) as popen,
    ):
        rc = studio.upload_file_to_server(source, "/tmp/deploy.tar.gz")

    assert rc == 0
    command = popen.call_args.args[0]
    assert command[:3] == ["sftp", "-q", "-b"]
    assert command[-(len(SSH_CONNECT_OPTIONS) + 1) : -1] == SSH_CONNECT_OPTIONS
    assert command[-1] == "root@example.test"
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL


def test_resumable_sftp_retries_same_remote_upload(tmp_path: Path) -> None:
    source = tmp_path / "deploy.tar.gz"
    source.write_bytes(b"archive")

    studio = object.__new__(FinoraDeployStudio)
    studio.server_ssh_var = _Var("root@example.test")
    studio.server_password_var = _Var("")
    studio.append_log = Mock()

    failed = Mock(stdout=Mock(), returncode=255)
    failed.stdout.readline.side_effect = [b"broken pipe\n", b""]
    failed.poll.return_value = 255
    succeeded = Mock(stdout=Mock(), returncode=0)
    succeeded.stdout.readline.return_value = b""
    succeeded.poll.return_value = 0

    with (
        patch("finora_deploy_studio._resolve_command", side_effect=lambda name: name),
        patch(
            "finora_deploy_studio.subprocess.Popen",
            side_effect=[failed, succeeded],
        ) as popen,
        patch(
            "finora_deploy_studio.subprocess.run",
            return_value=Mock(returncode=0),
        ),
        patch("finora_deploy_studio.time.sleep"),
    ):
        rc = studio.upload_file_to_server(source, "/tmp/deploy.tar.gz")

    assert rc == 0
    assert popen.call_count == 2
    first_command = popen.call_args_list[0].args[0]
    second_command = popen.call_args_list[1].args[0]
    assert "-a" not in first_command
    assert "-a" in second_command
    assert first_command[-1] == second_command[-1] == "root@example.test"
    assert first_command[first_command.index("-b") + 1] == second_command[second_command.index("-b") + 1]


def test_resumable_sftp_restarts_stalled_upload(tmp_path: Path) -> None:
    source = tmp_path / "deploy.tar.gz"
    source.write_bytes(b"archive")

    studio = object.__new__(FinoraDeployStudio)
    studio.server_ssh_var = _Var("root@example.test")
    studio.server_password_var = _Var("")
    studio.append_log = Mock()

    stalled = Mock(stdout=Mock(), returncode=255)
    stalled.stdout.readline.return_value = b""
    stalled.poll.return_value = None
    stalled.kill = Mock()
    stalled.wait = Mock()
    succeeded = Mock(stdout=Mock(), returncode=0)
    succeeded.stdout.readline.return_value = b""
    succeeded.poll.return_value = 0

    remote_stat = Mock(returncode=0, stdout=b"0\n")

    with (
        patch("finora_deploy_studio._resolve_command", side_effect=lambda name: name),
        patch(
            "finora_deploy_studio.subprocess.Popen",
            side_effect=[stalled, succeeded],
        ) as popen,
        patch("finora_deploy_studio.subprocess.run", return_value=remote_stat),
        patch(
            "finora_deploy_studio.time.monotonic",
            side_effect=[
                0,
                0,
                SMART_UPLOAD_STALL_TIMEOUT_SECONDS + 1,
                SMART_UPLOAD_STALL_TIMEOUT_SECONDS + 2,
                SMART_UPLOAD_STALL_TIMEOUT_SECONDS + 3,
            ],
        ),
        patch("finora_deploy_studio.time.sleep"),
    ):
        rc = studio.upload_file_to_server(source, "/tmp/deploy.tar.gz")

    assert rc == 0
    assert popen.call_count == 2
    stalled.kill.assert_called_once()


def test_runtime_learning_memory_is_never_uploaded() -> None:
    studio = object.__new__(FinoraDeployStudio)

    assert studio.is_safe_push_path("ai/parser.py") is True
    assert studio.is_safe_push_path("tests/test_orders.py") is False
    assert studio.is_safe_push_path("desktop/finora_core/e2e/__screenshots__/orb.png") is False
    assert studio.is_safe_push_path("ai/learned_areas.json") is False
    assert studio.is_safe_push_path("ai/learned_cities.json") is False
    assert studio.is_safe_push_path("finora_deploy_studio.py") is False
    assert studio.is_safe_push_path("artifacts/finora-social-debug.apk") is False
    assert studio.is_safe_push_path("static/downloads/finora-social.apk") is False
    assert studio.is_safe_push_path("mobile/finora_social/lib/main.dart") is False
    assert studio.is_safe_push_path("mobile/finora_social/build/output.bin") is False
    assert studio.is_safe_push_path("backups/old/app.py") is False
    assert studio.is_safe_push_path("tenants/test_deferred_stock_3356.db-wal") is False
    assert studio.is_safe_push_path("tenants/demo.db-shm") is False
    assert studio.is_safe_push_path("investment_server_5008.err") is False
    assert studio.is_safe_push_path("investment_server_5008.out") is False
    assert studio.is_safe_push_path(
        ".codex-tmp/media-runtime/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
    ) is False
    assert studio.is_safe_push_path("tools/helper.exe") is False
    assert studio.is_safe_push_path("static/branding/finora-dashboard-intro.mp4") is True


def test_publish_apk_uploads_only_the_selected_artifact(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    apk = artifacts / "finora-social-debug.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        zf.writestr("META-INF/CERT.SF", "Signature-Version: 1.0\n")
        zf.writestr("classes.dex", b"apk-only")
    pubspec = tmp_path / "mobile" / "finora_social" / "pubspec.yaml"
    pubspec.parent.mkdir(parents=True)
    pubspec.write_text("name: finora_social\nversion: 1.2.1+4\n", encoding="utf-8")

    studio = object.__new__(FinoraDeployStudio)
    studio.local_path_var = _Var(str(tmp_path))
    studio.server_path_var = _Var("/var/www/finora/supermaxi")
    studio.android_app_var = _Var("Social (finora_social)")
    studio.android_apk_var = _Var("")
    studio.last_duration_var = _Var("")
    studio.config_data = {"android_apk_path": ""}
    studio.append_log = Mock()
    studio.set_status = Mock()
    studio.set_busy = Mock()
    studio.upload_file_to_server = Mock(return_value=0)
    studio.run_ssh_script = Mock(return_value=0)

    studio._publish_apk_thread()

    assert studio.upload_file_to_server.call_count == 2
    studio.upload_file_to_server.assert_any_call(
        apk, "/tmp/finora-social.apk.uploading"
    )
    version_local = tmp_path / "artifacts" / "finora-social-version.json"
    assert version_local.is_file()
    studio.upload_file_to_server.assert_any_call(
        version_local, "/tmp/finora-social-version.json.uploading"
    )
    install_script = studio.run_ssh_script.call_args.args[0]
    assert "/static/downloads/finora-social.apk" in install_script
    assert "finora-social-version.json" in install_script
    assert "mobile/" not in install_script
    studio.set_busy.assert_called_once_with(False)


def test_smart_deploy_skips_local_exports_but_keeps_public_assets(tmp_path: Path) -> None:
    excluded = [
        "marketing/finora-promo/final/FINORA-promo-16x9-4K.mp4",
        "marketing/finora-promo/finora-promo-30s.mp4",
        "docs/reports/finora-consultation-details.json",
        "output/public-flow-redesign/login-1440.png",
    ]
    included = [
        "templates/login.html", "static/css/public-flow.css",
        "static/images/landing/inventory.png",
        "static/branding/finora-dashboard-intro.mp4",
        "docs/deployment.md",
    ]
    for rel in excluded + included:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    studio = object.__new__(FinoraDeployStudio)
    studio.append_log = Mock()
    candidates = b"\0".join(p.encode() for p in excluded + included) + b"\0"
    studio.git_capture_bytes = Mock(side_effect=[(0, candidates)] + [(0, b"")] * 4)

    selected, skipped, deleted = studio.collect_safe_changed_paths(tmp_path)

    assert selected == included
    assert skipped == excluded
    assert deleted == []
    # Keeping local marketing source in Git is independent of server deployment.
    assert studio.is_safe_push_path(excluded[0]) is True


def test_oversized_payload_stops_before_any_remote_action(tmp_path: Path) -> None:
    source = tmp_path / "large.bin"
    source.write_bytes(b"oversized")
    studio = object.__new__(FinoraDeployStudio)
    studio.local_path_var = _Var(str(tmp_path))
    studio.server_path_var = _Var("/srv/finora")
    studio.config_data = {}
    studio.append_log = Mock()
    studio.set_status = Mock()
    studio.set_busy = Mock()
    studio.validate_local_project_path = Mock(return_value=True)
    studio.current_git_commit = Mock(return_value="commit")
    studio.collect_safe_changed_paths = Mock(return_value=(["large.bin"], [], []))
    studio.run_ssh_script = Mock()
    studio.upload_file_to_server = Mock()
    studio.make_changed_files_archive = Mock()

    with patch("finora_deploy_studio.SMART_DEPLOY_MAX_BYTES", 1):
        studio._deploy_thread()

    studio.set_status.assert_called_with("Deploy blocked (payload is too large).")
    studio.run_ssh_script.assert_not_called()
    studio.upload_file_to_server.assert_not_called()
    studio.make_changed_files_archive.assert_not_called()
    studio.set_busy.assert_called_once_with(False)
