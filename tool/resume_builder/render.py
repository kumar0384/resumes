"""Render a Resume to plain text, HTML and DOCX.

All outputs follow ATS-safe rules: one column, no tables or text boxes,
standard section headings, real text (no images), common fonts.
Experience is always rendered newest-first regardless of input order.
"""

from __future__ import annotations

import html
import io
import re
from pathlib import Path

from . import photo
from .model import (PAGE_LABELS, PAGE_SIZES, Resume, Role, display_url,
                    format_date, format_range, href)

PHOTO_W_IN = 0.95                 # printed photo width; height follows 7:9

# Typography: a classic serif with a deep-navy accent for name, headings and
# contact labels. Garamond ships with Microsoft Office; Word substitutes a
# similar serif if it's missing. The PDF export embeds the first font it finds
# (see pdf.FONT_CANDIDATES), so the PDF looks the same on any machine.
FONT = "Garamond"
ACCENT = "1F3864"                 # deep navy
INK_HEX = "222222"
MUTED_HEX = "4A4A4A"
BODY_PT = 11
NAME_PT = 24
LABEL_IN = 1.55                  # contact label column / tab stop

HEADINGS = {
    "summary": "Professional Summary",
    "skills": "Core Skills",
    "experience": "Professional Experience",
    "education": "Education",
    "certifications": "Certifications",
    "projects": "Selected Projects",
    "additional": "Additional Information",
}


def _role_subline(r: Role) -> str:
    parts = [r.company, r.location]
    return " | ".join(p for p in parts if p.strip())


def _team_note(r: Role) -> str:
    if not r.is_lead:
        return ""
    n = r.team_size.strip()
    noun = "direct report" if n == "1" else "direct reports"
    return f"{n} {noun}" if n.isdigit() else f"Team: {n}"


def _visible_skills(resume: Resume):
    return [g for g in resume.core_skills if g.items]


def _visible_projects(resume: Resume):
    return [p for p in resume.projects if p.name.strip()]


def _project_title(p) -> tuple[str, str]:
    return p.name.strip(), p.tagline.strip()


def _project_links(p) -> list[tuple[str, str, str]]:
    """[(label, shown text, url)] — shown text is the clean URL so print copies stay usable."""
    return [(label, display_url(url), href(url)) for label, url in p.links()]


# --------------------------------------------------------------------------- #
# Plain text (live preview + .txt export for pasting into web forms)
# --------------------------------------------------------------------------- #
def to_text(resume: Resume, width: int = 78) -> str:
    c = resume.contact
    out: list[str] = []
    rule = "-" * width

    def section(key: str):
        out.extend(["", HEADINGS[key].upper(), rule])

    out.append(c.name.upper() or "YOUR NAME")
    if c.headline:
        out.append(c.headline)
    rows = c.labeled()
    if rows:
        w = max(len(k) for k, _ in rows) + 2
        out.extend(f"{k + ':':<{w}}{v}" for k, v in rows)

    if resume.summary.strip():
        section("summary")
        out.append(resume.summary.strip())

    groups = _visible_skills(resume)
    if groups:
        section("skills")
        for g in groups:
            out.append(f"{g.category}: {', '.join(g.items)}")

    roles = resume.sorted_experience()
    if roles:
        section("experience")
        for i, r in enumerate(roles):
            if i:
                out.append("")
            out.append(f"{r.title}    {format_range(r.start, r.end)}")
            sub = _role_subline(r)
            team = _team_note(r)
            if sub or team:
                out.append(" | ".join(x for x in (sub, team) if x))
            if r.scope.strip():
                out.append(r.scope.strip())
            out.extend(f"  • {b}" for b in r.highlights)

    edu = [e for e in resume.education if e.degree or e.institution]
    if edu:
        section("education")
        for e in edu:
            line = ", ".join(x for x in (e.degree, e.institution, e.location) if x)
            out.append(f"{line}    {format_date(e.year)}".rstrip())
            if e.details.strip():
                out.append(f"  {e.details.strip()}")

    certs = [x for x in resume.certifications if x.name.strip()]
    if certs:
        section("certifications")
        for x in certs:
            out.append(" — ".join(p for p in (x.name, x.issuer, x.year) if p))

    projects = _visible_projects(resume)
    if projects:
        section("projects")
        for i, p in enumerate(projects):
            if i:
                out.append("")
            name, tagline = _project_title(p)
            out.append(f"{name} — {tagline}" if tagline else name)
            if p.tech:
                out.append("  " + " · ".join(p.tech))
            if p.description.strip():
                out.append("  " + p.description.strip())
            out.extend(f"  • {b}" for b in p.highlights)
            links = _project_links(p)
            if links:
                out.append("  " + "  |  ".join(f"{lab}: {shown}" for lab, shown, _ in links))
            if p.shots:
                n = len(p.shots)
                out.append(f"  [{n} screenshot{'s' if n != 1 else ''} in the web version]")

    if resume.additional:
        section("additional")
        out.extend(f"  • {a}" for a in resume.additional)

    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# HTML (print to PDF from any browser; single column, print CSS)
# --------------------------------------------------------------------------- #
CSS = """
@page { size: __PAGE__; margin: 0.6in 0.7in; }
* { box-sizing: border-box; }
body { font-family: Garamond, "EB Garamond", "Cormorant Garamond", Georgia, Cambria, serif;
       font-size: 11pt; line-height: 1.35; color: #222; margin: 0;
       background: #f3f3f3; }
main { max-width: __WIDTH__in; margin: 24px auto; background: #fff;
       padding: 0.6in 0.7in; }
header.top { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; }
header.top img { width: 0.95in; height: 1.22in; object-fit: cover; border-radius: 3px; flex: none; }
h1 { font-size: 24pt; font-weight: 700; margin: 0; letter-spacing: 1px; color: #1F3864; }
.headline { font-size: 12pt; font-style: italic; margin: 2px 0 6px; color: #4A4A4A; }
.contact { display: grid; grid-template-columns: max-content 1fr; column-gap: 10px;
           font-size: 10pt; color: #222; margin: 0; }
.contact dt { font-weight: 700; color: #1F3864; }
.contact dd { margin: 0; }
h2 { font-size: 11.5pt; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;
     color: #1F3864; border-bottom: 0.75px solid #1F3864; margin: 14px 0 6px; padding-bottom: 2px; }
p { margin: 0 0 4px; }
.skills p { margin: 0 0 2px; }
.skills b { font-weight: 700; color: #1F3864; }
.role { margin: 0 0 8px; page-break-inside: avoid; }
.row { display: flex; justify-content: space-between; gap: 12px; }
.title { font-weight: 700; }
.dates { white-space: nowrap; }
.sub { color: #333; font-style: italic; }
.scope { color: #333; }
ul { margin: 2px 0 0 18px; padding: 0; }
li { margin: 0 0 2px; }
a { color: inherit; text-decoration: none; border-bottom: 0.5px dotted #1F3864; }
a:hover { color: #1F3864; border-bottom-style: solid; }
.project { display: flex; gap: 16px; align-items: flex-start; margin: 0 0 10px;
           page-break-inside: avoid; }
.project .text { flex: 1; min-width: 0; }
.project .tagline { font-style: italic; color: #4A4A4A; }
.project .tech { color: #4A4A4A; font-size: 10pt; }
.project .links { font-size: 10pt; color: #1F3864; margin-top: 2px; }
.project .links b { font-weight: 700; }
.project .shots { flex: none; width: 2.6in; }
a.shot { display: block; position: relative; border-bottom: 0; cursor: zoom-in; }
a.shot img { display: block; border: 0.5px solid #cfcfcf; border-radius: 4px; background: #f4f5f7; }
a.shot.main img { width: 100%; max-height: 2in; object-fit: contain; }
a.shot .zoom { position: absolute; right: 6px; bottom: 6px; padding: 2px 8px; border-radius: 3px;
               background: rgba(31, 56, 100, .88); color: #fff; font: 600 8.5pt system-ui, sans-serif;
               opacity: 0; transition: opacity .15s; }
a.shot:hover .zoom, a.shot:focus .zoom { opacity: 1; }
@media (hover: none) { a.shot .zoom { opacity: 1; } }
.minis { display: flex; gap: 4px; margin-top: 4px; }
.minis a.shot { flex: 1 1 0; min-width: 0; }
.minis img { width: 100%; height: 0.45in; object-fit: cover; object-position: top; border-radius: 3px; }
.minis .more { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
               background: rgba(0, 0, 0, .5); color: #fff; font: 700 10pt system-ui, sans-serif; border-radius: 3px; }
a.shot.extra { display: none; }
.lightbox { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center;
            background: rgba(10, 14, 22, .93); }
.lightbox[hidden] { display: none; }
.lightbox figure { margin: 0; display: flex; flex-direction: column; align-items: center; }
.lightbox img { max-width: 92vw; max-height: 84vh; object-fit: contain; background: #fff; border-radius: 4px;
                box-shadow: 0 10px 40px rgba(0, 0, 0, .5); }
.lightbox figcaption { margin-top: 10px; max-width: 80vw; text-align: center; color: #eee;
                       font: 11pt system-ui, sans-serif; }
.lightbox .count { opacity: .7; margin-left: 10px; }
.lightbox button { position: absolute; width: 46px; height: 46px; border: 0; border-radius: 50%; cursor: pointer;
                   background: rgba(255, 255, 255, .14); color: #fff; font: 26px/1 system-ui, sans-serif; }
.lightbox button:hover, .lightbox button:focus-visible { background: rgba(255, 255, 255, .3); outline: none; }
.lightbox .close { top: 14px; right: 14px; }
.lightbox .prev { left: 14px; top: calc(50% - 23px); }
.lightbox .next { right: 14px; top: calc(50% - 23px); }
.lightbox.single .prev, .lightbox.single .next, .lightbox.single .count { display: none; }
nav.downloads { max-width: __WIDTH__in; margin: 16px auto -12px; padding: 0 4px; text-align: right;
                font-size: 10.5pt; color: #4A4A4A; }
nav.downloads a { display: inline-block; margin-left: 8px; padding: 3px 12px; border: 0.75px solid #1F3864;
                  border-radius: 4px; color: #1F3864; font-weight: 700; }
nav.downloads a:hover { background: #1F3864; color: #fff; }
@media print { body { background: #fff; } main { margin: 0; padding: 0; max-width: none; }
               nav.downloads, .lightbox, .minis, a.shot .zoom { display: none !important; } }
@media screen and (max-width: 720px) {
  nav.downloads { margin: 0; padding: 12px 18px 0; text-align: left; }
  main { margin: 0; padding: 22px 18px; }
  header.top { flex-direction: column-reverse; }
  .row { flex-direction: column; gap: 0; }
  .project { flex-direction: column; }
  .project .shots { width: 100%; }
  a.shot.main img { max-height: 60vh; }
  .lightbox img { max-width: 100vw; border-radius: 0; }
  .lightbox .prev, .lightbox .next { top: auto; bottom: 18px; }
}
"""


def _a(text: str, url: str) -> str:
    """Escaped text, wrapped in a link when there's a target."""
    t = html.escape(text)
    if not url:
        return t
    ext = "" if url.startswith(("mailto:", "tel:")) else ' target="_blank" rel="noopener"'
    return f'<a href="{html.escape(url, quote=True)}"{ext}>{t}</a>'


def to_html(resume: Resume, noindex: bool | None = None,
            downloads: list[tuple[str, str]] | None = None,
            image_url=None) -> str:
    """Single-page HTML resume.

    noindex: add <meta name="robots" content="noindex,..."> so search engines
             skip the page (default: the resume's own `noindex` setting).
    downloads: [(label, relative url)] shown as buttons above the page on
               screen (hidden when printed), e.g. [("PDF", "cv.pdf")].
    """
    e = html.escape
    c = resume.contact
    noindex = resume.noindex if noindex is None else noindex
    image_url = image_url or photo.data_uri          # site builder passes a file writer instead
    body: list[str] = ['<header class="top"><div>', f"<h1>{e(c.name or 'Your Name')}</h1>"]
    if c.headline:
        body.append(f'<div class="headline">{e(c.headline)}</div>')
    rows = c.labeled_links()
    if rows:
        body.append('<dl class="contact">' + "".join(
            f"<dt>{e(k)}:</dt><dd>{_a(v, url)}</dd>" for k, v, url in rows) + "</dl>")
    body.append("</div>")
    if resume.has_photo:
        body.append(f'<img src="{photo.data_uri(resume.photo)}" alt="Photo of {e(c.name)}">')
    body.append("</header>")

    def h2(key: str):
        body.append(f"<h2>{HEADINGS[key]}</h2>")

    if resume.summary.strip():
        h2("summary")
        body.append(f"<p>{e(resume.summary.strip())}</p>")

    groups = _visible_skills(resume)
    if groups:
        h2("skills")
        body.append('<section class="skills">')
        for g in groups:
            body.append(f"<p><b>{e(g.category)}:</b> {e(', '.join(g.items))}</p>")
        body.append("</section>")

    roles = resume.sorted_experience()
    if roles:
        h2("experience")
        for r in roles:
            sub = " | ".join(x for x in (_role_subline(r), _team_note(r)) if x)
            body.append('<div class="role">')
            body.append(f'<div class="row"><span class="title">{e(r.title)}</span>'
                        f'<span class="dates">{e(format_range(r.start, r.end))}</span></div>')
            if sub:
                body.append(f'<div class="sub">{e(sub)}</div>')
            if r.scope.strip():
                body.append(f'<div class="scope">{e(r.scope.strip())}</div>')
            if r.highlights:
                body.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in r.highlights) + "</ul>")
            body.append("</div>")

    edu = [x for x in resume.education if x.degree or x.institution]
    if edu:
        h2("education")
        for x in edu:
            line = ", ".join(e(p) for p in (x.degree, x.institution, x.location) if p)
            body.append(f'<div class="row"><span>{line}</span>'
                        f'<span class="dates">{e(format_date(x.year))}</span></div>')
            if x.details.strip():
                body.append(f'<p class="scope">{e(x.details.strip())}</p>')

    certs = [x for x in resume.certifications if x.name.strip()]
    if certs:
        h2("certifications")
        body.append("<ul>" + "".join(
            f"<li>{e(' — '.join(p for p in (x.name, x.issuer, x.year) if p))}</li>"
            for x in certs) + "</ul>")

    has_gallery = False
    projects = _visible_projects(resume)
    if projects:
        h2("projects")
        for p in projects:
            name, tagline = _project_title(p)
            parts = ['<div class="project"><div class="text">',
                     f'<div><span class="title">{e(name)}</span>'
                     + (f' <span class="tagline">— {e(tagline)}</span>' if tagline else "")
                     + "</div>"]
            if p.tech:
                parts.append(f'<div class="tech">{e(" · ".join(p.tech))}</div>')
            if p.description.strip():
                parts.append(f"<p>{e(p.description.strip())}</p>")
            if p.highlights:
                parts.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in p.highlights) + "</ul>")
            links = _project_links(p)
            if links:
                parts.append('<div class="links">' + " &nbsp;·&nbsp; ".join(
                    f"<b>{e(lab)}:</b> {_a(shown, url)}" for lab, shown, url in links) + "</div>")
            parts.append("</div>")
            if p.shots:
                parts.append(_gallery_html(p, name, image_url))
                has_gallery = True
            parts.append("</div>")
            body.append("".join(parts))

    if resume.additional:
        h2("additional")
        body.append("<ul>" + "".join(f"<li>{e(a)}</li>" for a in resume.additional) + "</ul>")

    title = e(f"{c.name} – Resume" if c.name else "Resume")
    css = CSS.replace("__PAGE__", PAGE_LABELS[resume.page_size]) \
             .replace("__WIDTH__", str(PAGE_SIZES[resume.page_size][0]))
    meta = ['<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">']
    if noindex:
        meta.append('<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">')
    if c.headline.strip():
        meta.append(f'<meta name="description" content="{e(c.headline.strip(), quote=True)}">')
    nav = ""
    if downloads:
        nav = ('<nav class="downloads">Download ' + "".join(
            f'<a href="{e(url, quote=True)}" download>{e(label)}</a>' for label, url in downloads)
            + "</nav>\n")
    viewer = LIGHTBOX if has_gallery else ""
    return ("<!doctype html>\n<html lang=\"en\"><head>" + "".join(meta) +
            f"<title>{title}</title><style>{css}</style></head>"
            f"<body>\n{nav}<main>\n" + "\n".join(body) + f"\n</main>{viewer}</body></html>\n")


MINIS_SHOWN = 4

LIGHTBOX = """
<div id="lb" class="lightbox" hidden role="dialog" aria-modal="true" aria-label="Screenshot viewer">
<button class="close" type="button" aria-label="Close">&times;</button>
<button class="prev" type="button" aria-label="Previous screenshot">&#8249;</button>
<figure><img alt=""><figcaption><span class="cap"></span><span class="count"></span></figcaption></figure>
<button class="next" type="button" aria-label="Next screenshot">&#8250;</button>
</div>
<script>
(function () {
  var lb = document.getElementById("lb"), img = lb.querySelector("img"),
      cap = lb.querySelector(".cap"), cnt = lb.querySelector(".count"),
      items = [], i = 0, opener = null, x0 = null;
  function show(k) {
    i = (k + items.length) % items.length;
    var a = items[i], t = a.querySelector("img");
    img.src = a.getAttribute("href");
    img.alt = t ? t.alt : "";
    cap.textContent = a.getAttribute("data-caption") || "";
    cnt.textContent = items.length > 1 ? (i + 1) + " / " + items.length : "";
    lb.classList.toggle("single", items.length < 2);
  }
  function close() {
    lb.hidden = true; document.body.style.overflow = ""; img.removeAttribute("src");
    if (opener) opener.focus();
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.shot");
    if (!a) return;
    e.preventDefault();
    opener = a;
    items = [].slice.call(document.querySelectorAll('a.shot[data-gallery="' + a.getAttribute("data-gallery") + '"]'));
    show(items.indexOf(a));
    lb.hidden = false; document.body.style.overflow = "hidden";
    lb.querySelector(".close").focus();
  });
  lb.addEventListener("click", function (e) {
    var c = e.target.classList;
    if (e.target === lb || c.contains("close")) close();
    else if (c.contains("prev")) show(i - 1);
    else if (c.contains("next")) show(i + 1);
  });
  document.addEventListener("keydown", function (e) {
    if (lb.hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") show(i - 1);
    else if (e.key === "ArrowRight") show(i + 1);
  });
  lb.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, {passive: true});
  lb.addEventListener("touchend", function (e) {
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 50 && items.length > 1) show(dx < 0 ? i + 1 : i - 1);
    x0 = null;
  });
})();
</script>
"""


def _gallery_html(p, name: str, image_url) -> str:
    """Thumbnail (first screenshot) + strip of the others; all open in the viewer."""
    e = html.escape
    shots = p.shots
    gid = f"g-{p.id}"
    n = len(shots)

    def anchor(s, k, cls, inner):
        url = e(image_url(s.data), quote=True)
        cap = e(s.caption or f"{name}: screenshot {k + 1} of {n}", quote=True)
        return (f'<a class="shot {cls}" href="{url}" data-gallery="{gid}" data-caption="{cap}" '
                f'title="Click to enlarge">{inner}</a>')

    def img(s, k, lazy=True):
        alt = e(s.caption or f"Screenshot {k + 1} of {name}", quote=True)
        return (f'<img src="{e(image_url(s.data), quote=True)}" alt="{alt}"'
                + (' loading="lazy"' if lazy else "") + ">")

    out = ['<div class="shots">',
           anchor(shots[0], 0, "main",
                  img(shots[0], 0) + f'<span class="zoom">{"Enlarge" if n == 1 else f"View {n}"}</span>')]
    if n > 1:
        out.append('<div class="minis">')
        rest = shots[1:]
        for k, s in enumerate(rest[:MINIS_SHOWN], start=1):
            more = n - 1 - MINIS_SHOWN
            badge = f'<span class="more">+{more}</span>' if k == MINIS_SHOWN and more > 0 else ""
            out.append(anchor(s, k, "mini", img(s, k) + badge))
        out.append("</div>")
        for k, s in enumerate(rest[MINIS_SHOWN:], start=MINIS_SHOWN + 1):
            out.append(anchor(s, k, "extra", ""))
    out.append("</div>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# DOCX (what most ATS portals and recruiters ask for)
# --------------------------------------------------------------------------- #
def to_docx(resume: Resume, path: str | Path) -> Path:
    from docx import Document
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    pw, ph = PAGE_SIZES[resume.page_size]
    sec.page_width, sec.page_height = Inches(pw), Inches(ph)
    sec.left_margin = sec.right_margin = Inches(0.7)
    sec.top_margin = sec.bottom_margin = Inches(0.6)
    right_tab = sec.page_width - sec.left_margin - sec.right_margin

    accent, muted = RGBColor.from_string(ACCENT), RGBColor.from_string(MUTED_HEX)
    for style_name in ("Normal", "List Bullet"):
        st = doc.styles[style_name]
        st.font.name = FONT
        rfonts = st.element.get_or_add_rPr().get_or_add_rFonts()
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attr), FONT)
    normal = doc.styles["Normal"]
    normal.font.size = Pt(BODY_PT)
    normal.font.color.rgb = RGBColor.from_string(INK_HEX)
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.space_before = Pt(0)

    def tracking(run, points: float):
        """Letter-spacing (Word's 'Character spacing: Expanded')."""
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:val"), str(int(points * 20)))
        # keep the schema order Word expects (spacing sits before size etc.)
        run._r.get_or_add_rPr().insert_element_before(
            sp, "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight",
            "w:u", "w:effect", "w:bdr", "w:shd", "w:fitText", "w:vertAlign",
            "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
            "w:specVanish", "w:oMath")

    def para(text: str = "", bold=False, italic=False, size=None, after=2):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(after)
        if text:
            run = p.add_run(text)
            run.bold, run.italic = bold, italic
            if size:
                run.font.size = Pt(size)
        return p

    def bottom_border(p):
        ppr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        b = OxmlElement("w:bottom")
        for k, v in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", ACCENT)):
            b.set(qn(f"w:{k}"), v)
        bdr.append(b)
        ppr.append(bdr)

    def heading(key: str):
        p = para(HEADINGS[key].upper(), bold=True, size=11.5, after=3)
        p.runs[0].font.color.rgb = accent
        tracking(p.runs[0], 1.5)
        p.paragraph_format.space_before = Pt(10)
        bottom_border(p)

    def left_right(left: str, right: str, bold_left=True):
        p = para(after=0)
        p.paragraph_format.tab_stops.add_tab_stop(right_tab, WD_TAB_ALIGNMENT.RIGHT)
        r = p.add_run(left)
        r.bold = bold_left
        if right:
            p.add_run("\t" + right)
        return p

    def bullet(text: str):
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
        p.add_run(text)
        return p

    c = resume.contact
    name_p = para(c.name or "Your Name", bold=True, size=NAME_PT, after=0)
    name_p.runs[0].font.color.rgb = accent
    tracking(name_p.runs[0], 1)
    if resume.has_photo:
        _float_photo_right(name_p, photo.to_bytes(resume.photo), Inches(PHOTO_W_IN))
    if c.headline:
        p = para(c.headline, italic=True, size=12, after=4)
        p.runs[0].font.color.rgb = muted
    rows = c.labeled_links()
    for i, (label, value, url) in enumerate(rows):
        last = i == len(rows) - 1
        p = para(after=(10 if resume.has_photo else 4) if last else 0)
        p.paragraph_format.tab_stops.add_tab_stop(Inches(LABEL_IN))
        lab = p.add_run(f"{label}:")
        lab.bold, lab.font.size, lab.font.color.rgb = True, Pt(10), accent
        p.add_run("\t").font.size = Pt(10)
        if url:
            _hyperlink(p, value, url, size=10)
        else:
            p.add_run(value).font.size = Pt(10)

    if resume.summary.strip():
        heading("summary")
        para(resume.summary.strip())

    groups = _visible_skills(resume)
    if groups:
        heading("skills")
        for g in groups:
            p = para(after=1)
            cat = p.add_run(f"{g.category}: ")
            cat.bold, cat.font.color.rgb = True, accent
            p.add_run(", ".join(g.items))

    roles = resume.sorted_experience()
    if roles:
        heading("experience")
        for i, r in enumerate(roles):
            p = left_right(r.title, format_range(r.start, r.end))
            if i:
                p.paragraph_format.space_before = Pt(6)
            sub = " | ".join(x for x in (_role_subline(r), _team_note(r)) if x)
            if sub:
                para(sub, italic=True, after=0)
            if r.scope.strip():
                para(r.scope.strip(), after=0)
            for b in r.highlights:
                bullet(b)

    edu = [x for x in resume.education if x.degree or x.institution]
    if edu:
        heading("education")
        for x in edu:
            left_right(", ".join(p for p in (x.degree, x.institution, x.location) if p),
                       format_date(x.year), bold_left=False)
            if x.details.strip():
                para(x.details.strip(), italic=True)

    certs = [x for x in resume.certifications if x.name.strip()]
    if certs:
        heading("certifications")
        for x in certs:
            bullet(" — ".join(p for p in (x.name, x.issuer, x.year) if p))

    projects = _visible_projects(resume)
    if projects:
        heading("projects")
        for i, pr in enumerate(projects):
            name, tagline = _project_title(pr)
            p = para(after=0)
            if i:
                p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.keep_with_next = True
            p.add_run(name).bold = True
            if tagline:
                t = p.add_run(f" — {tagline}")
                t.italic, t.font.color.rgb = True, muted
            if pr.tech:
                t = para(" · ".join(pr.tech), italic=True, size=10, after=0)
                t.runs[0].font.color.rgb = muted
                t.paragraph_format.keep_with_next = True
            if pr.description.strip():
                para(pr.description.strip(), after=1)
            for b in pr.highlights:
                bullet(b)
            links = _project_links(pr)
            if links:
                lp = para(after=1)
                for j, (lab, shown, url) in enumerate(links):
                    if j:
                        lp.add_run("   ·   ").font.size = Pt(10)
                    r = lp.add_run(f"{lab}: ")
                    r.bold, r.font.size, r.font.color.rgb = True, Pt(10), accent
                    if url:
                        _hyperlink(lp, shown, url, size=10)
                    else:
                        lp.add_run(shown).font.size = Pt(10)

    if resume.additional:
        heading("additional")
        for a in resume.additional:
            bullet(a)

    doc.core_properties.author = c.name
    doc.core_properties.title = f"{c.name} Resume".strip()
    path = Path(path)
    doc.save(path)
    return path


def _hyperlink(paragraph, text: str, url: str, size: float | None = None,
               color: str = ACCENT) -> None:
    """Append a clickable external hyperlink run (python-docx has no API for it)."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    col = OxmlElement("w:color")             # schema order: color, sz, u
    col.set(qn("w:val"), color)
    rpr.append(col)
    if size:
        for tag in ("w:sz", "w:szCs"):
            sz = OxmlElement(tag)
            sz.set(qn("w:val"), str(int(size * 2)))
            rpr.append(sz)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def _float_photo_right(paragraph, image_bytes: bytes, width) -> None:
    """Insert a picture anchored to the top-right margin with text wrapping left.

    python-docx only creates inline pictures, so we build the inline one and
    swap its XML for a floating <wp:anchor>. The name, headline and contact
    lines then flow beside the photo instead of below it.
    """
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    run = paragraph.add_run()
    inline = run.add_picture(io.BytesIO(image_bytes), width=width)._inline
    cx, cy = inline.extent.cx, inline.extent.cy
    anchor = parse_xml(
        f'<wp:anchor {nsdecls("wp", "a", "pic", "r")} distT="0" distB="0" '
        f'distL="182880" distR="0" simplePos="0" relativeHeight="251658240" '
        f'behindDoc="0" locked="0" layoutInCell="1" allowOverlap="0">'
        f'<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="margin"><wp:align>right</wp:align></wp:positionH>'
        f'<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:wrapSquare wrapText="left"/>'
        f'<wp:docPr id="{inline.docPr.id}" name="Photo"/>'
        f'<wp:cNvGraphicFramePr/>'
        f'</wp:anchor>')
    anchor.append(inline.graphic)
    inline.getparent().replace(inline, anchor)


def file_stem(resume: Resume, profile_name: str = "") -> str:
    """'Alex Morgan' + 'EM - Energy' -> 'Alex_Morgan_EM-Energy_Resume'."""
    def clean(s: str) -> str:
        s = re.sub(r"\s*[-–—]\s*", "-", s.strip("[] "))
        return re.sub(r"[^\w\-]+", "_", s).strip("_-")
    parts = [clean(resume.contact.name) or "resume"]
    if profile_name.strip():
        parts.append(clean(profile_name))
    return "_".join(parts) + "_Resume"


def export(resume: Resume, path: str | Path) -> Path:
    """Export by extension: .pdf, .docx, .html, .txt or .json."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        return to_docx(resume, path)
    if ext == ".pdf":
        from .pdf import to_pdf
        return to_pdf(resume, path)
    if ext in (".html", ".htm"):
        path.write_text(to_html(resume), encoding="utf-8")
    elif ext == ".txt":
        path.write_text(to_text(resume), encoding="utf-8")
    elif ext == ".json":
        resume.save(path)
    else:
        raise ValueError(f"Unsupported export format: {ext or '(none)'}")
    return path
