"""Kalıcı hafıza: hangi ilanlar tarandı, hangileri Telegram'a gönderildi.

Tek dosya: state.json
{
  "version": 2,
  "seen": {"<kanonik-url>": "2026-11-14", ...},       # taranan ilanlar (TTL ile silinir)
  "sent": {"<parmak-izi>": {"title":..,"company":..,"url":..,"date":..}, ...}
}

Neden böyle?
- Siteler aynı ilanın URL'sine her gün farklı takip parametreleri ekliyor
  (?refId=, ?trackingId=, utm_...). canonical_url() bunları atıp ilanın gerçek
  kimliğini çıkarır (LinkedIn ilan no, Indeed jk=, Talent id= ...).
- Aynı ilan farklı URL ile tekrar yayınlanabiliyor. Bu yüzden Telegram'a
  gönderilenler ayrıca "normalize başlık + şirket" parmak iziyle tutulur.
- Kayıtlar tarih taşır ve TTL dolunca silinir; dosya şişmez.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

STATE_FILE = "state.json"
# STATE_KEY tanımlıysa hafıza şifreli tutulur (public repo'da başvuru geçmişin okunamasın).
STATE_KEY = os.getenv("STATE_KEY", "").strip()
LEGACY_SEEN_FILE = "seen_jobs.json"
LEGACY_SENT_LOG = "sent_messages.txt"

UNKNOWN_COMPANIES = {"", "see link", "see job link", "seelink", "unknown", "unknown company", "n/a"}

# ---------------------------------------------------------------------------
# URL kanonikleştirme
# ---------------------------------------------------------------------------
# Bu sitelerde ilan kimliği query string içinde durur; query'yi atarsak
# bütün ilanlar aynı URL'ye düşer. Diğer sitelerde query tamamen atılır.
_ID_PARAMS = {
    "indeed.": ("jk", "vjk"),
    "talent.com": ("id",),
    "glassdoor.": ("jobListingId", "jl"),
}


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")
    query = parse_qs(parts.query)

    # LinkedIn: /jobs/view/4385500765 veya /jobs/view/python-dev-at-x-4385500765
    if "linkedin.com" in host:
        m = re.search(r"/jobs/view/(?:[^/]*?-)?(\d{6,})", path)
        if m:
            return f"linkedin.com/jobs/view/{m.group(1)}"
        if "currentJobId" in query:
            return f"linkedin.com/jobs/view/{query['currentJobId'][0]}"

    # Europelanguagejobs: ilanların linki yok; kimlik URL fragment'ında (#ilan-basligi)
    if "europelanguagejobs" in host and parts.fragment:
        return f"{host}{path}#{parts.fragment}"

    # CareersInPoland: /job/539540,title-warszawa ve /job/539540,title aynı ilan
    m = re.match(r"/job/(\d+)", path)
    if m and "careersinpoland" in host:
        return f"{host}/job/{m.group(1)}"

    for host_key, params in _ID_PARAMS.items():
        if host_key in host:
            for p in params:
                if p in query and query[p][0]:
                    return f"{host}/job?{p}={query[p][0]}".replace("vjk=", "jk=").replace("jl=", "jobListingId=")

    return f"{host}{path}"


# ---------------------------------------------------------------------------
# Başlık / şirket parmak izi
# ---------------------------------------------------------------------------
_TITLE_NOISE = re.compile(
    r"\((?:[mkfwdx]\s*/\s*)+[mkfwdx]\)|\b(?:m|k|f|w)/(?:m|k|f|w)(?:/(?:d|x))?\b"
    r"|\b(?:hybrid|remote|on-?site|full[- ]time|part[- ]time|b2b|uop|warsaw|warszawa|poland|polska)\b",
    re.IGNORECASE,
)


def normalize_title(title: str) -> str:
    t = _TITLE_NOISE.sub(" ", (title or "").lower())
    t = re.sub(r"[^a-z0-9ąćęłńóśźżçğıöşü]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_company(company: str) -> str:
    c = (company or "").strip().lower()
    if c in UNKNOWN_COMPANIES:
        return ""
    c = re.sub(r"\b(sp\.?\s*z\s*o\.?\s*o\.?|s\.?a\.?|ltd\.?|llc|inc\.?|gmbh|group|poland|polska)\b", " ", c)
    c = re.sub(r"[^a-z0-9ąćęłńóśźżçğıöşü]+", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def fingerprint(title: str, company: str) -> str:
    return f"{normalize_title(title)}|{normalize_company(company)}"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class JobState:
    def __init__(self, path: str = STATE_FILE, seen_ttl_days: int = 30, sent_ttl_days: int = 120):
        self.path = path
        self.seen_ttl = seen_ttl_days
        self.sent_ttl = sent_ttl_days
        self.today = date.today().isoformat()
        self.seen: dict[str, str] = {}
        self.sent: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}  # baraj geçmiş ama günlük limit yüzünden henüz gönderilmemiş
        self.cursor: int = 0               # Word sırasında kaldığı arama linki
        self._load()
        self._rebuild_title_index()

    # ---- yükleme / göç -------------------------------------------------
    @property
    def enc_path(self) -> str:
        return self.path + ".enc"

    def _read_data(self):
        if STATE_KEY and os.path.exists(self.enc_path):
            from cryptography.fernet import Fernet

            with open(self.enc_path, "rb") as f:
                return json.loads(Fernet(STATE_KEY.encode()).decrypt(f.read()).decode("utf-8"))
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _load(self):
        if os.path.exists(self.path) or (STATE_KEY and os.path.exists(self.enc_path)):
            try:
                data = self._read_data()
                self.seen = dict(data.get("seen", {}))
                self.sent = dict(data.get("sent", {}))
                self.pending = dict(data.get("pending", {}))
                self.cursor = int(data.get("cursor", 0))
                return
            except Exception as e:
                print(f"⚠️ {self.path} okunamadı ({e}); eski dosyalardan yeniden kuruluyor.")
        self._migrate_legacy()

    def _migrate_legacy(self):
        """seen_jobs.json (bozuk olsa bile) ve sent_messages.txt'den state kurar."""
        migrated_seen = migrated_sent = 0
        if os.path.exists(LEGACY_SEEN_FILE):
            with open(LEGACY_SEEN_FILE, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            # Dosya birden fazla JSON listesinin yapışmasıyla bozulmuş olabilir:
            # JSON parse etmek yerine URL'leri doğrudan regex ile topla.
            for url in re.findall(r'"(https?://[^"\s]+)"', raw):
                key = canonical_url(url)
                if key and key not in self.seen:
                    self.seen[key] = self.today
                    migrated_seen += 1
        if os.path.exists(LEGACY_SENT_LOG):
            with open(LEGACY_SENT_LOG, "r", encoding="utf-8", errors="ignore") as f:
                log = f.read()
            for block in log.split("----------------------------------------"):
                title = re.search(r"^Role:\s*(.+)$", block, re.M)
                if not title:
                    continue
                company = re.search(r"^Company:\s*(.+)$", block, re.M)
                url = re.search(r"^URL:\s*(.+)$", block, re.M)
                when = re.search(r"^Date Added:\s*(\d{4}-\d{2}-\d{2})", block, re.M)
                self.sent[fingerprint(title.group(1), company.group(1) if company else "")] = {
                    "title": title.group(1).strip(),
                    "company": company.group(1).strip() if company else "",
                    "url": url.group(1).strip() if url else "",
                    "date": when.group(1) if when else self.today,
                }
                if url:
                    self.seen[canonical_url(url.group(1))] = self.today
                migrated_sent += 1
        if migrated_seen or migrated_sent:
            print(f"🔁 Eski hafıza taşındı: {migrated_seen} taranmış URL, {migrated_sent} gönderilmiş ilan.")

    def _rebuild_title_index(self):
        self._sent_titles = {fp.split("|", 1)[0] for fp in self.sent}

    # ---- seen ------------------------------------------------------------
    def is_seen(self, url: str) -> bool:
        return canonical_url(url) in self.seen

    def mark_seen(self, url: str):
        key = canonical_url(url)
        if key:
            self.seen[key] = self.today

    # ---- sent ------------------------------------------------------------
    def is_sent(self, title: str, company: str) -> bool:
        fp = fingerprint(title, company)
        if fp in self.sent:
            return True
        norm_title = fp.split("|", 1)[0]
        if len(norm_title) < 8:
            return False
        # Şirket bilinmiyorsa (ya da daha önce bilinmeden gönderildiyse) başlık tek başına yeter.
        if not normalize_company(company):
            return norm_title in self._sent_titles
        return f"{norm_title}|" in self.sent

    def mark_sent(self, title: str, company: str, url: str):
        fp = fingerprint(title, company)
        self.sent[fp] = {"title": title, "company": company, "url": url, "date": self.today}
        self._sent_titles.add(fp.split("|", 1)[0])
        self.mark_seen(url)

    # ---- pending (gönderim kuyruğu) ---------------------------------------
    def add_pending(self, job: dict, result: dict):
        key = fingerprint(job.get("title", ""), job.get("company", ""))
        old = self.pending.get(key)
        if old is None or result.get("match_score", 0) > old["result"].get("match_score", 0):
            keep = {k: v for k, v in result.items() if k != "job_vec"}
            self.pending[key] = {"job": job, "result": keep, "date": self.today}

    def pop_pending(self, key: str):
        self.pending.pop(key, None)

    # ---- bakım -----------------------------------------------------------
    def prune(self, pending_ttl_days: int = 7):
        pend_cut = (date.today() - timedelta(days=pending_ttl_days)).isoformat()
        self.pending = {k: v for k, v in self.pending.items() if v.get("date", self.today) >= pend_cut}
        seen_cut = (date.today() - timedelta(days=self.seen_ttl)).isoformat()
        sent_cut = (date.today() - timedelta(days=self.sent_ttl)).isoformat()
        before = (len(self.seen), len(self.sent))
        self.seen = {k: d for k, d in self.seen.items() if d >= seen_cut}
        self.sent = {k: v for k, v in self.sent.items() if v.get("date", self.today) >= sent_cut}
        self._rebuild_title_index()
        removed = (before[0] - len(self.seen), before[1] - len(self.sent))
        if any(removed):
            print(f"🧹 Hafıza temizlendi: {removed[0]} eski URL, {removed[1]} eski gönderim silindi.")

    def save(self):
        data = {"version": 3, "cursor": self.cursor, "seen": self.seen, "sent": self.sent, "pending": self.pending}
        raw = json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True).encode("utf-8")
        target = self.path
        if STATE_KEY:
            from cryptography.fernet import Fernet

            raw, target = Fernet(STATE_KEY.encode()).encrypt(raw), self.enc_path
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            os.replace(tmp, target)  # atomik: yarıda kesilse bile dosya bozulmaz
            if STATE_KEY and os.path.exists(self.path):
                os.remove(self.path)  # düz metin kopyası kalmasın
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
