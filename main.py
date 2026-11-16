"""ALgpt — günlük iş ilanı botu.

  python main.py                         # tam çalışma: tara → puanla → en iyi ilanları mektupla gönder
  python main.py --dry-run               # Telegram'a gönderme, hafızayı kaydetme (mektuplar yine yazılır)
  python main.py --folders turkish --max-minutes 10
  python main.py --send-only             # taramadan, kuyruktaki ilanları gönder
  python main.py --dump jobs.jsonl       # analiz edilen her ilanı dosyaya yaz (puan ayarı için)
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from analyzer import JobAnalyzer
from config import (DAILY_SEND_LIMIT, MIN_MATCH_SCORE, PENDING_TTL_DAYS, RUN_TIME_BUDGET_MIN, SEEN_TTL_DAYS,
                    SENT_TTL_DAYS, WRITE_COVER_LETTERS)
from notifier import TelegramNotifier
from scraper import ALL_JOB_LINKS, JobScraper
from state import JobState

SENT_LOG_FILE = "sent_messages.txt"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def append_to_sent_log(job: dict, score: int):
    try:
        with open(SENT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write("----------------------------------------\n"
                    f"Role: {job.get('title')}\nCompany: {job.get('company')}\nMatch Score: %{score}\n"
                    f"URL: {job.get('url')}\nDate Added: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "----------------------------------------\n\n")
    except Exception as e:
        print(f"⚠️ Kütüğe yazılamadı: {e}")


def parse_args():
    p = argparse.ArgumentParser(description="ALgpt: Polonya iş ilanı tarayıcı + cover letter + Telegram")
    p.add_argument("--folders", nargs="*", choices=list(ALL_JOB_LINKS), help="Sadece bu klasörler")
    p.add_argument("--sites", nargs="*", help="Sadece URL'sinde bu parça geçen siteler (örn. pracuj.pl)")
    p.add_argument("--max-minutes", type=float, default=RUN_TIME_BUDGET_MIN, help="Tarama süre bütçesi")
    p.add_argument("--max-per-page", type=int, default=None)
    p.add_argument("--limit", type=int, default=DAILY_SEND_LIMIT, help="En fazla gönderilecek ilan (0 = sınırsız)")
    p.add_argument("--min-score", type=int, default=MIN_MATCH_SCORE)
    p.add_argument("--dry-run", action="store_true", help="Telegram'a gönderme, hafızayı kaydetme")
    p.add_argument("--send-only", action="store_true", help="Tarama yapma, sadece kuyruğu gönder")
    p.add_argument("--no-letters", action="store_true", help="Cover letter üretme")
    p.add_argument("--dump", help="Analiz edilen ilanları JSONL olarak bu dosyaya yaz")
    return p.parse_args()


def scan(args, state, analyzer, counts):
    kwargs = {"max_per_page": args.max_per_page} if args.max_per_page else {}
    scraper = JobScraper(state, prefilter=analyzer.title_prefilter, folders=args.folders, sites=args.sites,
                         deadline=time.monotonic() + args.max_minutes * 60, **kwargs)
    dump = open(args.dump, "a", encoding="utf-8") if args.dump else None
    last_save = time.monotonic()
    try:
        for job in scraper.iter_jobs():
            counts["analyzed"] += 1
            result = analyzer.evaluate_job(job)
            score = result["match_score"]
            flag = "✅" if score >= args.min_score else ("⛔" if score == 0 else "·")
            print(f"   {flag} %{score:<3} {job['title'][:70]} @ {job['company'][:30]} — {result['reason'][:90]}")
            if dump:
                dump.write(json.dumps({**{k: v for k, v in job.items() if k != 'description'},
                                       "desc": job.get("description", "")[:600],
                                       **{k: v for k, v in result.items() if k != "job_vec"}}, ensure_ascii=False) + "\n")
            if score == 0:
                counts["rejected"] += 1
            elif score < args.min_score:
                counts["below"] += 1
            elif state.is_sent(job["title"], job["company"]):
                counts["duplicate"] += 1
            else:
                counts["qualified"] += 1
                job = {**job, "description": job.get("description", "")[:3000]}
                state.add_pending(job, result)
            if not args.dry_run and time.monotonic() - last_save > 60:
                state.save()
                last_save = time.monotonic()
    except KeyboardInterrupt:
        print("\n⏹️ Tarama elle durduruldu; bulunan ilanlar yine de gönderilecek.")
    except Exception as e:
        print(f"\n💥 Tarama hatası: {e!r}; bulunan ilanlar yine de gönderilecek.")
    finally:
        if dump:
            dump.close()
        scraper.print_health_report()
    return scraper


def send_pending(args, state, analyzer, notifier, counts):
    queue = sorted(state.pending.items(), key=lambda kv: -kv[1]["result"].get("match_score", 0))
    if not queue:
        print("\n📭 Gönderilecek yeni ilan yok.")
        return
    todo = queue[: args.limit] if args.limit else queue
    print(f"\n📨 {len(queue)} uygun ilan kuyrukta; en iyi {len(todo)} tanesi gönderiliyor"
          + (" (cover letter ile)" if not args.no_letters else "") + "...")
    notifier.send_text(f"🤖 <b>ALgpt</b> — bugün {len(todo)} ilan"
                       + (" + cover letter" if not args.no_letters else "")
                       + (f" (kuyrukta {len(queue) - len(todo)} tane daha)" if len(queue) > len(todo) else ""))
    from letters import write_letter_pdf

    for rank, (key, item) in enumerate(todo, 1):
        job, result = item["job"], item["result"]
        if state.is_sent(job["title"], job["company"]):
            state.pop_pending(key)
            continue
        letter = None
        if not args.no_letters:
            try:
                letter = write_letter_pdf(job, result, analyzer.matcher)
            except Exception as e:
                print(f"   ⚠️ Cover letter yazılamadı ({job['title']}): {e}")
        if notifier.send_job(job, result, letter, rank=rank):
            counts["sent"] += 1
            state.mark_sent(job["title"], job["company"], job["url"])
            state.pop_pending(key)
            if not args.dry_run:
                append_to_sent_log(job, result.get("match_score", 0))
        else:
            counts["send_failed"] += 1
        time.sleep(1.1)  # Telegram: sohbet başına ~1 mesaj/sn


def main():
    args = parse_args()
    started = time.monotonic()
    print("=" * 60)
    print(f"🤖 ALgpt | bütçe {args.max_minutes:.0f} dk | baraj %{args.min_score} | limit {args.limit or 'yok'}"
          + (" | DRY-RUN" if args.dry_run else ""))
    print("=" * 60)
    if args.no_letters is False and not WRITE_COVER_LETTERS:
        args.no_letters = True

    state = JobState(seen_ttl_days=SEEN_TTL_DAYS, sent_ttl_days=SENT_TTL_DAYS)
    state.prune(PENDING_TTL_DAYS)
    notifier = TelegramNotifier(dry_run=args.dry_run)
    if notifier.dry_run and not args.dry_run:
        print("⚠️ Telegram ayarları eksik → DRY-RUN moduna geçildi, hafıza kaydedilmeyecek.")
        args.dry_run = True
    analyzer = JobAnalyzer()

    counts = dict.fromkeys(["analyzed", "rejected", "below", "duplicate", "qualified", "sent", "send_failed"], 0)
    scraper = None
    try:
        if not args.send_only:
            scraper = scan(args, state, analyzer, counts)
        send_pending(args, state, analyzer, notifier, counts)
    finally:
        if not args.dry_run:
            state.save()
            print(f"💾 Hafıza kaydedildi: {len(state.seen)} URL, {len(state.sent)} gönderim, {len(state.pending)} kuyrukta.")

    minutes = (time.monotonic() - started) / 60
    summary = (f"{counts['analyzed']} ilan incelendi → {counts['qualified']} uygun, {counts['sent']} gönderildi | "
               f"elenen {counts['rejected']}, baraj altı {counts['below']}, tekrar {counts['duplicate']}"
               + (f", gönderilemeyen {counts['send_failed']}" if counts["send_failed"] else "")
               + f" | kuyrukta {len(state.pending)} | {minutes:.0f} dk"
               + (" | ⏱️ süre doldu, yarın kaldığı yerden" if scraper and scraper.stopped_early else ""))
    print("\n" + "=" * 60 + f"\n🏁 {summary}\n" + "=" * 60)
    notifier.send_text(f"🏁 <b>Seans bitti</b>\n{summary}")


if __name__ == "__main__":
    main()
