"""Command line: render or check a resume JSON without opening the app.

    python -m resume_builder.cli new my_resume.json
    python -m resume_builder.cli profiles my_resume.json
    python -m resume_builder.cli render my_resume.json out.pdf out.docx --profile "Engineering Manager"
    python -m resume_builder.cli render-all my_resume.json out_folder --formats pdf,docx,html
    python -m resume_builder.cli check my_resume.json --profile "Principal Engineer"
    python -m resume_builder.cli match my_resume.json job.txt --profile "Principal Engineer"
    python -m resume_builder.cli site my_resume.json _site --base-url https://me.github.io/resumes/

  Private site (resume encrypted in the repo, site under a secret folder):
    python -m resume_builder.cli encrypt my_resume.json resume.json.enc --key-env RESUME_SITE_KEY
    python -m resume_builder.cli site resume.json.enc _site --key-env RESUME_SITE_KEY --secret-path
    python -m resume_builder.cli link https://me.github.io/resumes/ --key-env RESUME_SITE_KEY
    python -m resume_builder.cli decrypt resume.json.enc my_resume.json --key-env RESUME_SITE_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import skeleton
from .keywords import match
from .model import Resume, check
from .render import export, file_stem


def _pick(resume: Resume, ref: str | None) -> Resume | None:
    if not ref:
        return resume.apply(None)
    if resume.profile(ref) is None:
        names = ", ".join(f"'{p.name}'" for p in resume.profiles) or "none"
        print(f"No profile named '{ref}'. Profiles in this file: {names}", file=sys.stderr)
        return None
    return resume.apply(ref)


def _overrides(resume: Resume, a) -> None:
    if getattr(a, "photo", None):
        from .photo import load
        resume.photo, resume.show_photo = load(a.photo), True
    if getattr(a, "no_photo", False):
        resume.show_photo = False
    if getattr(a, "a4", False) or getattr(a, "letter", False):
        resume.page_size = "a4" if a.a4 else "letter"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="resume_builder", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def profile_arg(p):
        p.add_argument("--profile", help="profile name or id (default: the master, everything)")

    def output_opts(p):
        paper = p.add_mutually_exclusive_group()
        paper.add_argument("--a4", action="store_true", help="A4 paper (overrides the file/profile)")
        paper.add_argument("--letter", action="store_true", help="US Letter paper")
        p.add_argument("--photo", help="image file to embed as the resume photo")
        p.add_argument("--no-photo", action="store_true", help="leave the photo out")

    p = sub.add_parser("new", help="write the hybrid skeleton to a JSON file")
    p.add_argument("out")
    p = sub.add_parser("profiles", help="list the profiles in a resume file")
    p.add_argument("resume")
    p = sub.add_parser("render", help="export to .pdf / .docx / .html / .txt")
    p.add_argument("resume")
    p.add_argument("outputs", nargs="+")
    profile_arg(p)
    output_opts(p)
    p = sub.add_parser("render-all", help="export every profile into a folder")
    p.add_argument("resume")
    p.add_argument("folder")
    p.add_argument("--formats", default="pdf,docx", help="comma-separated: pdf,docx,html,txt")
    output_opts(p)
    p = sub.add_parser("site", help="build a static website (one page per profile + downloads)")
    p.add_argument("resume")
    p.add_argument("folder")
    p.add_argument("--formats", default="pdf,docx", help="downloads per page: pdf,docx,txt")
    idx = p.add_mutually_exclusive_group()
    idx.add_argument("--noindex", dest="noindex", action="store_const", const=True,
                     help="ask search engines not to index (overrides the file)")
    idx.add_argument("--index", dest="noindex", action="store_const", const=False,
                     help="allow search engines to index (overrides the file)")
    p.add_argument("--base-url", help="public URL of the site, to print shareable links")
    p.add_argument("--key-env", help="environment variable holding the site key "
                                     "(needed for .enc input and --secret-path)")
    p.add_argument("--secret-path", action="store_true",
                   help="publish under a secret folder derived from the site key")
    p.add_argument("--show-links", action="store_true",
                   help="print the private links (don't use in public CI logs)")

    def key_cmd(name, help_, *positional):
        q = sub.add_parser(name, help=help_)
        for arg in positional:
            q.add_argument(arg)
        q.add_argument("--key-env", default="RESUME_SITE_KEY",
                       help="environment variable holding the site key (default RESUME_SITE_KEY)")
        return q
    key_cmd("encrypt", "encrypt a resume JSON with the site key", "resume", "out")
    key_cmd("decrypt", "decrypt resume.json.enc with the site key", "resume", "out")
    key_cmd("token", "print the secret folder name for the site key")
    key_cmd("link", "print the private link for the site key", "base_url")
    q = sub.add_parser("blank", help="write an empty site (nothing to show yet)")
    q.add_argument("folder")
    p = sub.add_parser("check", help="list improvement warnings")
    p.add_argument("resume")
    profile_arg(p)
    p = sub.add_parser("match", help="compare against a job description text file")
    p.add_argument("resume")
    p.add_argument("job")
    profile_arg(p)
    a = ap.parse_args(argv)

    if a.cmd == "new":
        out = Path(a.out)
        if out.exists():
            print(f"{out} already exists; not overwriting.", file=sys.stderr)
            return 1
        skeleton().save(out)
        print(f"Wrote {out}")
        return 0

    if a.cmd == "blank":
        from .site import blank_site
        print(f"Wrote an empty site ({len(blank_site(a.folder))} files) in {a.folder}")
        return 0

    if a.cmd in ("encrypt", "decrypt", "token", "link") or getattr(a, "key_env", None):
        from . import secure
        try:
            key = secure.clean_key(os.environ.get(a.key_env or "", ""))
        except secure.BadKey as exc:
            print(f"Site key: set the environment variable {a.key_env or '(see --key-env)'}. {exc}",
                  file=sys.stderr)
            return 2
        if a.cmd == "token":
            print(secure.path_token(key))
            return 0
        if a.cmd == "link":
            print(secure.private_url(a.base_url, key))
            return 0
        if a.cmd == "encrypt":
            text = json.dumps(Resume.load(a.resume).to_dict(), ensure_ascii=False)
            Path(a.out).write_text(secure.encrypt(text, key) + "\n", encoding="ascii")
            print(f"Encrypted {a.resume} -> {a.out}")
            return 0
        if a.cmd == "decrypt":
            try:
                data = json.loads(secure.decrypt(Path(a.resume).read_text(encoding="ascii"), key))
            except secure.BadKey as exc:
                print(exc, file=sys.stderr)
                return 2
            Resume.from_dict(data).save(a.out)
            print(f"Decrypted {a.resume} -> {a.out}")
            return 0
    else:
        key = None

    if a.resume.endswith(".enc"):
        from . import secure
        if not key:
            print("This resume is encrypted: pass --key-env with the site key.", file=sys.stderr)
            return 2
        try:
            resume = Resume.from_dict(json.loads(
                secure.decrypt(Path(a.resume).read_text(encoding="ascii"), key)))
        except secure.BadKey as exc:
            print(exc, file=sys.stderr)
            return 2
    else:
        resume = Resume.load(a.resume)

    if a.cmd == "site":
        from .site import build_site, site_links
        fmts = [x.strip().lstrip(".").lower() for x in a.formats.split(",") if x.strip()]
        secret = None
        if a.secret_path:
            from . import secure
            if not key:
                print("--secret-path needs the site key: pass --key-env.", file=sys.stderr)
                return 2
            secret = secure.path_token(key)
        written = build_site(resume, a.folder, formats=fmts, noindex=a.noindex, secret_path=secret)
        noindex = resume.noindex if a.noindex is None else a.noindex
        print(f"Built {len(written)} files in {a.folder} "
              f"({'hidden from' if noindex else 'visible to'} search engines"
              f"{', private link only' if secret else ''})")
        if secret and not a.show_links:
            return 0                       # never print the secret path unless asked
        base = a.base_url or "/"
        if secret:
            base = base.rstrip("/") + "/" + secret + "/"
        for label, url in site_links(resume, base):
            print(f"  {label}: {url}")
        return 0

    if a.cmd == "profiles":
        if not resume.profiles:
            print("No profiles yet (the master is used). Create them in the app's Profiles tab.")
        for p in resume.profiles:
            shown = resume.apply(p)
            print(f"- {p.name}  [{p.id}]  hides {len(p.hidden)} item(s); "
                  f"{len(shown.all_skills())} skills, {len(shown.projects)} projects")
        return 0

    if a.cmd == "render-all":
        folder = Path(a.folder)
        folder.mkdir(parents=True, exist_ok=True)
        exts = [f".{x.strip().lstrip('.').lower()}" for x in a.formats.split(",") if x.strip()]
        targets = [(p.name, p.id) for p in resume.profiles] or [("", None)]
        for name, pid in targets:
            shown = resume.apply(pid)
            _overrides(shown, a)
            for ext in exts:
                print(f"Wrote {export(shown, folder / (file_stem(shown, name) + ext))}")
        return 0

    shown = _pick(resume, getattr(a, "profile", None))
    if shown is None:
        return 2
    if a.cmd == "render":
        _overrides(shown, a)
        for out in a.outputs:
            print(f"Wrote {export(shown, out)}")
    elif a.cmd == "check":
        warnings = check(shown)
        print("\n".join(f"- {w}" for w in warnings) or "No issues found.")
    elif a.cmd == "match":
        r = match(shown, Path(a.job).read_text(encoding="utf-8"))
        print(f"Keyword coverage: {r.score}%")
        print("Your skills in the posting:", ", ".join(r.matched_skills) or "-")
        print("Posting terms you cover:  ", ", ".join(r.found_terms) or "-")
        print("Posting terms missing:    ", ", ".join(r.missing_terms) or "-")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
