"""Build a static website from one resume file (for GitHub Pages or any host).

Layout (with profiles "Principal Engineer" and "Engineering Manager"):

    index.html                         home page: the site_home profile
    principal-engineer/index.html      one page per profile, shareable link
    principal-engineer/Name_Principal_Engineer_Resume.pdf
    principal-engineer/Name_Principal_Engineer_Resume.docx
    engineering-manager/...
    .nojekyll                          serve files as-is on GitHub Pages

Pages don't link to each other, so a recruiter who gets the Engineering
Manager link doesn't see the other versions. Every page has PDF / Word
download buttons (hidden when printed) and, when `noindex` is on, a robots
meta tag asking search engines not to index or cache it.

Note: robots.txt only works at a domain's root, so for a project site like
user.github.io/resumes the meta tag is what keeps it out of search results.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from . import photo
from .model import Resume
from .render import export, file_stem, to_html

FORMATS = {"pdf": ("PDF", ".pdf"), "docx": ("Word", ".docx"), "txt": ("Text", ".txt")}


def slugify(name: str) -> str:
    """'Engineering Manager (Energy)' -> 'engineering-manager-energy'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "resume"


def targets(resume: Resume) -> list[tuple[str, str | None, str]]:
    """[(profile name, profile id, folder slug)] — just the master when there are no profiles."""
    if not resume.profiles:
        return [("", None, "")]
    out, used = [], set()
    for p in resume.profiles:
        slug, n = slugify(p.name or "profile"), 2
        while slug in used:
            slug, n = f"{slugify(p.name or 'profile')}-{n}", n + 1
        used.add(slug)
        out.append((p.name.strip(), p.id, slug))
    return out


def home_target(resume: Resume):
    ts = targets(resume)
    return next((t for t in ts if t[1] and t[1] == resume.site_home), ts[0])


def _image_writer(folder: Path, written: list[Path]):
    """Returns f(base64) -> relative URL, writing each screenshot once as img/<hash>.<ext>."""
    cache: dict[str, str] = {}

    def write(data: str) -> str:
        if data not in cache:
            name = f"{hashlib.sha1(data.encode()).hexdigest()[:12]}.{photo.extension(data)}"
            target = folder / "img" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(photo.to_bytes(data))
                written.append(target)
            cache[data] = f"img/{name}"
        return cache[data]
    return write


BLANK_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Not found</title>
<style>body{font:15px system-ui,sans-serif;color:#666;display:grid;place-items:center;height:90vh;margin:0}</style>
</head><body><p>Nothing here.</p></body></html>
"""


def blank_site(out_dir: str | Path) -> list[Path]:
    """An empty site: what the plain address shows (also used before the first publish)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name in ("index.html", "404.html"):
        (out / name).write_text(BLANK_PAGE, encoding="utf-8")
        written.append(out / name)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    written.append(out / ".nojekyll")
    return written


def build_site(resume: Resume, out_dir: str | Path, formats=("pdf", "docx"),
               noindex: bool | None = None, secret_path: str | None = None) -> list[Path]:
    """Write the site into out_dir (created if needed). Returns written files.

    secret_path: publish everything under out_dir/<secret_path>/ and leave a
    blank page at the plain address (and as 404.html), so the resume is only
    reachable by its private link.
    """
    root_dir = Path(out_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    pre: list[Path] = []
    if secret_path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,}", secret_path):
            raise ValueError("secret_path must be at least 8 letters, digits, '-' or '_'.")
        pre = blank_site(root_dir)
        out = root_dir / secret_path
    else:
        out = root_dir
    out.mkdir(parents=True, exist_ok=True)
    noindex = resume.noindex if noindex is None else noindex
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        raise ValueError(f"Unknown download format(s): {', '.join(unknown)}")
    written: list[Path] = list(pre)
    home = home_target(resume)

    for name, pid, slug in targets(resume):
        shown = resume.apply(pid)
        folder = out / slug if slug else out
        folder.mkdir(parents=True, exist_ok=True)
        stem = file_stem(shown, name)
        downloads = []
        for fmt in formats:
            label, ext = FORMATS[fmt]
            written.append(export(shown, folder / f"{stem}{ext}"))
            downloads.append((label, f"{stem}{ext}"))
        images = _image_writer(folder, written)
        page = folder / "index.html"
        page.write_text(to_html(shown, noindex=noindex, downloads=downloads, image_url=images),
                        encoding="utf-8")
        written.append(page)
        if slug and (name, pid, slug) == home:
            root_downloads = [(label, f"{slug}/{url}") for label, url in downloads]
            root = out / "index.html"
            root.write_text(to_html(shown, noindex=noindex, downloads=root_downloads,
                                    image_url=lambda data: f"{slug}/{images(data)}"),
                            encoding="utf-8")
            written.append(root)

    if not secret_path:
        nojekyll = out / ".nojekyll"
        nojekyll.write_text("", encoding="utf-8")
        written.append(nojekyll)
    return written


def site_links(resume: Resume, base_url: str) -> list[tuple[str, str]]:
    """[(label, full url)] for sharing, e.g. base 'https://me.github.io/resumes/'."""
    base = base_url.rstrip("/") + "/"
    home = home_target(resume)
    links = [("Home page" + (f" ({home[0]})" if home[0] else ""), base)]
    links += [(name, f"{base}{slug}/") for name, _pid, slug in targets(resume) if slug]
    return links
