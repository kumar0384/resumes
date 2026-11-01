"""Publish a resume to its live-site repo (e.g. kumar0384/resumes) with git.

The site repo holds `resume.json.enc` (the resume, encrypted with your site
key; see secure.py) plus a GitHub Action that decrypts it and rebuilds the
website on every push. Publishing encrypts the resume you're editing into that
repo, then runs: git pull --ff-only, add, commit, push.

Safety: the target must be a site repo — a git repo whose workflow builds the
site with `resume_builder.cli site`. Anything else (like the resume_builder
source repo) is refused, so a resume can't end up in the wrong place.

Your existing git login is used; nothing is stored here except, in the app,
the path of your local site folder (see settings.py).
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import secure
from .model import Resume

SITE_FILE = "resume.json"
SITE_MARKER = "resume_builder.cli site"


class PublishError(Exception):
    """Something the user needs to fix; the message says what."""


class ResetNeeded(PublishError):
    """GitHub's history was replaced; the local copy must be reset before publishing."""


@dataclass
class PublishResult:
    committed: bool
    repo_root: Path
    site_url: str            # https://owner.github.io/repo/
    repo_url: str            # https://github.com/owner/repo
    output: str
    private_url: str = ""    # https://owner.github.io/repo/<secret>/


def _git(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
    except FileNotFoundError as exc:
        raise PublishError("Git isn't installed or isn't on your PATH. Install it from "
                           "git-scm.com, then try again.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PublishError(f"'git {args[0]}' took too long. Check your internet connection "
                           "and try again.") from exc


def _github(remote: str) -> tuple[str, str] | None:
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", remote.strip())
    return (m.group(1), m.group(2)) if m else None


def pages_url(remote: str) -> str:
    """GitHub remote -> GitHub Pages URL ('' if it isn't a GitHub remote)."""
    gh = _github(remote)
    if not gh:
        return ""
    owner, repo = gh
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{repo}/"


def repo_url(remote: str) -> str:
    gh = _github(remote)
    return f"https://github.com/{gh[0]}/{gh[1]}" if gh else ""


def repo_root(path: str | Path) -> Path | None:
    p = Path(path).resolve()
    cwd = p if p.is_dir() else p.parent
    if not cwd.exists():
        return None
    r = _git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def is_site_repo(folder: str | Path) -> bool:
    """True if folder is the root of a repo whose workflow builds the resume site."""
    wf = Path(folder) / ".github" / "workflows"
    if not wf.is_dir():
        return False
    for f in list(wf.glob("*.yml")) + list(wf.glob("*.yaml")):
        try:
            if SITE_MARKER in f.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def check_site_folder(folder: str | Path) -> Path:
    """Validate a chosen site folder; returns the repo root or raises PublishError."""
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise PublishError(f"{folder} doesn't exist.")
    root = repo_root(folder)
    if root is None:
        raise PublishError(
            f"{folder} isn't a git repository.\n\n"
            "Clone your site repo first, e.g.:\n"
            "  git clone https://github.com/kumar0384/resumes\n"
            "then choose that 'resumes' folder.")
    if not is_site_repo(root):
        remote = _git(["remote", "get-url", "origin"], cwd=root).stdout.strip()
        name = repo_url(remote).replace("https://github.com/", "") or root.name
        raise PublishError(
            f"'{name}' isn't a resume site repo: it has no workflow that builds the site "
            f"('{SITE_MARKER}').\n\n"
            "Choose your local copy of your site repo instead (e.g. the 'resumes' folder "
            "cloned from github.com/kumar0384/resumes).")
    return root


def remote_was_reset(root: Path) -> bool:
    """True if GitHub's branch no longer shares history with ours (history was wiped)."""
    if _git(["fetch", "--quiet", "origin"], cwd=root).returncode:
        return False
    upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=root)
    if upstream.returncode:
        return False
    return _git(["merge-base", "HEAD", "@{u}"], cwd=root).returncode != 0


def reset_to_remote(site_folder: str | Path) -> None:
    """Make the local site repo match GitHub exactly (after a history wipe)."""
    root = check_site_folder(site_folder)
    r = _git(["fetch", "--quiet", "origin"], cwd=root)
    if r.returncode:
        raise PublishError(f"git fetch failed:\n{r.stderr.strip()}")
    r = _git(["reset", "--hard", "@{u}"], cwd=root)
    if r.returncode:
        raise PublishError(f"git reset failed:\n{r.stderr.strip()}")


def publish_resume(resume: Resume, site_folder: str | Path, key: str,
                   message: str | None = None) -> PublishResult:
    """Encrypt `resume` into <site repo>/resume.json.enc, then pull, commit and push it.

    A plain resume.json is never written; one left over from older versions is
    removed from the repo in the same commit.
    """
    try:
        key = secure.clean_key(key)
    except secure.BadKey as exc:
        raise PublishError(f"Set up your site key first. {exc}") from exc
    root = check_site_folder(site_folder)
    log: list[str] = []

    def run(args, timeout=120):
        r = _git(args, cwd=root, timeout=timeout)
        log.append(f"$ git {' '.join(args)}\n{r.stdout}{r.stderr}".rstrip())
        return r

    if remote_was_reset(root):
        raise ResetNeeded(
            "Your site repo on GitHub was reset (its history was replaced), so your local copy "
            "no longer matches it.")

    # Local edits to these files would block the pull; they're replaced below anyway.
    for f in (secure.ENC_FILE, SITE_FILE):
        tracked = run(["ls-files", "--error-unmatch", "--", f]).returncode == 0
        if tracked and run(["diff", "--quiet", "--", f]).returncode == 1:
            run(["checkout", "--", f])

    r = run(["pull", "--ff-only", "--quiet"])
    if r.returncode and "no tracking information" not in r.stderr:
        raise PublishError(
            "Couldn't update your local copy of the site repo from GitHub:\n"
            f"{r.stderr.strip()}\n\nOpen that folder in a terminal (or GitHub Desktop), "
            "run 'git pull', resolve anything it reports, then Publish again.")

    data = Resume.from_dict(resume.to_dict())
    data.prune_profiles()
    data.active_profile = ""
    text = json.dumps(data.to_dict(), ensure_ascii=False)
    target = root / secure.ENC_FILE
    # Fernet output differs every time; keep the old file if the resume didn't change
    unchanged = False
    if target.exists():
        try:
            unchanged = secure.decrypt(target.read_text(encoding="ascii"), key) == text
        except secure.BadKey:
            unchanged = False
    if not unchanged:
        target.write_text(secure.encrypt(text, key) + "\n", encoding="ascii")

    r = run(["add", "--", secure.ENC_FILE])
    if r.returncode:
        raise PublishError(f"git add failed:\n{r.stderr.strip()}")
    if run(["ls-files", "--error-unmatch", SITE_FILE]).returncode == 0:
        run(["rm", "--cached", "--quiet", "--", SITE_FILE])        # stop publishing plain text
    if (root / SITE_FILE).exists():
        (root / SITE_FILE).unlink()
    committed = run(["diff", "--cached", "--quiet"]).returncode == 1
    if committed:
        msg = message or f"Update resume ({datetime.now():%Y-%m-%d %H:%M})"
        r = run(["commit", "-m", msg])
        if r.returncode:
            raise PublishError("git commit failed. If git asks who you are, run:\n"
                               '  git config --global user.name "Your Name"\n'
                               '  git config --global user.email "you@example.com"\n\n'
                               + r.stderr.strip())
    r = run(["push"])
    if r.returncode:
        hint = ""
        if "rejected" in r.stderr or "fetch first" in r.stderr:
            hint = ("\n\nGitHub has changes you don't have. Run 'git pull --rebase' in the "
                    "site folder, then Publish again.")
        elif "Authentication" in r.stderr or "could not read Username" in r.stderr:
            hint = ("\n\nGit couldn't sign in to GitHub. Sign in once with GitHub Desktop or "
                    "'gh auth login', then Publish again.")
        raise PublishError(f"git push failed:\n{r.stderr.strip()}{hint}")
    remote = _git(["remote", "get-url", "origin"], cwd=root).stdout
    base = pages_url(remote)
    return PublishResult(committed=committed, repo_root=root, site_url=base,
                         repo_url=repo_url(remote), output="\n".join(log),
                         private_url=secure.private_url(base, key) if base else "")


def site_status(url: str, timeout: float = 6.0) -> int | None:
    """HTTP status of the live site (None if it couldn't be reached)."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "resume_builder"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def remote_urls(site_folder: str | Path) -> tuple[str, str]:
    """(GitHub repo URL, Pages base URL) for a site folder; blanks if unknown."""
    root = repo_root(site_folder)
    if root is None:
        return "", ""
    remote = _git(["remote", "get-url", "origin"], cwd=root).stdout
    return repo_url(remote), pages_url(remote)


def key_matches_repo(site_folder: str | Path, key: str) -> bool | None:
    """Does `key` decrypt the repo's resume.json.enc? None if there's no encrypted file yet."""
    root = repo_root(site_folder)
    enc = root / secure.ENC_FILE if root else None
    if not enc or not enc.exists():
        return None
    try:
        secure.decrypt(enc.read_text(encoding="ascii"), key)
        return True
    except secure.BadKey:
        return False
