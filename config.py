"""
config.py — every setting you are likely to change lives in this one file.

You can edit this file directly in the GitHub website (open the file, click the
pencil icon, change a value, click "Commit changes"). The next run uses it.
"""

# ---------------------------------------------------------------------------
# 1. REPORTING WINDOW AND LIMITS
# ---------------------------------------------------------------------------
TIMEZONE = "Asia/Kolkata"
LOOKBACK_DAYS = 7                 # rolling publication window
MIN_WORD_COUNT = 650              # strict long-form threshold (verified words only)
SELECTION_THRESHOLD = 70          # score (0-100) needed for the main digest
HEADLINE_ONLY_THRESHOLD = 55      # score needed for "headline-only" list (unverified text)
OFFICIAL_DOC_THRESHOLD = 40       # score needed for Government & Regulatory section
MAX_SELECTED_ARTICLES = 25        # cap on verified articles in the digest
MAX_HEADLINE_ONLY = 10            # cap on unverified "also noted" items
MAX_OFFICIAL_DOCS = 12            # cap on government/regulatory items
EXEC_OVERVIEW_COUNT = 8           # items in Executive Overview (5-10)
PRIORITY_ARTICLE_COUNT = 10       # items shown in full detail in Section 2

# ---------------------------------------------------------------------------
# 2. NETWORK BEHAVIOUR (polite, bounded)
# ---------------------------------------------------------------------------
MAX_ARTICLES_TO_FETCH = 90        # max article pages downloaded per run
REQUEST_TIMEOUT = 20              # seconds per HTTP request
REQUEST_RETRIES = 2               # retries on timeouts / 5xx
DELAY_BETWEEN_REQUESTS = 1.0      # seconds between article downloads
DECODE_GOOGLE_NEWS_LINKS = True   # resolve news.google.com links to publisher URLs
RESPECT_ROBOTS_TXT = True         # skip pages a site's robots.txt disallows
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 EnergyDigestBot/1.0 (weekly personal reading digest)"
)

# ---------------------------------------------------------------------------
# 3. HISTORY (avoid re-sending the same article)
# ---------------------------------------------------------------------------
HISTORY_ENABLED = True            # set False to disable (workflow then commits nothing)
HISTORY_FILE = "data/history.json"
HISTORY_DEDUP_DAYS = 120          # don't re-send an article seen within this many days
HISTORY_MAX_ENTRIES = 1500        # older entries are pruned automatically

# ---------------------------------------------------------------------------
# 3b. WEB PAGE (for GitHub Pages / embedding in Google Sites)
#     After each successful send, the digest is also saved as docs/index.html
#     (latest) and docs/archive/YYYY-MM-DD.html. Turn on GitHub Pages
#     (Settings -> Pages -> branch "main", folder "/docs") to get a web address.
# ---------------------------------------------------------------------------
PUBLISH_WEB_PAGE = True
WEB_PAGE_DIR = "docs"

# ---------------------------------------------------------------------------
# 4. GOOGLE NEWS RSS SEARCHES
#    The engine adds "when:7d" automatically (uses LOOKBACK_DAYS).
#    Each search is run separately; results are merged and de-duplicated.
# ---------------------------------------------------------------------------
GOOGLE_NEWS_ENDPOINT = "https://news.google.com/rss/search"
GOOGLE_NEWS_EN = {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
GOOGLE_NEWS_HI = {"hl": "hi", "gl": "IN", "ceid": "IN:hi"}

# The master query from the brief. Kept, but Google may truncate very long
# Boolean queries, so the topic-specific searches below do most of the work.
# Note: we deliberately do NOT exclude "market" (it would drop power-market and
# energy-exchange analysis). Stock-market noise is removed later by the filter.
MASTER_QUERY = (
    '("DISCOM" OR "power distribution" OR "tariff revision" OR "AT&C losses" OR '
    '"power generation" OR "thermal capacity" OR "renewable integration" OR '
    '"grid stability" OR "PPA" OR "CERC" OR "CEA" OR "RDSS" OR "Ministry of Power") '
    '("editorial" OR "opinion" OR "analysis" OR "perspective" OR "whitepaper" OR '
    '"deep dive" OR "policy") -stock -share -quarterly -nifty -sensex'
)

ANALYSIS_WORDS = '(editorial OR opinion OR analysis OR column OR explained OR perspective OR "deep dive")'

SEARCHES = [
    # (label, query, language-params)
    ("Master query", MASTER_QUERY, "en"),
    # Priority 1 — DISCOM and distribution
    ("DISCOM finances", f'(DISCOM OR discoms OR "distribution utilities") (losses OR debt OR viability OR reform) {ANALYSIS_WORDS}', "en"),
    ("AT&C / billing", '("AT&C losses" OR "billing efficiency" OR "collection efficiency" OR "ACS-ARR gap")', "en"),
    ("Tariff & subsidy", '("electricity tariff" OR "power tariff" OR "tariff order" OR "cross-subsidy" OR "power subsidy") India', "en"),
    ("Smart meters", '("smart meter" OR "smart prepaid meter" OR "AMI" OR "prepaid metering") (DISCOM OR electricity) India', "en"),
    ("RDSS", '("RDSS" OR "Revamped Distribution Sector Scheme")', "en"),
    ("Privatisation", '("power distribution privatisation" OR "distribution franchisee" OR "discom privatisation" OR "privatization of discoms")', "en"),
    ("Reliability", '("feeder" OR "outage" OR "power cuts" OR "supply reliability") (DISCOM OR distribution) analysis India', "en"),
    ("Digital DISCOM", '("artificial intelligence" OR "AI" OR "digital transformation" OR automation) (DISCOM OR "power distribution" OR utility) India', "en"),
    # Priority 2 — generation and grid
    ("Thermal & coal", '("thermal power" OR "coal stocks" OR "coal supply" OR "thermal capacity") India (analysis OR policy OR opinion)', "en"),
    ("Peak demand", '("peak demand" OR "power shortage" OR "resource adequacy" OR "demand forecasting") India electricity', "en"),
    ("RE integration", '("renewable integration" OR "grid stability" OR "curtailment" OR "grid-India") India', "en"),
    ("Storage", '("battery energy storage" OR BESS OR "pumped storage" OR "energy storage") India (policy OR tender OR analysis)', "en"),
    ("Transmission", '("transmission" OR "green energy corridor" OR "ISTS") India power (analysis OR policy)', "en"),
    ("Power markets", '("power exchange" OR "IEX" OR "market coupling" OR "electricity market" OR "real-time market") India -shares -stock', "en"),
    ("PPAs & procurement", '("power purchase agreement" OR "PPA" OR "power procurement" OR "long-term PPA") India DISCOM', "en"),
    # Priority 3 — policy & regulation
    ("Regulators", '("CERC" OR "Central Electricity Regulatory Commission" OR "SERC" OR "state electricity regulatory commission") order', "en"),
    ("CEA", '("Central Electricity Authority" OR "CEA report" OR "National Electricity Plan")', "en"),
    ("Electricity Act", '("Electricity Act" OR "Electricity (Amendment)" OR "Electricity Rules" OR "electricity amendment bill")', "en"),
    ("Policy", '("Ministry of Power" OR "power ministry" OR "national electricity policy" OR "tariff policy")', "en"),
    ("Transition & carbon", '("energy transition" OR "carbon market" OR "carbon credit trading scheme" OR "CCTS") India power', "en"),
    # Priority 4 — Bihar
    ("Bihar power", '(Bihar) (electricity OR power OR DISCOM OR BSPHCL OR SBPDCL OR NBPDCL OR BERC OR tariff OR "smart meter")', "en"),
    ("Bihar utilities", '(BSPHCL OR SBPDCL OR NBPDCL OR "Bihar Electricity Regulatory Commission" OR "Bihar State Power")', "en"),
    ("Bihar solar", '(Bihar) ("rooftop solar" OR solar OR BREDA OR "renewable energy")', "en"),
    # Hindi
    ("Hindi — Bihar bijli", '(बिहार) (बिजली OR विद्युत OR स्मार्ट मीटर OR बिजली दर OR बीएसपीएचसीएल)', "hi"),
    ("Hindi — DISCOM", '(बिजली वितरण OR डिस्कॉम OR बिजली दरें OR विद्युत नियामक आयोग)', "hi"),
]

# Official/government items found via Google News "site:" searches.
OFFICIAL_SEARCHES = [
    ("PIB — Power/MNRE", 'site:pib.gov.in (power OR electricity OR renewable OR "Ministry of Power" OR MNRE)', "en"),
    ("Ministry of Power", "site:powermin.gov.in", "en"),
    ("CEA", "site:cea.nic.in", "en"),
    ("CERC", "site:cercind.gov.in", "en"),
    ("MNRE", "site:mnre.gov.in", "en"),
    ("BERC", "site:berc.co.in", "en"),
    ("NITI Aayog energy", "site:niti.gov.in (energy OR power OR electricity)", "en"),
]

# ---------------------------------------------------------------------------
# 5. DIRECT RSS FEEDS (optional, best-effort)
#    If a feed is down or changes its address, the run just logs a warning
#    and continues. Add or remove lines freely: (label, url).
# ---------------------------------------------------------------------------
DIRECT_FEEDS = [
    ("Mercom India", "https://www.mercomindia.com/feed"),
    ("ET EnergyWorld", "https://energy.economictimes.indiatimes.com/rss/topstories"),
    ("ET EnergyWorld — Power", "https://energy.economictimes.indiatimes.com/rss/power"),
    ("Down To Earth — Energy", "https://www.downtoearth.org.in/energy/rss"),
    ("IEA News", "https://www.iea.org/api/rss/news"),
]

# ---------------------------------------------------------------------------
# 6. SOURCE CREDIBILITY (0-10 points). Matched against domain OR publisher name.
# ---------------------------------------------------------------------------
OFFICIAL_DOMAINS = [
    "pib.gov.in", "powermin.gov.in", "cea.nic.in", "cercind.gov.in", "mnre.gov.in",
    "berc.co.in", "niti.gov.in", "bsphcl.co.in", "sbpdcl.co.in", "nbpdcl.co.in",
    "grid-india.in", "posoco.in", "beeindia.gov.in", "iea.org",
]
SOURCE_TIERS = {
    10: OFFICIAL_DOMAINS + [
        "ceew.in", "Council on Energy, Environment and Water", "prayaspune.org", "Prayas",
        "ieefa.org", "IEEFA", "teriin.org", "TERI", "cseindia.org", "wri.org", "WRI India",
        "rmi.org", "ember-energy.org", "Ember", "cstep.in", "iesa.in", "India Energy Storage Alliance",
        "brookings.edu", "orfonline.org", "Observer Research Foundation", "carnegieindia.org",
        "epw.in", "Economic and Political Weekly", "NITI Aayog", "International Energy Agency",
    ],
    8: [
        "thehindu.com", "The Hindu", "indianexpress.com", "Indian Express", "livemint.com", "Mint",
        "business-standard.com", "Business Standard", "thehindubusinessline.com", "BusinessLine",
        "economictimes.indiatimes.com", "Economic Times", "ETEnergyWorld", "ET EnergyWorld",
        "financialexpress.com", "Financial Express", "powerline.net.in", "Power Line",
        "mercomindia.com", "Mercom", "downtoearth.org.in", "Down To Earth", "reuters.com", "Reuters",
        "bloomberg.com", "Bloomberg", "theprint.in", "ThePrint", "moneycontrol.com", "Moneycontrol",
        "scroll.in", "thewire.in", "carboncopy.info", "Carbon Copy", "saurenergy.com", "Saur Energy",
        "energy.economictimes.indiatimes.com", "pv-magazine-india.com", "pv magazine",
    ],
    6: [
        "timesofindia.indiatimes.com", "Times of India", "hindustantimes.com", "Hindustan Times",
        "deccanherald.com", "Deccan Herald", "newindianexpress.com", "New Indian Express",
        "telegraphindia.com", "Telegraph", "ndtv.com", "NDTV", "indiatoday.in", "India Today",
        "bhaskar.com", "Dainik Bhaskar", "jagran.com", "Dainik Jagran", "livehindustan.com",
        "Hindustan", "prabhatkhabar.com", "Prabhat Khabar", "amarujala.com", "Amar Ujala",
    ],
}
DEFAULT_SOURCE_POINTS = 4

# ---------------------------------------------------------------------------
# 7. KEYWORD LEXICONS (lower-case; matched as whole words/phrases)
# ---------------------------------------------------------------------------
POWER_SECTOR_TERMS = [
    "electricity", "power sector", "power distribution", "discom", "discoms", "utility", "utilities",
    "tariff", "grid", "transmission", "generation", "thermal", "coal", "renewable", "solar", "wind",
    "storage", "bess", "pumped storage", "power purchase", "ppa", "cerc", "cea", "serc", "regulator",
    "regulatory commission", "ministry of power", "rdss", "smart meter", "at&c", "load", "peak demand",
    "megawatt", "mw", "gw", "gigawatt", "kwh", "unit", "substation", "feeder", "power exchange",
    "iex", "electricity act", "bijli", "बिजली", "विद्युत",
]
INDIA_TERMS = [
    "india", "indian", "centre", "union government", "state government", "bihar", "uttar pradesh",
    "maharashtra", "gujarat", "rajasthan", "tamil nadu", "karnataka", "delhi", "punjab", "odisha",
    "west bengal", "jharkhand", "andhra pradesh", "telangana", "madhya pradesh", "kerala", "haryana",
    "crore", "lakh", "rs ", "₹", "भारत", "बिहार",
]
ANALYSIS_TERMS = [
    "editorial", "opinion", "op-ed", "column", "analysis", "analyse", "analyze", "perspective",
    "explained", "explainer", "deep dive", "whitepaper", "white paper", "report", "study", "research",
    "assessment", "policy brief", "why", "how", "lessons", "challenges", "the case for", "the way forward",
    "rethinking", "reform", "examines", "argues", "should", "need to", "must",
]
POLICY_TERMS = [
    "policy", "regulation", "regulatory", "regulator", "order", "amendment", "rules", "notification",
    "guidelines", "electricity act", "tariff policy", "national electricity plan", "cerc", "serc", "berc",
    "ministry of power", "mnre", "cea", "scheme", "consultation", "draft", "bill", "cabinet", "reform",
    "commission", "aptel", "supreme court", "mandate", "framework",
]
DISCOM_TERMS = [
    "discom", "discoms", "distribution company", "distribution utilities", "power distribution",
    "at&c", "aggregate technical and commercial", "billing", "collection efficiency", "acs-arr",
    "smart meter", "prepaid meter", "metering", "ami", "rdss", "feeder", "outage", "power cut",
    "reliability", "consumer", "subsidy", "cross-subsidy", "tariff", "franchisee", "privatisation",
    "privatization", "dues", "late payment surcharge", "lps", "power purchase cost", "receivables",
    "distribution transformer", "losses",
]
BIHAR_TERMS = [
    "bihar", "bsphcl", "sbpdcl", "nbpdcl", "berc", "bihar electricity regulatory commission",
    "patna", "bihar state power", "breda", "south bihar", "north bihar", "बिहार", "पटना",
]
# Bihar items get a bonus on top of the 100-point model (final score capped at 100).
BIHAR_BONUS = 10

# Anything clearly about share prices / earnings is dropped before scoring.
FINANCIAL_NOISE_PATTERNS = [
    r"\bshare price\b", r"\bshares? (rise|rises|rose|fall|falls|fell|jump|jumps|surge|surges|slump|gain|gains|drop|drops)\b",
    r"\bstock (price|rally|surges?|falls?)\b", r"\b(nifty|sensex)\b", r"\btarget price\b",
    r"\b(q[1-4]|quarterly) (results|earnings|profit|net profit)\b", r"\bnet profit\b.*\b(rises|falls|jumps|declines)\b",
    r"\bbuy or sell\b", r"\bstocks? to (buy|watch)\b", r"\bmultibagger\b", r"\bipo\b", r"\bdividend\b",
    r"\bbrokerage\b", r"\bupper circuit\b", r"\blower circuit\b", r"\bmarket cap\b",
]
PROMO_PATTERNS = [
    r"\bsponsored\b", r"\bpartner content\b", r"\bbrand ?connect\b", r"\badvertorial\b",
    r"\bpress release\b", r"\bwebinar\b", r"\bregister now\b", r"\baward(s)? 20\d\d\b",
]

# ---------------------------------------------------------------------------
# 8. CATEGORIES — first entry with the most hits becomes the primary category
# ---------------------------------------------------------------------------
CATEGORIES = {
    "DISCOM Reforms": [
        "discom", "discoms", "distribution", "at&c", "billing", "collection efficiency", "rdss",
        "smart meter", "prepaid meter", "franchisee", "privatisation", "privatization", "acs-arr",
        "feeder", "outage", "losses", "dues",
    ],
    "Tariff and Regulation": [
        "tariff", "cerc", "serc", "regulatory commission", "regulator", "tariff order", "true-up",
        "cross-subsidy", "aptel", "arr", "petition", "regulation",
    ],
    "Generation and Power Procurement": [
        "thermal", "coal", "generation", "capacity addition", "ppa", "power purchase", "procurement",
        "peak demand", "resource adequacy", "nuclear", "hydro", "gas-based", "power exchange", "iex",
        "market coupling",
    ],
    "Renewable Energy and Storage": [
        "renewable", "solar", "wind", "rooftop", "storage", "bess", "battery", "pumped storage",
        "green hydrogen", "hybrid", "round-the-clock", "rtc", "curtailment", "pm surya ghar",
    ],
    "Transmission and Grid Stability": [
        "transmission", "grid", "grid-india", "ists", "green energy corridor", "frequency", "inertia",
        "substation", "load despatch", "ldc", "grid stability", "congestion",
    ],
    "Government Policy": [
        "ministry of power", "policy", "scheme", "electricity act", "amendment", "rules", "cabinet",
        "national electricity plan", "mnre", "niti aayog", "budget", "carbon market", "ccts",
        "energy transition",
    ],
    "Technology and Innovation": [
        "artificial intelligence", "ai", "machine learning", "digital", "automation", "scada", "iot",
        "analytics", "blockchain", "drone", "gis", "forecasting", "digital twin", "cybersecurity",
    ],
    "Bihar Power Sector": BIHAR_TERMS,
}
