"""Gerçek Chrome ile ilan toplayıcı.

Neden gerçek Chrome + görünür pencere?
  Test (2026-11-14): Pracuj, Indeed, Glassdoor, JobLeads headless tarayıcıda Cloudflare
  "Just a moment..." / "Blocked" sayfasına takılıyor; patchright + sistem Chrome'u + headed
  modda hepsi açılıyor. Pencere ekran dışına konur, çalışırken seni rahatsız etmez.
  Linux/GitHub Actions'ta xvfb (sanal ekran) ile çalışır.

Akış: Word dosyasındaki sırayla klasör klasör, link link. Süre dolarsa kaldığı yer
state.json'a yazılır, sonraki çalışma oradan devam eder.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import random
import re
import time
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:  # patchright: otomasyon izlerini gizleyen Playwright sürümü
    from patchright.sync_api import sync_playwright
    STEALTH = True
except ImportError:  # pragma: no cover
    from playwright.sync_api import sync_playwright
    STEALTH = False

from config import (BROWSER_CHANNEL, BROWSER_PROFILE_DIR, BROWSER_WINDOW, DISABLED_SITES, HEADLESS,
                    LINKEDIN_MAX_PAGES, MAX_JOBS_PER_SITE, MAX_PAGES, REQUEST_DELAY,
                    STOP_AFTER_SEEN_PAGES)
from state import canonical_url


def _sleep():
    time.sleep(random.uniform(*REQUEST_DELAY))


def _clean_text(raw: str, limit: int = 5000) -> str:
    text = re.sub(r"\n{2,}", "\n", raw or "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()[:limit]


def _strip_html(raw: str) -> str:
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", raw or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(html_lib.unescape(text))


def site_label(url: str) -> str:
    host = urlsplit(url).netloc.lower().replace("www.", "")
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] in {"pl", "poland", "en", "jobs"}:
        parts = parts[1:]
    return parts[0]


COOKIE_BUTTONS = [
    "#onetrust-accept-btn-handler", "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "[data-test='button-submitCookie']", "button:has-text('Accept all')", "button:has-text('Accept All')",
    "button:has-text('Akceptuj wszystkie')", "button:has-text('Akceptuj')", "button:has-text('Zaakceptuj')",
    "button:has-text('Zgadzam się')", "button:has-text('Accept')", "button:has-text('I agree')",
    "button[id*='cookie' i]", "button[class*='cookie' i]",
]
CLOSE_BUTTONS = ["[data-test='button-close']", "button[aria-label='Close']", "button[aria-label='Dismiss']"]


def _handle_modals(page, cookies_only: bool = False):
    for sel in COOKIE_BUTTONS + ([] if cookies_only else CLOSE_BUTTONS):
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=150):
                btn.click(timeout=1000)
                time.sleep(0.2)
        except Exception:
            continue


def _scroll_page(page, scrolls: int = 8):
    for _ in range(scrolls):
        try:
            page.mouse.wheel(0, 1800)
        except Exception:
            return
        time.sleep(0.45)


BLOCK_MARKERS = re.compile(
    r"just a moment|performing security verification|verify(ing)? you are (a )?human|"
    r"additional verification required|checking your browser|are you a robot|access denied|"
    r"^blocked\b|captcha",
    re.I,
)


class BlockedPage(Exception):
    """Cloudflare / captcha sayfası beklemeye rağmen geçilemedi."""


def _is_blocked(page) -> bool:
    try:
        head = f"{page.title()}\n{page.inner_text('body', timeout=2500)[:600]}"
    except Exception:
        return False
    return bool(BLOCK_MARKERS.search(head))


def _wait_challenge(page, max_seconds: float = 25) -> bool:
    """Cloudflare JS doğrulaması gerçek Chrome'da genelde 3-10 sn'de kendiliğinden geçer."""
    end = time.monotonic() + max_seconds
    while _is_blocked(page):
        if time.monotonic() > end:
            return False
        time.sleep(1.5)
    return True


# ---------------------------------------------------------------------------
# Detay sayfası okuma
# ---------------------------------------------------------------------------
def _find_job_posting(obj):
    if isinstance(obj, list):
        for item in obj:
            found = _find_job_posting(item)
            if found:
                return found
    elif isinstance(obj, dict):
        t = obj.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return obj
        if "@graph" in obj:
            return _find_job_posting(obj["@graph"])
    return None


def _extract_json_ld(page) -> dict:
    try:
        blobs = page.eval_on_selector_all("script[type='application/ld+json']", "els => els.map(e => e.textContent)")
    except Exception:
        return {}
    for blob in blobs:
        try:
            posting = _find_job_posting(json.loads(blob))
        except Exception:
            continue
        if not posting:
            continue
        org = posting.get("hiringOrganization") or {}
        if isinstance(org, list):
            org = org[0] if org else {}
        loc = posting.get("jobLocation") or {}
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        addr = loc.get("address", {}) if isinstance(loc, dict) else {}
        city = addr.get("addressLocality", "") if isinstance(addr, dict) else ""
        if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
            city = f"{city} / Remote" if city else "Remote"
        return {
            "title": html_lib.unescape(str(posting.get("title") or "")).strip(),
            "company": html_lib.unescape(str(org.get("name") if isinstance(org, dict) else org or "")).strip(),
            "city": str(city).strip(),
            "description": _strip_html(str(posting.get("description") or "")),
            "date_posted": str(posting.get("datePosted") or "")[:10],
        }
    return {}


TITLE_SELECTORS = ["[data-test='text-positionName']", "[data-testid='vj-job-title']",
                   "[data-testid='jobsearch-JobInfoHeader-title']", "h1"]
COMPANY_SELECTORS = [
    "[data-test='text-employerName']", "[data-testid='inlineHeader-companyName'] a", ".topcard__org-name-link", ".top-card-layout__second-subline a",
    "[data-testid='inlineHeader-companyName']", "[data-company-name]", "[data-test='employer-name']",
    "[data-test='text-companyName']", "[data-testid='company-name']", "a[href*='/companies/'] h2",
    "[class*='company-name' i]", "[class*='companyName' i]", "[itemprop='hiringOrganization'] [itemprop='name']",
]
DESCRIPTION_SELECTORS = [
    "[data-test='section-offerview']", "#offer-description", "#jobDescriptionText", ".show-more-less-html__markup", "[data-test*='section-description']",
    "[data-test='offer-description']", "[class*='JobDetails_jobDescription' i]", ".job-description", ".job-details",
    "[class*='job-description' i]", "[class*='JobDescription' i]", ".description", "article", "[role='main']", "main",
]
GENERIC_TITLES = {"view offer", "apply", "apply now", "see more", "details", "more", "job opportunity", "zobacz",
                  "sprawdź", "see details", "read more"}


def _first_text(page, selectors, min_len=1, timeout=1500) -> str:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            txt = (loc.inner_text(timeout=timeout) or "").strip()
            if len(txt) >= min_len:
                return txt
        except Exception:
            continue
    return ""


def _company_from_url(url: str) -> str:
    m = re.search(r"/jobs/view/.+-at-([a-z0-9-]+?)-\d{6,}", url)
    return m.group(1).replace("-", " ").title() if m else ""


def _title_from_document(page) -> str:
    try:
        t = page.title() or ""
    except Exception:
        return ""
    t = re.sub(r"^(job|praca|oferta pracy|oferta)\s*:?\s*", "", t, flags=re.I)
    return re.split(r"\s+[|–—-]\s+", t)[0].strip()


# LinkedIn gerçek Chrome'a giriş duvarı gösteriyor; giriş istemeyen "guest" uç noktaları kullanılır.
LI_DROP = {"currentJobId", "origin", "refresh", "eBP", "refId", "trackingId", "referralSearchId"}


def linkedin_guest_search_url(url: str, start: int = 0) -> str:
    q = [(k, v) for k, v in parse_qsl(urlsplit(url).query) if k not in LI_DROP]
    return "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(q + [("start", str(start))])


def set_query_param(url: str, key: str, value) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != key] + [(key, str(value))]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def _linkedin_id(url: str) -> str:
    m = re.search(r"/jobs/view/(?:[^/?]*?-)?(\d{6,})", url) or re.search(r"currentJobId=(\d+)", url)
    return m.group(1) if m else ""


def _read_detail(page, url: str, fallback_title: str) -> dict | None:
    li_id = _linkedin_id(url) if "linkedin.com" in url else ""
    if li_id:
        url = f"https://www.linkedin.com/jobs/view/{li_id}"
        page.goto(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{li_id}", timeout=30000,
                  wait_until="domcontentloaded")
    else:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(0.8)
    if not _wait_challenge(page):
        raise BlockedPage(url)
    # Önce oku, sonra sadece çerez onayına dokun (kapat butonları Pracuj'da giriş penceresi açıyor).
    ld = _extract_json_ld(page)
    if not ld:
        _handle_modals(page, cookies_only=True)
    if fallback_title.lower() in GENERIC_TITLES:
        fallback_title = ""
    title = (ld.get("title") or _first_text(page, ["h2.top-card-layout__title"] if li_id else [], timeout=800)
             or _first_text(page, TITLE_SELECTORS, timeout=1000) or _title_from_document(page)
             or fallback_title or "Job Opportunity")
    company = ld.get("company") or _first_text(page, COMPANY_SELECTORS, timeout=800) or _company_from_url(url)
    description = ld.get("description") or ""
    if len(description) < 200:
        description = _clean_text(_first_text(page, DESCRIPTION_SELECTORS, min_len=150, timeout=2500))
    if len(description) < 150:
        try:
            description = _clean_text(page.inner_text("body"))
        except Exception:
            description = ""
    if len(description) < 100:
        return None
    return {
        "title": re.sub(r"\s+", " ", title)[:150],
        "company": re.sub(r"\s+", " ", company.split("\n")[0])[:80] or "Unknown",
        "city": ld.get("city") or "Warsaw / Remote",
        "description": description,
        "date_posted": ld.get("date_posted", ""),
        "url": page.url if ("jobListing.htm" in url or "/rc/clk" in url) else url,
    }


CITY_RE = re.compile(r"^(poland|polska|remote|zdalnie|hybrid\w*|warsaw|warszawa|krak[oó]w|wroc[lł]aw|gda[nń]sk|pozna[nń]|"
                     r"[lł][oó]d[zź]|katowice|gdynia|lublin|szczecin|bydgoszcz|bia[lł]ystok|rzesz[oó]w|opole|toru[nń])\b,?", re.I)
NOT_COMPANY_RE = re.compile(r"\d|zł|pln|eur|remote|hybrid|mandatory|advanced|proficiency|native|fluent|english|"
                            r"turkish|new$|apply|easy apply|promoted|ago$|days?$", re.I)


def _job_from_card(cand: dict) -> dict:
    """Detay sayfası açılamadığında arama kartındaki bilgiyle iş kaydı (başlık/şirket/şehir)."""
    lines = [l.strip() for l in (cand.get("card") or "").split("\n") if l.strip()]
    title = cand["title"] if cand["title"].lower() not in GENERIC_TITLES else (lines[0] if lines else "Job Opportunity")
    city = next((l.rstrip(",") for l in lines[1:6] if CITY_RE.search(l)), "Warsaw / Remote")
    company = next((l for l in lines[1:4] if l != title and not l.endswith(",") and not CITY_RE.search(l)
                    and not NOT_COMPANY_RE.search(l)), "Unknown")
    return {"title": title[:150], "company": company[:80], "city": city[:60],
            "description": "\n".join(lines)[:1500], "date_posted": "", "card_only": True, "url": cand["url"]}


# ---------------------------------------------------------------------------
# Site tablosu
# ---------------------------------------------------------------------------
CARD_SELECTORS = {
    "bulldogjob.pl": "a[href*='/companies/jobs/']",
    "hiringcafe.com": "a[href*='/job/']",
    "nofluffjobs.com": "a[href*='/job/']",
    "theprotocol.it": "a[href*='/szczegoly/']",
    "talent.com": "a[href*='/view?id='], a.link-job-title",
    "hays.": "a[href*='/job-detail/']",
    "michaelpage.pl": "a[href*='/job-detail/']",
    "devire.pl": "a[href*='/pojedyncza-oferta/']",
    "randstad.pl": "a[href*='/jobs/'][href*='_']",
    "amazon.jobs": "a[href*='/jobs/']",
    "pracuj.pl": "a[data-test='link-offer'], a[href*=',oferta,']",
    "linkedin.com": "a.base-card__full-link, a[href*='/jobs/view/']",
    "indeed.com": "a[data-jk], a.jcs-JobTitle, a[href*='jk=']",
    "justjoin.it": "a[href*='/job-offer/']",
    "careersinpoland.com": "a[href*='/job/']",
    "jobleads.com": "a[href*='/job/']",
    "rocketjobs.pl": "a[href*='/oferta-pracy/']",
    "glassdoor.com": "a[href*='jobListing.htm'], a[data-test='job-title'], a[href*='/job-listing/']",
    "xpatjobs.com": "a[href*='/job/']",
    "revolut.com": "a[href*='/careers/position/']",
    "jobs.ikea.com": "a[href*='/praca/']",
}
# Linki olmayan, ilanı kartta gösteren siteler: kart metninden iş kaydı üretilir.
CARD_MODE = {
    "europelanguagejobs.com": "div.cursor-pointer:has(.inner-card-job-container)",
}
# Detay URL'si bu kalıba uymalı (menü/kategori linklerini ilan sanmamak için).
DETAIL_URL_RE = {
    "pracuj.pl": r",oferta,", "rocketjobs.pl": r"/oferta-pracy/", "justjoin.it": r"/job-offer/",
    "nofluffjobs.com": r"/job/", "linkedin.com": r"/jobs/view/", "revolut.com": r"/position/",
    "theprotocol.it": r"/szczegoly/", "bulldogjob.pl": r"/companies/jobs/\d+", "devire.pl": r"/pojedyncza-oferta/.",
    "jobs.ikea.com": r"/praca/.", "glassdoor.com": r"jobListing\.htm|/job-listing/", "hiringcafe.com": r"/job/.",
    "randstad.pl": r"/jobs/[^/]+_[^/]+_\d+", "hays.": r"/job-detail/", "indeed.com": r"/rc/clk|/viewjob|/pagead/clk",
    "talent.com": r"id=", "amazon.jobs": r"/jobs/\d+", "careersinpoland.com": r"/job/\d+", "jobleads.com": r"/job/.",
}
# Ağır SPA siteleri: kartların yüklenmesini daha uzun bekle.
SLOW_SITES = ("hays.", "hiringcafe", "devire", "justjoin", "theprotocol", "bulldogjob", "revolut", "amazon.jobs", "glassdoor")
# Sayfalama yöntemi (14.11.2026'da canlı test edildi):
#   ("param", anahtar, 2.sayfa değeri, adım) | ("click", buton seçici) | ("linkedin",) | ("none",)
PAGINATION = {
    "nofluffjobs.com": ("param", "page", 2, 1),
    "theprotocol.it": ("param", "pageNumber", 2, 1),
    "pracuj.pl": ("param", "pn", 2, 1),
    "talent.com": ("param", "p", 2, 1),
    "jobleads.com": ("param", "page", 2, 1),
    "careersinpoland.com": ("param", "page", 2, 1),
    "michaelpage.pl": ("param", "page", 1, 1),      # 0'dan başlıyor
    "justjoin.it": ("param", "page", 2, 1),
    "linkedin.com": ("linkedin",),                   # guest API, sayfa başına 10 ilan (start=0,10,20...)
    "glassdoor.com": ("click", "button[data-test='load-more']"),
    "amazon.jobs": ("click", "button[aria-label*='next' i]"),
    "bulldogjob.pl": ("click", "button[aria-label*='next' i]"),
    "hiringcafe.com": ("click", "a[aria-label*='next' i]"),
    "indeed.com": ("none",),        # 2. sayfa giriş istiyor (secure.indeed.com/auth)
    "rocketjobs.pl": ("none",),     # sayfa/buton yok, arama başına ~50 ilan
    "revolut.com": ("none",),       # tüm ilanlar tek sayfada
}
NEXT_BUTTONS = ["a[rel='next']", "a[data-testid='pagination-page-next']", "[data-test='pagination-next']",
                "a[aria-label*='next page' i]", "button[aria-label*='next page' i]", "button:has-text('Load more')",
                "button:has-text('Show more jobs')", "button:has-text('Pokaż więcej')"]
JUNK_URL_PARTS = ["/login", "/register", "/signup", "/sign-in", "/employer", "/pracodawcy", "mailto:", "javascript:"]

CARD_JS = """els => els.map(e => {
  const c = e.closest('li, article, [class*="card" i], [class*="offer" i], [data-test*="offer"], [class*="job-item" i], [class*="result" i]') || e.parentElement;
  return [e.getAttribute('href'), (e.innerText || e.getAttribute('aria-label') || '').trim(), ((c && c.innerText) || '').trim().slice(0, 800)];
})"""


def _lookup(table: dict, url: str):
    return next((v for k, v in table.items() if k in url), None)

# ==========================================
# 📋 WORD BELGESİNDEKİ TÜM MANUEL LİNKLER
# ==========================================
ALL_JOB_LINKS = {
    "turkish": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dkrakow,gdansk,wroclaw,poznan,gdynia,lodz,lublin,katowice%20keyword%3Dturkish",
        "https://theprotocol.it/praca?kw=turkish",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=turkish",
        "https://www.hays.pl/en/job-search/turkish-jobs-in-poland-poland?q=Turkish&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Turkish%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Turkish%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Turkish%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/turkish/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6InR1cmtpc2giLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-turkish/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=turkish&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/turkish;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4475017826&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=turkish&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=turkish&l=Polska&radius=10&from=searchOnDesktopSerp%2Cwhereautocomplete&vjk=a78578ae21fb63b9",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=turkish&languages=en&sortBy=newest",
        "https://www.careersinpoland.com/jobs/language/english+turkish/city/remote+warszawa",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/turkish?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=turkish&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=turkish",
        "https://www.glassdoor.com/Job/poland-turkish-jobs-SRCH_IL.0,6_IN193_KO7,14.htm?fromAge=14&sortBy=date_desc",
        "https://poland.xpatjobs.com/search?ps=1&keyword=turkish&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=turkish"
    ],
    "operations": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Doperations",
        "https://theprotocol.it/praca?kw=operations",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=operations",
        "https://pl.talent.com/en/jobs?k=operations&l=Warsaw%2C+Mazovia&radius=5&id=631846930519436865",
        "https://www.hays.pl/en/job-search/operations-jobs-in-poland-poland?q=Operations&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Operations%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Operations%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Operations%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/operations",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6Im9wZXJhdGlvbnMiLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-operations/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?offset=0&result_limit=10&sort=recent&distanceType=Mi&radius=24km&latitude=52.2356&longitude=21.01037&loc_group_id=&loc_query=Poland&base_query=operations&city=&country=POL&region=&county=&query_options=&",
        "https://www.pracuj.pl/praca/operations;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=operations&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=operations&l=Polska&from=searchOnDesktopSerp&vjk=80dd41d5d53855cd",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=operations&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/operations?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=operations&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=operations",
        "https://www.glassdoor.com/Job/poland-operations-jobs-SRCH_IL.0,6_IN193_KO7,17.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=operations&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=operations"
    ],
    "analyst": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Danalyst",
        "https://theprotocol.it/praca?kw=analyst",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=Analyst",
        "https://pl.talent.com/en/jobs?k=Analyst&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/analyst-jobs-in-poland-poland?q=Analyst&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Analyst%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Analyst%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Analyst%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/analyst/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6IkFuYWx5c3QiLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-analyst/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=analyst&loc_query=Poland&latitude=52.2356&longitude=21.01037&loc_group_id=&invalid_location=false&country=POL&city=&region=&county=",
        "https://www.pracuj.pl/praca/analyst;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=analyst&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=analyst&l=Polska&from=searchOnDesktopSerp&vjk=569eefbc59822d63",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=analyst&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/analyst?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=analyst&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=analyst",
        "https://www.glassdoor.com/Job/poland-analyst-jobs-SRCH_IL.0,6_IN193_KO7,14.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=analyst&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=analyst"
    ],
    "automation": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Dautomation",
        "https://theprotocol.it/praca?kw=automation",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=automation",
        "https://pl.talent.com/en/jobs?k=automation&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/automation-jobs-in-poland-poland?q=Automation&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Automation%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Automation%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Automation%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/automation/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6ImF1dG9tYXRpb24iLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-automation/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=automation&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/automation;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=automation&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=automation&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=automation&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/automation?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=automation&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=automation",
        "https://www.glassdoor.com/Job/poland-automation-jobs-SRCH_IL.0,6_IN193_KO7,17.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=automation&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=automation"
    ],
    "compliance": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Dcompliance",
        "https://theprotocol.it/praca?kw=compliance",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=compliance",
        "https://pl.talent.com/en/jobs?k=compliance&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/compliance-jobs-in-poland-poland?q=Compliance&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Compliance%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Compliance%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Compliance%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/compliance/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6ImNvbXBsaWFuY2UiLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-compliance/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=compliance&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/compliance;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=compliance&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=compliance&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=compliance&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/compliance?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=compliance&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=compliance",
        "https://www.glassdoor.com/Job/poland-compliance-jobs-SRCH_IL.0,6_IN193_KO7,17.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=compliance&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=compliance"
    ],
    "quality": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Dquality",
        "https://theprotocol.it/praca?kw=quality",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=quality",
        "https://pl.talent.com/en/jobs?k=quality&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/quality-jobs-in-poland-poland?q=Quality&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Quality%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Quality%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Quality%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/quality/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6InF1YWxpdHkiLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-quality/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=quality&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/quality;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=quality&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=quality&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=quality&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/quality?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=quality&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=quality",
        "https://www.glassdoor.com/Job/poland-quality-jobs-SRCH_IL.0,6_IN193_KO7,14.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=quality&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=quality"
    ],
    "risk": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Drisk",
        "https://theprotocol.it/praca?kw=risk",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=risk",
        "https://pl.talent.com/en/jobs?k=risk&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/risk-jobs-in-poland-poland?q=Risk&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Risk%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Risk%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Risk%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/risk/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6InJpc2siLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-risk/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=risk&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/risk;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=risk&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=risk&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=risk&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/risk?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=risk&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=risk",
        "https://www.glassdoor.com/Job/poland-risk-jobs-SRCH_IL.0,6_IN193_KO7,11.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=risk&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=risk"
    ],
    "data": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Ddata",
        "https://theprotocol.it/praca?kw=data",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=data",
        "https://pl.talent.com/en/jobs?k=data&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/data-jobs-in-poland-poland?q=Data&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Data%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Data%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Data%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/data/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6ImRhdGEiLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-data/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=data&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/data;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=data&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=data&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=data&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/data?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=data&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=data",
        "https://www.glassdoor.com/Job/poland-data-jobs-SRCH_IL.0,6_IN193_KO7,11.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=data&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=data"
    ],
    "junior": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Djunior",
        "https://theprotocol.it/praca?kw=junior",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=junior",
        "https://pl.talent.com/en/jobs?k=junior&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/junior-jobs-in-poland-poland?q=Junior&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Junior%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Junior%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Junior%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/junior/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6Imp1bmlvciIsImNpdGllcyI6W3siaWQiOiJPTCIsIm5hbWUiOiJQb2xza2EifSx7ImlkIjoiUEwxNDY1MDEwOTE4MTIzIiwibmFtZSI6IldhcnN6YXdhLCBNYXpvd2llY2tpZSJ9XSwicmVtb3RlIjpmYWxzZX0=",
        "https://www.randstad.pl/en/jobs/q-junior/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=junior&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/junior;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4473462047&f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=junior&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=junior&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=junior&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/junior?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=junior&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=junior",
        "https://www.glassdoor.com/Job/poland-junior-jobs-SRCH_IL.0,6_IN193_KO7,13.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=junior&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=junior"
    ],
    "programmer": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Dprogrammer",
        "https://theprotocol.it/praca?kw=programmer",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=programmer",
        "https://pl.talent.com/en/jobs?k=programmer&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/programmer-jobs-in-poland-poland?q=Programmer&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Programmer%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Programmer%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Programmer%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/programmer/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6InByb2dyYW1tZXIiLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-programmer/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=programmer&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/programmer;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=programmer&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=programmer&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=programmer&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/programmer?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=programmer&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=programmer",
        "https://www.glassdoor.com/Job/poland-programmer-jobs-SRCH_IL.0,6_IN193_KO7,17.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=programmer&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=programmer"
    ],
    "excel": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Dexcel",
        "https://theprotocol.it/praca?kw=excel",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=excel",
        "https://pl.talent.com/en/jobs?k=excel&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/excel-jobs-in-poland-poland?q=Excel&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Excel%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Excel%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Excel%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/excel/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6ImV4Y2VsIiwiY2l0aWVzIjpbeyJpZCI6IlBMIiwibmFtZSI6IlBvbHNrYSJ9LHsiaWQiOiJQTDE0NjUwMTA5MTgxMjMiLCJuYW1lIjoiV2Fyc3phd2EsIE1hem93aWVja2llIn1dLCJyZW1vdGUiOmZhbHNlfQ==",
        "https://www.randstad.pl/en/jobs/q-excel/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=excel&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/excel;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=excel&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=excel&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=excel&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/excel?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=excel&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=excel",
        "https://www.glassdoor.com/Job/poland-excel-jobs-SRCH_IL.0,6_IN193_KO7,12.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=excel&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=excel"
    ],
    "process": [
        "https://nofluffjobs.com/pl/warszawa?criteria=city%3Dgdansk,gdynia,lodz%20keyword%3Dprocess",
        "https://theprotocol.it/praca?kw=process",
        "https://europelanguagejobs.com/jobs-in-Poland?keywords=process",
        "https://pl.talent.com/en/jobs?k=process&l=Warsaw%2C+Mazovia&radius=5",
        "https://www.hays.pl/en/job-search/process-jobs-in-poland-poland?q=Process&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Process%20Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20Process%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20Process%20jobs%20now",
        "https://www.michaelpage.pl/en/jobs/process/poland",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6InByb2Nlc3MiLCJjaXRpZXMiOlt7ImlkIjoiUEwiLCJuYW1lIjoiUG9sc2thIn0seyJpZCI6IlBMMTQ2NTAxMDkxODEyMyIsIm5hbWUiOiJXYXJzemF3YSwgTWF6b3dpZWNraWUifV0sInJlbW90ZSI6ZmFsc2V9",
        "https://www.randstad.pl/en/jobs/q-process/mazowieckie/warszawa/remote/",
        "https://amazon.jobs/pl/search?base_query=process&loc_query=Poland&country=POL",
        "https://www.pracuj.pl/praca/process;kw/warszawa;wp?rd=30&wpl=true",
        "https://www.linkedin.com/jobs/search/?f_E=1%2C2&f_WT=2%2C3&geoId=105072130&keywords=process&origin=JOB_SEARCH_PAGE_SEARCH_BUTTON&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=process&l=Polska&from=searchOnDesktopSerp",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,internship&keyword=process&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland/q/process?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://pl.talent.com/en/jobs?k=process&l=Warszawa%2C+Masovian+Voivodeship&radius=100",
        "https://rocketjobs.pl/oferty-pracy/warszawa?radius=100&keyword=process",
        "https://www.glassdoor.com/Job/poland-process-jobs-SRCH_IL.0,6_IN193_KO7,14.htm",
        "https://poland.xpatjobs.com/search?ps=1&keyword=process&city=Warsaw&areas=28",
        "https://www.revolut.com/careers/?city=Poland+-+Remote&text=process"
    ],
    "other": [
        "https://bulldogjob.pl/companies/jobs/s/city,Remote,Warszawa,Polska",
        "https://hiringcafe.com/ai-search/c/01m3z9fb1mnd2f5tv5me29ctx5",
        "https://www.revolut.com/careers/?city=Poland+-+Remote",
        "https://jobs.ikea.com/pl/szukanie-pracy/Warszawa%2C%20Wojew%C3%B3dztwo%20mazowieckie/22908/4/798544-858787-6695624-7531926-756135/52x22977/21x01178/25/2"
    ],
    "last_24_hours_angielski": [
        "https://nofluffjobs.com/pl/warszawa?criteria=jobLanguage%3Den",
        "https://theprotocol.it/filtry/umowa-o-prace;c/warszawa;wp",
        "https://europelanguagejobs.com/jobs-in-Warsaw-for-English-speakers",
        "https://www.hays.pl/en/job-search/in-poland-poland?q=&location=Poland,%20Poland&specialismId=&subSpecialismId=&locationf=&industryf=&sortType=0&jobType=-1&flexiWorkType=-1&payTypefacet=-1&minPay=-1&maxPay=-1&jobSource=HaysGCJ&searchPageTitle=Jobs%20in%20Poland,%20Poland%20%7C%20Hays%20Recruitment&searchPageDesc=Find%20the%20perfect%20job%20in%20Poland,%20Poland.%20Hays%20Recruitment%20can%20help%20you%20find%20the%20ideal%20role.%20Search%20for%20jobs%20now",
        "https://devire.pl/en/find-your-job/#s=eyJmaWx0ZXJzIjp7ImJyYW5jaGUiOltdLCJjYXRlZ29yeSI6W10sImxhbmd1YWdlIjpbXSwicmVnaW9uIjpbXSwiZWR1Y2F0aW9uIjpbXSwiam9iVHlwZSI6W10sInBvc2l0aW9uIjpbXSwic2FsYXJ5RnJvbSI6MCwic2FsYXJ5VG8iOjB9LCJwb3NpdGlvbiI6IiIsImNpdGllcyI6W3siaWQiOiJQTCIsIm5hbWUiOiJQb2xza2EifSx7ImlkIjoiUEwxNDY1MDEwOTE4MTIzIiwibmFtZSI6IldhcnN6YXdhLCBNYXpvd2llY2tpZSJ9XSwicmVtb3RlIjpmYWxzZX0=",
        "https://www.pracuj.pl/praca/warszawa;wp/ostatnich%207%20dni;p,7?rd=30&tc=0&ws=0&wpl=true",
        "https://www.linkedin.com/jobs/search/?currentJobId=4353923480&distance=10&f_E=2%2C3&f_JT=F&f_TPR=r86400&f_WT=2%2C1%2C3&geoId=102560051&origin=JOB_SEARCH_PAGE_JOB_FILTER&refresh=true&sortBy=DD",
        "https://pl.indeed.com/jobs?q=&l=Polska&fromage=7&sc=0kf%3Aattr%285QWDV%7CCF3CP%252COR%29%3B&from=searchOnDesktopSerp&vjk=6c75eae6cf3ace1c",
        "https://justjoin.it/job-offers/warszawa?employment-types=permanent&remote-work-options=hybrid,remote,office&working-times=full-time&experience-levels=junior,mid&published-date=7&languages=en&sortBy=newest",
        "https://www.jobleads.com/pl/jobs/l/Poland?filter_by_daysReleased=14&location_coordinates_radius=474205.0232836308&location_latitude=51.919438&location_longitude=19.145136&minSalary=90000",
        "https://www.glassdoor.com/Job/poland-turkish-jobs-SRCH_IL.0,6_IN193_KO7,14.htm?fromAge=30&sortBy=date_desc",
        # Word: LinkedIn "search-results" (giriş ister) -> aynı filtrelerle herkese açık arama (son 24 saat, maaş, Easy Apply)
        "https://www.linkedin.com/jobs/search/?keywords=warsaw&f_TPR=r86400&f_SAL=f_SA_id_226001%3A272015%24f_SA_id_227001%3A276001%2C277001&sortBy=DD",
        "https://www.linkedin.com/jobs/search/?keywords=warsaw&f_TPR=r86400&f_AL=true&f_SAL=f_SA_id_227001%3A276001%2C277001%24f_SA_id_226001%3A272015&sortBy=DD",
        "https://hiringcafe.com/saved?feed=all&unread=0&filters=%7B%22locations%22%3A%5B%7B%22id%22%3A%226hk1yZQBoEtHp_8UlzB9%22%2C%22types%22%3A%5B%22locality%22%5D%2C%22address_components%22%3A%5B%7B%22long_name%22%3A%22Warsaw%22%2C%22short_name%22%3A%22Warsaw%22%2C%22types%22%3A%5B%22locality%22%5D%7D%2C%7B%22long_name%22%3A%22Mazovia%22%2C%22short_name%22%3A%2278%22%2C%22types%22%3A%5B%22administrative_area_level_1%22%5D%7D%2C%7B%22long_name%22%3A%22Poland%22%2C%22short_name%22%3A%22PL%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22geometry%22%3A%7B%22location%22%3A%7B%22lat%22%3A52.22977%2C%22lon%22%3A21.01178%7D%7D%2C%22formatted_address%22%3A%22Warsaw%2C+Mazovia%2C+PL%22%2C%22population%22%3A1702139%2C%22options%22%3A%7B%22radius%22%3A25%2C%22radius_unit%22%3A%22miles%22%2C%22ignore_radius%22%3Afalse%7D%7D%5D%2C%22seniorityLevel%22%3A%5B%22No+Prior+Experience+Required%22%2C%22Entry+Level%22%5D%2C%22excludedLanguageRequirements%22%3A%5B%22polish%22%5D%2C%22languageRequirements%22%3A%5B%22english%22%5D%7D"
    ]
}



class JobScraper:
    def __init__(self, state, prefilter=None, folders=None, sites=None, deadline=None,
                 max_per_page=MAX_JOBS_PER_SITE, use_cursor=True):
        self.state = state
        self.prefilter = prefilter or (lambda title: "")
        self.deadline = deadline
        self.max_per_page = max_per_page
        self.use_cursor = use_cursor and not folders and not sites
        self.stats = defaultdict(lambda: {"pages": 0, "cards": 0, "new": 0, "prefiltered": 0, "jobs": 0,
                                          "card_only": 0, "blocked": 0, "errors": 0})
        self.blocked_streak = defaultdict(int)
        self.stopped_early = False
        self.plan = self._build_plan(folders, sites)

    @staticmethod
    def _build_plan(folders, sites) -> list:
        """Word dosyasındaki sırayla (klasör, url) listesi; tekrar eden arama linki bir kez."""
        seen, plan = set(), []
        for folder, urls in ALL_JOB_LINKS.items():
            if folders and folder not in folders:
                continue
            for u in urls:
                explicitly = sites and any(s in u for s in sites)
                if sites and not explicitly:
                    continue
                if any(d in u for d in DISABLED_SITES) and not explicitly:
                    continue
                if u not in seen:
                    seen.add(u)
                    plan.append((folder, u))
        return plan

    def _time_left(self) -> bool:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.stopped_early = True
            return False
        return True

    # ------------------------------------------------------------------
    def _goto_search(self, page, url: str, page_url: str) -> bool:
        page.goto(url, timeout=40000, wait_until="domcontentloaded")
        time.sleep(1.0)
        if not _wait_challenge(page):
            return False
        _handle_modals(page)
        sel = _lookup(CARD_MODE, page_url) or _lookup(CARD_SELECTORS, page_url)
        try:
            page.wait_for_selector(sel, timeout=15000 if any(s in page_url for s in SLOW_SITES) else 6000)
        except Exception:
            pass
        return True

    def _grab(self, page, ctx) -> tuple:
        """Ekrandaki kartları topla. (yeni_link, yeni_görülmemiş) sayısı döner."""
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(page.url))
        new_keys = new_unseen = 0
        try:
            items = page.eval_on_selector_all(ctx["sel"], CARD_JS)
        except Exception:
            return 0, 0
        for href, text, card in items:
            if not href:
                continue
            if href.startswith("//"):
                full = "https:" + href
            elif href.startswith("/"):
                full = origin + href
            elif href.startswith("http"):
                full = href
            else:
                continue
            full = full.replace("&amp;", "&")
            if any(j in full for j in JUNK_URL_PARTS) or (ctx["must"] and not re.search(ctx["must"], full)):
                continue
            key = canonical_url(full)
            if key == ctx["page_key"] or key in ctx["local"] or len(key) < 15:
                continue
            ctx["local"].add(key)
            ctx["st"]["cards"] += 1
            new_keys += 1
            if self.state.is_seen(full):
                continue
            title = (text or "").split("\n")[0].strip() or (card.split("\n")[0].strip() if card else "")
            ctx["out"].append({"url": full, "title": title or "Job Opportunity", "card": card})
            new_unseen += 1
        return new_keys, new_unseen

    def _scroll_grab(self, page, ctx, scrolls: int = 8) -> tuple:
        """Kaydırırken her adımda topla (kaydırdıkça eski kartı silen listeler için)."""
        k = u = 0
        for _ in range(scrolls):
            a, b = self._grab(page, ctx)
            k, u = k + a, u + b
            try:
                page.mouse.wheel(0, 1800)
            except Exception:
                break
            time.sleep(0.45)
        a, b = self._grab(page, ctx)
        return k + a, u + b

    def _next_page(self, page, page_url: str, n: int) -> bool:
        """n. sayfaya geç (URL parametresi, LinkedIn guest API ya da 'sonraki/daha fazla' butonu)."""
        mode = _lookup(PAGINATION, page_url) or ("click", None)
        if mode[0] == "none":
            return False
        if mode[0] == "linkedin":
            return self._goto_search(page, linkedin_guest_search_url(page_url, 10 * (n - 1)), page_url)
        if mode[0] == "param":
            _, key, first, step = mode
            return self._goto_search(page, set_query_param(page_url, key, first + (n - 2) * step), page_url)
        for sel in ([mode[1]] if mode[1] else NEXT_BUTTONS):
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=400):
                    btn.click(timeout=4000)
                    time.sleep(2.5)
                    return _wait_challenge(page)
            except Exception:
                continue
        return False

    def _collect_candidates(self, page, page_url: str) -> list:
        label = site_label(page_url)
        st = self.stats[label]
        first = linkedin_guest_search_url(page_url, 0) if "linkedin.com" in page_url else page_url
        if not self._goto_search(page, first, page_url):
            st["blocked"] += 1
            print(f"      🛡️ [{label}] arama sayfası doğrulamayı geçemedi.")
            return []

        card_mode = _lookup(CARD_MODE, page_url)
        if card_mode:
            _scroll_page(page)
            texts = page.eval_on_selector_all(card_mode, "els => els.map(e => e.innerText.trim().slice(0, 1500))")
            out = []
            for t in texts:
                title = t.split("\n")[0].strip()
                url = f"{page_url}#{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:80]}"
                st["cards"] += 1
                if not self.state.is_seen(url):
                    out.append({"url": url, "title": title, "card": t, "card_mode": True})
            return out

        sel = _lookup(CARD_SELECTORS, page_url)
        if not sel:
            print(f"      ⚠️ [{label}] için kart seçicisi yok.")
            return []
        ctx = {"sel": sel, "must": _lookup(DETAIL_URL_RE, page_url), "page_key": canonical_url(page_url),
               "local": set(), "out": [], "st": st}
        new_keys, new_unseen = self._scroll_grab(page, ctx)
        pages, seen_streak = 1, (0 if new_unseen else 1)
        # Sayfa sayfa ilerle: yeni ilan çıkmayınca, üst üste N sayfa tamamen görülmüşse
        # (önceki günlerde taranmış) ya da MAX_PAGES'e ulaşınca dur.
        max_pages = LINKEDIN_MAX_PAGES if "linkedin.com" in page_url else MAX_PAGES
        while new_keys and pages < max_pages and seen_streak < STOP_AFTER_SEEN_PAGES and self._time_left():
            try:
                if not self._next_page(page, page_url, pages + 1):
                    break
            except Exception:
                break
            pages += 1
            new_keys, new_unseen = self._scroll_grab(page, ctx, scrolls=5)
            seen_streak = 0 if new_unseen else seen_streak + 1
            time.sleep(random.uniform(0.6, 1.4))
        st["pages"] += pages - 1
        if pages > 1:
            print(f"      📄 [{label}] {pages} sayfa tarandı, {len(ctx['local'])} ilan linki.")
        return ctx["out"]

    def _scrape_search_page(self, page, page_url: str, folder: str):
        label = site_label(page_url)
        st = self.stats[label]
        st["pages"] += 1
        try:
            candidates = self._collect_candidates(page, page_url)
        except Exception as e:
            st["errors"] += 1
            print(f"      ⚠️ [{label}] arama sayfası açılamadı: {str(e).splitlines()[0][:120]}")
            return

        fresh = []
        for cand in candidates:
            reason = self.prefilter(cand["title"])
            if reason:
                st["prefiltered"] += 1
                self.state.mark_seen(cand["url"])
            else:
                fresh.append(cand)
        if self.max_per_page:
            fresh = fresh[: self.max_per_page]
        st["new"] += len(fresh)
        print(f"      📍 [{label}] {len(candidates)} yeni ilan, {len(candidates) - len(fresh)} başlıktan elendi, "
              f"{len(fresh)} incelenecek.")

        for cand in fresh:
            if not self._time_left():
                return
            detail = None
            if cand.get("card_mode"):
                detail = _job_from_card(cand)
                detail["card_only"] = False  # bu sitede ilanın tamamı kartta
            elif self.blocked_streak[label] >= 3:
                detail = _job_from_card(cand)  # site bu çalışmada detayları engelliyor: kart bilgisiyle devam
            else:
                try:
                    detail = _read_detail(page, cand["url"], cand["title"])
                    self.blocked_streak[label] = 0
                except BlockedPage:
                    self.blocked_streak[label] += 1
                    st["blocked"] += 1
                    detail = _job_from_card(cand)
                    if self.blocked_streak[label] == 3:
                        print(f"      🛡️ [{label}] detay sayfaları engelli; bu çalışmada kart bilgisi kullanılacak.")
                except Exception:
                    st["errors"] += 1
                    detail = _job_from_card(cand) if cand.get("card") else None
                _sleep()
            self.state.mark_seen(cand["url"])
            if detail:
                st["card_only" if detail.get("card_only") else "jobs"] += 1
                detail.setdefault("url", cand["url"])
                detail.update({"id": canonical_url(cand["url"]), "site": label,
                               "source_site": f"{folder.upper()} - {label.upper()}"})
                yield detail

    # ------------------------------------------------------------------
    def _launch(self, p):
        os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
        args = ["--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding", "--window-size=1366,900"]
        if BROWSER_WINDOW == "offscreen" and not HEADLESS:
            args.append("--window-position=-2400,-2400")
        kwargs = dict(headless=HEADLESS, no_viewport=True, args=args)
        try:
            return p.chromium.launch_persistent_context(BROWSER_PROFILE_DIR, channel=BROWSER_CHANNEL, **kwargs)
        except Exception as e:
            print(f"⚠️ Sistem Chrome'u açılamadı ({str(e).splitlines()[0][:80]}); yerleşik Chromium deneniyor.")
            return p.chromium.launch_persistent_context(BROWSER_PROFILE_DIR, **kwargs)

    def iter_jobs(self):
        n = len(self.plan)
        start = self.state.cursor % n if (self.use_cursor and n) else 0
        mode = "gerçek Chrome" + (" (headless)" if HEADLESS else "") + (" + patchright" if STEALTH else "")
        print(f"🌐 Tarama: {n} arama linki, Word sırasıyla"
              + (f", {start + 1}. linkten devam ({self.plan[start][0]})" if start else "") + f" | {mode}")
        with sync_playwright() as p:
            ctx = self._launch(p)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            current_folder = None
            try:
                for i in range(n):
                    idx = (start + i) % n
                    folder, url = self.plan[idx]
                    if not self._time_left():
                        if self.use_cursor:
                            self.state.cursor = idx
                        print(f"⏱️ Süre doldu; sonraki çalışma {idx + 1}. linkten ({folder}) devam edecek.")
                        return
                    if folder != current_folder:
                        current_folder = folder
                        print(f"\n📁 KLASÖR: [{folder.upper()}]")
                    yield from self._scrape_search_page(page, url, folder)
                if self.use_cursor:
                    self.state.cursor = 0  # tam tur bitti: yarın baştan (Turkish) başla
            finally:
                ctx.close()

    def print_health_report(self):
        print("\n📊 SİTE SAĞLIK RAPORU")
        print(f"   {'site':<20}{'sayfa':>6}{'kart':>6}{'yeni':>6}{'elendi':>7}{'detay':>7}{'kart-only':>10}{'engel':>6}{'hata':>5}")
        for label, s in sorted(self.stats.items()):
            flag = "  ❌ ilan linki yok" if s["cards"] == 0 else ""
            print(f"   {label:<20}{s['pages']:>6}{s['cards']:>6}{s['new']:>6}{s['prefiltered']:>7}{s['jobs']:>7}"
                  f"{s['card_only']:>10}{s['blocked']:>6}{s['errors']:>5}{flag}")
