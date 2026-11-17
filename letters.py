"""İlana özel cover letter (PDF), Alperen'in kendi ağzından.

Kurallar (ALPEREN_COVER_LETTER_FEEDBACK.md'ye göre):
  * Birinci tekil şahıs, Alperen imzalı. Asistan/bot, puan, "match report" kutusu, teknik terim
    (Playwright, model adı...) YOK.
  * İlk paragraf ilk eleme filtresini geçirenle başlar: anadil Türkçe (ilan Türkçe istiyorsa),
    C1 İngilizce, çalışma izni gerekmiyor, Amazon'da 2 yıl compliance.
  * Başlıktaki ana alan CV'de yoksa (ör. payroll) bu açıkça söylenir; o alanla ilgili şartlar
    zayıf kanıtla eşleştirilmez, aktarılabilir deneyim gösterilir.
  * "Şartınız → deneyimim" düzeni korunur; kanıt yoksa şart hiç yazılmaz.
  * Kendi yaptığı iş arama aracı yalnızca bir cümleyle, sona yakın anılır.
  * B2 seviyesinde sade İngilizce; ilanlar arasında cümleler değişir (hepsi aynı şablon gibi
    görünmesin); yapay zekâ metinlerine özgü kalıp ifadeler (delve, passionate, leverage...)
    üretimden sonra PDF'te aranır.
ATS: gerçek metin PDF, standart font, tek sütun, tek sayfa; pozisyon ve şirket adı birebir;
eşleşen beceriler metinde; PDF meta verisi dolu. Her iddia profile_data.py'den (CV) gelir.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import date

import profile_data as P
from matcher import domain_gap, gap_pattern

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "letters")
ACCENT = (23, 92, 168)
MUTED = (95, 95, 95)
MAX_BODY_WORDS = 320  # başlık/iletişim hariç gövde

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
OWN_SITES = {"amazon", "revolut", "ikea"}  # şirketin kendi kariyer sayfası (eski klasörler)

PRETTY = {"sql": "SQL", "vba": "VBA", "sop": "SOPs", "fastapi": "FastAPI", "databricks": "Databricks", "etl": "ETL",
          "ci/cd": "CI/CD", "vs code": "VS Code", "github": "GitHub", "android studio": "Android Studio",
          "claude code": "Claude Code", "chatgpt": "ChatGPT", "claude": "Claude",
          "power bi": "Power BI", "javascript": "JavaScript",
          "html": "HTML", "css": "CSS", "git": "Git", "jira": "Jira", "python": "Python", "excel": "Excel",
          "kotlin": "Kotlin", "llm": "LLMs", "ai": "AI", "kanban": "Kanban", "agile": "Agile", "lean": "Lean",
          "root cause analysis": "root cause analysis", "compliance": "compliance", "audit": "audit"}
TOOLS_FIRST = ["Python", "SQL", "Power BI", "Excel", "VBA", "ETL", "Databricks", "FastAPI", "JavaScript", "Kotlin",
               "Jira", "Git", "root cause analysis", "audit", "compliance"]
# Teknik rollerde araç biraz daha açık anlatılır; diğerlerinde tek cümle.
TECH_ROLE = re.compile(r"\b(data|analyst|analytics|automation|developer|engineer|python|software|programmer|"
                       r"bi|ai|machine learning|qa|test\w*)\b", re.I)
CLICHES = re.compile(r"passionate|hit the ground running|leverag|synerg|team player|go-getter|think outside", re.I)
# Yapay zekâ metinlerinde sık görülen, insan yazısında nadir kalıplar. Mektupta hiçbiri olmamalı.
AI_TELLS = re.compile(
    r"\bdelv\w*|\bthrilled\b|\bexcited to\b|\beager to\b|\bdynamic\b|fast-paced|\bfurthermore\b|\bmoreover\b|"
    r"\badditionally\b|i am confident|\bseamless\w*|\brobust\b|\btestament\b|\bspearhead\w*|\bhoned\b|\brealm\b|"
    r"\btapestry\b|cutting-edge|\bunwavering\b|in today's|\bjourney\b|\binvaluable\b|\bmeticulous\w*|"
    r"\bnavigat\w* the\b|\bfoster\w*\b|\bempower\w*\b|\bholistic\b|\bplethora\b|\bkeen interest\b|"
    r"\bperfect fit\b|\bideal candidate\b|\buniquely\b|\bsynergy\b|\bstrive\b|\bwell-versed\b",
    re.I)
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve"]


def _clean_company(company: str) -> str:
    c = (company or "").strip()
    return "" if c.lower() in {"", "unknown", "see link", "see job link", "confidential"} else c


def _join(items: list) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _num(n: int) -> str:
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else str(n)


def _slug(s: str, n: int = 60) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-")


def letter_filename(job: dict) -> str:
    """alperen-simsek-<pozisyon>-letter.pdf"""
    title = re.sub(r"\((?:[mkfwdx]\s*/\s*)+[mkfwdx]\)|\b[mkf]/[mkf](?:/[dx])?\b", "", job.get("title") or "")
    return f"{_slug(P.NAME)}-{_slug(title) or 'position'}-letter.pdf"


def reference_id(job: dict) -> str:
    """Yalnızca klasör adı için (aynı isimli pozisyonlar çakışmasın); mektupta görünmez."""
    h = hashlib.sha1(f"{job.get('url')}|{job.get('title')}".encode()).hexdigest()[:6].upper()
    return f"{date.today():%Y%m%d}-{h}"


EMOJI_RE = re.compile("[🀀-🫿☀-➿️‍⬀-⯿]")


def _strip_emoji(text: str) -> str:
    """İlan başlıklarındaki emojiler PDF fontunda yok (boş kutu çıkar): temizle."""
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", text or "")).strip()


def _no_dashes(text: str) -> str:
    """Yazım kuralı: uzun tire yok (virgül ile değiştir)."""
    return re.sub(r"\s*[—–]\s*", ", ", text)


def _where(job: dict) -> str:
    site = (job.get("site") or "").lower()
    if job.get("company_site") or site in OWN_SITES:
        return "on your careers page"
    return f"on {SITE_NAMES[site]}" if site in SITE_NAMES else ""


def _short_quote(text: str, limit: int = 115) -> str:
    """İlandan alıntı: uzunsa kelime sınırında kısalt (uzun alıntı şablon gibi görünür)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def build_letter(job: dict, result: dict, matcher=None) -> dict:
    company = _strip_emoji(_clean_company(job.get("company")))
    role = _strip_emoji(job.get("title") or "") or "this position"
    at = f" at {company}" if company else ""
    where = _where(job)
    matched = [PRETTY.get(s, s) for s in result.get("matched_skills", [])]
    matched = sorted(matched, key=lambda m: TOOLS_FIRST.index(m) if m in TOOLS_FIRST else 99)[:8]
    total = result.get("skill_total", 0)
    turkish = bool(re.search(r"\bturkish\b", f"{role} {job.get('description', '')}", re.I))
    gap = result.get("gap") or domain_gap(role)
    tech = bool(TECH_ROLE.search(role)) and not gap

    # Aynı ilan hep aynı mektubu alır; farklı ilanlar farklı cümle kombinasyonları.
    seed = int(hashlib.sha1(f"{job.get('url')}|{role}".encode()).hexdigest(), 16)

    def pick(options: list, slot: int) -> str:
        return options[(seed >> (slot * 5)) % len(options)]

    # 1) Açılış: pozisyon + ilk filtreyi geçirenler
    first = pick([
        f"I am applying for the {role} position{at}" + (f", which I found {where}" if where else "") + ".",
        f"I would like to apply for the {role} role{at}" + (f" that I saw {where}" if where else "") + ".",
        f"I'm writing to apply for the {role} job{at}" + (f", which I came across {where}" if where else "") + ".",
    ], 0)
    amazon = pick([
        "I spent two years at Amazon Corporate Services Poland as a Compliance Associate, checking products "
        "against EMEA and US regulations and safety standards, so accuracy was part of my daily work.",
        "I worked for two years at Amazon Corporate Services Poland as a Compliance Associate. I reviewed "
        "products against EMEA and US rules every day, and getting the details right was a normal part of "
        "the job.",
    ], 1)
    if turkish:
        langs = pick([
            "I'm a native Turkish speaker with C1 English, and I don't need a work permit in Poland.",
            "Turkish is my native language, my English is at C1 level, and I can work in Poland without a "
            "work permit.",
        ], 2)
        opening = f"{first} {langs} {amazon}"
    else:
        langs = pick([
            "My English is at C1 level, Turkish is my native language, and I don't need a work permit in Poland.",
            "I speak English at C1 level and I can work in Poland without a work permit, as I graduated from a "
            "Polish university.",
        ], 2)
        opening = f"{first} {amazon} {langs}"

    # 2) Şartlar → kanıt (CV'nin cevaplayamadığı alan şartları atlanır)
    pairs = matcher.match_requirements(job, skip=gap_pattern(gap)) if matcher else []
    achievements = []
    if len(pairs) < 2:
        pairs = []
        if matcher is not None:
            _, vec = matcher.semantic(job)
            idx = [P.ACHIEVEMENTS.index(a) for a in matcher.best_achievements(vec, n=3)]
        else:
            idx = [0, 1, 2]
        achievements = [P.EVIDENCE_FIRST[i] for i in idx]

    if gap:
        lead_in = pick([
            f"I have not worked in {gap} before, and I want to be clear about that. What I do bring is the work "
            f"around it:",
            f"To be honest, I haven't worked in {gap} yet. A lot of what this role needs, though, is close to what "
            f"I did every day:",
            f"I should say openly that I have no direct {gap} experience. Here is what I can bring instead:",
        ], 3)
    elif pairs:
        lead_in = pick([
            "Here is how my experience matches what you are looking for:",
            "A few points from your posting, and what I have done in each area:",
            "Looking at your requirements, this is where my experience fits:",
        ], 3)
    else:
        lead_in = pick([
            "A few things I have done that are relevant here:",
            "Some examples of my work that fit this role:",
        ], 3)

    # 3) Beceri sayısı: puan yerine sayılan şeyin kendisi ("8 beceriden 6'sı")
    skills = ""
    if total >= 4 and len(matched) >= 2 and len(matched) / total >= 0.4:
        top = _join(matched[:3])
        skills = pick([
            f"From the skills and tools in your posting, I already use {_num(len(matched))} of the {_num(total)} "
            f"in my work, including {top}.",
            f"I already work with {_num(len(matched))} of the {_num(total)} skills you list, for example {top}.",
        ], 4)

    # 4) Eğitim + araç (tek cümle, sona yakın)
    edu = pick([f"I hold {P.EDUCATION}.", f"I have {P.EDUCATION}."], 5)
    tool = pick([
        "Outside work I keep building small tools in Python, and one of them is the job-search assistant that "
        "found this posting for me.",
        "I like to automate my own routine too: I found this posting with a small job-search tool I wrote myself.",
    ] if tech else [
        "I tend to notice repetitive work and build something that removes it. I even found this role with a "
        "job-search assistant I built myself.",
        "I like finding repetitive tasks and making them simpler, and I found this role with a small job-search "
        "tool I built myself.",
    ], 6)
    background = f"{edu} {tool}"

    closing = pick([
        "I would welcome a short call to talk about the role. Thank you for your time.",
        "I'd be glad to discuss the role in a short call. Thank you for reading my application.",
        f"If you think my background could help {company or 'your team'}, I would be happy to talk. Thank you for "
        f"your time.",
    ], 7)

    L = {
        "company": company, "role": role, "matched": matched, "total": total, "gap": gap, "turkish": turkish,
        "greeting": f"Dear {company} Hiring Team," if company else "Dear Hiring Manager,",
        "opening": opening, "lead_in": lead_in, "pairs": pairs, "achievements": achievements,
        "skills": skills, "background": background, "closing": closing, "ref": reference_id(job),
    }
    for k in ("opening", "lead_in", "skills", "background", "closing"):
        L[k] = _no_dashes(L[k])
    L["pairs"] = [(q, _no_dashes(e)) for q, e in L["pairs"]]
    return L


def letter_text(L: dict) -> str:
    """Mektubun düz metni (kontroller ve testler için)."""
    parts = [L["greeting"], L["opening"], L["lead_in"]]
    parts += [f'"{_short_quote(q)}" {e}' for q, e in L["pairs"]] + L["achievements"]
    parts += [L["skills"], L["background"], L["closing"], "Kind regards,", P.NAME]
    return "\n".join(p for p in parts if p)


def body_word_count(L: dict) -> int:
    parts = [L["opening"], L["lead_in"], L["skills"], L["background"], L["closing"]]
    parts += [_short_quote(q) + " " + e for q, e in L["pairs"]] + L["achievements"]
    return sum(len(p.split()) for p in parts if p)


def _ascii(text: str) -> str:
    text = (text.replace("ł", "l").replace("Ł", "L").replace("—", "-").replace("–", "-").replace("’", "'")
            .replace("“", '"').replace("”", '"').replace("→", "->").replace("•", "-"))
    return unicodedata.normalize("NFKD", text).encode("latin-1", "ignore").decode("latin-1")


def _render(L: dict, scale: float):
    """PDF'i verilen yazı ölçeğiyle çizer; FPDF nesnesini döner (henüz yazmadan)."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_margins(22, 16, 22)
    pdf.set_auto_page_break(True, margin=12)
    pdf.set_title(f"Cover Letter - {L['role']}" + (f" - {L['company']}" if L["company"] else ""))
    pdf.set_author(P.NAME)
    pdf.set_subject(f"Application for {L['role']}")
    pdf.set_keywords(", ".join([L["role"], L["company"]] + L["matched"] + ["cover letter", P.NAME]))
    pdf.set_creator(P.NAME)
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

    def para(text, size=10.5, style="", color=(0, 0, 0), lh=5.3, after=2.6, indent=0):
        if not text:
            return
        pdf.set_font(font, style, size * s)
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(w - indent, lh * s, conv(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(after * s)

    # Başlık: ad + iletişim
    pdf.set_font(font, "B", 19 * s)
    pdf.set_text_color(*ACCENT)
    pdf.cell(w, 9 * s, conv(P.NAME), new_x="LMARGIN", new_y="NEXT")
    para("  |  ".join(x for x in [P.LOCATION, P.EMAIL, P.PHONE, P.LINKEDIN, P.GITHUB] if x), size=8.6, color=MUTED,
         lh=4.5, after=0.5)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.l_margin + w, pdf.get_y() + 1)
    pdf.ln(5 * s)

    para(f"{date.today():%d %B %Y}", size=9.5, color=MUTED, lh=4.6, after=2.0)
    para(f"Application for {L['role']}" + (f", {L['company']}" if L["company"] else ""), size=11.5, style="B",
         lh=6, after=3.0)
    para(L["greeting"])
    para(L["opening"])
    para(L["lead_in"], after=1.8)

    if L["pairs"]:
        for req, ev in L["pairs"]:
            y0 = pdf.get_y()
            q = _short_quote(req)
            para(f"\u201c{q}\u201d" if conv is not _ascii else f'"{q}"', size=9.6, style=italic,
                 color=MUTED, lh=4.7, after=0.6, indent=5)
            para(ev, size=10.2, lh=5.0, after=2.2, indent=5)
            pdf.set_draw_color(*ACCENT)
            pdf.set_line_width(0.7)
            pdf.line(pdf.l_margin + 1.5, y0 + 0.5, pdf.l_margin + 1.5, pdf.get_y() - 2.2 * s)
    else:
        for a in L["achievements"]:
            para(("\u2022 " if conv is not _ascii else "- ") + a, size=10.2, lh=5.0, after=1.6, indent=4)
        pdf.ln(0.8 * s)

    para(L["skills"])
    para(L["background"])
    para(L["closing"], after=4)

    para("Kind regards,", after=0.8)
    para(P.NAME, style="B", after=0)
    return pdf


def verify_letter_pdf(path: str, L: dict) -> list:
    """PDF'i bir ATS gibi oku: tek sayfa mı, pozisyon/şirket/beceriler okunuyor mu, yapay zekâ kalıbı var mı?"""
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
    for label, needle in [("pozisyon", L["role"]), ("şirket", L["company"])]:
        if needle and fold(needle)[:40] not in text:
            problems.append(f"{label} metinde okunamıyor: {needle!r}")
    if CLICHES.search(text):
        problems.append("klişe ifade var")
    m = AI_TELLS.search(text)
    if m:
        problems.append(f"yapay zekâ kalıbı: {m.group(0)!r}")
    if re.search(r"algpt|/100\b|match report|playwright|bge-small", text):
        problems.append("bot/puan/teknik detay mektupta görünüyor")
    return problems


def write_letter_pdf(job: dict, result: dict, matcher=None, out_dir: str | None = None) -> str:
    L = build_letter(job, result, matcher)
    # Kelime bütçesi: aşılırsa önce son kanıt çiftini, sonra başarı maddesini çıkar.
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
        print(f"   ⚠️ Mektup kontrolü ({os.path.basename(path)}): " + "; ".join(problems))
    return path
