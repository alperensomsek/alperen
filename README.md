# ALgpt: İş İlanı Botu

ALgpt, Polonya'daki iş ilanı sitelerini her gün Word dosyandaki sırayla, **sayfa sayfa** tarar. Her ilanı CV'ne göre **çevrimdışı bir AI modeliyle** puanlar. Uygun bulduğu **her** ilan için o ilana özel bir cover letter yazar (`alperen-simsek-<pozisyon>-letter.pdf`) ve onu ilanla birlikte Telegram'a gönderir.

```
scraper.py (gerçek Chrome, sayfalama)  →  analyzer.py (eleme)  →  matcher.py (AI puanı)
                                                                        ↓
                    Telegram  ←  notifier.py  ←  letters.py (ilana özel PDF)
```

## Nasıl çalışır

**1. Tarama** ([scraper.py](scraper.py))
- 14 klasörü (turkish → operations → … → last 24 hours) Word sırasıyla gezer. Süre dolarsa kaldığı link şifreli hafızaya yazılır ve ertesi gün oradan devam eder.
- **Sayfalama:** her aramada sonuç sayfalarını tek tek geçer. Yöntemler 14.11.2026'da canlı test edildi:

| Site | Yöntem | Test sonucu |
|---|---|---|
| TheProtocol | `pageNumber=` | 10 sayfa, 492 ilan |
| NoFluffJobs | `page=` | 6 sayfa, 100 ilan |
| Talent.com | `p=` | 6 sayfa |
| JobLeads, CareersInPoland, JustJoin | `page=` | ✓ |
| Michael Page | `page=` (0'dan başlar) | ✓ |
| Pracuj.pl | `pn=` | ✓ |
| LinkedIn | herkese açık guest API, 10'ar ilan | 25 sayfaya kadar (250 ilan) |
| Glassdoor | "Load more" butonu | 30 → 60 |
| Amazon, Bulldogjob, HiringCafe | "Next" butonu | 50 / 200 / 184 |
| Indeed | yalnızca 1. sayfa | 2. sayfa giriş istiyor |
| RocketJobs | yalnızca ~50 ilan | sayfa yok |

- **Durma koşulları:** yeni ilan çıkmayınca, üst üste 2 sayfanın tamamı önceki günlerde görülmüşse ya da `MAX_PAGES` (10) dolunca durur. İlk çalışma derine iner, sonraki günler sadece yeni ilanlara kadar gider.
- Kaydırırken kartlar biriktirilerek toplanır. Kaydırdıkça eski kartları silen listelerde de ilan kaçmaz.
- **Engel aşma:** `patchright` + gerçek Google Chrome + görünür pencere (ekran dışında, sunucuda sanal ekranda).
  - Headless'ta engellenen Pracuj, Indeed, Glassdoor ve JobLeads bu kurulumla açıldı.
  - Tarayıcı profili kalıcıdır: çerez onayları ve Cloudflare izinleri hatırlanır.
  - Geçilemeyen detay sayfalarında ilan, arama kartı bilgisiyle yine değerlendirilir.

**2. Eleme** ([analyzer.py](analyzer.py))
- Lehçe ya da İngilizce/Türkçe dışında yazılmış ilanlar elenir.
- Lehçe (B2+), Almanca vb. dil şartı olan ilanlar elenir.
- 3 yıldan fazla tecrübe isteyen, Senior/Manager/Lead, staj ve Java/.NET/SAP gibi teknolojiler içeren ilanlar elenir.

**3. Çevrimdışı AI puanı** ([matcher.py](matcher.py))
- Model `BAAI/bge-small-en-v1.5` (~67 MB, CPU). API, kota ve internet gerektirmez.
- Puan dört parçadan oluşur: anlamsal uyum, ilanın istediği becerilerden sende olanların oranı, başlıktaki rol ve kıdem/Türkçe/tecrübe yılı.
- Barajı (`MIN_MATCH_SCORE` = 70) geçen **bütün** ilanlar gönderilir; günlük sınır yok (`DAILY_SEND_LIMIT=0`).

**4. İlana özel cover letter** ([letters.py](letters.py))
- **Dosya adı:** `alperen-simsek-compliance-analyst-financial-crime-letter.pdf`. Her ilan ayrı klasörde üretilir, aynı isimli pozisyonlar çakışmaz.
- **ATS uyumu:** gerçek metin PDF, standart font, tek sütun. Pozisyon ve şirket adı birebir geçer, ilanın anahtar becerileri metinde yer alır. PDF meta verisinde başlık, konu ve anahtar kelimeler bulunur.
- **İşe alımcı için:**
  - ALgpt'nin kendini tanıttığı bir giriş.
  - **"Your requirements, his evidence"** bölümü: model ilan metninden şart cümlelerini çıkarır, CV'ne en çok benzeyen 2-3 tanesini **birebir alıntılar** ve her birinin altına CV'den kanıtı yazar.
  - Gerçek puan ve eşleşen becerilerle bir **ALgpt Match Report** kutusu ve referans numarası.
- Her iddia [profile_data.py](profile_data.py)'den (CV) gelir. Uydurma beceri ya da rakam yoktur.

## Online kurulum: GitHub Actions (public repo, ücretsiz ve sınırsız)

Public repolarda GitHub Actions dakikası **sınırsızdır** ve tek iş 6 saate kadar sürebilir. Daha önce yaşadığın "dakika bitti" sorunu private repo kotasından kaynaklanıyordu; Groq token sorunu da artık yok. Kişisel bilgiler koda yazılmaz:

1. Repo'yu GitHub'a **public** olarak push'la. `.env`, `state.json` ve `output/` `.gitignore`'da olduğu için gitmez. `state.json.enc` (şifreli hafıza) gider.
2. *Settings → Secrets and variables → Actions → New repository secret* ile şunları ekle:

   | Secret | Değer |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | @BotFather'dan aldığın token |
   | `TELEGRAM_CHAT_ID` | sohbet ID'n |
   | `STATE_KEY` | yereldeki `.env` dosyasındaki `STATE_KEY` değeri (**aynısı** olmalı, yoksa hafıza açılmaz) |
   | `CANDIDATE_EMAIL` / `CANDIDATE_PHONE` / `CANDIDATE_LINKEDIN` | mektup başlığındaki iletişim bilgileri |

3. *Actions* sekmesinde **ALgpt Daily Jobs → Run workflow** ile ilk testi yap. Sonra her gün 05:17 UTC'de kendiliğinden çalışır.

Güvenceler:
- **Sessiz kalmaz:** iş hata verirse Telegram'a "⚠️ ALgpt hata verdi" mesajı ve log linki gelir.
- **Kapanmaz:** GitHub, 60 gün aktivite olmayan repolarda zamanlanmış işleri durdurur. Bot her gün hafızayı commit'lediği için repo hep aktif kalır.
- **Kontrol edilebilir:** her çalışmanın logunda site sağlık raporu var. GitHub sunucularının IP'si ev IP'sine göre Cloudflare'e daha sık takılabilir; ilk günlerde rapora bak.
- **İsim görünür:** public repoda kodla birlikte adın ve CV özetin (`profile_data.py`) görünür, LinkedIn profilin gibi. E-posta, telefon ve başvuru geçmişi görünmez.

### Alternatif: kendi sunucun (Oracle Cloud "Always Free")

Oracle Cloud'un ücretsiz katmanında süresiz bir Ubuntu sunucusu açılabilir (kayıtta kart doğrulaması ister). Repo'yu sunucuya klonla, `.env` dosyasını oluştur ve şunu çalıştır:

```bash
bash deploy/linux_vm_setup.sh     # Chrome + sanal ekran + Python ortamı + günlük cron
```

Kendi bilgisayarında çalıştırmak için de `install_task.ps1` hâlâ duruyor. Hangi yolu seçersen seç **yalnızca birini** kullan: hafızalar ayrı olduğu için ikisi birden çalışırsa aynı ilanlar iki kez gelir.

## Yerel kullanım

```bash
pip install -r requirements.txt
python main.py                       # tam çalışma
python main.py --dry-run             # Telegram'a gönderme, hafızayı kaydetme; PDF'ler output/letters/'a yazılır
python main.py --folders turkish --max-minutes 20
python main.py --sites pracuj.pl linkedin
python main.py --min-score 65 --limit 50
python -m pytest -q tests
```

## Ayarlar ([config.py](config.py))

| Ayar | Varsayılan | Etki |
|---|---|---|
| `MIN_MATCH_SCORE` | 70 | Gönderim barajı |
| `DAILY_SEND_LIMIT` | 0 (sınırsız) | Bir çalışmada en fazla kaç ilan |
| `MAX_PAGES` / `LINKEDIN_MAX_PAGES` | 10 / 25 | Arama başına en fazla sayfa |
| `STOP_AFTER_SEEN_PAGES` | 2 | Üst üste bu kadar sayfa tamamen görülmüşse dur |
| `RUN_TIME_BUDGET_MIN` | 120 (GitHub'da 240) | Tarama süresi |
| `BROWSER_WINDOW` | offscreen | İzlemek için `visible` |

CV değişirse yalnızca [profile_data.py](profile_data.py)'yi güncelle.

## Bilinen sınırlar

- Günlük ilan sayısı yeni ilan akışına bağlıdır. Testlerde detayı okunan ilanların ~%20'si uygun çıktı.
- Siteler tasarımını değiştirirse seçiciler bozulabilir. Sağlık raporunda birkaç gün "❌ ilan linki yok" görünen sitenin `CARD_SELECTORS`/`PAGINATION` ayarı güncellenmeli.
- Mektuplar ilana göre uyarlanır, ama yapısı her ilanda aynıdır. **Göndermeden önce oku.**
