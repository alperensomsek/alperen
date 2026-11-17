"""Aday profili — Alperen_Simsek.pdf (Kasım 2026 CV'si) ile birebir.

Eşleştirme (matcher.py) ve cover letter (letters.py) yalnızca buradaki bilgileri
kullanır. CV değişirse SADECE bu dosyayı güncelle. Buraya CV'de olmayan bir iddia
(rakam, araç, unvan) yazma: mektupta senin imzanla çıkar.
İletişim bilgileri koda yazılmaz: .env (yerel) ya da GitHub Secrets'tan okunur,
böylece repo public olsa bile e-posta/telefon görünmez.
"""
import os

from dotenv import load_dotenv

load_dotenv()

NAME = "Alperen Simsek"
ASSISTANT_NAME = "ALgpt"  # yalnızca Telegram/log; mektuplarda geçmez
EMAIL = os.getenv("CANDIDATE_EMAIL", "")
PHONE = os.getenv("CANDIDATE_PHONE", "")
LINKEDIN = os.getenv("CANDIDATE_LINKEDIN", "")
GITHUB = os.getenv("CANDIDATE_GITHUB", "github.com/alperenosmansimsek")
LOCATION = "Warsaw, Poland"

# Model bu metni ilanlarla karşılaştırır (İngilizce, kısa ve yoğun tut).
SUMMARY = (
    "Analytical professional with a Master's in Computer Science, a Bachelor's in Mathematics and 2 years at "
    "Amazon as Compliance Associate. Product compliance review against EMEA/US regulations, safety standards and "
    "policies; risk-based assessment; root cause analysis (5 Whys) of recurring audit errors; Python data analysis, "
    "SQL, Excel (VBA, pivot tables), Power BI; browser-based automation workflows; SOP-based mentoring and "
    "procedure development. ETL pipelines with Python, FastAPI and Databricks; JavaScript, Kotlin/Android. "
    "Junior to mid-level analyst, specialist or associate. English C1, Turkish native, Polish A2."
)

# İdeal iş tanımları: ilan bunlardan birine ne kadar benziyorsa o kadar uygun.
TARGET_ROLES = [
    "Compliance Analyst / Compliance Specialist: regulatory and product compliance checks, policy controls, "
    "audits, reporting.",
    "Risk Analyst: risk-based assessment, controls testing, risk reporting, KYC/AML screening.",
    "Operations Analyst: analyze operational data, improve workflows and procedures, reporting in Excel and Power BI.",
    "Process Improvement Specialist: root cause analysis, standard operating procedures, procedure development, "
    "workflow automation.",
    "Data Analyst / Business Analyst: SQL, Python, Power BI dashboards, data analysis and insights for stakeholders.",
    "Junior Data Engineer: ETL pipelines in Python, FastAPI, Databricks, data quality, pytest, Git.",
    "Quality Analyst / Content Review Specialist: quality audits, policy and safety reviews, error analysis.",
    "Automation / QA Automation Specialist: Python scripts, test automation, workflow automation, browser automation.",
    "Turkish-speaking specialist: customer, operations or content role requiring native Turkish and English.",
    "Junior Python Developer / Junior Software Engineer: Python, JavaScript, Kotlin, automation tools, Git.",
]

# CV'deki beceriler (ilanla kesişimi "Matches" olur). Küçük harf, ilanda geçen yazımıyla.
# Yalnızca CV'de (deneyim, proje, beceri, sertifika) geçenler.
CV_SKILLS = {
    "python", "sql", "javascript", "html", "kotlin", "android", "android studio", "git", "github", "vs code",
    "jira", "power bi", "dashboards", "data visualization", "excel", "vba", "macros", "pivot tables", "vlookup",
    "microsoft office", "fastapi", "databricks", "etl", "pytest", "ci/cd", "data engineering",
    "root cause analysis", "5 whys", "compliance", "risk assessment", "audit", "auditing", "data analysis",
    "reporting", "process improvement", "automation", "agile", "kanban", "sop", "procedure development",
    "training", "mentoring", "stakeholder management", "prompt engineering", "ai", "llm", "claude", "chatgpt",
    "claude code", "english", "turkish", "mathematics",
}

# İlanlarda aranacak beceri sözlüğü (CV'de olmayanlar "Asks for" = eksik olarak gösterilir).
SKILL_VOCAB = CV_SKILLS | {
    "tableau", "looker", "qlik", "alteryx", "sas", "spss", "r", "snowflake", "spark", "airflow", "dbt",
    "bigquery", "azure", "aws", "gcp", "docker", "kubernetes", "terraform", "linux", "bash", "selenium",
    "playwright", "cypress", "postman", "rest api", "api", "servicenow", "confluence", "salesforce", "sap",
    "oracle", "java", "c#", ".net", "c++", "react", "angular", "typescript", "node.js", "scrum", "six sigma",
    "lean", "kaizen", "capa", "kpi", "sla", "pareto", "power query", "powerapps", "kyc", "aml", "gdpr", "sox",
    "iso 27001", "internal audit", "machine learning", "pandas", "numpy", "data warehouse", "jupyter",
    "accounting", "ifrs", "statistics", "quality assurance", "quality control", "polish", "german",
}

# Cover letter'da kanıt olarak kullanılacak başarılar (üçüncü şahıs; model eşleştirmesi için).
# EVIDENCE_SHORT, EVIDENCE_FIRST ve ACHIEVEMENT_WEIGHTS bu listeyle AYNI SIRADA olmalı.
ACHIEVEMENTS = [
    "At Amazon he reviewed and classified products against EMEA/US marketplace-specific regulations, safety "
    "standards and Amazon policies to protect customers and sellers.",
    "At Amazon he analyzed complex large datasets with Python for actionable insights, using Root Cause Analysis "
    "(5 Whys) to identify recurring audit errors for stakeholder and vendor relations.",
    "At Amazon he developed internal browser-based automation workflows to reduce risks, mentored 20+ "
    "cross-functional colleagues on internal processes through SOP-based sessions and earned Employee of the "
    "Month twice.",
    "He built the Multi-Text Keyword Highlighter, a Chrome extension that detects prohibited content and restricted "
    "keywords in operations, reaching 99% accuracy and cutting manual review audit time by 97.5%.",
    "He is engineering an end-to-end ETL pipeline with Python, FastAPI and medallion (bronze/silver/gold) layers on "
    "Databricks, with automated rate limiting, price-history tracking and pytest unit tests, in a remote agile "
    "team using Git/GitHub.",
    "For his thesis he built a serverless indoor positioning Android app in Kotlin that reached 90.96% accuracy "
    "without GPS, using weighted trilateration and real-time 2D rendering over TCP/IP sockets.",
    "As a Data Analyst intern at DenizBank he supported retail and SME banking, prepared customer satisfaction "
    "reports in Excel (Pivot Tables, VLOOKUP, VBA) and ran surveys that raised satisfaction by 8%.",
]
# Seçimde öncelik: Amazon deneyimi > projeler > staj (benzerliğe eklenir).
ACHIEVEMENT_WEIGHTS = [0.04, 0.04, 0.05, 0.02, 0.0, -0.03, -0.04]

# Eşleştirmede kullanılan kısa kanıtlar (model bunları ilanın şart cümleleriyle karşılaştırır).
EVIDENCE_SHORT = [
    "Amazon: reviewed and classified products against EMEA/US regulations, safety standards and policies; "
    "risk-based compliance assessment.",
    "Amazon: analyzed large datasets in Python; Root Cause Analysis (5 Whys) of recurring audit errors, insights "
    "for stakeholders and vendors.",
    "Amazon: built browser-based automation workflows to reduce risk; SOP-based mentoring of 20+ colleagues; "
    "Employee of the Month twice.",
    "Own project: Chrome extension detecting prohibited content and restricted keywords, 99% accuracy, manual "
    "review time down 97.5%.",
    "Data engineering: ETL pipeline in Python, FastAPI and Databricks, data ingestion, pytest testing, Git, agile "
    "remote team.",
    "Thesis: Android app in Kotlin, indoor positioning over WiFi, 90.96% accuracy, real-time data processing.",
    "DenizBank (Data Analyst intern): Excel reporting with Pivot Tables, VLOOKUP and VBA; customer surveys, "
    "satisfaction up 8%.",
]

# Her kanıtın konusu (kelime kökleri, ACHIEVEMENTS ile aynı sırada). İlandaki şart cümlesi bu köklerden
# birini içermiyorsa eşleşme için çok yüksek anlamsal benzerlik gerekir: zayıf eşleşme hiç yoktan kötüdür.
EVIDENCE_TAGS = [
    ["complian", "regulat", "polic", "safety", "risk", "review", "classif", "standard", "product"],
    ["python", "analy", "dataset", "data", "root cause", "insight", "stakeholder", "vendor", "audit", "error"],
    ["automat", "workflow", "process", "sop", "procedure", "mentor", "train", "onboard", "risk"],
    ["automat", "javascript", "keyword", "content", "moderat", "manual review", "accura", "tool"],
    ["etl", "pipeline", "databricks", "fastapi", "pytest", "unit test", "git", "agile", "data engineer", "ingest"],
    ["kotlin", "android", "mobile", "app"],
    ["excel", "vba", "pivot", "vlookup", "report", "survey", "customer", "bank", "satisfaction"],
]

# Mektupta kullanılan, BİRİNCİ TEKİL şahısla yazılmış kanıtlar (ACHIEVEMENTS ile aynı sırada).
# Mektubu Alperen imzalıyor: buradaki her cümle CV'de doğrulanabilir olmalı.
EVIDENCE_FIRST = [
    "At Amazon I reviewed and classified products against EMEA and US marketplace regulations, safety standards "
    "and internal policies, to keep customers and sellers safe.",
    "I analysed large, complex datasets in Python and used root cause analysis (5 Whys) to find audit errors that "
    "kept coming back, then shared clear findings with stakeholders and vendors.",
    "I built internal browser-based automation workflows to reduce risk, mentored more than 20 colleagues through "
    "SOP-based sessions, and was named Employee of the Month twice.",
    "I wrote a Chrome extension that flags prohibited content and restricted keywords. It reached 99% accuracy "
    "and cut manual review time by 97.5%.",
    "In a data engineering community I am building an ETL pipeline with Python, FastAPI and Databricks, with "
    "pytest tests and Git, together with a remote agile team.",
    "For my master's thesis I built an Android app in Kotlin that finds a device's position indoors over WiFi, "
    "without GPS, with 90.96% accuracy.",
    "As a data analyst intern at DenizBank I prepared customer satisfaction reports in Excel (pivot tables, "
    "VLOOKUP, VBA) and ran surveys that raised satisfaction by 8%.",
]

EDUCATION = ("an MSc in Computer Science from Vizja University in Warsaw and a BSc in Mathematics from Uludag "
             "University")

BACKGROUND = (
    "Alperen holds a Master's in Computer Science from Vizja University (Warsaw) and a Bachelor's in Mathematics "
    "from Uludag University, and spent two years at Amazon Corporate Services Poland as a Compliance Associate. "
    "He speaks English (C1) and Turkish (native), is improving his Polish (A2), and needs no work permit as a "
    "Polish university graduate."
)
