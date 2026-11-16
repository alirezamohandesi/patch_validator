"""Thin, explicit wrapper around the git CLI.

Only the operations the validator actually needs are exposed.  Every revision
the tool is given is resolved to a full commit hash immediately and that hash
is what ends up in the report, so a report never depends on a branch name that
may have moved since.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import VcsError

log = logging.getLogger(__name__)

_GIT_TIMEOUT = 120


@dataclass(frozen=True)
class CommitInfo:
    """Identifying metadata for one commit."""

    revision: str
    commit: str
    subject: str
    author: str
    authored_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "revision": self.revision,
            "commit": self.commit,
            "subject": self.subject,
            "author": self.author,
            "authored_at": self.authored_at,
        }


class GitRepo:
    """A git repository the validator reads revisions and diffs from."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if shutil.which("git") is None:
            raise VcsError(
                "git executable not found",
                remedy="install git; the validator needs it to read target revisions",
            )
        if not (path / ".git").exists():
            raise VcsError(f"{path} is not a git repository")

    def _run(self, *args: str, check: bool = True) -> str:
        command = ["git", "-C", str(self.path), *args]
        log.debug("git: %s", " ".join(args))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VcsError(f"git {' '.join(args)} timed out") from exc
        except OSError as exc:
            raise VcsError(f"cannot run git: {exc}") from exc

        if check and completed.returncode != 0:
            raise VcsError(
                f"git {' '.join(args)} failed with exit code "
                f"{completed.returncode}: {completed.stderr.strip()}"
            )
        return completed.stdout

    def resolve(self, revision: str) -> str:
        """Resolve a branch, tag or abbreviated hash to a full commit hash."""
        output = self._run("rev-parse", "--verify", f"{revision}^{{commit}}").strip()
        if not output:
            raise VcsError(f"cannot resolve revision '{revision}'")
        return output

    def describe(self, revision: str) -> CommitInfo:
        commit = self.resolve(revision)
        fields = self._run(
            "show", "--no-patch", "--format=%s%n%an <%ae>%n%aI", commit
        ).splitlines()
        subject = fields[0] if fields else ""
        author = fields[1] if len(fields) > 1 else ""
        authored_at = fields[2] if len(fields) > 2 else ""
        return CommitInfo(
            revision=revision,
            commit=commit,
            subject=subject,
            author=author,
            authored_at=authored_at,
        )

    def diff(self, base: str, patched: str, *, context: int = 3) -> str:
        """Return the unified diff introduced between two commits."""
        return self._run(
            "diff",
            f"--unified={context}",
            "--no-color",
            "--no-ext-diff",
            f"{self.resolve(base)}..{self.resolve(patched)}",
        )

    def file_at(self, revision: str, relative_path: str) -> str | None:
        """Return the text of one file at one revision, or None if absent."""
        command = ["show", f"{self.resolve(revision)}:{relative_path}"]
        completed = subprocess.run(
            ["git", "-C", str(self.path), *command],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
            errors="replace",
        )
        if completed.returncode != 0:
            return None
        return completed.stdout

    def add_worktree(self, revision: str, destination: Path) -> Path:
        """Check ``revision`` out into ``destination`` as a detached worktree.

        A worktree is used rather than a checkout so the two versions under
        comparison exist side by side and neither disturbs the user's own
        checkout of the target repository.
        """
        commit = self.resolve(revision)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            self.remove_worktree(destination)
        self._run("worktree", "add", "--detach", "--force", str(destination), commit)
        log.debug("worktree for %s (%s) at %s", revision, commit[:12], destination)
        return destination

    def remove_worktree(self, destination: Path) -> None:
        """Remove a worktree, falling back to a plain delete if git refuses."""
        self._run("worktree", "remove", "--force", str(destination), check=False)
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        self._run("worktree", "prune", check=False)
