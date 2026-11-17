"""Ağ/tarayıcı gerektirmeyen hızlı testler:  python -m pytest -q"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from analyzer import JobAnalyzer
from config import MIN_MATCH_SCORE
from state import JobState, canonical_url

ENG = "We are a global company and you will work with stakeholders across EMEA in a fast team. " * 5


@pytest.fixture(scope="module")
def a():
    return JobAnalyzer()


def score(a, title, desc):
    return a.evaluate_job({"title": title, "description": ENG + desc, "company": "X"})["match_score"]


@pytest.mark.parametrize("title,desc", [
    ("Operations Manager", "Python and Excel skills."),            # yönetici + alakasız keyword
    (".NET Engineer", "Python, Excel"),
    ("Backend Developer", "Must know C++ and Python."),             # eski regex C++'ı yakalamıyordu
    ("Software Engineer", "3+ years with C# and .NET Core."),
    ("Compliance Specialist", "Requirements: at least 5 years of experience in AML/KYC."),
    ("KYC Analyst", "Fluent German and English required. KYC AML Excel."),
    ("KYC Analyst with German", "KYC, AML"),
    ("Customer Operations Specialist", "Fluent Polish (C1) and English. Excel."),
    ("Business Analyst", "Strong SAP FI/CO experience. SQL."),
    ("Finance Intern", ""),
    ("Head of Compliance", "Compliance, risk, Python."),
])
def test_rejected(a, title, desc):
    assert score(a, title, desc) == 0


@pytest.mark.parametrize("title,desc", [
    ("Junior Compliance Analyst", "Requirements: 1-2 years of experience in compliance or risk. Excel, SQL."),
    ("KYC Analyst", "Fluent English. German would be a plus. KYC AML Excel."),
    ("Customer Operations Specialist", "Fluent English required. Polish is a nice to have. Excel, SQL, Turkish."),
    ("Turkish Speaking Customer Support Specialist", "Native Turkish, fluent English. Excel."),
    ("Data Analyst", "SQL, Python, Power BI, Excel. 2+ years of experience."),
    ("QA Automation Engineer", "Python, Selenium, Playwright, Jira. You will react quickly to incidents."),
])
def test_accepted(a, title, desc):
    assert score(a, title, desc) >= MIN_MATCH_SCORE


@pytest.mark.parametrize("title,desc", [
    ("Senior Data Analyst", "SQL, Python, Power BI, Excel."),
    ("Marketing Coordinator", "Social media, Excel."),
    ("Software Engineer", "Python is a plus."),
])
def test_below_threshold(a, title, desc):
    assert 0 < score(a, title, desc) < MIN_MATCH_SCORE


def test_polish_and_spanish_postings_rejected(a):
    pl = "Wymagania: znajomość języka polskiego, doświadczenie w obsłudze klienta, umiejętność pracy w zespole. " * 4
    es = "Buscamos un analista de datos con experiencia en la gestión de procesos y en el análisis de la información para el equipo. " * 4
    assert a.evaluate_job({"title": "Specjalista", "description": pl})["match_score"] == 0
    assert a.evaluate_job({"title": "Analista de Datos", "description": es})["match_score"] == 0


@pytest.mark.parametrize("urls", [
    ["https://pl.linkedin.com/jobs/view/python-developer-at-ithouse-co-4385500765?refId=abc&trackingId=x",
     "https://www.linkedin.com/jobs/view/4385500765/"],
    ["https://pl.indeed.com/rc/clk?jk=abc123&bb=zzz", "https://pl.indeed.com/viewjob?jk=abc123"],
    ["https://www.pracuj.pl/praca/x,oferta,1004974208?s=1&ref=2#top", "https://pracuj.pl/praca/x,oferta,1004974208"],
    ["https://www.careersinpoland.com/job/539540,junior-rep-warszawa", "https://www.careersinpoland.com/job/539540,junior-rep"],
])
def test_canonical_url_collapses_tracking(urls):
    assert len({canonical_url(u) for u in urls}) == 1


def test_indeed_ids_stay_distinct():
    assert canonical_url("https://pl.indeed.com/rc/clk?jk=a1") != canonical_url("https://pl.indeed.com/rc/clk?jk=b2")


def test_sent_dedup_by_title_and_company(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # eski dosyalardan göç etmesin
    s = JobState(path=str(tmp_path / "state.json"))
    s.mark_sent("Python Developer (m/f/d)", "See Link", "https://x/1")
    assert s.is_sent("Python Developer", "Unknown")            # şirket bilinmiyor → başlık yeter
    assert s.is_sent("Python Developer - Hybrid", "IT House")  # önce şirketsiz gönderilmişti
    s.mark_sent("Data Analyst", "Allegro", "https://x/2")
    assert s.is_sent("Data Analyst (k/m)", "Allegro sp. z o.o.")
    assert not s.is_sent("Data Analyst", "Revolut")
    s.save()
    assert JobState(path=str(tmp_path / "state.json")).is_sent("Data Analyst", "Allegro")


def test_glassdoor_and_elj_canonical():
    a = "https://www.glassdoor.com/partner/jobListing.htm?pos=101&guid=x&jobListingId=1007465476151&jrtk=abc"
    b = "https://www.glassdoor.com/job-listing/pmo-analyst-JV_KO0,11.htm?jl=1007465476151"
    assert canonical_url(a) == canonical_url(b)
    e1 = canonical_url("https://europelanguagejobs.com/jobs-in-Poland?keywords=x#recruiter-with-turkish")
    e2 = canonical_url("https://europelanguagejobs.com/jobs-in-Poland?keywords=x#sales-with-czech")
    assert e1 != e2


def test_linkedin_guest_urls():
    from scraper import _linkedin_id, linkedin_guest_search_url, set_query_param
    u = linkedin_guest_search_url("https://www.linkedin.com/jobs/search/?currentJobId=1&keywords=turkish&geoId=105072130", 50)
    assert "jobs-guest" in u and "currentJobId" not in u and u.endswith("start=50")
    assert set_query_param("https://x.pl/praca?kw=a&pn=2", "pn", 3) == "https://x.pl/praca?kw=a&pn=3"
    assert _linkedin_id("https://pl.linkedin.com/jobs/view/python-dev-at-x-4385500765?position=1") == "4385500765"


def test_cover_letter_and_caption(a, tmp_path):
    from letters import build_letter, letter_filename, write_letter_pdf
    from notifier import TelegramNotifier
    desc = ("• Analysing large datasets with SQL or Python to identify recurring risk patterns\n"
            "• Monitoring compliance KPIs and preparing weekly reports for stakeholders\n"
            "• Improving and automating manual review processes\n"
            "• 1-2 years of experience in compliance or audit; strong Excel and Power BI\n")
    job = {"title": "Junior Compliance Analyst (k/m)", "company": "Revolut", "site": "linkedin", "url": "https://x/1",
           "description": ENG + desc}
    r = a.evaluate_job(job)
    L = build_letter(job, r, a.matcher)
    from letters import letter_text
    body = letter_text(L)
    assert "ALgpt" not in body and "/100" not in body                         # bot ve puan yok
    assert "LinkedIn" in body and "Revolut" in body and body.rstrip().endswith("Alperen Simsek")
    assert " I " in body or body.count("I'm") or body.count("I am")         # birinci şahıs
    assert len(L["pairs"]) >= 2 and all(q in desc for q, _ in L["pairs"])   # ilandan birebir alıntı
    assert letter_filename(job) == "alperen-simsek-junior-compliance-analyst-letter.pdf"
    pdf = write_letter_pdf(job, r, a.matcher, out_dir=str(tmp_path))
    assert os.path.basename(pdf) == letter_filename(job) and os.path.getsize(pdf) > 5000
    cap = TelegramNotifier.build_caption({**job, "url": "https://x/" + "y" * 900}, r, rank=1)
    assert len(cap) <= 1024 and "https://x/" in cap


def test_pending_queue_keeps_best(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = JobState(path=str(tmp_path / "state.json"))
    job = {"title": "Data Analyst", "company": "X", "url": "u"}
    s.add_pending(job, {"match_score": 72})
    s.add_pending(job, {"match_score": 90})
    s.add_pending(job, {"match_score": 80})
    assert len(s.pending) == 1 and next(iter(s.pending.values()))["result"]["match_score"] == 90
    s.cursor = 17
    s.save()
    s2 = JobState(path=str(tmp_path / "state.json"))
    assert s2.cursor == 17 and len(s2.pending) == 1


@pytest.mark.parametrize("desc,rejected", [
    ("Requirements: EU citizenship required. Excel, SQL.", True),
    ("Candidates must hold a valid security clearance. Excel.", True),
    ("Polish citizenship is required for this role.", True),
    ("EU citizenship is not required; we welcome all nationalities. Excel.", False),
    ("We support EU and non-EU candidates. Excel, SQL, compliance.", False),
])
def test_eligibility_gate(a, desc, rejected):
    r = a.evaluate_job({"title": "Compliance Analyst", "description": ENG + desc, "company": "X"})
    assert (r["match_score"] == 0 and "Eligibility" in r["reason"]) == rejected


def test_letter_quality_rules(a, tmp_path):
    from letters import body_word_count, build_letter, verify_letter_pdf, write_letter_pdf
    desc = ("• Analysing large datasets with SQL or Python to identify recurring risk patterns\n"
            "• Monitoring compliance KPIs and preparing weekly reports for stakeholders\n"
            "• Improving and automating manual review processes\n"
            "• Supporting internal audits and implementing corrective actions\n")
    job = {"title": "Compliance Analyst", "company": "Revolut", "site": "linkedin", "url": "u", "description": ENG + desc}
    r = a.evaluate_job(job)
    L = build_letter(job, r, a.matcher)
    from letters import AI_TELLS, letter_text
    text = letter_text(L)
    assert "—" not in text and "–" not in text                       # uzun tire yok
    assert not AI_TELLS.search(text)                                   # yapay zekâ kalıbı yok
    assert not re.search(r"\b(he|his|him)\b", text)                    # üçüncü şahıs kalmadı
    pdf = write_letter_pdf(job, r, a.matcher, out_dir=str(tmp_path))
    assert verify_letter_pdf(pdf, L) == []                            # tek sayfa + ATS okunabilir
    assert body_word_count(L) <= 330


def test_payroll_letter_is_honest_about_gap(a, tmp_path):
    """Geri bildirim örneği: Payroll Specialist with Turkish. Puan tavanlanır, mektup açığı söyler."""
    from letters import build_letter, letter_text, verify_letter_pdf, write_letter_pdf
    desc = ("• Manage end-to-end payroll operations across EMEA\n"
            "• Ensure compliance with local regulations and support internal and external audits\n"
            "• Identify process improvements and automate manual steps in Excel\n"
            "• Native Turkish and fluent English\n")
    job = {"title": "Payroll Specialist with Turkish", "company": "Dyson", "site": "linkedin", "url": "u2",
           "description": ENG + desc}
    r = a.evaluate_job(job)
    assert r["gap"] == "payroll" and 0 < r["match_score"] <= 72
    L = build_letter(job, r, a.matcher)
    text = letter_text(L)
    assert "payroll" in L["lead_in"] and "Turkish" in L["opening"] and "work permit" in L["opening"]
    assert not any("payroll" in q.lower() for q, _ in L["pairs"])    # cevaplanamayan şart eşleştirilmez
    assert L["opening"].index("Turkish") < L["opening"].index("Amazon")
    pdf = write_letter_pdf(job, r, a.matcher, out_dir=str(tmp_path))
    assert verify_letter_pdf(pdf, L) == [], text


def test_letters_vary_between_postings(a):
    from letters import build_letter
    job = {"title": "Compliance Analyst", "company": "X", "site": "linkedin", "description": ENG}
    r = a.evaluate_job(job)
    openings = {build_letter({**job, "url": f"https://x/{i}"}, r, a.matcher)["opening"] for i in range(12)}
    assert len(openings) >= 3


def test_domain_gap():
    from matcher import domain_gap
    assert domain_gap("Payroll Specialist with Turkish") == "payroll"
    assert domain_gap("Accounts Payable Specialist") == "accounting"
    assert domain_gap("Logistics Data Analyst") == ""                 # çekirdek alan (data) başlıkta
    assert domain_gap("Junior Compliance Analyst") == ""


def test_company_sites_and_generic_links():
    from company_sites import COMPANY_CAREER_SITES
    from scraper import ALL_JOB_LINKS, card_abroad, generic_job_link, in_poland
    urls = [u for _, u in COMPANY_CAREER_SITES]
    assert len(urls) == len(set(urls)) >= 190 and ALL_JOB_LINKS["companies"] == urls
    assert generic_job_link("https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers/job/Warsaw-Poland/Analyst_R1")
    assert generic_job_link("https://x.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/a/requisitions/preview/28")
    assert not generic_job_link("https://jobs.sap.com/search/")
    assert card_abroad("Data Analyst\nBengaluru, India") and not card_abroad("Analyst\nWarsaw, Poland")
    assert in_poland({"location": "Warszawa, PL"}) and not in_poland({"location": "Dublin, IE", "description": "x"})
