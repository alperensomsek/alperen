"""İlan eleme ve puanlama.

Akış:
  1. title_prefilter()  -> sadece başlığa bakar; detay sayfası açılmadan önce
                           kesin uymayanları atar (zaman/kota tasarrufu).
  2. hard_reject()      -> tam metin kuralları: dil, Lehçe şartı, tecrübe yılı,
                           istenmeyen teknoloji, staj, anti-bot sayfası.
  3. matcher.score()    -> çevrimdışı AI modeli + beceri karşılama oranı (matcher.py).
"""
from __future__ import annotations

import re

from config import BLACK_LIST_COMPANIES, MAX_YEARS_EXPERIENCE
from matcher import JobMatcher

# ---------------------------------------------------------------------------
# Kural tabloları
# ---------------------------------------------------------------------------
# Başlıkta geçerse kesin ret (üst düzey kıdem).
SENIOR_TITLE_RE = re.compile(
    r"\b(lead|leader|head|director|principal|manager|managing|vp|vice president|chief|"
    r"c[eft]o|architect|staff engineer|expert|partner|supervisor|team ?leader)\b",
    re.I,
)
INTERN_TITLE_RE = re.compile(r"\b(intern|internship|trainee|praktykant\w*|sta[żz]\w*|student\w*|apprentice)\b", re.I)

# İstenmeyen teknolojiler. (Önceki sürümdeki r'\bc\+\+\b' ve r'\b\.net\b' asla eşleşmiyordu.)
EXCLUDED_TECH = {
    "Java": r"\bjava\b(?!\s*script)",
    "C++": r"(?<![\w])c\+\+",
    "C#": r"(?<![\w])c#(?![\w])",
    ".NET": r"(?<![\w])\.net\b|\basp\.net\b|\bdotnet\b",
    "Spring": r"\bspring\s*(boot|framework|mvc)\b",
    "Go": r"\bgolang\b",
    "Rust": r"\brust\b",
    "PHP": r"\bphp\b",
    "Ruby": r"\bruby\b",
    "Flutter": r"\bflutter\b",
    "Angular": r"\bangular(js)?\b",
    "React": r"\breact(\.?js)?\b(?!\s+(to|quickly|fast|promptly|appropriately))",
    "Salesforce": r"\bsalesforce\b",
    "SAP": r"\bsap\b",
}

# Ret sebebi olan yabancı diller (İngilizce ve Türkçe hariç her şey).
BANNED_LANGUAGES = [
    "german", "deutsch", "french", "italian", "spanish", "dutch", "portuguese", "czech",
    "slovak", "hungarian", "romanian", "swedish", "norwegian", "danish", "finnish",
    "greek", "hebrew", "arabic", "russian", "ukrainian", "japanese", "chinese",
    "mandarin", "korean", "bulgarian", "croatian", "serbian", "lithuanian", "latvian", "estonian",
]
# Dil adının yakınında bunlardan biri varsa "şart" sayılır...
LANG_REQUIREMENT_RE = re.compile(
    r"\b(b2|c1|c2|fluent|fluency|native|proficien\w*|advanced|very good|excellent|"
    r"business[- ]level|communicative|spoken|written|speaking|speaker|language skills?|"
    r"required|must|mandatory|essential|biegł\w*|dobra znajomość|bardzo dobra)\b",
    re.I,
)
# ...ama bunlardan biri varsa "artı" sayılır ve ret sebebi değildir.
SOFT_CONTEXT_RE = re.compile(
    r"(nice to have|is a plus|would be a plus|an? (advantage|asset|plus)|advantageous|"
    r"beneficial|preferred|desirable|optional|bonus|mile widzian\w*|atut\w*)",
    re.I,
)

ELIGIBILITY_PATTERN = (
    r"\b(eu|e\.u\.|european union|eea|polish|uk|us|u\.s\.) (citizenship|citizens?|nationals?|passport)\b"
    r"|\bsecurity clearance\b|\bnato (secret|clearance)\b|\bpoświadczeni\w* bezpieczeństwa\b"
    r"|\bobywatelstw\w* polskie\w*\b|\bcitizenship (is )?(required|mandatory)\b"
)
ENGLISH_STOPWORDS = set("the and to of a in for with you we our will is are on as be your this that or an at by from have".split())
POLISH_STOPWORDS = set("i w z na się sie do dla oraz jest że ze nie od jak po przez lub są sa który ktory która ktora naszego twój nasz będzie bedzie".split())
# "de/da/en" bilerek yok: İspanyolca/Fransızcada da çok sık geçiyorlar.
TURKISH_STOPWORDS = set("ve bir için ile bu olarak çok veya olan iş deneyim aranan ilgili sahip tercihen".split())
POLISH_CHARS_RE = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
LETTERS_RE = re.compile(r"[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
YEARS_RE = re.compile(
    r"(?:at least|min(?:imum|\.)?|over|more than)?\s*(\d{1,2})\s*(?:\+|-|–|to)?\s*(\d{1,2})?\s*\+?\s*"
    r"(?:years?|yrs?)",
    re.I,
)


def _windows(text: str, pattern: str, before: int = 70, after: int = 70):
    for m in re.finditer(pattern, text, re.I):
        yield text[max(0, m.start() - before): m.end() + after], m


def _is_required(window: str) -> bool:
    return bool(LANG_REQUIREMENT_RE.search(window)) and not SOFT_CONTEXT_RE.search(window)


class JobAnalyzer:
    def __init__(self, matcher: JobMatcher | None = None):
        self.matcher = matcher or JobMatcher()

    # ------------------------------------------------------------------
    # 1) Başlık ön filtresi (detay sayfası açılmadan önce)
    # ------------------------------------------------------------------
    def title_prefilter(self, title: str) -> str:
        """Ret sebebi döner; uygunsa boş string."""
        t = title or ""
        m = SENIOR_TITLE_RE.search(t)
        if m:
            return f"Seniority in title ({m.group(0)})"
        m = INTERN_TITLE_RE.search(t)
        if m:
            return f"Intern/student role ({m.group(0)})"
        for name, pat in EXCLUDED_TECH.items():
            if re.search(pat, t, re.I):
                return f"Excluded tech in title ({name})"
        for lang in BANNED_LANGUAGES:
            if re.search(rf"\b{lang}\b", t, re.I):
                return f"Foreign language in title ({lang})"
        return ""

    # ------------------------------------------------------------------
    # 2) Tam metin kesin ret kuralları
    # ------------------------------------------------------------------
    def hard_reject(self, job: dict) -> str:
        title = job.get("title", "")
        desc = job.get("description", "")
        company = (job.get("company") or "").lower()
        text = f"{title}\n{desc}"

        if company and any(b.lower() in company for b in BLACK_LIST_COMPANIES):
            return f"Blacklisted company ({job.get('company')})"

        reason = self.title_prefilter(title)
        if reason:
            return reason

        if len(desc) < 1500 and re.search(r"captcha|security (check|verification)|verify(ing)? you are (a )?human|access denied|cloudflare|additional verification required|just a moment", desc, re.I):
            return "Anti-bot / blocked page"

        # İlan Lehçe yazılmış mı? İki sinyal: Lehçe karakter oranı ve bağlaç (stopword) dengesi.
        # Sitenin Lehçe arayüz etiketleri ("Obowiązkowe", "Mile widziane") bağlaç içermez,
        # bu yüzden İngilizce ilan metni + Lehçe menü yanlışlıkla elenmez.
        letters = len(LETTERS_RE.findall(desc)) or 1
        pl_ratio = len(POLISH_CHARS_RE.findall(desc)) / letters
        words = re.findall(r"[a-ząćęłńóśźżçğıöşü]+", desc.lower())
        n = len(words) or 1
        en = sum(w in ENGLISH_STOPWORDS for w in words) / n
        pl = sum(w in POLISH_STOPWORDS for w in words) / n
        tr = sum(w in TURKISH_STOPWORDS for w in words) / n
        if len(words) >= 40 and (pl > en or (pl_ratio > 0.02 and pl > en * 0.5)):
            return f"Polish-language posting (PL stopwords {pl:.0%} vs EN {en:.0%})"

        # Uygunluk kapısı (ai-job-search'ten): vatandaşlık / güvenlik izni şartı = ret.
        # Alperen Türk vatandaşı; Polonya diploması sayesinde çalışma izninden muaf ama
        # "EU citizen only" veya güvenlik izni isteyen ilanlara başvuramaz.
        for window, m in _windows(text, ELIGIBILITY_PATTERN, before=40, after=40):
            if not SOFT_CONTEXT_RE.search(window) and not re.search(r"\bnot (required|necessary)\b|\bno need\b", window, re.I):
                return f"Eligibility: requires {m.group(0).strip()}"

        # İlan İngilizce veya Türkçe değilse (İspanyolca, Almanca... ilanlar) ret.
        if len(words) >= 80:
            if en < 0.06 and tr < 0.04:
                return f"Posting not in English/Turkish (EN stopwords {en:.0%})"

        # Lehçe şartı (B2/C1/fluent...). "Polish is a plus" ret sebebi değil.
        for window, _ in _windows(text, r"\b(polish|polski\w*)\b", before=45, after=35):
            if _is_required(window):
                return "Requires Polish language"

        for lang in BANNED_LANGUAGES:
            for window, _ in _windows(text, rf"\b{lang}\b", before=45, after=35):
                if _is_required(window) or re.search(rf"\b(with|speaking|-speaking)\s+{lang}\b|\b{lang}[- ]speak", window, re.I):
                    return f"Requires foreign language ({lang})"

        # İstenmeyen teknoloji: "nice to have" bağlamında değilse ret.
        for name, pat in EXCLUDED_TECH.items():
            for window, _ in _windows(desc, pat, before=60, after=40):
                if not SOFT_CONTEXT_RE.search(window):
                    return f"Excluded tech stack ({name})"

        years = self.required_years(text)
        if years is not None and years > MAX_YEARS_EXPERIENCE:
            return f"Requires {years}+ years of experience"

        return ""

    @staticmethod
    def required_years(text: str):
        """'3-5 years of experience' -> 3, 'at least 5 years' -> 5. Bulamazsa None."""
        found = []
        for m in YEARS_RE.finditer(text):
            ctx = text[m.start(): m.end() + 60].lower()
            if "experience" not in ctx and "exp." not in ctx and "background" not in ctx:
                continue
            if SOFT_CONTEXT_RE.search(text[max(0, m.start() - 40): m.end() + 60]):
                continue
            lo = int(m.group(1))
            if 0 < lo <= 15:  # "20 years of experience in the market" = şirket tanıtımı
                found.append(lo)
        return max(found) if found else None

    # ------------------------------------------------------------------
    def evaluate_job(self, job: dict) -> dict:
        reason = self.hard_reject(job)
        if reason:
            return {"match_score": 0, "reason": f"HARD REJECT: {reason}", "matched_skills": [],
                    "missing_skills": [], "skill_total": 0, "job_vec": None, "engine": "rules"}
        years = self.required_years(job.get("title", "") + "\n" + job.get("description", ""))
        return self.matcher.score(job, required_years=years)
