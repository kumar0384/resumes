"""Data model for a hybrid resume.

Hybrid layout, top to bottom:
    1. Contact + headline
    2. Professional summary (3-4 lines)
    3. Core skills block (tools, codes/standards, analysis methods, leadership)
       -> dense keywords near the top for ATS filters and the recruiter's first scan
    4. Professional experience in reverse-chronological order
       -> shows progression, including into leading people (team size per role)
    5. Education, certifications, selected projects, additional info

Profiles: one master resume holds all content. Each Profile (e.g. "Principal
Engineer", "Engineering Manager") hides what doesn't fit that target and can
override the headline, summary, paper size and photo. Resume.apply(profile)
returns the tailored copy that gets rendered, so a fix made once in the master
reaches every profile.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
PRESENT_WORDS = {"present", "current", "now", "today", ""}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DEFAULT_SKILL_CATEGORIES = [
    "Tools & software",
    "Codes & standards",
    "Analysis methods",
    "Leadership & delivery",
]


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def parse_date(value: str) -> tuple[int, int] | None:
    """Parse 'YYYY-MM', 'YYYY/MM', 'MM/YYYY', 'Mon YYYY' or 'YYYY'.

    Returns (year, month) or None. 'Present' and blanks return None.
    """
    v = (value or "").strip()
    if v.lower() in PRESENT_WORDS:
        return None
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})", v)
    if m:
        return int(m.group(1)), max(1, min(12, int(m.group(2))))
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", v)
    if m:
        return int(m.group(2)), max(1, min(12, int(m.group(1))))
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{4})", v)
    if m:
        key = m.group(1)[:3].title()
        if key in MONTHS:
            return int(m.group(2)), MONTHS.index(key) + 1
    m = re.fullmatch(r"(\d{4})", v)
    if m:
        return int(m.group(1)), 1
    return None


def is_present(value: str) -> bool:
    return (value or "").strip().lower() in PRESENT_WORDS


def format_date(value: str) -> str:
    """'2021-03' -> 'Mar 2021', 'present' -> 'Present', '2019' -> '2019'."""
    v = (value or "").strip()
    if is_present(v):
        return "Present"
    if re.fullmatch(r"\d{4}", v):
        return v
    parsed = parse_date(v)
    if parsed is None:
        return v  # leave unrecognised text (e.g. placeholders) untouched
    year, month = parsed
    return f"{MONTHS[month - 1]} {year}"


def format_range(start: str, end: str) -> str:
    s, e = format_date(start), format_date(end)
    if not s:
        return e
    return f"{s} – {e}"


# --------------------------------------------------------------------------- #
# Paper
# --------------------------------------------------------------------------- #
PAGE_SIZES = {                      # width, height in inches
    "letter": (8.5, 11.0),
    "a4": (8.27, 11.69),
}
PAGE_LABELS = {"letter": "Letter", "a4": "A4"}


def normalize_page_size(value) -> str:
    v = str(value or "").strip().lower().replace(" ", "")
    if v in ("a4", "din-a4", "dina4"):
        return "a4"
    return "letter"


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
@dataclass
class Contact:
    name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    website: str = ""
    work_authorization: str = ""

    def links(self) -> list[str]:
        return [x for x in (self.email, self.phone, self.location,
                            self.linkedin, self.website,
                            self.work_authorization) if x.strip()]

    def labeled(self) -> list[tuple[str, str]]:
        """(label, value) pairs for the header, one per line, blanks skipped.

        URLs are shown cleanly: no https://, no www., no tracking query
        (LinkedIn's share link adds ?utm_source=... which looks messy in print).
        """
        rows = [("Email", self.email.strip()), ("Phone", self.phone.strip()),
                ("Location", self.location.strip()),
                ("LinkedIn", display_url(self.linkedin)),
                ("Website", display_url(self.website)),
                ("Work Authorization", self.work_authorization.strip())]
        return [(k, v) for k, v in rows if v]

    def labeled_links(self) -> list[tuple[str, str, str]]:
        """(label, shown text, clickable target or '') for the header."""
        targets = {"Email": href(self.email), "LinkedIn": href(self.linkedin),
                   "Website": href(self.website)}
        phone = re.sub(r"[^\d+]", "", self.phone)
        if len(phone) >= 7:
            targets["Phone"] = f"tel:{phone}"
        return [(k, v, targets.get(k, "")) for k, v in self.labeled()]


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def href(value: str) -> str:
    """Turn what people type into a clickable target.

    'github.com/me' -> 'https://github.com/me', 'me@x.com' -> 'mailto:me@x.com'.
    Returns '' for blanks and [placeholders].
    """
    v = (value or "").strip()
    if not v or (v.startswith("[") and v.endswith("]")) or " " in v:
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*:", v, flags=re.I):
        return v
    if re.fullmatch(r"[^@\s/]+@[^@\s/]+\.[^@\s/]+", v):
        return f"mailto:{v}"
    if "." in v.split("/")[0]:
        return f"https://{v}"
    return ""


def display_url(url: str) -> str:
    """'https://www.linkedin.com/in/x?utm_source=a' -> 'linkedin.com/in/x'."""
    u = (url or "").strip()
    if u.startswith("[") and u.endswith("]"):
        return u                                   # skeleton placeholder
    u = re.sub(r"^[a-z]+://", "", u, flags=re.I)
    u = re.sub(r"^www\.", "", u, flags=re.I)
    u = re.split(r"[?#]", u, maxsplit=1)[0]
    return u.rstrip("/")


@dataclass
class SkillGroup:
    category: str = ""
    items: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)


@dataclass
class Role:
    title: str = ""
    company: str = ""
    location: str = ""
    start: str = ""
    end: str = "Present"
    team_size: str = ""          # people led in this role; blank = individual contributor
    scope: str = ""              # one-line context: product, budget, programme
    highlights: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    @property
    def is_lead(self) -> bool:
        return bool(re.search(r"\d", self.team_size or "")) and \
            not re.fullmatch(r"\s*0+\s*", self.team_size or "")

    def sort_key(self) -> tuple[int, int, int, int]:
        """Larger = more recent. Current roles first, then by end, then start."""
        end = (9999, 12) if is_present(self.end) else (parse_date(self.end) or (0, 0))
        start = parse_date(self.start) or (0, 0)
        return end[0], end[1], start[0], start[1]


@dataclass
class Education:
    degree: str = ""
    institution: str = ""
    location: str = ""
    year: str = ""
    details: str = ""


@dataclass
class Certification:
    name: str = ""
    issuer: str = ""
    year: str = ""


@dataclass
class Screenshot:
    data: str = ""                   # base64 PNG or JPEG (see photo.load_screenshot)
    caption: str = ""                # shown under the enlarged image


@dataclass
class Project:
    """A personal or side project shown under Selected Projects.

    Keep it scannable: a tagline, the stack, one sentence of context and
    one to three results. Links are clickable in PDF, Word and HTML.
    Screenshots: the first is the thumbnail; all open full size on click
    (HTML) or on the screenshot pages at the end (PDF).
    """
    name: str = ""
    description: str = ""            # one or two sentences: what it is, who uses it
    link: str = ""                   # main link, usually the repository
    tagline: str = ""                # short subtitle, e.g. "Open-source FEA desktop app"
    tech: list[str] = field(default_factory=list)          # stack, shown as a line
    highlights: list[str] = field(default_factory=list)    # 1-3 result bullets
    demo: str = ""                   # live demo, video or write-up
    images: list[Screenshot] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    @property
    def shots(self) -> list[Screenshot]:
        return [s for s in self.images if s.data]

    def links(self) -> list[tuple[str, str]]:
        """[(label, url)] for the links that are filled in."""
        out = []
        if self.link.strip():
            label = "Code" if re.search(r"github|gitlab|bitbucket", self.link, re.I) else "Link"
            out.append((label, self.link.strip()))
        if self.demo.strip():
            out.append(("Demo", self.demo.strip()))
        return out


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
SECTIONS = ["education", "certifications", "projects", "additional"]


def key_group(g: SkillGroup) -> str:
    return f"group:{g.id}"


def key_skill(item: str) -> str:
    return f"skill:{item.strip().lower()}"


def key_role(r: Role) -> str:
    return f"role:{r.id}"


def key_bullet(r: Role, text: str) -> str:
    return f"bullet:{r.id}:{text.strip()}"


def key_project(p: Project) -> str:
    return f"project:{p.id}"


def key_section(name: str) -> str:
    return f"section:{name}"


@dataclass
class Profile:
    """A tailored version of the master resume.

    `hidden` lists what this profile leaves out (keys from the key_* helpers),
    so anything added to the master later shows up everywhere by default.
    Blank overrides inherit from the master.
    """
    name: str = ""
    headline: str = ""
    summary: str = ""
    page_size: str = ""              # "", "letter" or "a4"
    show_photo: bool | None = None   # None = same as master
    hidden: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def is_hidden(self, key: str) -> bool:
        return key in self.hidden

    def set_hidden(self, key: str, hide: bool) -> None:
        if hide and key not in self.hidden:
            self.hidden.append(key)
        elif not hide and key in self.hidden:
            self.hidden.remove(key)


@dataclass
class Resume:
    contact: Contact = field(default_factory=Contact)
    summary: str = ""
    core_skills: list[SkillGroup] = field(default_factory=list)
    experience: list[Role] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)
    certifications: list[Certification] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    additional: list[str] = field(default_factory=list)
    photo: str = ""               # base64 JPEG, 7:9 portrait (see photo.py)
    show_photo: bool = False      # off by default: US/UK/CA norms are no photo
    page_size: str = "letter"     # "letter" (US/Canada) or "a4" (rest of world)
    project_images_in_pdf: bool = False   # screenshots always show in HTML
    noindex: bool = True          # HTML/live site asks search engines not to index it
    site_home: str = ""           # profile id shown at the live site's root ('' = first)
    profiles: list[Profile] = field(default_factory=list)
    active_profile: str = ""      # id of the profile last selected in the app
    schema_version: int = SCHEMA_VERSION

    @property
    def has_photo(self) -> bool:
        return self.show_photo and bool(self.photo)

    # ------------------------------------------------------------ profiles
    def profile(self, ref: str | None) -> Profile | None:
        """Find a profile by id or (case-insensitive) name."""
        if not ref:
            return None
        for p in self.profiles:
            if p.id == ref or p.name.strip().lower() == ref.strip().lower():
                return p
        return None

    def apply(self, profile: Profile | str | None) -> "Resume":
        """The resume as this profile shows it (the master if None)."""
        prof = self.profile(profile) if isinstance(profile, str) else profile
        out = copy.deepcopy(self)
        out.profiles, out.active_profile = [], ""
        if prof is None:
            return out
        hide = set(prof.hidden)
        if prof.headline.strip():
            out.contact.headline = prof.headline.strip()
        if prof.summary.strip():
            out.summary = prof.summary.strip()
        if prof.page_size:
            out.page_size = normalize_page_size(prof.page_size)
        if prof.show_photo is not None:
            out.show_photo = prof.show_photo

        groups = []
        for g in out.core_skills:
            if key_group(g) in hide:
                continue
            g.items = [s for s in g.items if key_skill(s) not in hide]
            groups.append(g)
        out.core_skills = groups

        roles = []
        for r in out.experience:
            if key_role(r) in hide:
                continue
            r.highlights = [b for b in r.highlights if key_bullet(r, b) not in hide]
            roles.append(r)
        out.experience = roles

        out.projects = [p for p in out.projects if key_project(p) not in hide]
        for name in SECTIONS:
            if key_section(name) in hide:
                setattr(out, name, [])
        return out

    def valid_keys(self) -> set[str]:
        keys = {key_section(s) for s in SECTIONS}
        for g in self.core_skills:
            keys.add(key_group(g))
            keys.update(key_skill(s) for s in g.items)
        for r in self.experience:
            keys.add(key_role(r))
            keys.update(key_bullet(r, b) for b in r.highlights)
        keys.update(key_project(p) for p in self.projects)
        return keys

    def prune_profiles(self) -> None:
        """Drop hidden-keys that no longer match anything (edited/deleted items)."""
        valid = self.valid_keys()
        for p in self.profiles:
            p.hidden = [k for k in p.hidden if k in valid]

    # ---------------------------------------------------------------- build
    @classmethod
    def blank(cls) -> "Resume":
        return cls(core_skills=[SkillGroup(c, []) for c in DEFAULT_SKILL_CATEGORIES],
                   experience=[Role()], education=[Education()])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Resume":
        def build(klass, raw):
            if not isinstance(raw, dict):
                return klass()
            known = {k: v for k, v in raw.items() if k in klass.__dataclass_fields__}
            return klass(**known)

        def build_list(klass, raw):
            return [build(klass, r) for r in (raw or []) if isinstance(r, dict)]

        def clean_strs(raw):
            return [str(x).strip() for x in (raw or []) if str(x).strip()]

        r = cls(
            contact=build(Contact, data.get("contact")),
            summary=str(data.get("summary", "")),
            core_skills=build_list(SkillGroup, data.get("core_skills")),
            experience=build_list(Role, data.get("experience")),
            education=build_list(Education, data.get("education")),
            certifications=build_list(Certification, data.get("certifications")),
            projects=build_list(Project, data.get("projects")),
            additional=clean_strs(data.get("additional")),
            photo=str(data.get("photo") or ""),
            show_photo=bool(data.get("show_photo", False)),
            page_size=normalize_page_size(data.get("page_size")),
            project_images_in_pdf=bool(data.get("project_images_in_pdf", False)),
            noindex=bool(data.get("noindex", True)),
            site_home=str(data.get("site_home") or ""),
            profiles=build_list(Profile, data.get("profiles")),
            active_profile=str(data.get("active_profile") or ""),
            schema_version=SCHEMA_VERSION,
        )
        for g in r.core_skills:
            g.items = clean_strs(g.items)
        for role in r.experience:
            role.highlights = clean_strs(role.highlights)
            role.team_size = str(role.team_size)
        raw_projects = [x for x in (data.get("projects") or []) if isinstance(x, dict)]
        for p, raw in zip(r.projects, raw_projects):
            p.tech = clean_strs(p.tech if isinstance(p.tech, list)
                                else re.split(r"[,·|]", str(p.tech)))
            p.highlights = clean_strs(p.highlights)
            shots = []
            for s in (p.images or []):
                if isinstance(s, dict):
                    shots.append(Screenshot(data=str(s.get("data") or ""),
                                            caption=str(s.get("caption") or "").strip()))
                elif isinstance(s, str):
                    shots.append(Screenshot(data=s))
                elif isinstance(s, Screenshot):
                    shots.append(s)
            if raw.get("image"):                       # files from before multiple screenshots
                shots.insert(0, Screenshot(data=str(raw["image"])))
            p.images = [s for s in shots if s.data]
        for prof in r.profiles:
            prof.hidden = clean_strs(prof.hidden)
            prof.page_size = normalize_page_size(prof.page_size) if prof.page_size else ""
            if prof.show_photo is not None:
                prof.show_photo = bool(prof.show_photo)
        r._ensure_ids()
        if not r.profile(r.active_profile):
            r.active_profile = ""
        return r

    def _ensure_ids(self) -> None:
        """Give every item a unique id (older files have none)."""
        seen: set[str] = set()
        for item in [*self.core_skills, *self.experience, *self.projects, *self.profiles]:
            if not item.id or item.id in seen:
                item.id = new_id()
            seen.add(item.id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: str | Path) -> "Resume":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2,
                                         ensure_ascii=False) + "\n",
                              encoding="utf-8")

    # ------------------------------------------------------------- helpers
    def sorted_experience(self) -> list[Role]:
        """Reverse-chronological order: current roles first, newest end date next."""
        return sorted(self.experience, key=lambda r: r.sort_key(), reverse=True)

    def sort_experience(self) -> None:
        self.experience = self.sorted_experience()

    def all_skills(self) -> list[str]:
        return [s for g in self.core_skills for s in g.items]

    def full_text(self) -> str:
        """Everything a parser would read; used for keyword matching."""
        parts = [self.contact.headline, self.contact.location,
                 self.contact.work_authorization, self.summary, *self.all_skills()]
        for r in self.experience:
            parts += [r.title, r.company, r.location, r.scope, *r.highlights]
        for e in self.education:
            parts += [e.degree, e.institution, e.details]
        parts += [c.name for c in self.certifications]
        for p in self.projects:
            parts += [p.name, p.tagline, p.description, *p.tech, *p.highlights,
                      *(s.caption for s in p.shots)]
        parts += self.additional
        return "\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Quality checks (advisory, never blocking)
# --------------------------------------------------------------------------- #
PLACEHOLDER = re.compile(r"\[[^\]]+\]")
WEAK_OPENERS = ("responsible for", "worked on", "helped", "assisted",
                "duties included", "involved in", "tasked with")


def check(resume: Resume) -> list[str]:
    """Return human-readable warnings based on recruiter/ATS guidance."""
    w: list[str] = []
    c = resume.contact
    if not c.name.strip():
        w.append("Add your name.")
    if not c.email.strip() and not c.phone.strip():
        w.append("Add at least an email or phone number.")
    if not c.headline.strip():
        w.append("Add a headline (target title) under your name.")

    words = len(resume.summary.split())
    if words == 0:
        w.append("Add a 3-4 line summary.")
    elif words > 80:
        w.append(f"Summary is {words} words; aim for 40-80.")

    n_skills = len(resume.all_skills())
    if n_skills < 8:
        w.append(f"Core skills block has {n_skills} items; 12-24 keywords works best.")
    elif n_skills > 36:
        w.append(f"Core skills block has {n_skills} items; trim to the 24-30 most relevant.")

    if not resume.experience:
        w.append("Add at least one role.")
    if [r.sort_key() for r in resume.experience] != \
            [r.sort_key() for r in resume.sorted_experience()]:
        w.append("Experience is not newest-first; it will be sorted on export.")
    for r in resume.experience:
        label = r.title or r.company or "A role"
        if r.start and parse_date(r.start) is None and not PLACEHOLDER.search(r.start):
            w.append(f"{label}: start date '{r.start}' not recognised (use YYYY-MM).")
        if not r.highlights:
            w.append(f"{label}: add 3-5 achievement bullets.")
        elif len(r.highlights) > 6:
            w.append(f"{label}: {len(r.highlights)} bullets; keep to 6 or fewer.")
        unquantified = sum(1 for b in r.highlights
                           if not re.search(r"\d", b) and not PLACEHOLDER.search(b))
        if unquantified:
            w.append(f"{label}: {unquantified} bullet(s) have no number; quantify results.")
        weak = sum(1 for b in r.highlights if b.strip().lower().startswith(WEAK_OPENERS))
        if weak:
            w.append(f"{label}: {weak} bullet(s) start weakly; lead with an action verb.")

    for p in resume.projects:
        if not p.name.strip():
            continue
        if not p.link.strip() and not p.demo.strip():
            w.append(f"Project '{p.name}': add a link so reviewers can see it.")
        for url in (p.link, p.demo):
            if url.strip() and not href(url) and not PLACEHOLDER.search(url):
                w.append(f"Project '{p.name}': '{url}' doesn't look like a web link.")
        if len(p.highlights) > 3:
            w.append(f"Project '{p.name}': {len(p.highlights)} bullets; keep projects to 1-3.")
        if len(p.shots) > 6:
            w.append(f"Project '{p.name}': {len(p.shots)} screenshots; 2-4 of the best is plenty.")
    shown = [p for p in resume.projects if p.name.strip()]
    if len(shown) > 4:
        w.append(f"{len(shown)} projects shown; pick the 2-4 most relevant to this role.")

    if resume.show_photo and not resume.photo:
        w.append("Photo is switched on but none is chosen.")
    elif resume.has_photo:
        w.append("Photo included: right for Germany/EU/India; for US, UK or Canada "
                 "applications switch it off (recruiters often discard photo resumes).")

    left = placeholders(resume)
    if left:
        w.append(f"{len(left)} [placeholder] field(s) still to fill, e.g. {left[0]}")
    return w


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in ("photo", "image", "data", "id", "hidden", "active_profile", "site_home"):
                yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def placeholders(resume: Resume) -> list[str]:
    """Every [bracketed placeholder] still present in a text field."""
    return [m for s in _strings(resume.to_dict()) for m in PLACEHOLDER.findall(s)]
