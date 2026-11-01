"""Direct PDF export with ReportLab (no browser or Word needed).

Same hybrid layout as the Word export: header (with optional photo on the
right), summary, core skills, newest-first experience, then the rest.
Text stays real, selectable text so ATS parsers can read it.
"""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from . import photo
from .model import Resume, format_date, format_range, normalize_page_size
from .render import (ACCENT, BODY_PT, HEADINGS, INK_HEX, LABEL_IN, MUTED_HEX, NAME_PT,
                     PHOTO_W_IN, _project_links, _project_title,
                     _role_subline, _team_note, _visible_projects, _visible_skills)


INK = colors.HexColor(f"#{INK_HEX}")
MUTED = colors.HexColor(f"#{MUTED_HEX}")
NAVY = colors.HexColor(f"#{ACCENT}")
LABEL_W = LABEL_IN * inch             # contact label column, same as the Word tab stop

# Fonts with full Unicode coverage (umlauts, accents, dashes), first found wins.
# Elegant serifs first (Garamond ships with MS Office), then common fallbacks.
FONT_CANDIDATES = [
    ("Garamond", "C:/Windows/Fonts/GARA.TTF", "C:/Windows/Fonts/GARABD.TTF",
     "C:/Windows/Fonts/GARAIT.TTF"),
    ("EBGaramond", "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Regular.ttf",
     "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Bold.ttf",
     "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Italic.ttf"),
    ("Georgia", "C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/georgiab.ttf",
     "C:/Windows/Fonts/georgiai.ttf"),
    ("Georgia", "/System/Library/Fonts/Supplemental/Georgia.ttf",
     "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
     "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"),
    ("Caladea", "/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf",
     "/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf",
     "/usr/share/fonts/truetype/crosextra/Caladea-Italic.ttf"),
    ("LiberationSerif", "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
    ("Calibri", "C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf",
     "C:/Windows/Fonts/calibrii.ttf"),
    ("Carlito", "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
     "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
     "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf"),
    ("Arial", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf",
     "C:/Windows/Fonts/ariali.ttf"),
    ("Arial", "/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
    ("Arial", "/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf",
     "/Library/Fonts/Arial Italic.ttf"),
    ("LiberationSans", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
]
_FONTS: tuple[str, str, str] | None = None


def fonts() -> tuple[str, str, str]:
    """(regular, bold, italic) font names, registering a TTF family if found."""
    global _FONTS
    if _FONTS:
        return _FONTS
    for family, reg, bold, ital in FONT_CANDIDATES:
        if all(Path(p).exists() for p in (reg, bold, ital)):
            try:
                pdfmetrics.registerFont(TTFont(family, reg))
                pdfmetrics.registerFont(TTFont(f"{family}-Bold", bold))
                pdfmetrics.registerFont(TTFont(f"{family}-Italic", ital))
                pdfmetrics.registerFontFamily(family, normal=family, bold=f"{family}-Bold",
                                              italic=f"{family}-Italic",
                                              boldItalic=f"{family}-Bold")
                _FONTS = (family, f"{family}-Bold", f"{family}-Italic")
                return _FONTS
            except Exception:  # noqa: BLE001 - corrupt font file: try the next one
                continue
    _FONTS = ("Times-Roman", "Times-Bold", "Times-Italic")
    return _FONTS


def _styles():
    reg, bold, ital = fonts()
    base = ParagraphStyle("base", fontName=reg, fontSize=BODY_PT, leading=BODY_PT * 1.3,
                          textColor=INK, spaceAfter=2)
    return {
        "name": ParagraphStyle("name", base, fontName=bold, fontSize=NAME_PT,
                               leading=NAME_PT * 1.2, textColor=NAVY),
        "headline": ParagraphStyle("headline", base, fontName=ital, fontSize=12, leading=15,
                                   textColor=MUTED, spaceAfter=4),
        "contact_label": ParagraphStyle("contact_label", base, fontName=bold, fontSize=10,
                                        leading=13, textColor=NAVY, spaceAfter=0),
        "contact": ParagraphStyle("contact", base, fontSize=10, leading=13, spaceAfter=0),
        "h2": ParagraphStyle("h2", base, fontName=bold, fontSize=11.5, leading=14,
                             textColor=NAVY, spaceBefore=10, spaceAfter=0),
        "body": base,
        "skill": ParagraphStyle("skill", base, spaceAfter=1.5),
        "title": ParagraphStyle("title", base, fontName=bold, spaceAfter=0),
        "dates": ParagraphStyle("dates", base, alignment=TA_RIGHT, spaceAfter=0),
        "sub": ParagraphStyle("sub", base, fontName=ital, textColor=MUTED, spaceAfter=0),
        "scope": ParagraphStyle("scope", base, textColor=MUTED, spaceAfter=1),
        "bullet": ParagraphStyle("bullet", base, leftIndent=15, bulletIndent=4,
                                 spaceAfter=1.5, bulletFontName=reg),
        "tech": ParagraphStyle("tech", base, fontName=ital, fontSize=10, leading=13,
                               textColor=MUTED, spaceAfter=1),
        "links": ParagraphStyle("links", base, fontSize=10, leading=13, textColor=NAVY,
                                spaceAfter=1),
    }


SHOT_PAGE_MAX_H = 4.1 * inch          # two screenshots fit on a page


def _screenshot_pages(projects, st, width, heading_style):
    """Appendix: every project screenshot full width, each a link target."""
    out = [PageBreak(), Paragraph("PROJECT SCREENSHOTS", heading_style),
           HRFlowable(width="100%", thickness=0.75, color=NAVY, spaceBefore=2, spaceAfter=6)]
    for p in projects:
        name = escape(p.name.strip())
        shots = p.shots
        n = len(shots)
        title = Paragraph(f"<b>{name}</b>&nbsp;&nbsp;<font size=9>"
                          f'<a href="#proj-{p.id}" color="#{ACCENT}">&#171; back to project</a>'
                          "</font>", st["body"])
        for k, s in enumerate(shots):
            iw, ih = photo.size_of(s.data)
            w = width
            h = w * ih / iw
            if h > SHOT_PAGE_MAX_H:
                h, w = SHOT_PAGE_MAX_H, SHOT_PAGE_MAX_H * iw / ih
            img = Image(io.BytesIO(photo.to_bytes(s.data)), width=w, height=h)
            img.hAlign = "CENTER"
            cap = escape(s.caption) if s.caption else f"Screenshot {k + 1} of {n}"
            block = ([title] if k == 0 else []) + [
                Paragraph(f'<a name="shot-{p.id}-{k}"/>{cap}', st["sub"]), Spacer(1, 3), img,
                Spacer(1, 10)]
            out.append(KeepTogether(block))
    return out


def _link(text: str, url: str) -> str:
    """ReportLab markup for clickable text (plain text when there's no target)."""
    t = escape(text)
    if not url:
        return t
    return f'<a href="{escape(url, {chr(34): "&quot;"})}" color="#{ACCENT}">{t}</a>'


def to_pdf(resume: Resume, path: str | Path, page_size: str | None = None) -> Path:
    """Write a PDF. page_size overrides the resume's own setting when given."""
    st = _styles()
    size = normalize_page_size(page_size or resume.page_size)
    page = A4 if size == "a4" else LETTER
    left = right = 0.7 * inch
    width = page[0] - left - right - 12      # frame has 6 pt padding each side
    path = Path(path)
    c = resume.contact
    e = escape

    story = []

    def heading(key: str):
        story.append(Paragraph(e(HEADINGS[key].upper()), st["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.75, color=NAVY,
                                spaceBefore=2, spaceAfter=4))

    def left_right(left_text: str, right_text: str, left_style="title"):
        t = Table([[Paragraph(left_text, st[left_style]), Paragraph(e(right_text), st["dates"])]],
                  colWidths=[width - 1.7 * inch, 1.7 * inch])
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    def bullet(text: str):
        return Paragraph(text, st["bullet"], bulletText="•")

    # ---- header (photo on the right when switched on)
    head = [Paragraph(e(c.name or "Your Name"), st["name"])]
    if c.headline:
        head.append(Paragraph(e(c.headline), st["headline"]))
    rows = c.labeled_links()
    head_w = width - (PHOTO_W_IN + 0.2) * inch if resume.has_photo else width
    if rows:
        ct = Table([[Paragraph(e(f"{k}:"), st["contact_label"]),
                     Paragraph(_link(v, url), st["contact"])]
                    for k, v, url in rows], colWidths=[LABEL_W, head_w - LABEL_W], hAlign="LEFT")
        ct.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                                ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        head.append(ct)
    if resume.has_photo:
        pw = PHOTO_W_IN * inch
        img = Image(io.BytesIO(photo.to_bytes(resume.photo)), width=pw, height=pw * 9 / 7)
        img.hAlign = "RIGHT"
        t = Table([[head, img]], colWidths=[width - pw - 0.2 * inch, pw + 0.2 * inch])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)
    else:
        story.extend(head)

    if resume.summary.strip():
        heading("summary")
        story.append(Paragraph(e(resume.summary.strip()), st["body"]))

    groups = _visible_skills(resume)
    if groups:
        heading("skills")
        for g in groups:
            story.append(Paragraph(f'<font color="#{ACCENT}"><b>{e(g.category)}:</b></font> '
                                   f"{e(', '.join(g.items))}", st["skill"]))

    roles = resume.sorted_experience()
    if roles:
        heading("experience")
        for i, r in enumerate(roles):
            block = []
            if i:
                block.append(Spacer(1, 5))
            block.append(left_right(e(r.title), format_range(r.start, r.end)))
            sub = " | ".join(x for x in (_role_subline(r), _team_note(r)) if x)
            if sub:
                block.append(Paragraph(e(sub), st["sub"]))
            if r.scope.strip():
                block.append(Paragraph(e(r.scope.strip()), st["scope"]))
            bullets = [bullet(e(b)) for b in r.highlights]
            # keep the role header with its first two bullets
            story.append(KeepTogether(block + bullets[:2]))
            story.extend(bullets[2:])

    edu = [x for x in resume.education if x.degree or x.institution]
    if edu:
        heading("education")
        for x in edu:
            line = ", ".join(e(p) for p in (x.degree, x.institution, x.location) if p)
            block = [left_right(line, format_date(x.year), left_style="body")]
            if x.details.strip():
                block.append(Paragraph(e(x.details.strip()), st["sub"]))
            story.append(KeepTogether(block))

    certs = [x for x in resume.certifications if x.name.strip()]
    if certs:
        heading("certifications")
        story += [bullet(e(" — ".join(p for p in (x.name, x.issuer, x.year) if p))) for x in certs]

    projects = _visible_projects(resume)
    with_shots = []
    if projects:
        heading("projects")
        for i, p in enumerate(projects):
            name, tagline = _project_title(p)
            head_txt = f'<a name="proj-{p.id}"/><b>{e(name)}</b>'
            if tagline:
                head_txt += f' <font color="#{MUTED_HEX}"><i>— {e(tagline)}</i></font>'
            parts = [Paragraph(head_txt, st["body"])]
            if p.tech:
                parts.append(Paragraph("&nbsp;&nbsp;·&nbsp;&nbsp;".join(e(t) for t in p.tech),
                                       st["tech"]))
            if p.description.strip():
                parts.append(Paragraph(e(p.description.strip()), st["body"]))
            parts += [bullet(e(b)) for b in p.highlights]
            links = _project_links(p)
            if links:
                parts.append(Paragraph("&nbsp;&nbsp;·&nbsp;&nbsp;".join(
                    f"<b>{e(lab)}:</b> {_link(shown, url)}" for lab, shown, url in links),
                    st["links"]))
            block = [Spacer(1, 5)] if i else []
            if p.shots and resume.project_images_in_pdf:
                n = len(p.shots)
                parts.append(Paragraph(
                    f'<a href="#shot-{p.id}-0" color="#{ACCENT}">View {n} screenshot'
                    f'{"s" if n != 1 else ""} full size &#187;</a>', st["links"]))
                with_shots.append(p)
            block += parts
            story.append(KeepTogether(block))

    if resume.additional:
        heading("additional")
        story += [bullet(e(a)) for a in resume.additional]

    if with_shots:
        story += _screenshot_pages(with_shots, st, width, heading_style=st["h2"])

    reg = fonts()[0]

    def later_pages(canvas, doc):
        canvas.saveState()
        canvas.setFont(reg, 8.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(page[0] - right, 0.4 * inch,
                               f"{c.name} – page {doc.page}".strip(" –"))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=left, rightMargin=right,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title=f"{c.name} Resume".strip(), author=c.name,
                            subject=c.headline, creator="Hybrid Resume Builder")
    doc.build(story, onLaterPages=later_pages)
    return path
