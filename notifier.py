from __future__ import annotations

import html
import os
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

CAPTION_LIMIT = 1024  # Telegram'ın dosya açıklaması sınırı


class TelegramNotifier:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run or not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        if self.dry_run and not dry_run:
            print("⚠️ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID yok → mesajlar sadece konsola yazılacak.")
        self.base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    def _post(self, method: str, data: dict, files: dict | None = None, attempts: int = 5) -> bool:
        """429'da Telegram'ın söylediği süre kadar bekler, 5xx/bağlantı hatasında tekrar dener."""
        for attempt in range(1, attempts + 1):
            try:
                if files:
                    for f in files.values():
                        f[1].seek(0)
                res = requests.post(f"{self.base}/{method}", data=data, files=files, timeout=60)
                if res.status_code == 200:
                    return True
                if res.status_code == 429:
                    wait = res.json().get("parameters", {}).get("retry_after", 5)
                    print(f"   ⏳ Telegram rate-limit, {wait}s bekleniyor")
                    time.sleep(wait + 1)
                    continue
                if res.status_code >= 500:
                    time.sleep(3 * attempt)
                    continue
                print(f"   ⚠️ Telegram hatası ({res.status_code}): {res.text[:200]}")
                return False
            except requests.RequestException as e:
                print(f"   ⚠️ Telegram bağlantı hatası ({attempt}/{attempts}): {e}")
                time.sleep(3 * attempt)
        return False

    def send_text(self, text: str) -> bool:
        if self.dry_run:
            print("   [DRY-RUN] " + text.replace("\n", "\n             "))
            return True
        return self._post("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                                          "disable_web_page_preview": "true"})

    @staticmethod
    def build_caption(job: dict, result: dict, rank: int | None = None) -> str:
        esc = lambda v, d="": html.escape(str(v or d))
        matched = ", ".join(result.get("matched_skills", [])[:8]) or "-"
        missing = ", ".join(result.get("missing_skills", [])[:6]) or "-"
        head = f"#{rank} " if rank else ""
        note = "\n⚠️ <i>Sadece arama kartı okunabildi; ilanı kontrol et.</i>" if job.get("card_only") else ""
        posted = f" · 🗓 {esc(job.get('date_posted'))}" if job.get("date_posted") else ""
        score = result.get("match_score", 0)
        band = "🟢 Strong Fit" if score >= 85 else ("🟡 Good Fit" if score >= 75 else "🟠 Moderate Fit")
        cap = (f"{head}📌 <b>{esc(job.get('title'), 'Role')}</b>\n"
               f"🏢 {esc(job.get('company'), 'Unknown')} · 📍 {esc(job.get('city'), 'Warsaw / Remote')}{posted}\n"
               f"📊 <b>%{score}</b> {band} — {esc(result.get('reason'))}\n"
               f"✅ {esc(matched)}\n❌ Eksik: {esc(missing)}{note}\n"
               f"🌐 {esc(job.get('site', '').capitalize())}\n🔗 {esc(job.get('url'))}")
        if len(cap) > CAPTION_LIMIT:  # önce eksik/eşleşen listeleri kısalt, link asla kesilmesin
            cap = (f"{head}📌 <b>{esc(job.get('title'), 'Role')[:120]}</b>\n🏢 {esc(job.get('company'))[:60]}\n"
                   f"📊 <b>%{result.get('match_score', 0)}</b>\n🔗 {esc(job.get('url'))}")[:CAPTION_LIMIT]
        return cap

    def send_job(self, job: dict, result: dict, letter_path: str | None = None, rank: int | None = None) -> bool:
        caption = self.build_caption(job, result, rank)
        if self.dry_run:
            print(f"   [DRY-RUN] 📎 {os.path.basename(letter_path) if letter_path else '(mektup yok)'}\n"
                  + "\n".join("      " + l for l in caption.splitlines()))
            return True
        if letter_path and os.path.exists(letter_path):
            with open(letter_path, "rb") as fh:
                return self._post("sendDocument", {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                                  files={"document": (os.path.basename(letter_path), fh, "application/pdf")})
        return self.send_text(caption)
