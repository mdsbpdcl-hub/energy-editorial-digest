"""
digest.py — Energy Sector Weekly Editorial & Policy Digest.

Pipeline (each step logs its counts):
  1. Discover   : Google News RSS searches + official "site:" searches + direct RSS feeds
  2. Window     : keep items published in the last LOOKBACK_DAYS (Asia/Kolkata)
  3. Noise      : drop share-price / earnings / promotional items
  4. De-dup     : URL + normalised headline + headline similarity
  5. History    : drop articles already sent in earlier digests (optional)
  6. Verify     : resolve publisher URL, download page (robots.txt respected),
                  extract article body with Trafilatura, count words
  7. Score      : transparent 0-100 keyword model (+ Bihar bonus), classify
  8. Select     : verified >= MIN_WORD_COUNT and score >= threshold
  9. Render     : HTML + plain-text email (Jinja2 template, auto-escaped)
 10. Deliver    : Gmail SMTP (or dry-run), save history, write run summary

Usage:
  python digest.py              # full run, sends email
  python digest.py --dry-run    # full run, writes output/digest.html, sends nothing
  python digest.py --smtp-test  # only tests Gmail login and sends a short test mail
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import logging
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.robotparser
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
import requests
import trafilatura
from jinja2 import Environment, FileSystemLoader, select_autoescape

import config as C

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
TZ = ZoneInfo(C.TIMEZONE)

log = logging.getLogger("digest")


# ===========================================================================
# Data model
# ===========================================================================
@dataclass
class Article:
    title: str
    link: str                       # link as given by the feed (may be news.google.com)
    publisher: str = ""
    publisher_site: str = ""        # publisher homepage from the RSS <source> tag
    published: datetime | None = None
    rss_description: str = ""
    feed_label: str = ""
    from_official_search: bool = False
    resolved_url: str = ""          # final publisher URL after decoding/redirects
    word_count: int | None = None   # None = Unknown / not verified
    extract_status: str = "not_attempted"
    meta_description: str = ""
    body_text: str = field(default="", repr=False)
    is_pdf: bool = False
    prescore: float = 0.0
    score: int = 0
    breakdown: dict = field(default_factory=dict)
    category: str = ""
    tags: list = field(default_factory=list)
    matched_terms: list = field(default_factory=list)
    is_bihar: bool = False

    # ---- convenience -----------------------------------------------------
    @property
    def best_url(self) -> str:
        return self.resolved_url or self.link

    @property
    def domain(self) -> str:
        return host_of(self.best_url) or host_of(self.publisher_site)

    @property
    def is_official(self) -> bool:
        d = self.domain
        return self.from_official_search or any(d == o or d.endswith("." + o) for o in C.OFFICIAL_DOMAINS)

    @property
    def verified(self) -> bool:
        return self.word_count is not None

    def summary_text(self, limit: int = 300) -> str:
        """Short description from publisher metadata or RSS. Never invented."""
        for cand in (self.meta_description, self.rss_description):
            cand = clean_space(cand)
            if cand and not near_duplicate_text(cand, self.title):
                return truncate(cand, limit)
        return ""


# ===========================================================================
# Small helpers
# ===========================================================================
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
TRACKING_PARAMS = {"fbclid", "gclid", "ref", "ref_src", "cmpid", "ito", "from", "source", "ocid", "oc"}


def clean_space(text: str | None) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


def strip_html(text: str | None) -> str:
    return clean_space(html_lib.unescape(TAG_RE.sub(" ", text or "")))


def truncate(text: str, limit: int) -> str:
    text = clean_space(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:.-") + "…"


def host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def canonical_url(url: str) -> str:
    """Normalise a URL so the same article from different links compares equal."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = host_of(url)
    path = re.sub(r"/(amp|amp\.html)/?$", "", parts.path or "/")
    path = re.sub(r"/+$", "", path) or "/"
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    # news.google.com article links are identified by their path only
    if host == "news.google.com":
        query = []
    return urlunsplit(("https", host, path.lower() if host == "news.google.com" else path, urlencode(sorted(query)), ""))


def normalise_title(title: str, publisher: str = "") -> str:
    t = clean_space(title)
    if publisher and t.lower().endswith(" - " + publisher.lower()):
        t = t[: -(len(publisher) + 3)]
    else:
        t = re.sub(r"\s+[-|–]\s+[^-|–]{2,60}$", "", t)   # trailing " - Publisher"
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return clean_space(t)


def near_duplicate_text(a: str, b: str) -> bool:
    na, nb = normalise_title(a), normalise_title(b)
    if not na or not nb:
        return False
    return na == nb or nb in na and len(na) < len(nb) + 40 or SequenceMatcher(None, na, nb).ratio() > 0.85


def titles_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    if len(ta) >= 5 and len(tb) >= 5:
        jac = len(ta & tb) / len(ta | tb)
        if jac >= 0.8:
            return True
        if jac < 0.4:
            return False
    sm = SequenceMatcher(None, a, b)
    return sm.quick_ratio() >= 0.88 and sm.ratio() >= 0.88


def to_ist(struct_time) -> datetime | None:
    """feedparser gives UTC time.struct_time; convert to aware Asia/Kolkata datetime."""
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6], tzinfo=timezone.utc).astimezone(TZ)
    except (TypeError, ValueError):
        return None


_TERM_CACHE: dict[str, re.Pattern] = {}


def _term_pattern(term: str) -> re.Pattern:
    pat = _TERM_CACHE.get(term)
    if pat is None:
        t = term.strip().lower()
        if not t.isascii():
            pat = re.compile(re.escape(t))            # Hindi/₹: plain substring
        else:
            pat = re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])")
        _TERM_CACHE[term] = pat
    return pat


def matched(terms: Iterable[str], text: str) -> list[str]:
    """Distinct lexicon terms found in text (text must already be lower-case)."""
    return [t for t in dict.fromkeys(terms) if _term_pattern(t).search(text)]


# ===========================================================================
# HTTP with retries
# ===========================================================================
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": C.USER_AGENT,
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.6",
})


def http_get(url: str, *, timeout: int | None = None, retries: int | None = None, **kw) -> requests.Response | None:
    timeout = timeout or C.REQUEST_TIMEOUT
    retries = C.REQUEST_RETRIES if retries is None else retries
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, timeout=timeout, allow_redirects=True, **kw)
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return resp
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            log.warning("  network error for %s: %s", host_of(url), type(exc).__name__)
        except requests.RequestException as exc:
            log.warning("  request failed for %s: %s", host_of(url), type(exc).__name__)
            break
    return None


# ===========================================================================
# 1. Discovery
# ===========================================================================
def build_google_news_url(query: str, lang: str = "en", days: int | None = None) -> str:
    days = C.LOOKBACK_DAYS if days is None else days
    params = dict(C.GOOGLE_NEWS_HI if lang == "hi" else C.GOOGLE_NEWS_EN)
    q = f"{query} when:{days}d" if days else query
    return C.GOOGLE_NEWS_ENDPOINT + "?" + urlencode({"q": q, **params}, quote_via=quote)


def build_bing_news_url(query: str) -> str:
    params = {"q": query, "format": "rss", "setmkt": "en-IN", "setlang": "en", "qft": 'sortbydate="1"'}
    return C.BING_NEWS_ENDPOINT + "?" + urlencode(params, quote_via=quote)


def parse_feed_entries(parsed, label: str, official: bool = False) -> list[Article]:
    items: list[Article] = []
    for e in parsed.entries:
        title = strip_html(e.get("title"))
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        link = unwrap_bing(link)
        src = e.get("source") or {}
        publisher = (clean_space(src.get("title") if hasattr(src, "get") else "")
                     or clean_space(e.get("news_source", ""))
                     or clean_space(parsed.feed.get("title", "")))
        if label.startswith("Bing") and (not publisher or "bing" in publisher.lower()):
            publisher = host_of(link)
        publisher_site = (src.get("href") if hasattr(src, "get") else "") or ""
        if publisher and title.lower().endswith(" - " + publisher.lower()):
            title = title[: -(len(publisher) + 3)].strip()
        published = to_ist(e.get("published_parsed") or e.get("updated_parsed"))
        desc = strip_html(e.get("summary") or e.get("description"))
        # Google News descriptions usually just repeat "headline publisher" — drop those
        if desc and (near_duplicate_text(desc, title) or desc.lower().startswith(title.lower()[:40])):
            desc = ""
        items.append(Article(
            title=title, link=link, publisher=publisher, publisher_site=publisher_site,
            published=published, rss_description=desc, feed_label=label,
            from_official_search=official,
        ))
    return items


def fetch_feed(url: str, label: str, official: bool = False) -> list[Article]:
    resp = http_get(url)
    if resp is None:
        log.warning("  [%s] feed unavailable (network)", label)
        return []
    if resp.status_code != 200:
        log.warning("  [%s] feed returned HTTP %s", label, resp.status_code)
        return []
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        log.warning("  [%s] feed could not be parsed", label)
        return []
    items = parse_feed_entries(parsed, label, official)
    log.info("  [%s] %d items", label, len(items))
    return items


def discover() -> tuple[list[Article], dict]:
    log.info("STEP 1 — Discovering articles")
    stats = {"feeds_ok": 0, "feeds_failed": 0}
    found: list[Article] = []
    jobs = [(lbl, build_google_news_url(q, lang), False) for lbl, q, lang in C.SEARCHES]
    jobs += [(f"Official: {lbl}", build_google_news_url(q, lang), True) for lbl, q, lang in C.OFFICIAL_SEARCHES]
    jobs += [(f"Feed: {lbl}", url, False) for lbl, url in C.DIRECT_FEEDS]
    jobs += [(f"Bing: {lbl}", build_bing_news_url(q), False) for lbl, q in C.BING_SEARCHES]
    for label, url, official in jobs:
        items = fetch_feed(url, label, official)
        stats["feeds_ok" if items else "feeds_failed"] += 1
        found.extend(items)
        time.sleep(0.5)
    stats["discovered"] = len(found)
    log.info("  discovered %d raw items from %d sources (%d returned nothing)",
             len(found), len(jobs), stats["feeds_failed"])
    return found, stats


# ===========================================================================
# 2-3. Window and noise filters
# ===========================================================================
NOISE_RE = [re.compile(p, re.I) for p in C.FINANCIAL_NOISE_PATTERNS]
PROMO_RE = [re.compile(p, re.I) for p in C.PROMO_PATTERNS]


def in_window(a: Article, now: datetime, days: int) -> bool:
    if a.published is None:
        return False
    return now - timedelta(days=days) <= a.published <= now + timedelta(hours=6)


def is_noise(a: Article) -> str | None:
    text = f"{a.title} {a.rss_description}"
    if any(r.search(text) for r in NOISE_RE):
        return "financial"
    if any(r.search(a.title) for r in PROMO_RE):
        return "promotional"
    return None


# ===========================================================================
# 4. De-duplication
# ===========================================================================
def quality_key(a: Article) -> tuple:
    return (
        a.verified and (a.word_count or 0) >= C.MIN_WORD_COUNT,
        a.score or a.prescore,
        a.word_count or 0,
        source_points(a),
        -(a.published.timestamp() if a.published else 0),   # earlier = original
    )


def deduplicate(items: list[Article]) -> list[Article]:
    """Keep the best copy of each story (URL, exact title, or similar title)."""
    ordered = sorted(items, key=quality_key, reverse=True)
    kept: list[Article] = []
    seen_urls: set[str] = set()
    kept_titles: list[str] = []
    for a in ordered:
        urls = {canonical_url(a.link)}
        if a.resolved_url:
            urls.add(canonical_url(a.resolved_url))
        if urls & seen_urls:
            continue
        nt = normalise_title(a.title, a.publisher)
        if any(titles_similar(nt, t) for t in kept_titles):
            continue
        kept.append(a)
        seen_urls |= urls
        kept_titles.append(nt)
    return kept


# ===========================================================================
# 5. History (persisted in data/history.json, committed back by the workflow)
# ===========================================================================
def load_history(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        data.setdefault("entries", [])
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("  history file unreadable (%s) — starting fresh", exc)
        return {"version": 1, "entries": []}


def history_keys(history: dict, now: datetime, days: int) -> tuple[set, list]:
    cutoff = (now - timedelta(days=days)).date().isoformat()
    urls, titles = set(), []
    for e in history.get("entries", []):
        if e.get("selected_on", "") >= cutoff:
            urls.add(e.get("url_key", ""))
            titles.append(e.get("title_key", ""))
    return urls, titles


def already_sent(a: Article, urls: set, titles: list) -> bool:
    keys = {canonical_url(a.link), canonical_url(a.resolved_url)} - {""}
    if keys & urls:
        return True
    nt = normalise_title(a.title, a.publisher)
    return any(titles_similar(nt, t) for t in titles if t)


def update_history(history: dict, sent: list[Article], now: datetime) -> dict:
    today = now.date().isoformat()
    for a in sent:
        history["entries"].append({
            "url_key": canonical_url(a.resolved_url or a.link),
            "title_key": normalise_title(a.title, a.publisher),
            "title": a.title,
            "url": a.best_url,
            "publisher": a.publisher,
            "category": a.category,
            "score": a.score,
            "word_count": a.word_count,
            "published": a.published.date().isoformat() if a.published else None,
            "selected_on": today,
        })
    history["entries"] = history["entries"][-C.HISTORY_MAX_ENTRIES:]
    history["updated"] = now.isoformat(timespec="seconds")
    return history


# ===========================================================================
# 6. Verification: resolve, robots.txt, download, extract, count
# ===========================================================================
_ROBOTS: dict[str, urllib.robotparser.RobotFileParser | None] = {}
PAYWALL_CUES = re.compile(
    r"(subscribe to (continue|read)|subscriber[- ]only|premium (article|story|content)|"
    r"paywall|\"isAccessibleForFree\"\s*:\s*\"?false|sign in to (continue|read)|"
    r"already a subscriber|unlock this (article|story))", re.I)


_DECODED: dict[str, str | None] = {}


def unwrap_bing(url: str) -> str:
    """bing.com/news/apiclick.aspx?...&url=<publisher> -> publisher URL."""
    if host_of(url).endswith("bing.com"):
        target = dict(parse_qsl(urlsplit(url).query)).get("url")
        if target and target.startswith("http"):
            return target
    return url


def batch_decode_google_news(urls: list[str]) -> int:
    """Decode many news.google.com links in one batched request (handles Google's consent page).
    Results are cached for resolve_google_news(). Returns how many were resolved."""
    todo = [u for u in dict.fromkeys(urls) if host_of(u) == "news.google.com" and u not in _DECODED]
    if not todo or not C.DECODE_GOOGLE_NEWS_LINKS:
        return 0
    try:
        from gnews_decoder import decode_many
        for start in range(0, len(todo), 40):
            chunk = todo[start:start + 40]
            res = decode_many(chunk, ceid="IN:en", concurrency=8, timeout=C.REQUEST_TIMEOUT)
            for u in chunk:
                _DECODED[u] = res.get(u)
            time.sleep(1)
    except Exception as exc:
        log.warning("  batch Google News decoding failed: %s", type(exc).__name__)
    ok = sum(1 for u in todo if _DECODED.get(u))
    log.info("  Google News links resolved to publishers: %d of %d", ok, len(todo))
    return ok


def resolve_google_news(url: str) -> str | None:
    """news.google.com/rss/articles/... -> publisher URL (None if not possible)."""
    url = unwrap_bing(url)
    if host_of(url) != "news.google.com":
        return url
    if not C.DECODE_GOOGLE_NEWS_LINKS:
        return None
    if _DECODED.get(url):
        return _DECODED[url]
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url, interval=1, timeout=C.REQUEST_TIMEOUT)
        if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
            return res["decoded_url"]
        log.info("  could not decode Google News link: %s", (res or {}).get("message", "unknown")[:80])
    except Exception as exc:  # decoder depends on Google's internal endpoint
        log.info("  Google News decoder error: %s", type(exc).__name__)
    return None


def robots_allows(url: str) -> bool:
    if not C.RESPECT_ROBOTS_TXT:
        return True
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        resp = http_get(base + "/robots.txt", timeout=10, retries=0)
        if resp is None or resp.status_code >= 500 or resp.status_code == 404:
            _ROBOTS[base] = None                 # no usable robots.txt -> allowed
        elif resp.status_code in (401, 403):
            _ROBOTS[base] = None                 # robots.txt itself blocked: treat as allowed for the page check
        else:
            rp.parse(resp.text.splitlines())
            _ROBOTS[base] = rp
    rp = _ROBOTS[base]
    return True if rp is None else rp.can_fetch(C.USER_AGENT, url)


def count_words(text: str) -> int:
    return len([w for w in text.split() if any(ch.isalnum() for ch in w)])


def extract_from_html(html: str, url: str) -> tuple[str, str]:
    """Return (body_text, meta_description). body_text excludes menus/ads/nav."""
    body = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=False,
        include_links=False, favor_precision=True,
    ) or ""
    meta_desc = ""
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta is not None:
            meta_desc = clean_space(getattr(meta, "description", "") or "")
    except Exception:
        pass
    return body, meta_desc


def verify_article(a: Article) -> None:
    """Fill resolved_url, word_count, extract_status. Never guesses a word count."""
    url = resolve_google_news(a.link)
    if not url:
        a.extract_status = "link_not_resolved"
        return
    if not robots_allows(url):
        a.resolved_url = url
        a.extract_status = "robots_disallowed"
        return
    resp = http_get(url)
    if resp is None:
        a.resolved_url = url
        a.extract_status = "network_error"
        return
    a.resolved_url = resp.url or url
    if resp.status_code in (401, 402, 403, 451):
        a.extract_status = f"blocked_http_{resp.status_code}"
        return
    if resp.status_code != 200:
        a.extract_status = f"http_{resp.status_code}"
        return
    ctype = resp.headers.get("Content-Type", "").lower()
    if "pdf" in ctype or a.resolved_url.lower().endswith(".pdf"):
        a.is_pdf = True
        a.extract_status = "pdf_document"
        return
    if "html" not in ctype and "xml" not in ctype and ctype:
        a.extract_status = "not_html"
        return
    try:
        body, meta_desc = extract_from_html(resp.text, a.resolved_url)
    except Exception as exc:
        a.extract_status = f"extract_error_{type(exc).__name__}"
        return
    a.meta_description = meta_desc
    words = count_words(body)
    if words == 0:
        a.extract_status = "no_body_found"
        return
    if words < C.MIN_WORD_COUNT and PAYWALL_CUES.search(resp.text[:400000]):
        a.extract_status = "partial_paywall"     # truncated text: length unknown
        a.body_text = body[:20000]
        return
    a.word_count = words
    a.body_text = body[:20000]
    a.extract_status = "ok"


# ===========================================================================
# 7. Scoring and classification (deterministic, explainable)
# ===========================================================================
ANALYSIS_URL_RE = re.compile(r"/(opinion|opinions|editorial|editorials|columns?|analysis|explained|"
                             r"perspective|blogs?|views?|ideas|commentary|op-?ed|research|reports?|insights?)/", re.I)


def source_points(a: Article) -> int:
    d = a.domain
    pub = (a.publisher or "").lower()
    for pts in sorted(C.SOURCE_TIERS, reverse=True):
        for s in C.SOURCE_TIERS[pts]:
            s_low = s.lower()
            if "." in s_low and (d == s_low or d.endswith("." + s_low)):
                return pts
            if "." not in s_low and pub and (pub == s_low or s_low in pub):
                return pts
    return C.DEFAULT_SOURCE_POINTS


def _frac(n: float, full: float) -> float:
    return max(0.0, min(1.0, n / full))


def is_bihar(title_l: str, all_l: str) -> list[str]:
    hits_title = matched(C.BIHAR_TERMS, title_l)
    hits_all = matched(C.BIHAR_TERMS, all_l)
    if "berc" in hits_all and "bangladesh" in all_l and "bihar" not in all_l:
        hits_all = [h for h in hits_all if h != "berc"]       # Bangladesh ERC, not Bihar
        hits_title = [h for h in hits_title if h != "berc"]
    if hits_title or len(hits_all) >= 2 or ("bihar" in hits_all and all_l.count("bihar") >= 2):
        return hits_all or hits_title
    return []


def score_article(a: Article) -> None:
    title_l = a.title.lower()
    head_l = f"{a.title} {a.rss_description} {a.meta_description}".lower()
    body_l = " ".join(a.body_text.split()[:4000]).lower()
    all_l = f"{head_l} {body_l}"

    def weighted(terms):
        return len(matched(terms, all_l)) + 2 * len(matched(terms, title_l))

    power_n = weighted(C.POWER_SECTOR_TERMS)
    india_n = len(matched(C.INDIA_TERMS, all_l))
    relevance = 20 * _frac(power_n, 8) + (10 if india_n >= 2 else 6 if india_n == 1 else 2)

    wc = a.word_count
    wc_pts = 0 if wc is None else 2 if wc < 300 else 5 if wc < 650 else 10 if wc < 1000 else 13 if wc < 1500 else 15
    cue_pts = 0
    if matched(C.ANALYSIS_TERMS, title_l):
        cue_pts += 6
    if ANALYSIS_URL_RE.search(a.best_url):
        cue_pts += 6
    cue_pts += min(4, len(matched(C.ANALYSIS_TERMS, all_l)))
    if a.is_official or a.is_pdf:
        cue_pts += 4
    depth = wc_pts + min(10, cue_pts)

    policy = 20 * _frac(weighted(C.POLICY_TERMS), 6)
    discom = 15 * _frac(weighted(C.DISCOM_TERMS), 6)
    cred = source_points(a)

    bihar_hits = is_bihar(title_l, all_l)
    a.is_bihar = bool(bihar_hits)
    bonus = C.BIHAR_BONUS if a.is_bihar else 0

    a.breakdown = {
        "relevance": round(relevance), "depth": round(depth), "policy": round(policy),
        "discom": round(discom), "source": cred, "bihar_bonus": bonus,
    }
    a.score = int(min(100, round(relevance + depth + policy + discom + cred + bonus)))

    # classification
    cat_scores = {}
    for cat, terms in C.CATEGORIES.items():
        n = len(matched(terms, all_l)) + 3 * len(matched(terms, title_l))
        if n:
            cat_scores[cat] = n
    topical = {k: v for k, v in cat_scores.items() if k != "Bihar Power Sector"}
    if topical:
        a.category = max(topical, key=lambda k: (topical[k], -list(C.CATEGORIES).index(k)))
    elif a.is_bihar:
        a.category = "Bihar Power Sector"
    else:
        a.category = "Government Policy" if a.is_official else "DISCOM Reforms"
    a.tags = [k for k, v in sorted(cat_scores.items(), key=lambda kv: -kv[1])
              if (v >= 3 or k == a.category) and k != "Bihar Power Sector"][:4]
    if a.category not in a.tags:
        a.tags.insert(0, a.category)
    if a.is_bihar and "Bihar Power Sector" not in a.tags:
        a.tags.append("Bihar Power Sector")

    topic_terms = matched(C.DISCOM_TERMS, head_l) + matched(C.POLICY_TERMS, head_l) + matched(C.POWER_SECTOR_TERMS, head_l)
    if len(topic_terms) < 3:
        topic_terms += matched(C.DISCOM_TERMS, body_l) + matched(C.POLICY_TERMS, body_l)
    noise = {"how", "why", "should", "must", "unit", "load", "order", "rules", "draft", "mw", "gw", "consumer", "utility"}
    seen_stems, terms = set(), []
    for t in dict.fromkeys(topic_terms):
        stem = t[:-1] if t.endswith("s") and len(t) > 4 else t
        if t not in noise and stem not in seen_stems:
            seen_stems.add(stem)
            terms.append(t)
    a.matched_terms = terms[:6]


def prescore(a: Article) -> None:
    """Cheap score from headline + RSS text, used to decide which pages to download."""
    score_article(a)
    a.prescore = a.score + (15 if a.is_bihar else 0) + (10 if a.is_official else 0)


def relevance_note(a: Article) -> str:
    """Evidence-based 'why it matters' line built only from matched terms."""
    parts = []
    if a.breakdown.get("discom", 0) >= 9:
        parts.append("DISCOM operations")
    if a.breakdown.get("policy", 0) >= 12:
        parts.append("policy / regulation")
    if a.is_bihar:
        parts.append("Bihar")
    lead = "Relevant to " + ", ".join(parts) + "." if parts else ""
    terms = ", ".join(t.upper() if len(t) <= 4 else t for t in a.matched_terms)
    return clean_space(f"{lead} Topics found in the text: {terms}." if terms else lead)


# ===========================================================================
# 8. Selection
# ===========================================================================
def select(articles: list[Article]) -> dict:
    official, selected, headline_only = [], [], []
    for a in sorted(articles, key=lambda x: (-x.score, -(x.word_count or 0))):
        if a.is_official:
            if a.score >= C.OFFICIAL_DOC_THRESHOLD:
                official.append(a)
        elif a.verified and a.word_count >= C.MIN_WORD_COUNT and a.score >= C.SELECTION_THRESHOLD:
            selected.append(a)
        elif not a.verified and a.score >= C.HEADLINE_ONLY_THRESHOLD:
            headline_only.append(a)
    return {
        "selected": selected[: C.MAX_SELECTED_ARTICLES],
        "official": official[: C.MAX_OFFICIAL_DOCS],
        "headline_only": headline_only[: C.MAX_HEADLINE_ONLY],
        "eligible_longform": sum(1 for a in articles if a.verified and a.word_count >= C.MIN_WORD_COUNT and not a.is_official),
    }


# ===========================================================================
# 9. Rendering
# ===========================================================================
def fmt_date(d: datetime | None) -> str:
    return d.strftime("%d %b %Y") if d else "Date unknown"


def article_view(a: Article) -> dict:
    return {
        "title": a.title, "url": a.best_url, "publisher": a.publisher or a.domain or "Unknown source",
        "date": fmt_date(a.published), "category": a.category, "tags": a.tags,
        "words": f"{a.word_count:,}" if a.word_count is not None else "Unknown",
        "verified": a.verified, "score": a.score, "breakdown": a.breakdown,
        "summary": a.summary_text(), "why": relevance_note(a), "is_bihar": a.is_bihar,
        "is_pdf": a.is_pdf, "status": a.extract_status.replace("_", " "),
        "topics": [t.upper() if len(t) <= 4 else t for t in a.matched_terms[:4]],
    }


def build_context(buckets: dict, stats: dict, now: datetime) -> dict:
    selected, official, headline = buckets["selected"], buckets["official"], buckets["headline_only"]
    top = sorted(selected + official, key=lambda a: -a.score)[: C.EXEC_OVERVIEW_COUNT]
    priority = selected[: C.PRIORITY_ARTICLE_COUNT]
    rest = selected[C.PRIORITY_ARTICLE_COUNT:]
    by_cat: dict[str, list] = {}
    for a in rest:
        by_cat.setdefault(a.category, []).append(article_view(a))
    category_order = [c for c in C.CATEGORIES if c in by_cat]
    dist: dict[str, int] = {}
    for a in selected:
        dist[a.category] = dist.get(a.category, 0) + 1
    where = {id(a): (a.category if i >= C.START_HERE_COUNT else "Start Here") for i, a in enumerate(selected)}
    where.update({id(a): "Government & Regulatory" for a in official})
    where.update({id(a): "Also Noted" for a in headline})
    bihar = [dict(article_view(a), listed_in=where[id(a)])
             for a in (selected + official + headline) if a.is_bihar]
    start = now - timedelta(days=C.LOOKBACK_DAYS)
    return {
        "period": f"{start.strftime('%d %b %Y')} – {now.strftime('%d %b %Y')}",
        "generated": now.strftime("%d %b %Y, %I:%M %p IST"),
        "stats": stats,
        "eligible": buckets["eligible_longform"],
        "n_selected": len(selected),
        "n_official": len(official),
        "n_headline": len(headline),
        "n_bihar": len(bihar),
        "distribution": [(c, dist[c]) for c in C.CATEGORIES if c in dist],
        "overview": [article_view(a) for a in top],
        "priority": [article_view(a) for a in priority],
        "by_category": [(c, by_cat[c]) for c in category_order],
        "bihar": bihar,
        "official": [article_view(a) for a in official],
        "headline_only": [article_view(a) for a in headline],
        "all_links": [article_view(a) for a in selected + official],
        "start_here": [article_view(a) for a in selected[:C.START_HERE_COUNT]],
        "chapters": [(c, [article_view(a) for a in selected[C.START_HERE_COUNT:] if a.category == c])
                     for c in C.CATEGORIES
                     if any(a.category == c for a in selected[C.START_HERE_COUNT:])],
        "min_words": C.MIN_WORD_COUNT,
        "threshold": C.SELECTION_THRESHOLD,
        "lookback": C.LOOKBACK_DAYS,
    }


def render_html(ctx: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(BASE_DIR / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    return env.get_template("email.html").render(**ctx)


def render_text(ctx: dict) -> str:
    L = ["ENERGY SECTOR — WEEKLY EDITORIAL & POLICY DIGEST", f"Reporting period: {ctx['period']}", ""]
    L.append(f"Verified long-form articles (>= {ctx['min_words']} words): {ctx['eligible']} | "
             f"Selected: {ctx['n_selected']} | Govt/Regulatory: {ctx['n_official']} | Bihar-related: {ctx['n_bihar']}")
    if ctx["distribution"]:
        L.append("By topic: " + "; ".join(f"{c} {n}" for c, n in ctx["distribution"]))
    L.append("")

    def block(title, items, detail=False):
        if not items:
            return
        L.append("=" * 70)
        L.append(title.upper())
        L.append("=" * 70)
        for i, it in enumerate(items, 1):
            L.append(f"{i}. {it['title']}")
            L.append(f"   {it['publisher']} | {it['date']} | {it['category']} | words: {it['words']} | score: {it['score']}")
            if detail and it["summary"]:
                L.append(f"   {it['summary']}")
            if detail and it["why"]:
                L.append(f"   {it['why']}")
            L.append(f"   {it['url']}")
        L.append("")

    if not ctx["n_selected"] and not ctx["n_official"]:
        L.append("No articles met the selection criteria this week.")
        L.append("")
    block("1. Executive overview", ctx["overview"])
    block("2. Priority articles", ctx["priority"], detail=True)
    for cat, items in ctx["by_category"]:
        block(f"3. Reading list — {cat}", items)
    block("4. Bihar-specific coverage", ctx["bihar"])
    block("5. Government and regulatory publications", ctx["official"], detail=True)
    block("Also noted — headline only (text not verified)", ctx["headline_only"])
    L.append("Links point to the original publishers. Summaries come only from publisher/RSS metadata.")
    return "\n".join(L)


# ===========================================================================
# 10. Email
# ===========================================================================
def recipients_from_env() -> list[str]:
    raw = os.environ.get("EMAIL_RECEIVER", "")
    return [r.strip() for r in re.split(r"[,;\s]+", raw) if r.strip()]


def check_email_env() -> list[str]:
    missing = [k for k in ("EMAIL_USER", "EMAIL_PASS", "EMAIL_RECEIVER") if not os.environ.get(k, "").strip()]
    return missing


def send_email(subject: str, html_body: str, text_body: str) -> None:
    user = os.environ["EMAIL_USER"].strip()
    password = os.environ["EMAIL_PASS"].replace(" ", "").strip()   # app passwords are shown with spaces
    to = recipients_from_env()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Energy Policy Digest", user))
    msg["To"] = ", ".join(to)
    msg["Message-ID"] = make_msgid(domain=user.split("@")[-1])
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    ctx = ssl.create_default_context()
    last_exc = None
    for attempt in range(3):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=60) as s:
                s.login(user, password)
                s.send_message(msg)
            log.info("  email sent to %d recipient(s)", len(to))
            return
        except smtplib.SMTPAuthenticationError:
            log.error("  Gmail rejected the login. Check EMAIL_USER and that EMAIL_PASS is a 16-character "
                      "App Password (not your normal password) and 2-Step Verification is ON.")
            raise
        except (smtplib.SMTPException, OSError) as exc:
            last_exc = exc
            log.warning("  SMTP attempt %d failed: %s", attempt + 1, type(exc).__name__)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Email could not be sent after 3 attempts: {type(last_exc).__name__}")


# ===========================================================================
# Orchestration
# ===========================================================================
def write_step_summary(stats: dict, buckets: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    rows = "\n".join(f"| {k.replace('_', ' ')} | {v} |" for k, v in stats.items())
    sel = "\n".join(f"| {a.score} | {a.word_count or '—'} | {a.category} | {a.title[:90].replace('|', '/')} |"
                    for a in buckets["selected"][:25])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"## Energy digest run\n\n| Step | Count |\n|---|---:|\n{rows}\n\n")
        if sel:
            fh.write(f"### Selected\n\n| Score | Words | Category | Title |\n|---:|---:|---|---|\n{sel}\n")


def run(dry_run: bool = False, articles: list[Article] | None = None, now: datetime | None = None,
        verify: bool = True) -> dict:
    now = now or datetime.now(TZ)
    OUTPUT_DIR.mkdir(exist_ok=True)
    if not dry_run:
        missing = check_email_env()
        if missing:
            log.error("Missing GitHub secret(s): %s. Add them under Settings → Secrets and variables → Actions.",
                      ", ".join(missing))
            sys.exit(2)

    if articles is None:
        articles, stats = discover()
    else:
        stats = {"discovered": len(articles)}

    log.info("STEP 2 — Publication window: last %d days", C.LOOKBACK_DAYS)
    no_date = sum(1 for a in articles if a.published is None)
    articles = [a for a in articles if in_window(a, now, C.LOOKBACK_DAYS)]
    stats["in_window"] = len(articles)
    log.info("  %d in window (%d had no parseable date)", len(articles), no_date)

    log.info("STEP 3 — Removing market/earnings/promotional noise")
    kept = []
    noise_count = 0
    for a in articles:
        if is_noise(a):
            noise_count += 1
        else:
            kept.append(a)
    articles = kept
    stats["noise_removed"] = noise_count
    log.info("  removed %d, %d remain", noise_count, len(articles))

    log.info("STEP 4 — De-duplicating")
    for a in articles:
        prescore(a)
    articles = deduplicate(articles)
    stats["after_dedup"] = len(articles)
    log.info("  %d unique stories", len(articles))

    history_path = BASE_DIR / C.HISTORY_FILE
    history = load_history(history_path) if C.HISTORY_ENABLED else {"entries": []}
    if C.HISTORY_ENABLED:
        log.info("STEP 5 — Skipping articles sent in the last %d days", C.HISTORY_DEDUP_DAYS)
        h_urls, h_titles = history_keys(history, now, C.HISTORY_DEDUP_DAYS)
        before = len(articles)
        articles = [a for a in articles if not already_sent(a, h_urls, h_titles)]
        stats["skipped_history"] = before - len(articles)
        log.info("  skipped %d previously sent", stats["skipped_history"])

    log.info("STEP 6 — Verifying article text and word counts")
    articles.sort(key=lambda a: -a.prescore)
    to_fetch = articles[: C.MAX_ARTICLES_TO_FETCH] if verify else []
    if to_fetch:
        stats["google_links_resolved"] = batch_decode_google_news([a.link for a in to_fetch])
    status_counts: dict[str, int] = {}
    for i, a in enumerate(to_fetch, 1):
        verify_article(a)
        status_counts[a.extract_status] = status_counts.get(a.extract_status, 0) + 1
        log.info("  %2d/%d %-20s %6s words  %s", i, len(to_fetch), a.extract_status,
                 a.word_count if a.word_count is not None else "?", truncate(a.title, 70))
        time.sleep(C.DELAY_BETWEEN_REQUESTS)
    stats["pages_checked"] = len(to_fetch)
    stats["word_count_verified"] = sum(1 for a in articles if a.verified)
    log.info("  extraction results: %s", status_counts)

    log.info("STEP 7 — Scoring and classifying")
    for a in articles:
        score_article(a)
    if C.HISTORY_ENABLED:  # resolved URLs are known now: second history pass
        articles = [a for a in articles if not already_sent(a, h_urls, h_titles)]
    articles = deduplicate(articles)

    log.info("STEP 8 — Selecting")
    buckets = select(articles)
    stats["eligible_longform"] = buckets["eligible_longform"]
    stats["selected"] = len(buckets["selected"])
    stats["official_docs"] = len(buckets["official"])
    stats["headline_only"] = len(buckets["headline_only"])
    log.info("  selected %d | official %d | headline-only %d",
             stats["selected"], stats["official_docs"], stats["headline_only"])

    log.info("STEP 9 — Rendering email")
    ctx = build_context(buckets, stats, now)
    html_body = render_html(ctx)
    text_body = render_text(ctx)
    (OUTPUT_DIR / "digest.html").write_text(html_body, encoding="utf-8")
    (OUTPUT_DIR / "digest.txt").write_text(text_body, encoding="utf-8")
    (OUTPUT_DIR / "run_summary.json").write_text(json.dumps({
        "generated": now.isoformat(timespec="seconds"), "stats": stats,
        "articles": [{k: v for k, v in asdict(a).items() if k != "body_text"} | {"published": fmt_date(a.published)}
                     for a in sorted(articles, key=lambda x: -x.score)],
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    write_step_summary(stats, buckets)

    subject = (f"Energy Sector Weekly Digest — {now.strftime('%d %b %Y')} "
               f"({stats['selected']} analyses, {stats['official_docs']} official)")
    if dry_run:
        log.info("STEP 10 — DRY RUN: email not sent. Preview saved to output/digest.html")
    else:
        log.info("STEP 10 — Sending email")
        send_email(subject, html_body, text_body)
        if C.HISTORY_ENABLED:
            sent = buckets["selected"] + buckets["official"]
            history_path.parent.mkdir(exist_ok=True)
            history_path.write_text(json.dumps(update_history(history, sent, now), ensure_ascii=False, indent=1),
                                    encoding="utf-8")
            log.info("  history updated (%d entries)", len(history["entries"]))
        if C.PUBLISH_WEB_PAGE:
            publish_web_page(html_body, now, BASE_DIR / C.WEB_PAGE_DIR)
    return {"stats": stats, "buckets": buckets, "html": html_body, "text": text_body, "subject": subject}


# ===========================================================================
# Web page (GitHub Pages) — latest digest + archive, for embedding in Google Sites
# ===========================================================================
NAV_BAR = ('<div style="max-width:760px;margin:0 auto;padding:14px 12px 0 12px;font-family:Outfit,\'Segoe UI\',Roboto,'
           'Arial,sans-serif;font-size:13px;text-align:right;"><a href="{href}" target="_top" style="color:#0a8a76;'
           'text-decoration:none;font-weight:500;">{label}</a></div>')


def _with_nav(html: str, href: str, label: str) -> str:
    nav = NAV_BAR.format(href=href, label=html_lib.escape(label))
    return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + nav, html, count=1)


def publish_web_page(html_body: str, now: datetime, web_dir: Path) -> None:
    """Write docs/index.html (latest), docs/archive/YYYY-MM-DD.html and docs/archive/index.html."""
    archive = web_dir / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    (web_dir / ".nojekyll").write_text("", encoding="utf-8")
    day = now.date().isoformat()
    (web_dir / "index.html").write_text(_with_nav(html_body, "archive/", "Past digests →"), encoding="utf-8")
    (archive / f"{day}.html").write_text(_with_nav(html_body, "./", "← All past digests"), encoding="utf-8")
    pages = sorted((p.stem for p in archive.glob("20*.html")), reverse=True)
    items = "\n".join(
        f'<li style="padding:12px 0;border-bottom:1px solid #e4dccd;"><a href="{d}.html" style="color:#2a251f;'
        f'text-decoration:none;">Digest of {datetime.fromisoformat(d).strftime("%d %B %Y")}</a></li>'
        for d in pages)
    (archive / "index.html").write_text(
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width, initial-scale=1"><title>Energy Digest — Archive</title></head>'
        '<link href="https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,400;7..72,600&family=Outfit:wght@400;500;600&display=swap" rel="stylesheet">'
        '<body style="margin:0;background:#f3eee4;color:#2a251f;">'
        '<div style="max-width:760px;margin:22px auto;background:#fffcf6;border:1px solid #e4dccd;border-radius:14px;padding:30px;">'
        '<div style="font-family:Outfit,Segoe UI,Arial,sans-serif;font-size:12px;letter-spacing:1.8px;text-transform:uppercase;color:#0a8a76;font-weight:600;">Weekly Reading · India Power Sector</div>'
        '<div style="font-family:Literata,Georgia,serif;font-size:28px;font-weight:600;margin-top:8px;">Past Digests</div>'
        '<div style="width:44px;height:2px;background:#0a8a76;margin-top:10px;"></div>'
        '<p style="font-family:Outfit,Segoe UI,Arial,sans-serif;font-size:13px;margin:16px 0 4px;"><a href="../" target="_top" style="color:#0a8a76;text-decoration:none;font-weight:500;">← Latest digest</a></p>'
        f'<ul style="list-style:none;padding:0;margin:0;font-family:Literata,Georgia,serif;font-size:17px;">{items}</ul></div></body></html>',
        encoding="utf-8")
    log.info("  web page updated: %s/index.html (+ archive, %d issues)", C.WEB_PAGE_DIR, len(pages))


def smtp_test() -> None:
    missing = check_email_env()
    if missing:
        log.error("Missing secret(s): %s", ", ".join(missing))
        sys.exit(2)
    send_email("Energy digest — SMTP test", "<p>SMTP test successful. Your digest is ready to run.</p>",
               "SMTP test successful. Your digest is ready to run.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="Energy Sector Weekly Editorial & Policy Digest")
    p.add_argument("--dry-run", action="store_true", help="build the digest but do not send email")
    p.add_argument("--smtp-test", action="store_true", help="only test Gmail login by sending a short mail")
    args = p.parse_args()
    dry = args.dry_run or os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    if args.smtp_test:
        smtp_test()
        return
    run(dry_run=dry)


if __name__ == "__main__":
    main()
