"""Which code is running: the branch and commit of the folder Clicky started from (pure Python, never raises).

Reads git's own files instead of running git, so startup stays fast and works without git on PATH. Handles a normal
checkout (`.git` is a folder) and a worktree (`.git` is a file pointing at its git folder, which shares refs with the
main repository through `commondir`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SHORT_COMMIT_LENGTH = 7


@dataclass(frozen=True)
class BuildInfo:
    branch: str
    commit: str  # short hash

    def describe(self) -> str:
        return f"{self.commit} ({self.branch})"


def _git_dirs(project_root: Path) -> tuple[Path, Path] | None:
    """(this checkout's git folder, the shared folder holding refs), or None if this isn't a git checkout."""
    dot_git = project_root / ".git"
    if dot_git.is_dir():
        return dot_git, dot_git
    if not dot_git.is_file():
        return None
    pointer = dot_git.read_text(encoding="utf-8").strip()
    if not pointer.startswith("gitdir:"):
        return None
    git_dir = Path(pointer[len("gitdir:") :].strip())
    if not git_dir.is_absolute():
        git_dir = (project_root / git_dir).resolve()
    common_file = git_dir / "commondir"
    if common_file.is_file():
        common = Path(common_file.read_text(encoding="utf-8").strip())
        return git_dir, common if common.is_absolute() else (git_dir / common).resolve()
    return git_dir, git_dir


def _resolve_ref(ref: str, folders: tuple[Path, ...]) -> str | None:
    for folder in folders:
        loose = folder / ref
        if loose.is_file():
            return loose.read_text(encoding="utf-8").strip()
    for folder in folders:
        packed = folder / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and not line.startswith(("#", "^")):
                    return parts[0]
    return None


def read_build_info(project_root: Path) -> BuildInfo | None:
    """The branch and short commit checked out at `project_root`, or None if it can't be told."""
    try:
        dirs = _git_dirs(project_root)
        if dirs is None:
            return None
        git_dir, common_dir = dirs
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head[len("ref:") :].strip()
            commit = _resolve_ref(ref, (git_dir, common_dir))
            branch = ref.removeprefix("refs/heads/")
        else:
            commit, branch = head, "detached"
        if not commit or len(commit) < SHORT_COMMIT_LENGTH:
            return None
        return BuildInfo(branch=branch, commit=commit[:SHORT_COMMIT_LENGTH])
    except (OSError, UnicodeDecodeError):
        return None
