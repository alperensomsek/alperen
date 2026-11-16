"""Aday profili — cv-alperen-simsek.pdf'ten alındı.

Eşleştirme (matcher.py) ve cover letter (letters.py) yalnızca buradaki bilgileri
kullanır. CV değişirse SADECE bu dosyayı güncelle.
İletişim bilgileri koda yazılmaz: .env (yerel) ya da GitHub Secrets'tan okunur,
böylece repo public olsa bile e-posta/telefon görünmez.
"""
import os

from dotenv import load_dotenv

load_dotenv()

NAME = "Alperen Simsek"
ASSISTANT_NAME = "ALgpt"
EMAIL = os.getenv("CANDIDATE_EMAIL", "")
PHONE = os.getenv("CANDIDATE_PHONE", "")
LINKEDIN = os.getenv("CANDIDATE_LINKEDIN", "")
LOCATION = "Warsaw, Poland"

# Model bu metni ilanlarla karşılaştırır (İngilizce, kısa ve yoğun tut).
SUMMARY = (
    "Analytical professional with an MSc in Computer Science and a BSc in Mathematics and 2 years at Amazon "
    "as Compliance Associate/Specialist. Risk and audit, compliance, quality, root cause analysis (5 Whys, Pareto), "
    "CAPA, KPI/SLA monitoring, process improvement and SOP trainings. Python and Power BI data analysis, SQL, "
    "Excel VBA/macros, browser automation tools and AI-driven workflow automation for EMEA/US risk teams. "
    "Junior to mid-level analyst, specialist or associate. English C1, Turkish native."
)

# İdeal iş tanımları: ilan bunlardan birine ne kadar benziyorsa o kadar uygun.
TARGET_ROLES = [
    "Compliance Analyst / Compliance Specialist: regulatory compliance checks, policy controls, audits, reporting.",
    "Risk Analyst: operational risk assessment, controls testing, risk reporting, KYC/AML screening.",
    "Operations Analyst: analyze operational data, KPIs and SLAs, improve workflows, reporting in Excel and Power BI.",
    "Process Improvement Specialist: lean, continuous improvement, root cause analysis, CAPA, standard operating procedures.",
    "Data Analyst / Business Analyst: SQL, Python, Power BI dashboards, data analysis and insights for stakeholders.",
    "Quality Analyst / Quality Specialist: quality audits, error analysis, corrective actions, KPI monitoring.",
    "Automation / QA Automation Specialist: Python scripts, test automation, workflow automation, browser automation.",
    "Turkish-speaking specialist: customer, operations or content role requiring native Turkish and English.",
    "Junior Python Developer / Junior Software Engineer: Python, JavaScript, automation tools, Git.",
]

# CV'deki beceriler (ilanla kesişimi "Matches" olur). Küçük harf, ilanda geçen yazımıyla.
CV_SKILLS = {
    "python", "sql", "javascript", "html", "css", "power bi", "power query", "excel", "vba", "macros",
    "pivot tables", "vlookup", "kotlin", "android", "git", "github", "aws", "powerapps", "jira",
    "microsoft office", "root cause analysis", "5 whys", "pareto", "capa", "kaizen", "continuous improvement",
    "lean", "agile", "kanban", "kpi", "sla", "compliance", "risk assessment", "audit", "auditing",
    "data analysis", "data visualization", "dashboards", "reporting", "process improvement", "automation",
    "prompt engineering", "ai", "llm", "claude", "chatgpt", "english", "turkish", "statistics", "mathematics",
    "sop", "training", "stakeholder management", "quality assurance", "quality control", "excel macros",
}

# İlanlarda aranacak beceri sözlüğü (CV'de olmayanlar "Asks for" = eksik olarak gösterilir).
SKILL_VOCAB = CV_SKILLS | {
    "tableau", "looker", "qlik", "alteryx", "sas", "spss", "r", "snowflake", "databricks", "spark",
    "airflow", "dbt", "bigquery", "azure", "gcp", "docker", "kubernetes", "terraform", "linux", "bash",
    "selenium", "playwright", "cypress", "postman", "rest api", "api", "servicenow", "confluence",
    "salesforce", "sap", "oracle", "java", "c#", ".net", "c++", "react", "angular", "typescript", "node.js",
    "scrum", "six sigma", "kyc", "aml", "gdpr", "sox", "iso 27001", "internal audit", "machine learning",
    "pandas", "numpy", "etl", "data warehouse", "jupyter", "vlookup", "accounting", "ifrs", "polish", "german",
}

# Cover letter'da kanıt olarak kullanılacak başarılar. Model ilana en uygun 2-3 tanesini seçer.
ACHIEVEMENTS = [
    "At Amazon he analyzed large, complex datasets with Python and Power BI, applying Root Cause Analysis "
    "(5 Whys) and Pareto analysis to find recurring audit errors and turn them into actionable insights for "
    "stakeholders and vendors.",
    "He developed a browser-based automation tool and an agile workflow for Amazon's EMEA/US risk teams that "
    "cut manual audit time by 26% and classified safety policies, earning him Employee of the Month twice.",
    "He led process improvements across 4+ quality teams, implementing CAPA frameworks with KPI monitoring, and "
    "trained 20+ cross-functional colleagues on internal processes through SOP-based sessions.",
    "He built the Multi-Text Keyword Highlighter, a Chrome extension written in JavaScript with AI tools, which "
    "reached 99% keyword accuracy and reduced manual review work in operations and data analysis by 97.5%.",
    "As a Data Analyst intern at DenizBank he supported retail and SME banking operations, built reports with "
    "Excel (Pivot Tables, VBA, VLOOKUP) and ran customer surveys that raised satisfaction by 8%.",
]
# Seçimde öncelik: Amazon deneyimi > proje > staj (benzerliğe eklenir).
ACHIEVEMENT_WEIGHTS = [0.04, 0.05, 0.04, 0.0, -0.04]

# "Şartınız → kanıtı" bölümünde kullanılan kısa kanıtlar (ACHIEVEMENTS ile aynı sırada).
EVIDENCE_SHORT = [
    "Amazon: analyzed large audit datasets in Python and Power BI; Root Cause (5 Whys) and Pareto analysis "
    "turned recurring errors into actions for stakeholders and vendors.",
    "Amazon: built a browser-based automation tool for EMEA/US risk teams - manual audit time down 26%, "
    "Employee of the Month twice.",
    "Amazon: led process improvement across 4+ quality teams with CAPA and KPI monitoring; trained 20+ "
    "colleagues through SOP-based sessions.",
    "Own project: Chrome extension in JavaScript + AI tools - 99% keyword accuracy, manual review work down 97.5%.",
    "DenizBank (Data Analyst intern): Excel reporting with Pivot Tables, VBA and VLOOKUP; surveys that lifted "
    "customer satisfaction by 8%.",
]

BACKGROUND = (
    "Alperen holds an MSc in Computer Science from the University of Economics and Computer Sciences in Warsaw "
    "and a BSc in Mathematics (honor student) from Uludag University, and spent two years at Amazon Corporate "
    "Services Poland as a Compliance Associate/Specialist. He speaks English (C1) and Turkish (native), is "
    "improving his Polish (A2), and is exempt from the work-permit requirement thanks to his Polish university "
    "diploma."
)
