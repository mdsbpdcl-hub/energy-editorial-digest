"""
Offline self-tests. They need no internet and no secrets.
Run locally:   python -m unittest discover -s tests -v
They also run automatically in GitHub Actions before every digest.
"""
import os
import smtplib
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import feedparser  # noqa: E402

import config as C  # noqa: E402
import digest as D  # noqa: E402

NOW = datetime(2026, 11, 2, 7, 45, tzinfo=D.TZ)

GN_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>"DISCOM" - Google News</title>
<item>
  <title>Why India's discoms need tariff reform now - The Hindu</title>
  <link>https://news.google.com/rss/articles/CBMiABC123?oc=5</link>
  <pubDate>Fri, 30 Oct 2026 03:30:00 GMT</pubDate>
  <description>&lt;a href="x"&gt;Why India's discoms need tariff reform now&lt;/a&gt;&amp;nbsp;&lt;font&gt;The Hindu&lt;/font&gt;</description>
  <source url="https://www.thehindu.com">The Hindu</source>
</item>
<item>
  <title>Item without date - Mint</title>
  <link>https://news.google.com/rss/articles/CBMiNODATE</link>
  <source url="https://www.livemint.com">Mint</source>
</item>
</channel></rss>"""

FILLER = ("The distribution utility must reduce AT&C losses, improve billing and collection efficiency, "
          "and rationalise the tariff and cross-subsidy structure under the regulatory commission's order. ")
ARTICLE_HTML = f"""<html><head><title>Discom reform</title>
<meta name="description" content="An analysis of why Indian DISCOMs need structural tariff reform."></head>
<body><nav><a href="/">Home</a> <a href="/news">News</a> <a href="/sports">Sports</a> Subscribe Login Menu</nav>
<div class="ad">Advertisement buy now limited offer</div>
<article><h1>Why India's discoms need tariff reform now</h1>
{''.join(f'<p>{FILLER} Paragraph {i} discusses the Ministry of Power policy, RDSS and smart meter rollout in India.</p>' for i in range(30))}
</article><footer>Copyright footer links privacy terms contact about careers</footer></body></html>"""


def make(title="Why India's discoms need tariff reform now", **kw):
    base = dict(title=title, link="https://example.org/opinion/discom-reform", publisher="The Hindu",
                published=NOW - timedelta(days=2), rss_description="")
    base.update(kw)
    return D.Article(**base)


class FakeResp:
    def __init__(self, status=200, text="", ctype="text/html; charset=utf-8", url="https://example.org/a", content=None):
        self.status_code, self.text, self.url = status, text, url
        self.headers = {"Content-Type": ctype}
        self.content = content if content is not None else text.encode()


class TestQueryAndFeeds(unittest.TestCase):
    def test_google_news_url_is_encoded(self):
        url = D.build_google_news_url('("AT&C losses" OR DISCOM) -stock', "en", days=7)
        parts = urlsplit(url)
        self.assertEqual(parts.netloc, "news.google.com")
        q = parse_qs(parts.query)
        self.assertEqual(q["q"][0], '("AT&C losses" OR DISCOM) -stock when:7d')
        self.assertEqual(q["hl"][0], "en-IN")
        self.assertEqual(q["ceid"][0], "IN:en")
        self.assertNotIn(" ", url)
        self.assertIn("%26", url)  # the & in AT&C must be encoded, not treated as a separator

    def test_hindi_params(self):
        q = parse_qs(urlsplit(D.build_google_news_url("बिजली", "hi")).query)
        self.assertEqual(q["hl"][0], "hi")
        self.assertTrue(q["q"][0].startswith("बिजली"))

    def test_parse_google_news_feed(self):
        items = D.parse_feed_entries(feedparser.parse(GN_FEED), "test")
        self.assertEqual(len(items), 2)
        a = items[0]
        self.assertEqual(a.title, "Why India's discoms need tariff reform now")   # " - The Hindu" stripped
        self.assertEqual(a.publisher, "The Hindu")
        self.assertEqual(a.rss_description, "")             # GN boilerplate description dropped
        self.assertEqual(a.published.utcoffset(), timedelta(hours=5, minutes=30))
        self.assertEqual((a.published.hour, a.published.minute), (9, 0))     # 03:30 GMT = 09:00 IST
        self.assertIsNone(items[1].published)

    def test_empty_and_unavailable_feeds(self):
        with mock.patch.object(D, "http_get", return_value=None):
            self.assertEqual(D.fetch_feed("https://x", "down"), [])
        with mock.patch.object(D, "http_get", return_value=FakeResp(500)):
            self.assertEqual(D.fetch_feed("https://x", "500"), [])
        with mock.patch.object(D, "http_get", return_value=FakeResp(200, "not xml at all <<<")):
            self.assertEqual(D.fetch_feed("https://x", "junk"), [])
        empty = '<?xml version="1.0"?><rss><channel><title>t</title></channel></rss>'
        with mock.patch.object(D, "http_get", return_value=FakeResp(200, empty)):
            self.assertEqual(D.fetch_feed("https://x", "empty"), [])


BING_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=discom&amp;format=rss"><channel>
<title>discom - BingNews</title>
<item><title>Why discoms must fix tariff design</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=abc&amp;url=https%3a%2f%2fwww.thehindu.com%2fopinion%2fdiscom-tariff%2farticle1.ece&amp;c=123&amp;mkt=en-in</link>
<description>An editorial on DISCOM tariff design and subsidies.</description>
<pubDate>Fri, 30 Oct 2026 04:00:00 GMT</pubDate>
<News:Source>The Hindu</News:Source></item>
</channel></rss>"""


class TestBingAndDecoding(unittest.TestCase):
    def test_bing_feed_gives_publisher_link(self):
        items = D.parse_feed_entries(feedparser.parse(BING_FEED), "Bing: DISCOM")
        self.assertEqual(len(items), 1)
        a = items[0]
        self.assertEqual(a.link, "https://www.thehindu.com/opinion/discom-tariff/article1.ece")
        self.assertEqual(a.publisher, "The Hindu")
        self.assertIn("tariff design", a.rss_description)

    def test_bing_url_built(self):
        q = parse_qs(urlsplit(D.build_bing_news_url('"AT&C losses"')).query)
        self.assertEqual(q["format"][0], "rss")
        self.assertEqual(q["q"][0], '"AT&C losses"')

    def test_batch_decode_used_by_resolver(self):
        g1, g2 = "https://news.google.com/rss/articles/AAA?oc=5", "https://news.google.com/rss/articles/BBB?oc=5"
        fake = mock.MagicMock(return_value={g1: "https://mercomindia.com/x", g2: None})
        with mock.patch.dict(sys.modules, {"gnews_decoder": mock.MagicMock(decode_many=fake)}), \
             mock.patch.object(D.time, "sleep"):
            D._DECODED.clear()
            self.assertEqual(D.batch_decode_google_news([g1, g2, "https://direct.in/a"]), 1)
        self.assertEqual(D.resolve_google_news(g1), "https://mercomindia.com/x")
        self.assertEqual(D.resolve_google_news("https://direct.in/a"), "https://direct.in/a")
        D._DECODED.clear()


class TestFilters(unittest.TestCase):
    def test_window(self):
        self.assertTrue(D.in_window(make(), NOW, 7))
        self.assertFalse(D.in_window(make(published=NOW - timedelta(days=8)), NOW, 7))
        self.assertFalse(D.in_window(make(published=None), NOW, 7))

    def test_noise(self):
        self.assertEqual(D.is_noise(make("Tata Power share price rises 4% after Q2 results")), "financial")
        self.assertEqual(D.is_noise(make("Sensex, Nifty end higher; power stocks gain")), "financial")
        self.assertIsNone(D.is_noise(make("Market coupling: what it means for India's power exchange")))
        self.assertEqual(D.is_noise(make("Sponsored: smart meter solutions for utilities")), "promotional")


class TestDedup(unittest.TestCase):
    def test_canonical_url(self):
        a = D.canonical_url("https://www.example.com/story/1/?utm_source=x&id=5#top")
        b = D.canonical_url("http://example.com/story/1?id=5")
        self.assertEqual(a, b)
        self.assertEqual(D.canonical_url("https://m.site.in/a/amp"), D.canonical_url("https://site.in/a"))

    def test_similar_titles_and_best_copy_kept(self):
        long_copy = make(link="https://a.in/x", word_count=1200, extract_status="ok")
        syndicated = make("Why India’s discoms need tariff reform now!", link="https://b.in/y", publisher="Other")
        different = make("Pumped storage is India's missing grid battery", link="https://c.in/z")
        kept = D.deduplicate([syndicated, different, long_copy])
        self.assertEqual(len(kept), 2)
        self.assertIn(long_copy, kept)

    def test_same_url_different_title(self):
        a = make(link="https://a.in/x?utm_medium=rss")
        b = make("Completely different headline about coal", link="https://a.in/x")
        self.assertEqual(len(D.deduplicate([a, b])), 1)


class TestExtraction(unittest.TestCase):
    def test_body_word_count_excludes_page_chrome(self):
        body, meta = D.extract_from_html(ARTICLE_HTML, "https://example.org/opinion/x")
        n = D.count_words(body)
        self.assertGreater(n, 650)
        self.assertNotIn("Advertisement", body)
        self.assertNotIn("careers", body)
        self.assertIn("DISCOMs", meta)

    def test_verify_ok(self):
        with mock.patch.object(D, "robots_allows", return_value=True), \
             mock.patch.object(D, "http_get", return_value=FakeResp(200, ARTICLE_HTML)):
            a = make()
            D.verify_article(a)
        self.assertEqual(a.extract_status, "ok")
        self.assertGreater(a.word_count, 650)

    def test_blocked_timeout_and_unresolved_keep_unknown(self):
        cases = [(FakeResp(403), "blocked_http_403"), (None, "network_error"), (FakeResp(404), "http_404")]
        for resp, status in cases:
            with mock.patch.object(D, "robots_allows", return_value=True), \
                 mock.patch.object(D, "http_get", return_value=resp):
                a = make()
                D.verify_article(a)
            self.assertEqual(a.extract_status, status)
            self.assertIsNone(a.word_count, "word count must stay Unknown when not verified")
        with mock.patch.object(D, "resolve_google_news", return_value=None):
            a = make(link="https://news.google.com/rss/articles/XYZ")
            D.verify_article(a)
        self.assertEqual(a.extract_status, "link_not_resolved")
        self.assertIsNone(a.word_count)

    def test_paywall_partial_is_unknown(self):
        html = "<html><body><article><p>" + "Discom tariff reform text. " * 30 + \
               "</p><p>Subscribe to continue reading this premium article.</p></article></body></html>"
        with mock.patch.object(D, "robots_allows", return_value=True), \
             mock.patch.object(D, "http_get", return_value=FakeResp(200, html)):
            a = make()
            D.verify_article(a)
        self.assertEqual(a.extract_status, "partial_paywall")
        self.assertIsNone(a.word_count)

    def test_pdf_detected(self):
        with mock.patch.object(D, "robots_allows", return_value=True), \
             mock.patch.object(D, "http_get", return_value=FakeResp(200, "", "application/pdf", "https://cea.nic.in/r.pdf")):
            a = make(link="https://cea.nic.in/r.pdf")
            D.verify_article(a)
        self.assertTrue(a.is_pdf)
        self.assertIsNone(a.word_count)

    def test_word_count_hindi(self):
        self.assertEqual(D.count_words("बिहार में बिजली वितरण सुधार — 2026 ."), 6)


class TestScoring(unittest.TestCase):
    def verified_article(self, **kw):
        a = make(**kw)
        a.body_text, a.meta_description = D.extract_from_html(ARTICLE_HTML, a.link)
        a.word_count = D.count_words(a.body_text)
        a.extract_status = "ok"
        D.score_article(a)
        return a

    def test_long_discom_editorial_selected(self):
        a = self.verified_article()
        self.assertGreaterEqual(a.score, C.SELECTION_THRESHOLD)
        self.assertEqual(a.category, "DISCOM Reforms")
        self.assertEqual(sum(a.breakdown.values()), a.score)
        self.assertLessEqual(a.score, 100)

    def test_deterministic(self):
        self.assertEqual(self.verified_article().score, self.verified_article().score)

    def test_bihar_bonus_and_tag(self):
        a = make("SBPDCL smart prepaid meter rollout: lessons for Bihar discoms")
        D.score_article(a)
        self.assertTrue(a.is_bihar)
        self.assertIn("Bihar Power Sector", a.tags)
        self.assertEqual(a.breakdown["bihar_bonus"], C.BIHAR_BONUS)

    def test_bangladesh_berc_not_bihar(self):
        a = make("BERC raises electricity tariff in Bangladesh", rss_description="Bangladesh Energy Regulatory Commission")
        D.score_article(a)
        self.assertFalse(a.is_bihar)

    def test_unverified_cannot_enter_main_list(self):
        a = make()
        D.score_article(a)
        a.score = 95
        buckets = D.select([a])
        self.assertEqual(buckets["selected"], [])
        self.assertEqual(buckets["headline_only"], [a])

    def test_official_goes_to_section5(self):
        a = make("CEA releases National Electricity Plan transmission report", link="https://cea.nic.in/plan.pdf",
                 publisher="CEA", is_pdf=True)
        D.score_article(a)
        self.assertTrue(a.is_official)
        self.assertEqual(D.select([a])["official"], [a])


class TestRenderingAndEmail(unittest.TestCase):
    def test_html_escaping(self):
        a = make('<script>alert("x")</script> Discom & tariff', link='https://e.org/a?x=1&y="2"',
                 word_count=900, extract_status="ok", rss_description="<b>bold</b> & more")
        D.score_article(a)
        a.score = 90
        html = D.render_html(D.build_context(D.select([a]), {"discovered": 1}, NOW))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;y=&#34;2&#34;", html)

    def test_zero_article_report(self):
        ctx = D.build_context({"selected": [], "official": [], "headline_only": [], "eligible_longform": 0}, {}, NOW)
        self.assertIn("No articles met the selection criteria", D.render_html(ctx))
        self.assertIn("No articles met the selection criteria", D.render_text(ctx))

    def test_missing_env_vars_exit(self):
        with mock.patch.dict(os.environ, {"EMAIL_USER": "", "EMAIL_PASS": "", "EMAIL_RECEIVER": ""}):
            self.assertEqual(set(D.check_email_env()), {"EMAIL_USER", "EMAIL_PASS", "EMAIL_RECEIVER"})
            with self.assertRaises(SystemExit):
                D.run(dry_run=False, articles=[])

    def test_multiple_recipients(self):
        with mock.patch.dict(os.environ, {"EMAIL_RECEIVER": "a@x.com, b@y.com;c@z.com"}):
            self.assertEqual(D.recipients_from_env(), ["a@x.com", "b@y.com", "c@z.com"])

    def test_smtp_auth_failure_raises(self):
        env = {"EMAIL_USER": "me@gmail.com", "EMAIL_PASS": "abcd efgh ijkl mnop", "EMAIL_RECEIVER": "you@x.com"}
        smtp = mock.MagicMock()
        smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        with mock.patch.dict(os.environ, env), mock.patch.object(D.smtplib, "SMTP_SSL", smtp):
            with self.assertRaises(smtplib.SMTPAuthenticationError):
                D.send_email("s", "<p>h</p>", "t")
        smtp.return_value.__enter__.return_value.login.assert_called_with("me@gmail.com", "abcdefghijklmnop")

    def test_smtp_success_multipart(self):
        env = {"EMAIL_USER": "me@gmail.com", "EMAIL_PASS": "x", "EMAIL_RECEIVER": "you@x.com"}
        smtp = mock.MagicMock()
        with mock.patch.dict(os.environ, env), mock.patch.object(D.smtplib, "SMTP_SSL", smtp):
            D.send_email("Subject", "<p>html</p>", "text")
        msg = smtp.return_value.__enter__.return_value.send_message.call_args[0][0]
        self.assertEqual(msg.get_content_type(), "multipart/alternative")


class TestWebPage(unittest.TestCase):
    def test_publish_latest_and_archive(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp) / "docs"
            D.publish_web_page("<html><body><p>Digest</p></body></html>", NOW, web)
            D.publish_web_page("<html><body><p>Digest 2</p></body></html>", NOW + timedelta(days=7), web)
            self.assertIn("Digest 2", (web / "index.html").read_text())
            self.assertIn("Past digests", (web / "index.html").read_text())
            self.assertTrue((web / "archive" / "2026-11-02.html").exists())
            listing = (web / "archive" / "index.html").read_text()
            self.assertLess(listing.index("09 November 2026"), listing.index("02 November 2026"))
            self.assertTrue((web / ".nojekyll").exists())


class TestHistory(unittest.TestCase):
    def test_round_trip(self):
        a = make(resolved_url="https://thehindu.com/opinion/discom?utm_source=rss", category="DISCOM Reforms", score=88)
        h = D.update_history({"entries": []}, [a], NOW)
        urls, titles = D.history_keys(h, NOW + timedelta(days=7), 120)
        self.assertTrue(D.already_sent(make(link="https://www.thehindu.com/opinion/discom"), urls, titles))
        self.assertTrue(D.already_sent(make(link="https://other.in/x"), urls, titles))   # same headline
        self.assertFalse(D.already_sent(make("Coal stocks at plants fall to 10-day level", link="https://z.in"), urls, titles))
        urls_old, _ = D.history_keys(h, NOW + timedelta(days=200), 120)
        self.assertEqual(urls_old, set())

    def test_corrupt_history_file(self):
        p = Path(__file__).parent / "_tmp_hist.json"
        p.write_text("{not json", encoding="utf-8")
        try:
            self.assertEqual(D.load_history(p)["entries"], [])
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
