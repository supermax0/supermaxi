"""Use real repositories to ensure deployment cannot discard local work."""
import subprocess
import runpy
from pathlib import Path

import pytest

from scripts.safe_git_update import safe_git_update


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


@pytest.fixture
def release(tmp_path):
    git(tmp_path, 'init')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Deployment test')
    (tmp_path / 'app.py').write_text('old release\n')
    (tmp_path / '.gitignore').write_text('server-only.py\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'baseline')
    baseline = git(tmp_path, 'rev-parse', 'HEAD')
    (tmp_path / 'app.py').write_text('new release\n')
    git(tmp_path, 'commit', '-am', 'release')
    target = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'checkout', '--detach', baseline)
    return tmp_path, target


def test_clean_fast_forward_preserves_untracked_data(release):
    repo, target = release
    (repo / 'customer.db').write_bytes(b'customer data')
    safe_git_update(repo, target)
    assert git(repo, 'rev-parse', 'HEAD') == target
    assert (repo / 'app.py').read_text() == 'new release\n'
    assert (repo / 'customer.db').read_bytes() == b'customer data'


@pytest.mark.parametrize('staged', [False, True])
def test_local_features_block_update_without_changing_files(release, staged):
    repo, target = release
    before = git(repo, 'rev-parse', 'HEAD')
    (repo / 'app.py').write_text('months of local features\n')
    if staged:
        git(repo, 'add', 'app.py')
    with pytest.raises(RuntimeError, match='local changes'):
        safe_git_update(repo, target)
    assert git(repo, 'rev-parse', 'HEAD') == before
    assert (repo / 'app.py').read_text() == 'months of local features\n'


def test_divergent_history_is_not_reset(release):
    repo, target = release
    (repo / 'local-feature.py').write_text('feature\n')
    git(repo, 'add', 'local-feature.py')
    git(repo, 'commit', '-m', 'local work')
    before = git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(RuntimeError, match='diverges'):
        safe_git_update(repo, target)
    assert git(repo, 'rev-parse', 'HEAD') == before


def test_ignored_server_only_file_is_not_overwritten(release):
    repo, target = release
    baseline = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '--detach', target)
    (repo / 'server-only.py').write_text('upstream\n')
    git(repo, 'add', '-f', 'server-only.py')
    git(repo, 'commit', '-m', 'incoming ignored file')
    target = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '--detach', baseline)
    (repo / 'server-only.py').write_text('live local implementation\n')
    with pytest.raises(RuntimeError, match='server-only file'):
        safe_git_update(repo, target)
    assert (repo / 'server-only.py').read_text() == 'live local implementation\n'


def test_deploy_failure_returns_nonzero_without_restarting(tmp_path):
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'server_tool.py deploy'))
    calls = []
    def fail_fetch(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)
    deploy = namespace['deploy']
    deploy.__globals__.update(REPO_DIR=tmp_path, run=fail_fetch, log=lambda message: None)
    with pytest.raises(SystemExit) as exc:
        deploy()
    assert exc.value.code == 1
    assert calls == [['git', 'fetch', 'origin']]
