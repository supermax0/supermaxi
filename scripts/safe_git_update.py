"""Fast-forward a deployment without discarding server-side changes."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def safe_git_update(repo: Path, ref: str = "origin/main") -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise RuntimeError(
            "Deployment stopped: tracked server files have local changes. "
            "Back up and merge those changes before deploying. No files were replaced."
        )
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", ref], cwd=repo, check=False
    ).returncode:
        raise RuntimeError("Deployment stopped: server history diverges from the release.")

    tracked = set(git("ls-files", "-z").split("\0"))
    incoming = git("diff", "--name-only", "--diff-filter=ACMRT", "-z", "HEAD", ref)
    for name in incoming.split("\0"):
        if name and name not in tracked and (repo / name).exists():
            raise RuntimeError(
                f"Deployment stopped: incoming file would replace a server-only file: {name}"
            )
    subprocess.run(["git", "merge", "--ff-only", ref], cwd=repo, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="origin/main")
    args = parser.parse_args()
    try:
        safe_git_update(Path(__file__).resolve().parents[1], args.ref)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")
