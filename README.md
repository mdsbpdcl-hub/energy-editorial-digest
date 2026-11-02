# Energy Sector — Weekly Editorial & Policy Digest

Every Monday morning this repository emails you a curated digest of **long-form analysis, editorials, policy and regulatory writing** on India's power sector, with extra weight given to Bihar (BSPHCL, SBPDCL, NBPDCL, BERC). The scheduling, searching, filtering and emailing all run on GitHub's servers, so your computer does not need to be on.

---

## 1. How it works (system architecture)

```
 Every Monday 07:45 IST
 GitHub Actions (free cloud computer) starts the workflow
        │
        ▼
 ① DISCOVER  ~26 Google News RSS searches (English + Hindi)
             + 7 "site:" searches on official sites (PIB, MoP, CEA, CERC, MNRE, BERC, NITI)
             + 5 publisher RSS feeds (Mercom, ET EnergyWorld, Down To Earth, IEA)
        ▼
 ② FILTER    last 7 days only (Asia/Kolkata) → drop share-price/earnings/promo items
        ▼
 ③ DE-DUP    same URL / same headline / ≥88% similar headline → keep best copy
             + skip anything already sent in earlier weeks (data/history.json)
        ▼
 ④ VERIFY    resolve Google News link → publisher URL → check robots.txt →
             download page → Trafilatura extracts ONLY the article body → count words
             (paywalled / blocked / unresolved ⇒ word count stays "Unknown")
        ▼
 ⑤ SCORE     0-100 keyword model (relevance 30, depth 25, policy 20, DISCOM 15,
             source 10) + Bihar bonus 10 (capped at 100) → category & tags
        ▼
 ⑥ SELECT    main list = verified ≥650 words AND score ≥70
             official docs → own section; unverified-but-relevant → "headline only"
        ▼
 ⑦ DELIVER   HTML + plain-text email via Gmail SMTP → history saved to the repo
             → preview (digest.html) + run log kept as a downloadable artifact
```

**Files**

```
energy-editorial-digest/
├── digest.py                    # the engine (all steps above)
├── config.py                    # ALL settings you'd normally change
├── requirements.txt             # Python packages (pinned versions)
├── README.md                    # this guide
├── .gitignore
├── templates/
│   └── email.html               # email design (Jinja2, auto-escaped)
├── data/
│   └── history.json             # previously sent articles (auto-updated)
├── tests/
│   └── test_digest.py           # 29 offline self-tests, run before every digest
└── .github/
    └── workflows/
        └── weekly.yml           # the schedule and run steps
```

---

## 2. Prerequisites

| You need | Why | Cost |
|---|---|---|
| A GitHub account | Hosts the code and runs it on schedule | Free |
| A Gmail account with **2-Step Verification ON** | Sends the email | Free |
| A Gmail **App Password** | Lets the script log in without your real password | Free |

You do **not** need Python, Git or VS Code on your own computer. Everything is done in the browser.

> **Note on Gmail accounts:** App Passwords are only available on personal Gmail accounts (and Workspace accounts where the admin allows them) that have 2-Step Verification enabled. They are not available if the account uses *only* security keys for 2-Step Verification or is enrolled in *Advanced Protection*. A separate Gmail account just for sending the digest (e.g. `energydigest.sender@gmail.com`) is a good idea.

---

## 3. GitHub setup — step by step

### Step 1 — Create the account and repository
1. Go to **github.com** → **Sign up**, then follow the prompts (email, password, username, verify the email).
2. Top-right **+** → **New repository**.
3. *Repository name*: `energy-editorial-digest`
4. Select **Private**.
5. Tick **Add a README file**.
6. Click **Create repository**.

You now see the repository page. The tabs you will use are **Code** (files), **Actions** (runs and logs) and **Settings** (secrets).

### Step 2 — Upload the files
**The easy way (recommended): upload the whole folder at once**
1. Unzip `energy-editorial-digest.zip` on your computer.
2. In the repository, click **Add file → Upload files**.
3. Open the unzipped `energy-editorial-digest` folder, select **everything inside it** (including the `.github` folder) and drag it into the browser upload area.
   - **Windows:** `.github` is visible normally.
   - **Mac:** press **Cmd + Shift + .** in Finder to show hidden folders such as `.github`.
4. Click **Commit changes**. When GitHub asks whether to replace the existing `README.md`, let it replace the file.
5. Check the **Code** tab. You should see `digest.py`, `config.py`, `requirements.txt`, `templates/`, `data/`, `tests/` and `.github/workflows/weekly.yml`.

**If `.github` did not upload** (dragging hidden folders sometimes fails), create the file by hand:
1. **Add file → Create new file**.
2. In the name box, type exactly `.github/workflows/weekly.yml`. Each `/` you type creates a folder.
3. Paste in the contents of `weekly.yml` from the zip, then click **Commit changes**.

You can create any other file the same way: type the path (e.g. `templates/email.html`), paste the contents, and commit.

### Step 3 — Create a Gmail App Password
1. Sign in to the sending Gmail account → open **myaccount.google.com**.
2. **Security** → **2-Step Verification** → turn it **ON** (phone verification).
3. Go to **myaccount.google.com/apppasswords** (or search "App passwords" in the account search bar).
4. Name it `Energy Digest` → **Create**.
5. Google shows a 16-letter password like `abcd efgh ijkl mnop`. **Copy it now**, because Google will not show it again. The spaces don't matter; the script removes them.

### Step 4 — Add the three secrets to GitHub
1. In the repository: **Settings** (top tab) → left menu **Secrets and variables** → **Actions**.
2. Click **New repository secret** three times:

| Name (exactly) | Secret value |
|---|---|
| `EMAIL_USER` | the sending Gmail address, e.g. `energydigest.sender@gmail.com` |
| `EMAIL_PASS` | the 16-letter App Password |
| `EMAIL_RECEIVER` | where to deliver it. Several addresses are allowed, separated by commas: `a@x.com, b@y.gov.in` |

GitHub hides secrets in logs automatically (they appear as `***`), and nobody can read them back, including you. To change one, click it and choose **Update**.

### Step 5 — Allow the workflow to save history
**Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → **Save**.
The workflow uses this only to commit `data/history.json` back to the repository. If you would rather keep it read-only, see §11 "Disable history".

---

## 4. Code

All code is in the zip. A summary of each file:

- **`digest.py`** contains the full pipeline. Run options:
  - `python digest.py` does a full run and sends the email.
  - `python digest.py --dry-run` builds `output/digest.html` without sending anything.
  - `python digest.py --smtp-test` only tests the Gmail login.
- **`config.py`** holds every tunable value: window, thresholds, limits, search queries, feeds, source credibility tiers, keyword lists and categories.
- **`templates/email.html`** is the email layout. It uses inline styles so it renders in Gmail and Outlook on desktop and phone. Jinja2 auto-escaping makes sure any odd characters in a headline cannot break the email or inject code.
- **`tests/test_digest.py`** covers query encoding, empty and broken feeds, date conversion to IST, timeouts, blocked pages, paywalls, PDFs, body-only word counts, de-duplication, scoring, Bihar and Bangladesh-BERC disambiguation, HTML escaping, missing secrets, SMTP failures, zero-article weeks and history.

## 5. Requirements file

```
feedparser==6.0.14
requests==2.34.2
trafilatura==2.3.1
Jinja2==3.1.6
googlenewsdecoder==0.2.2
```

## 6. Workflow schedule

`.github/workflows/weekly.yml` runs:
- **every Monday at 07:45 IST**, using `cron: "45 7 * * 1"` with `timezone: "Asia/Kolkata"` (GitHub has supported time zones in schedules since March 2026). The run takes 5–15 minutes, so the email normally lands around 8:00.
- **on demand** through the **Run workflow** button, which offers *dry run* and *SMTP test* tick-boxes.

Safeguards built in:
- `concurrency` stops two runs from overlapping.
- The job times out after 40 minutes.
- Offline tests run first.
- The HTML preview and run log are uploaded as an artifact for 30 days.
- History is committed only after a successful send.

**Scheduled runs are not exact.** GitHub queues scheduled jobs. At busy times, especially around the top of the hour, a run can start 5–30 minutes late. Very rarely, under heavy load, a scheduled run can be dropped. That is why the schedule is set to 07:45 and not 08:00. If a Monday email never arrives, press **Run workflow** manually.

---

## 7. First test (do this right after setup)

**Test A — Gmail login**
1. Open the **Actions** tab. If asked, click **"I understand my workflows, go ahead and enable them."**
2. Left side: **Weekly Energy Digest** → right side: **Run workflow** ▾ → tick **Only test Gmail login** → **Run workflow**.
3. After about a minute a green ✔ should appear, and a one-line "SMTP test successful" email should be in your inbox.

**Test B — Dry run (no email)**
1. **Run workflow** → tick **Dry run** → run.
2. Click the run, then the **digest** job, and expand **Build and send digest** to read the log (see §8).
3. Scroll to the bottom of the run summary page → **Artifacts** → download `digest-N`. Unzip it and open `digest.html` in your browser. This is exactly what the email will look like.

**Test C — Real run**
**Run workflow** with no boxes ticked. The digest arrives by email, and a new commit "Update digest history" appears in the **Code** tab.

---

## 8. Checking the results

The log prints every step with counts. Here's what to look for:

| Log line | Healthy sign | If not |
|---|---|---|
| `[DISCOM finances] 37 items` | Most searches return 5–100 items | Many `0 items` or `HTTP 503`: Google is rate-limiting; re-run later |
| `discovered N raw items` | Several hundred | Fewer than 50: see Troubleshooting |
| `N in window (k had no parseable date)` | k small | Large k: a feed has a non-standard date format |
| `removed N` (noise) | A handful | |
| `N unique stories` | Clearly lower than discovered | |
| `1/90 ok  1234 words  Title…` | Many `ok` lines | Many `link_not_resolved`: see Troubleshooting |
| `extraction results: {...}` | `ok` is the largest group | `blocked_http_403`, `partial_paywall` and `robots_disallowed` are normal for some publishers |
| `selected N \| official N \| headline-only N` | 5–25 selected | 0 selected: lower the threshold (§11) |

The run page also shows a **summary table** of selected titles, scores and word counts. `run_summary.json` inside the artifact lists **every** candidate with its score breakdown, extraction status and URL. Use it to fine-tune the settings.

**How to check word-count accuracy:** open two or three `ok` articles from the email and compare the reported count with a word counter on the article body. Trafilatura counts only the article text, not menus, ads, related-story lists or footers. Expect results within about ±10%.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Missing GitHub secret(s): EMAIL_PASS` | Secret not created, or name misspelt | Settings → Secrets → Actions; names are case-sensitive |
| `Gmail rejected the login` / `535 5.7.8` | Normal password used instead of App Password; 2-Step Verification off; password revoked | Create a new App Password (§3 Step 3) and update `EMAIL_PASS` |
| No App Passwords option in Google | 2-Step Verification off, Workspace admin restriction, or Advanced Protection | Turn on 2SV, or use a separate personal Gmail as sender |
| Email in Spam | New sender | Mark "Not spam" once and add the sender to contacts |
| Workflow not visible in Actions | `weekly.yml` not at `.github/workflows/weekly.yml` | Re-create it at that exact path (§3 Step 2) |
| `remote: Permission to … denied` at "Save history" | Workflow permissions are read-only | §3 Step 5 |
| Many `link_not_resolved` | Google changed its News link format, so the decoder can't translate links | Update the decoder (§11, "Update packages"). Until then those items appear as headline-only, and links still work through Google News |
| Many `blocked_http_403` | Publisher blocks automated readers | Normal. The item can't be verified and shows as headline-only. Don't try to bypass it |
| `0 items` for every Google search | Temporary Google rate limiting from GitHub's IP | Re-run after an hour |
| Direct feed `HTTP 404` | Publisher moved its RSS address | Fix or delete that line in `DIRECT_FEEDS` in `config.py` |
| Tests fail (`FAILED`) and no email | A config edit broke something, e.g. a missing comma or quote | Open the log; the failing test names the problem. Undo the last edit via the file's **History** |
| Scheduled run didn't happen | GitHub delay/drop, or schedule disabled | Run manually. Check **Actions → Weekly Energy Digest**: if it says *disabled*, click **Enable workflow** |
| Run time doesn't match 07:45 IST | `timezone:` key not honoured | Delete the `timezone:` line and set `cron: "15 2 * * 1"` (UTC) |

---

## 10. Maintenance

Edit files directly on GitHub: open the file → ✏️ pencil icon → change → **Commit changes**. Then **Run workflow** with *Dry run* ticked to check the result.

| To change… | Where | How |
|---|---|---|
| Keywords / searches | `config.py` → `SEARCHES` | Add a line `("Label", 'query words', "en"),`. Use `"hi"` for Hindi. Quotes = exact phrase, `OR` = either, `-word` = exclude |
| Add an official site | `config.py` → `OFFICIAL_SEARCHES` **and** `OFFICIAL_DOMAINS` | `("Label", "site:example.gov.in", "en"),` plus `"example.gov.in"` in the domain list |
| Add a publisher RSS feed | `config.py` → `DIRECT_FEEDS` | `("Name", "https://site/feed"),`. If it fails, the run logs a warning and continues |
| Number of articles | `MAX_SELECTED_ARTICLES`, `PRIORITY_ARTICLE_COUNT`, `EXEC_OVERVIEW_COUNT` | Any whole number |
| Minimum word count | `MIN_WORD_COUNT` | e.g. `800` |
| Score threshold | `SELECTION_THRESHOLD` | Lower (e.g. 60) = more articles; higher = stricter |
| Scoring weights | `score_article()` in `digest.py` | The numbers 20/10 (relevance), 15+10 (depth), 20, 15 are the weights. Credibility tiers are in `SOURCE_TIERS`; Bihar weight is `BIHAR_BONUS` |
| Trusted sources | `SOURCE_TIERS` | Add a domain (`"site.in"`) or publisher name to the 10/8/6 tier |
| Reporting window | `LOOKBACK_DAYS` | e.g. `14` for a fortnightly digest (also change the schedule) |
| Recipients | Secret `EMAIL_RECEIVER` | Settings → Secrets → `EMAIL_RECEIVER` → Update → `a@x.com, b@y.com` |
| Delivery day/time | `weekly.yml` → `cron:` | Format `minute hour day-of-month month weekday` in IST. Examples: `"30 6 * * 1"` = Mon 06:30; `"45 7 * * 1,4"` = Mon & Thu 07:45 |
| Pause the digest | Actions → Weekly Energy Digest → **⋯** → **Disable workflow** | **Enable workflow** to resume |
| Disable history | `config.py` → `HISTORY_ENABLED = False` | Then you may set `permissions: contents: read` in `weekly.yml` |
| Reset history | Edit `data/history.json` | Replace its contents with `{"version": 1, "entries": []}` |
| Update packages | `requirements.txt` | Change a version number, e.g. `googlenewsdecoder==0.2.3`, then dry-run |

**Scoring model, plainly:** each article is matched against keyword lists in `config.py`. Every list contributes points up to its maximum, and a match in the headline counts three times. Depth comes from the *verified* word count (up to 15) plus analysis signals (up to 10): words like *editorial / analysis / explained* in the title, or an `/opinion/` or `/editorial/` URL. The same input always gives the same score. The breakdown is printed under every Priority Article.

---

## 11. Costs and limitations

**Cost**

| Service | Status |
|---|---|
| GitHub private repo + Actions | Free plan includes **2,000 Actions minutes/month** for private repos. This digest uses about 10–15 minutes a week (≈60/month). Public repos have unlimited minutes |
| Gmail SMTP | Free. Personal Gmail allows a few hundred recipients a day, far above what this needs |
| Google News RSS | Free, no key. It is an unofficial feed with no published quota or guarantee |
| Python packages | Free, open source |

There are no paid APIs, AI credits, servers or databases.

**Limitations to be aware of**
1. **Google News RSS is unofficial.** It returns a maximum of about 100 items per search, may change without notice, and can temporarily rate-limit. Splitting into roughly 26 focused searches reduces the impact.
2. **Link decoding depends on Google.** Google News gives `news.google.com/...` links, not publisher links. The `googlenewsdecoder` package translates them by calling Google. If Google changes this, decoding fails until the package is updated. Affected items still appear with working links as "headline only".
3. **Paywalls and blocks are respected, not bypassed.** Articles from paywalled sites (and sites whose robots.txt disallows readers) can't have their length verified. They never enter the ≥650-word list, and their word count shows as *Unknown*.
4. **Summaries are never invented.** The email shows only the publisher's own description (meta tag or RSS). Where none exists it says so. "Topics found in the text" lists keywords actually detected; it is not an AI interpretation.
5. **Keyword scoring is indicative.** It is transparent and free, but it can't judge argument quality the way a human or a paid AI model can. Tune it with `run_summary.json` over the first few weeks.
6. **Official sites rarely have RSS.** PIB, CEA, CERC, MNRE and BERC are covered through Google News `site:` searches, which only catch documents that Google has indexed in the week. Some regulatory orders (often PDFs) may appear late or not at all.
7. **Schedule precision:** usually within minutes of 07:45, occasionally later. See §6.
8. **Hindi coverage** is a couple of focused searches. Hindi articles are scored on the same lexicon (which includes key Hindi terms), so they score lower unless they are clearly about बिजली/बिहार.

---

## 12. Running locally (optional, for advanced users)

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v       # offline tests
python digest.py --dry-run                     # builds output/digest.html, sends nothing
# real send (Mac/Linux):
EMAIL_USER=me@gmail.com EMAIL_PASS="abcd efgh ijkl mnop" EMAIL_RECEIVER=you@x.com python digest.py
```

---

## 13. Showing the digest on a web page / Google Sites (optional)

After every successful send, the workflow also saves the digest as `docs/index.html` (latest issue) and `docs/archive/YYYY-MM-DD.html` (all past issues). Turn on **GitHub Pages** to get a web address for it:

1. On the free GitHub plan, Pages needs a **public** repository: **Settings → General → Danger Zone → Change visibility → Public**. Your secrets stay hidden. The code, `history.json` and the digests become readable by anyone.
2. **Settings → Pages →** *Source*: **Deploy from a branch** → Branch **main**, folder **/docs** → **Save**.
3. After a minute the page shows your address: `https://<username>.github.io/energy-editorial-digest/`
4. In **Google Sites**: open your site → **Insert → Embed → By URL** → paste the address → choose **Whole page** → **Insert**. Drag the box to full size → **Publish**.

The page updates itself every Monday. Set `PUBLISH_WEB_PAGE = False` in `config.py` to stop it.
