"""ALgpt imzalı, ilana özel cover letter (PDF).

Hedef: hem ATS'den geçsin hem işe alımcının dikkatini çeksin.
  ATS:      gerçek metin PDF, standart font, tek sütun; pozisyon ve şirket adı birebir; ilanın
            anahtar becerileri metinde; PDF meta verisinde başlık/konu/anahtar kelimeler.
            Üretimden sonra PDF metni bir ATS gibi okunup doğrulanır (verify_letter_pdf).
  İnsan:    ilandan birebir alıntılanan şartlar + her birinin altında CV'den kanıt,
            gerçek puanla "ALgpt Match Report" kutusu.
Yazım kuralları (ai-job-search / 03-writing-style.md'den uyarlandı):
  250-300 kelime gövde, tek sayfa (zorunlu), uzun tire yok, klişe yok, ileriye dönük cümle,
  başlık = pozisyon + ilandan anahtar kelime. Her iddia profile_data.py'den (CV) gelir.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import date

import profile_data as P

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "letters")
ACCENT = (23, 92, 168)
MUTED = (95, 95, 95)
MAX_BODY_WORDS = 320  # başlık/iletişim/rapor kutusu hariç gövde

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
]

SITE_NAMES = {
    "linkedin": "LinkedIn", "pracuj": "Pracuj.pl", "nofluffjobs": "No Fluff Jobs", "theprotocol": "theprotocol.it",
    "justjoin": "Just Join IT", "rocketjobs": "RocketJobs", "talent": "Talent.com", "indeed": "Indeed",
    "glassdoor": "Glassdoor", "jobleads": "JobLeads", "michaelpage": "Michael Page", "hays": "Hays",
    "randstad": "Randstad", "devire": "Devire", "careersinpoland": "Careers in Poland",
    "europelanguagejobs": "Europe Language Jobs", "bulldogjob": "Bulldogjob", "hiringcafe": "HiringCafe",
}
OWN_SITES = {"amazon", "revolut", "ikea"}  # şirketin kendi kariyer sayfası

PRETTY = {"sql": "SQL", "vba": "VBA", "kpi": "KPI", "sla": "SLA", "capa": "CAPA", "aws": "AWS", "sop": "SOPs",
          "power bi": "Power BI", "power query": "Power Query", "powerapps": "PowerApps", "javascript": "JavaScript",
          "html": "HTML", "css": "CSS", "git": "Git", "jira": "Jira", "python": "Python", "excel": "Excel",
          "kotlin": "Kotlin", "llm": "LLMs", "ai": "AI", "kanban": "Kanban", "agile": "Agile", "lean": "Lean",
          "root cause analysis": "Root Cause Analysis", "compliance": "compliance", "audit": "audit"}
# İleriye dönük cümlede kullanılabilecek görev cümleleri bu fiillerle başlamalı.
TASK_VERB = re.compile(r"^(analy[sz]|monitor|prepar|support|improv|develop|manag|coordinat|perform|ensur|build|"
                       r"creat|maintain|conduct|review|identify|deliver|automat|investigat|assess|track|report|"
                       r"design|implement|optimi[sz]|handl|own|lead|drive|work)\w*\b", re.I)
HEADLINE_PRIORITY = ["Python", "SQL", "Power BI", "Excel", "VBA", "JavaScript", "AWS", "Root Cause Analysis", "CAPA",
                     "KPI", "Jira", "Git", "Kotlin", "audit", "compliance"]
CLICHES = re.compile(r"passionate|hit the ground running|leverage my|synerg|team player|go-getter|think outside", re.I)


def _clean_company(company: str) -> str:
    c = (company or "").strip()
    return "" if c.lower() in {"", "unknown", "see link", "see job link", "confidential"} else c


def _join(items: list) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _slug(s: str, n: int = 60) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-")


def letter_filename(job: dict) -> str:
    """alperen-simsek-<pozisyon>-letter.pdf"""
    title = re.sub(r"\((?:[mkfwdx]\s*/\s*)+[mkfwdx]\)|\b[mkf]/[mkf](?:/[dx])?\b", "", job.get("title") or "")
    return f"{_slug(P.NAME)}-{_slug(title) or 'position'}-letter.pdf"


def reference_id(job: dict) -> str:
    h = hashlib.sha1(f"{job.get('url')}|{job.get('title')}".encode()).hexdigest()[:6].upper()
    return f"ALgpt-{date.today():%Y%m%d}-{h}"


EMOJI_RE = re.compile("[🀀-🫿☀-➿️‍⬀-⯿]")


def _strip_emoji(text: str) -> str:
    """İlan başlıklarındaki emojiler PDF fontunda yok (boş kutu çıkar): temizle."""
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", text or "")).strip()


def _no_dashes(text: str) -> str:
    """Yazım kuralı: uzun tire yok (virgül/nokta ile değiştir)."""
    return re.sub(r"\s*[—–]\s*", ", ", text)


def build_letter(job: dict, result: dict, matcher=None) -> dict:
    company = _strip_emoji(_clean_company(job.get("company")))
    role = _strip_emoji(job.get("title") or "") or "this position"
    site = (job.get("site") or "").lower()
    where = "on your careers website" if site in OWN_SITES else f"on {SITE_NAMES.get(site, 'a job board')}"
    score = result.get("match_score", 0)
    matched = [PRETTY.get(s, s) for s in result.get("matched_skills", [])][:8]
    total = result.get("skill_total", 0)
    turkish = bool(re.search(r"\bturkish\b", f"{role} {job.get('description', '')}", re.I))

    pairs = matcher.match_requirements(job) if matcher else []
    achievements = []
    if len(pairs) < 2 and matcher is not None:  # kısa ilan / kart-only: en uygun CV başarıları
        _, vec = matcher.semantic(job)
        achievements = matcher.best_achievements(vec, n=3)

    # Başlık formülü: [eğitim/deneyim] + ilandan anahtar kelime (önce somut araçlar: ATS bunları arar)
    tools_first = sorted(matched, key=lambda m: (HEADLINE_PRIORITY.index(m) if m in HEADLINE_PRIORITY else 99))
    keywords = _join(tools_first[:2]) if matched else "process automation"
    headline = f"MSc Computer Science, 2 years in compliance at Amazon, hands-on with {keywords}"

    intro = (
        f"I am {P.ASSISTANT_NAME}, the AI job-search assistant {P.NAME} built himself. Each day I scan Polish job "
        f"boards, read every new posting and score it against his CV with an offline AI model. Your {role} role, "
        f"which I found {where}, scored {score}/100: one of the strongest matches I have found for him. "
        f"I wrote this letter for your posting specifically; Alperen reviews and sends it himself."
    )
    skills = (f"Of the {total} skills your posting lists, he brings {len(matched)}: {_join(matched)}."
              if total >= 2 and matched else
              (f"The skills this role relies on are ones he uses daily: {_join(matched)}." if matched else ""))
    background = ("He holds an MSc in Computer Science (Warsaw) and a BSc in Mathematics, speaks English (C1) and "
                  "Turkish (native), and is exempt from the Polish work-permit requirement."
                  + (" His native Turkish covers the language requirement of this role." if turkish else ""))
    # İleriye dönük: yukarıda gösterilmeyen bir görev cümlesine bağla (fiille başlıyorsa, dilbilgisi bozulmasın).
    shown = {q for q, _ in pairs}
    task = matcher.best_task(job, shown, TASK_VERB) if matcher else ""
    forward = (f"In this role he would bring the same approach to {task[0].lower() + task[1:]}: find the manual, "
               f"repetitive work, build the tool that removes it and measure the result."
               if task else
               "In this role he would bring the same approach: find the manual, repetitive work, build the tool "
               "that removes it and measure the result.")
    closing = (f"Someone who designs an assistant like me to run his own job search will bring that instinct to "
               f"{company or 'your team'}. He would welcome a short call about how he can contribute.")
    L = {
        "company": company, "role": role, "score": score, "matched": matched, "total": total,
        "headline": headline,
        "greeting": f"Dear {company} Hiring Team," if company else "Dear Hiring Team,",
        "intro": intro, "pairs": pairs, "achievements": achievements, "skills": skills,
        "background": background, "forward": forward, "closing": closing, "ref": reference_id(job),
    }
    for k in ("headline", "intro", "skills", "background", "forward", "closing"):
        L[k] = _no_dashes(L[k])
    return L


def body_word_count(L: dict) -> int:
    parts = [L["intro"], L["skills"], L["background"], L["forward"], L["closing"]]
    parts += [q + " " + e for q, e in L["pairs"]] + L["achievements"]
    return sum(len(p.split()) for p in parts if p)


def _ascii(text: str) -> str:
    text = (text.replace("ł", "l").replace("Ł", "L").replace("—", "-").replace("–", "-").replace("’", "'")
            .replace("“", '"').replace("”", '"').replace("→", "->").replace("•", "-"))
    return unicodedata.normalize("NFKD", text).encode("latin-1", "ignore").decode("latin-1")


def _render(L: dict, scale: float):
    """PDF'i verilen yazı ölçeğiyle çizer; FPDF nesnesini döner (henüz yazmadan)."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_margins(20, 15, 20)
    pdf.set_auto_page_break(True, margin=12)
    pdf.set_title(f"Cover Letter - {L['role']}" + (f" - {L['company']}" if L["company"] else ""))
    pdf.set_author(P.NAME)
    pdf.set_subject(f"Application for {L['role']}")
    pdf.set_keywords(", ".join([L["role"], L["company"]] + L["matched"] + ["cover letter", P.NAME]))
    pdf.set_creator(f"{P.ASSISTANT_NAME} (Python, offline AI)")
    pdf.add_page()

    font, conv, has_italic = "helvetica", _ascii, True
    for reg, bold, ital in FONT_CANDIDATES:
        if os.path.exists(reg) and os.path.exists(bold):
            pdf.add_font("body", "", reg)
            pdf.add_font("body", "B", bold)
            has_italic = os.path.exists(ital)
            if has_italic:
                pdf.add_font("body", "I", ital)
            font, conv = "body", (lambda t: t)
            break
    italic = "I" if has_italic else ""
    w = pdf.epw
    s = scale

    def para(text, size=10, style="", color=(0, 0, 0), lh=5.0, after=2.2, indent=0):
        if not text:
            return
        pdf.set_font(font, style, size * s)
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(w - indent, lh * s, conv(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(after * s)

    # Başlık
    pdf.set_font(font, "B", 20 * s)
    pdf.set_text_color(*ACCENT)
    pdf.cell(w, 9 * s, conv(P.NAME), new_x="LMARGIN", new_y="NEXT")
    para("  |  ".join(x for x in [P.LOCATION, P.EMAIL, P.PHONE, P.LINKEDIN] if x), size=8.8, color=MUTED,
         lh=4.5, after=0.5)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.l_margin + w, pdf.get_y() + 1)
    pdf.ln(4 * s)

    para(f"{date.today():%d %B %Y}   ·   Ref: {L['ref']}", size=8.8, color=MUTED, lh=4.5, after=1.2)
    para(f"Application: {L['role']}" + (f" at {L['company']}" if L["company"] else ""), size=12, style="B",
         lh=6, after=0.4)
    para(L["headline"], size=9.5, style=italic, color=ACCENT, lh=4.8, after=2.4)
    para(L["greeting"], size=10)
    para(L["intro"], size=10)

    if len(L["pairs"]) >= 2:
        para("Your requirements, his evidence", size=10.5, style="B", color=ACCENT, lh=5.5, after=1.2)
        for req, ev in L["pairs"]:
            y0 = pdf.get_y()
            para(f"\u201c{req}\u201d" if conv is not _ascii else f'"{req}"', size=9.3, style=italic,
                 color=MUTED, lh=4.6, after=0.6, indent=5)
            para(f"\u2192 {ev}" if conv is not _ascii else f"-> {ev}", size=9.6, lh=4.8, after=2.0, indent=5)
            pdf.set_draw_color(*ACCENT)
            pdf.set_line_width(0.8)
            pdf.line(pdf.l_margin + 1.5, y0 + 0.5, pdf.l_margin + 1.5, pdf.get_y() - 2.0 * s)
    else:
        para("What he has already delivered", size=10.5, style="B", color=ACCENT, lh=5.5, after=1.2)
        for a in L["achievements"]:
            para(("\u2022 " if conv is not _ascii else "- ") + a, size=9.6, lh=4.8, after=1.2, indent=4)
        pdf.ln(0.8 * s)

    para(L["skills"], size=10)
    para(L["background"], size=10)
    para(L["forward"] + " " + L["closing"], size=10)

    para("Kind regards,", size=10, after=0.5)
    para(f"{P.ASSISTANT_NAME}, on behalf of {P.NAME}", size=10, style="B", after=3)

    # ALgpt Match Report kutusu
    box_h = 16 * s
    x0, y0 = pdf.l_margin, pdf.get_y()
    pdf.set_fill_color(240, 245, 252)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.3)
    pdf.rect(x0, y0, w, box_h, style="DF")
    pdf.set_xy(x0 + 4, y0 + 2.5 * s)
    pdf.set_font(font, "B", 9 * s)
    pdf.set_text_color(*ACCENT)
    pdf.cell(60, 4.5 * s, conv(f"{P.ASSISTANT_NAME} MATCH REPORT"))
    bar_x, bar_w = x0 + 62, 60
    pdf.set_fill_color(210, 220, 235)
    pdf.rect(bar_x, y0 + 3 * s, bar_w, 3.2 * s, style="F")
    pdf.set_fill_color(*ACCENT)
    pdf.rect(bar_x, y0 + 3 * s, bar_w * L["score"] / 100, 3.2 * s, style="F")
    pdf.set_xy(bar_x + bar_w + 3, y0 + 2.5 * s)
    pdf.cell(30, 4.5 * s, conv(f"{L['score']}/100"))
    pdf.set_xy(x0 + 4, y0 + 8 * s)
    pdf.set_font(font, "", 8 * s)
    pdf.set_text_color(*MUTED)
    skills_line = (f"Skills matched: {len(L['matched'])}/{L['total']} ({', '.join(L['matched'])})"
                   if L["total"] >= 2 and L["matched"] else "Scored on role fit, skills and seniority")
    pdf.multi_cell(w - 8, 3.8 * s, conv(
        f"{skills_line}. Generated for this posting by {P.ASSISTANT_NAME}, a Python pipeline (Playwright, offline "
        f"embedding model) that Alperen built. Every statement comes from his CV."), new_x="LMARGIN", new_y="NEXT")
    return pdf


def verify_letter_pdf(path: str, L: dict) -> list:
    """PDF'i bir ATS gibi oku: tek sayfa mı, pozisyon/şirket/beceriler metinde okunuyor mu? Sorun listesi döner."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(path)
        text = " ".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        return [f"PDF okunamadı: {e}"]
    fold = lambda t: re.sub(r"\s+", " ", unicodedata.normalize("NFKC", t)).lower()
    text = fold(text)
    problems = []
    if len(reader.pages) != 1:
        problems.append(f"{len(reader.pages)} sayfa (1 olmalı)")
    for label, needle in [("pozisyon", L["role"]), ("şirket", L["company"])] + [("beceri", m) for m in L["matched"][:5]]:
        if needle and fold(needle)[:40] not in text:
            problems.append(f"{label} metinde okunamıyor: {needle!r}")
    if CLICHES.search(text):
        problems.append("klişe ifade var")
    return problems


def write_letter_pdf(job: dict, result: dict, matcher=None, out_dir: str | None = None) -> str:
    L = build_letter(job, result, matcher)
    # Kelime bütçesi: aşılırsa önce en uzun kanıt çiftini, sonra başarı maddesini çıkar.
    while body_word_count(L) > MAX_BODY_WORDS and (len(L["pairs"]) > 2 or len(L["achievements"]) > 2):
        if len(L["pairs"]) > 2:
            L["pairs"] = L["pairs"][:-1]
        else:
            L["achievements"] = L["achievements"][:-1]

    base = out_dir or os.path.join(OUTPUT_DIR, date.today().isoformat())
    folder = os.path.join(base, L["ref"])  # her ilana ayrı klasör: aynı pozisyon adları çakışmasın
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, letter_filename(job))

    # Tek sayfa zorunlu: sığmazsa yazıyı küçülterek yeniden çiz.
    for scale in (1.0, 0.95, 0.9, 0.85):
        pdf = _render(L, scale)
        if pdf.page_no() == 1:
            break
    pdf.output(path)
    problems = verify_letter_pdf(path, L)
    if problems:
        print(f"   ⚠️ Mektup ATS kontrolü ({os.path.basename(path)}): " + "; ".join(problems))
    return path
