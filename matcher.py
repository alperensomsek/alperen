"""Çevrimdışı AI eşleştirme.

Model: BAAI/bge-small-en-v1.5 (fastembed, ONNX, ~67 MB, CPU). İnternet/API/kota yok;
ilk çalışmada .models/ klasörüne bir kez iner.

Puan (0-100) = anlamsal uyum (model) + beceri karşılama oranı + başlık rolü + kıdem/Türkçe/yıl.
Model yüklenemezse (ör. çevrimdışı ilk kurulum) anlamsal kısım nötr sayılır, sistem çalışmaya devam eder.
"""
from __future__ import annotations

import os
import re

import numpy as np

import profile_data as P

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".models")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

STRONG_ROLES = [
    "compliance", "risk", "aml", "kyc", "fraud", "audit", "internal control", "controls",
    "operations analyst", "process improvement", "process analyst", "business analyst",
    "data analyst", "reporting analyst", "bi analyst", "power bi", "qa automation", "test automation",
    "automation", "turkish", "python", "regulatory", "governance", "quality analyst", "quality specialist",
    "continuous improvement", "lean",
]
MEDIUM_ROLES = [
    "analyst", "operations", "specialist", "associate", "coordinator", "quality", "qa", "tester",
    "data", "reporting", "junior developer", "junior software", "process", "excel", "android", "kotlin",
    "customer support", "onboarding", "screening", "investigat", "consultant", "officer",
]


def _skill_pattern(skill: str) -> str:
    s = re.escape(skill)
    return rf"(?<![\w.#+]){s}(?![\w#+])"


SKILL_PATTERNS = {s: re.compile(_skill_pattern(s), re.I) for s in P.SKILL_VOCAB}
# Aynı becerinin farklı yazımları tek sayılsın.
SKILL_ALIASES = {"auditing": "audit", "excel macros": "vba", "macros": "vba", "github": "git",
                 "dashboards": "data visualization", "5 whys": "root cause analysis", "pareto": "root cause analysis"}
IGNORED_FOR_COVERAGE = {"english", "polish", "german", "turkish", "microsoft office", "reporting", "ai", "api", "training"}


def extract_skills(text: str) -> set:
    found = set()
    for skill, pat in SKILL_PATTERNS.items():
        if pat.search(text):
            found.add(SKILL_ALIASES.get(skill, skill))
    return found


REQ_HINT = re.compile(
    r"\b(experience|knowledge|skills?|ability|able to|proficien|familiar|understanding|background|degree|"
    r"you will|you'll|responsib|analy[sz]|report|automat|improv|monitor|audit|complian|risk|python|sql|excel|"
    r"power bi|stakeholder|process|quality|data|kpi|support|ensure|prepare|develop|manage|coordinat)",
    re.I,
)
REQ_SKIP = re.compile(r"\b(we offer|benefit|salary|bonus|insurance|multisport|medical|holiday|office|"
                      r"apply|recruitment|equal opportunit|privacy|gdpr consent|about us|who we are)\b", re.I)


def extract_requirements(desc: str, limit: int = 40) -> list:
    """İlan metninden şart/görev cümlelerini çıkarır (madde işaretleri ve cümleler)."""
    parts = re.split(r"\n+|(?<=[.;!?])\s+(?=[A-Z])|\s+[•·▪●◦]\s+", desc or "")
    out, seen = [], set()
    for p in parts:
        t = re.sub(r"^[\s•·▪●◦\-–*\d.)]+", "", p).strip()
        if not (30 <= len(t) <= 220) or not REQ_HINT.search(t) or REQ_SKIP.search(t):
            continue
        ascii_ratio = sum(c.isascii() for c in t) / len(t)
        if ascii_ratio < 0.97 or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t.rstrip(" .;:,"))
        if len(out) >= limit:
            break
    return out


class JobMatcher:
    def __init__(self):
        self.model = None
        self.cv_vec = None
        self.role_vecs = None
        self.ach_vecs = None
        try:
            from fastembed import TextEmbedding

            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            self.model = TextEmbedding(MODEL_NAME, cache_dir=MODEL_DIR)
            self.cv_vec = self._embed([QUERY_PREFIX + P.SUMMARY])[0]
            self.role_vecs = self._embed([QUERY_PREFIX + r for r in P.TARGET_ROLES])
            self.ach_vecs = self._embed(P.ACHIEVEMENTS)
            print(f"🧠 Çevrimdışı AI modeli hazır ({MODEL_NAME}).")
        except Exception as e:
            print(f"⚠️ AI modeli yüklenemedi, sadece kural puanı kullanılacak: {e}")

    def _embed(self, texts: list) -> np.ndarray:
        v = np.array(list(self.model.embed(texts)), dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    # ------------------------------------------------------------------
    def semantic(self, job: dict):
        """0-1 arası anlamsal uyum; model yoksa None."""
        if self.model is None:
            return None, None
        text = f"{job.get('title', '')}. {job.get('description', '')[:2000]}"
        v = self._embed([text])[0]
        sim = max(float(v @ self.cv_vec), float((self.role_vecs @ v).max()))
        return sim, v

    def best_achievements(self, job_vec, n: int = 3) -> list:
        """İlana en çok benzeyen CV başarıları (cover letter için)."""
        if job_vec is None or self.ach_vecs is None:
            return P.ACHIEVEMENTS[:n]
        order = np.argsort(-(self.ach_vecs @ job_vec + np.array(P.ACHIEVEMENT_WEIGHTS)))
        return [P.ACHIEVEMENTS[i] for i in order[:n]]

    def match_requirements(self, job: dict, k: int = 3, min_sim: float = 0.62) -> list:
        """İlan metnindeki şart cümlelerini CV kanıtlarıyla eşleştirir.

        Dönüş: [(ilandan_alıntı, kanıt_metni), ...] — her kanıt en fazla bir kez, benzerliği eşiğin üstünde olanlar.
        """
        if self.model is None:
            return []
        reqs = extract_requirements(job.get("description") or "")
        if not reqs:
            return []
        rv = self._embed(reqs)
        ev = self._embed(P.EVIDENCE_SHORT)
        sims = rv @ ev.T
        pairs, used_r, used_e = [], set(), set()
        for flat in np.argsort(-sims, axis=None):
            r, e = divmod(int(flat), sims.shape[1])
            if sims[r, e] < min_sim or len(pairs) >= k:
                break
            if r in used_r or e in used_e:
                continue
            used_r.add(r)
            used_e.add(e)
            pairs.append((reqs[r], P.EVIDENCE_SHORT[e]))
        return pairs

    def best_task(self, job: dict, exclude: set, verb_re) -> str:
        """İlanın görev cümlelerinden (fiille başlayan, gösterilmemiş) CV'ye en yakın olanı."""
        reqs = [r for r in extract_requirements(job.get("description") or "")
                if verb_re.match(r) and r not in exclude and len(r) <= 140]
        if not reqs:
            return ""
        if self.model is None:
            return reqs[0]
        sims = self._embed(reqs) @ self.cv_vec
        return reqs[int(np.argmax(sims))]

    # ------------------------------------------------------------------
    def score(self, job: dict, required_years=None) -> dict:
        title = (job.get("title") or "").lower()
        desc = job.get("description") or ""
        text = f"{title}\n{desc}"

        sim, job_vec = self.semantic(job)
        # bge-small'da hedef rollerle 0.70+ çok iyi, 0.50 altı alakasız.
        sem = 0.5 if sim is None else min(max((sim - 0.50) / 0.20, 0.0), 1.0)

        ad_skills = extract_skills(text) - IGNORED_FOR_COVERAGE
        cv_skills = {SKILL_ALIASES.get(s, s) for s in P.CV_SKILLS}
        matched = sorted(ad_skills & cv_skills)
        missing = sorted(ad_skills - cv_skills)
        # Laplace yumuşatma: 3 beceri listeleyen ilanda tek eksik oranı aşırı düşürmesin.
        coverage = (len(matched) + 1) / (len(ad_skills) + 2) if len(ad_skills) >= 2 else 0.5

        role = next((r for r in STRONG_ROLES if re.search(rf"\b{re.escape(r)}", title)), None)
        role_pts = 25 if role else 0
        if not role:
            role = next((r for r in MEDIUM_ROLES if re.search(rf"\b{re.escape(r)}", title)), None)
            role_pts = 14 if role else 0

        score = 35 * sem + 25 * coverage + role_pts
        if re.search(r"\b(junior|jr\.?|entry[- ]level|graduate|associate)\b", title):
            score += 8
        if re.search(r"\b(senior|sr\.?)\b", title):
            score -= 20
        turkish = bool(re.search(r"\bturkish\b|\bturkey\b|türk", text, re.I))
        if turkish:
            score += 12
        if required_years is not None and required_years <= 3:
            score += 5
        if job.get("card_only"):
            score -= 5  # sadece kart bilgisi var: daha temkinli
        if not role:
            score = min(score, 64)
        score = int(round(max(0, min(score, 99))))

        reasons = []
        if sim is not None:
            reasons.append(f"AI fit {sem:.0%}")
        if len(ad_skills) >= 2:
            reasons.append(f"has {len(matched)}/{len(ad_skills)} listed skills")
        if role:
            reasons.append(f"title: {role}")
        if turkish:
            reasons.append("Turkish")
        if required_years is not None:
            reasons.append(f"asks {required_years}+ yrs")
        return {
            "match_score": score,
            "semantic": None if sim is None else round(sim, 3),
            "matched_skills": matched,
            "missing_skills": missing,
            "skill_total": len(ad_skills),
            "reason": "; ".join(reasons),
            "job_vec": job_vec,
            "engine": "ai" if sim is not None else "rules",
        }
