import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


# ==========================================
# 🔑 TELEGRAM (tek gereken gizli bilgi)
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ==========================================
# ⚙️ ELEME & PUANLAMA
# ==========================================
MIN_MATCH_SCORE = int(os.getenv("MIN_MATCH_SCORE", "70"))  # Telegram'a gitmesi için gereken puan (0-100)
MAX_YEARS_EXPERIENCE = 3       # İlan bundan fazla yıl tecrübe istiyorsa elenir
DAILY_SEND_LIMIT = int(os.getenv("DAILY_SEND_LIMIT", "0"))  # 0 = sınırsız: barajı geçen HER ilan gönderilir
PENDING_TTL_DAYS = 7           # Limit yüzünden gönderilemeyen ilanlar kaç gün kuyrukta bekler
WRITE_COVER_LETTERS = _env_bool("WRITE_COVER_LETTERS", True)

# ==========================================
# 🌐 TARAYICI (Cloudflare için gerçek Chrome + görünür pencere)
# ==========================================
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")   # sistemdeki Google Chrome
HEADLESS = _env_bool("HEADLESS", False)                    # True yaparsan Cloudflare'li siteler engellenir
BROWSER_WINDOW = os.getenv("BROWSER_WINDOW", "offscreen")  # "offscreen" = ekran dışı, "visible" = izle
BROWSER_PROFILE_DIR = os.getenv("BROWSER_PROFILE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".browser-profile"))
REQUEST_DELAY = (1.0, 2.2)     # Detay sayfaları arası bekleme (siteleri yormamak için)
MAX_JOBS_PER_SITE = 0          # 0 = sınırsız: bir aramada kaç yeni ilan varsa hepsi incelenir
MAX_PAGES = int(os.getenv("MAX_PAGES", "10"))  # Her aramada en fazla kaç sonuç sayfası gezilir
LINKEDIN_MAX_PAGES = 25        # LinkedIn sayfası 10 ilan: 25 sayfa = 250 ilan
COMPANY_MAX_PAGES = int(os.getenv("COMPANY_MAX_PAGES", "3"))  # Şirket kariyer sayfalarında (~200 şirket) en fazla sayfa
STOP_AFTER_SEEN_PAGES = 2      # Üst üste bu kadar sayfanın tamamı önceden görülmüşse daha derine inme
RUN_TIME_BUDGET_MIN = float(os.getenv("RUN_TIME_BUDGET_MIN", "120"))  # Süre dolarsa kaldığı yerden devam eder

# Yalnızca gerçekten taranamayan ya da kopya üreten siteler.
DISABLED_SITES = [
    "xpatjobs.com",  # Kendi ilanı yok: bütün linkler pl.talent.com/redirect (Talent.com zaten taranıyor)
]

# ==========================================
# 🧠 HAFIZA
# ==========================================
SEEN_TTL_DAYS = 45
SENT_TTL_DAYS = 180

# ==========================================
# 🏢 FİRMA AYARLARI
# ==========================================
BLACK_LIST_COMPANIES = []  # Bu şirketlerin ilanları gönderilmez (küçük/büyük harf duyarsız)
