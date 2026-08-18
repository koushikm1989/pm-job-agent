"""Job fetchers from multiple sources. Each function returns a list of dicts with a common schema."""
import logging
import time
from typing import List, Dict, Optional
import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common schema every fetcher returns:
# {
#   "source": str, "title": str, "company": str, "location": str,
#   "url": str, "description": str, "posted_date": str, "is_remote": bool
# }

SEARCH_TERMS = [
    "Lead Product Owner",
    "Senior Product Owner",
    "AI Product Owner",
    "Technical Product Owner",
    "Product Owner",
    "Product Manager",
]

# Broad net at fetch time. Strict matching happens in filters.py
TITLE_KEYWORDS = ["product owner", "product manager"]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"

# Remote-first companies worth watching. Slug is a guess used against
# Greenhouse / Lever / Ashby. The fetcher tries all three and logs what works.
TARGET_COMPANIES = [
    ("Atlassian", "atlassian"),
    ("Canonical", "canonical"),
    ("GitLab", "gitlab"),
    ("Creatio", "creatio"),
    ("Xsolla", "xsolla"),
    ("Flex", "flex"),
    ("Colibri Group", "colibrigroup"),
    ("Automattic", "automattic"),
    ("Zapier", "zapier"),
    ("Remote.com", "remotecom"),
    ("Deel", "deel"),
    ("Buffer", "buffer"),
    ("Miro", "miro"),
    ("HubSpot", "hubspot"),
    ("Shopify", "shopify"),
    ("Cloudflare", "cloudflare"),
    ("Elastic", "elastic"),
    ("1Password", "1password"),
    ("DuckDuckGo", "duckduckgo"),
    ("Doist", "doist"),
    ("MongoDB", "mongodb"),
    ("Grafana Labs", "grafanalabs"),
    ("Vercel", "vercel"),
    ("Multiplier", "multiplier"),
    ("Chargebee", "chargebee"),
    ("Freshworks", "freshworks"),
    ("Postman", "postman"),
    ("HashiCorp", "hashicorp"),
    ("Personio", "personio"),
]


def _title_matches(title: str) -> bool:
    return any(t in (title or "").lower() for t in TITLE_KEYWORDS)


def _clean_html(raw: str, limit: int = 3000) -> str:
    """Strip HTML tags from a description blob."""
    if not raw:
        return ""
    try:
        text = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)
    except Exception:
        text = raw
    return text[:limit]


def _country_for_indeed(location: str) -> str:
    """Map our search location to the country JobSpy's Indeed scraper expects."""
    mapping = {
        "India": "India",
        "Kolkata, India": "India",
        "Singapore": "Singapore",
        "United Kingdom": "UK",
        "United States": "USA",
        "Australia": "Australia",
        "New Zealand": "New Zealand",
        "Germany": "Germany",
        "Netherlands": "Netherlands",
        "Remote": "India",
    }
    return mapping.get(location, "India")


# --- JobSpy ---------------------------------------------------------------

def fetch_jobspy_sources() -> List[Dict]:
    """
    LinkedIn, Indeed, Google only.
    ZipRecruiter (Cloudflare 403), Glassdoor (403), and Naukri (recaptcha 406)
    block automated access. Removed rather than worked around.
    """
    from jobspy import scrape_jobs

    all_jobs = []
    sites = ["linkedin", "indeed", "google"]
    locations = [
        "Remote",
        "India",
        "Kolkata, India",
        "Singapore",
        "United Kingdom",
        "United States",
        "Australia",
        "New Zealand",
        "Germany",
        "Netherlands",
    ]

    for term in SEARCH_TERMS[:4]:
        for location in locations:
            try:
                logger.info(f"JobSpy: '{term}' in '{location}'")
                df = scrape_jobs(
                    site_name=sites,
                    search_term=term,
                    location=location,
                    results_wanted=15,
                    hours_old=168,
                    country_indeed=_country_for_indeed(location),
                    is_remote=(location == "Remote"),
                )
                if df is None or df.empty:
                    continue
                for _, row in df.iterrows():
                    all_jobs.append({
                        "source": row.get("site", "jobspy"),
                        "title": str(row.get("title", "")),
                        "company": str(row.get("company", "")),
                        "location": str(row.get("location", "")),
                        "url": str(row.get("job_url", "")),
                        "description": str(row.get("description", ""))[:3000],
                        "posted_date": str(row.get("date_posted", "")),
                        "is_remote": bool(row.get("is_remote", False)),
                    })
                time.sleep(2)
            except Exception as e:
                logger.warning(f"JobSpy failed for {term}/{location}: {e}")
                continue
    return all_jobs


# --- Free public job APIs -------------------------------------------------

def fetch_remotive() -> List[Dict]:
    """Remotive public API. Good remote B2B SaaS volume."""
    jobs = []
    for term in ["product owner", "product manager"]:
        try:
            r = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": term, "limit": 50},
                headers={"User-Agent": UA},
                timeout=25,
            )
            r.raise_for_status()
            for item in r.json().get("jobs", []):
                title = item.get("title", "")
                if not _title_matches(title):
                    continue
                jobs.append({
                    "source": "remotive",
                    "title": title,
                    "company": item.get("company_name", ""),
                    "location": item.get("candidate_required_location", "Remote"),
                    "url": item.get("url", ""),
                    "description": _clean_html(item.get("description", "")),
                    "posted_date": item.get("publication_date", ""),
                    "is_remote": True,
                })
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Remotive failed for '{term}': {e}")
    return jobs


def fetch_arbeitnow() -> List[Dict]:
    """Arbeitnow public API. Europe-heavy, good EU coverage."""
    jobs = []
    try:
        for page in (1, 2, 3):
            r = requests.get(
                "https://www.arbeitnow.com/api/job-board-api",
                params={"page": page},
                headers={"User-Agent": UA},
                timeout=25,
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                break
            for item in data:
                title = item.get("title", "")
                if not _title_matches(title):
                    continue
                jobs.append({
                    "source": "arbeitnow",
                    "title": title,
                    "company": item.get("company_name", ""),
                    "location": item.get("location", "Europe"),
                    "url": item.get("url", ""),
                    "description": _clean_html(item.get("description", "")),
                    "posted_date": str(item.get("created_at", "")),
                    "is_remote": bool(item.get("remote", False)),
                })
            time.sleep(1)
    except Exception as e:
        logger.warning(f"Arbeitnow failed: {e}")
    return jobs


def fetch_jobicy() -> List[Dict]:
    """Jobicy public API. Remote-only listings."""
    jobs = []
    try:
        r = requests.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 50, "tag": "product manager"},
            headers={"User-Agent": UA},
            timeout=25,
        )
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            title = item.get("jobTitle") or item.get("title", "")
            if not _title_matches(title):
                continue
            jobs.append({
                "source": "jobicy",
                "title": title,
                "company": item.get("companyName", ""),
                "location": item.get("jobGeo", "Remote"),
                "url": item.get("url", ""),
                "description": _clean_html(
                    item.get("jobDescription") or item.get("jobExcerpt", "")
                ),
                "posted_date": item.get("pubDate", ""),
                "is_remote": True,
            })
    except Exception as e:
        logger.warning(f"Jobicy failed: {e}")
    return jobs


def fetch_himalayas() -> List[Dict]:
    """Himalayas public API. Remote roles, well structured."""
    jobs = []
    try:
        r = requests.get(
            "https://himalayas.app/jobs/api",
            params={"limit": 100},
            headers={"User-Agent": UA},
            timeout=25,
        )
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            title = item.get("title", "")
            if not _title_matches(title):
                continue
            restrictions = item.get("locationRestrictions") or []
            location = ", ".join(restrictions) if restrictions else "Remote"
            jobs.append({
                "source": "himalayas",
                "title": title,
                "company": item.get("companyName", ""),
                "location": location,
                "url": item.get("applicationLink") or item.get("guid", ""),
                "description": _clean_html(item.get("description", "")),
                "posted_date": str(item.get("pubDate", "")),
                "is_remote": True,
            })
    except Exception as e:
        logger.warning(f"Himalayas failed: {e}")
    return jobs


def fetch_remoteok() -> List[Dict]:
    """
    RemoteOK public API. The first array element is a legal notice,
    not a job, so it gets skipped.
    """
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": UA},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return jobs
        for item in data[1:]:  # skip legal notice
            if not isinstance(item, dict):
                continue
            title = item.get("position") or item.get("title", "")
            if not _title_matches(title):
                continue
            jobs.append({
                "source": "remoteok",
                "title": title,
                "company": item.get("company", ""),
                "location": item.get("location") or "Remote",
                "url": item.get("url") or item.get("apply_url", ""),
                "description": _clean_html(item.get("description", "")),
                "posted_date": item.get("date", ""),
                "is_remote": True,
            })
    except Exception as e:
        logger.warning(f"RemoteOK failed: {e}")
    return jobs


def fetch_weworkremotely() -> List[Dict]:
    """WeWorkRemotely RSS feed."""
    jobs = []
    try:
        feed = feedparser.parse("https://weworkremotely.com/categories/remote-product-jobs.rss")
        for entry in feed.entries:
            title = entry.get("title", "")
            if not _title_matches(title):
                continue
            company = title.split(":")[0] if ":" in title else ""
            role = title.split(":", 1)[1].strip() if ":" in title else title
            jobs.append({
                "source": "weworkremotely",
                "title": role,
                "company": company,
                "location": "Remote",
                "url": entry.get("link", ""),
                "description": _clean_html(entry.get("summary", "")),
                "posted_date": entry.get("published", ""),
                "is_remote": True,
            })
    except Exception as e:
        logger.warning(f"WeWorkRemotely failed: {e}")
    return jobs


# --- Company ATS boards ---------------------------------------------------

def _try_greenhouse(company: str, slug: str) -> Optional[List[Dict]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = requests.get(url, params={"content": "true"}, headers={"User-Agent": UA}, timeout=20)
    if r.status_code != 200:
        return None
    payload = r.json()
    if "jobs" not in payload:
        return None
    out = []
    for item in payload.get("jobs", []):
        title = item.get("title", "")
        if not _title_matches(title):
            continue
        loc = (item.get("location") or {}).get("name", "")
        out.append({
            "source": f"greenhouse:{slug}",
            "title": title,
            "company": company,
            "location": loc,
            "url": item.get("absolute_url", ""),
            "description": _clean_html(item.get("content", "")),
            "posted_date": str(item.get("updated_at", "")),
            "is_remote": "remote" in (loc + " " + title).lower(),
        })
    return out


def _try_lever(company: str, slug: str) -> Optional[List[Dict]]:
    url = f"https://api.lever.co/v0/postings/{slug}"
    r = requests.get(url, params={"mode": "json"}, headers={"User-Agent": UA}, timeout=20)
    if r.status_code != 200:
        return None
    payload = r.json()
    if not isinstance(payload, list):
        return None
    out = []
    for item in payload:
        title = item.get("text", "")
        if not _title_matches(title):
            continue
        cats = item.get("categories") or {}
        loc = cats.get("location", "") or ""
        out.append({
            "source": f"lever:{slug}",
            "title": title,
            "company": company,
            "location": loc,
            "url": item.get("hostedUrl", ""),
            "description": _clean_html(
                item.get("descriptionPlain") or item.get("description", "")
            ),
            "posted_date": str(item.get("createdAt", "")),
            "is_remote": "remote" in (loc + " " + title).lower(),
        })
    return out


def _try_ashby(company: str, slug: str) -> Optional[List[Dict]]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    if r.status_code != 200:
        return None
    payload = r.json()
    if "jobs" not in payload:
        return None
    out = []
    for item in payload.get("jobs", []):
        title = item.get("title", "")
        if not _title_matches(title):
            continue
        loc = item.get("location", "") or ""
        out.append({
            "source": f"ashby:{slug}",
            "title": title,
            "company": company,
            "location": loc,
            "url": item.get("jobUrl") or item.get("applyUrl", ""),
            "description": _clean_html(
                item.get("descriptionPlain") or item.get("descriptionHtml", "")
            ),
            "posted_date": str(item.get("publishedAt", "")),
            "is_remote": bool(item.get("isRemote", False)) or "remote" in loc.lower(),
        })
    return out


def fetch_company_boards() -> List[Dict]:
    """
    Hit public ATS endpoints for the target company list.
    Tries Greenhouse, then Lever, then Ashby for each slug.
    Logs which provider resolved so the list can be pruned after the first run.
    """
    all_jobs = []
    resolved = []
    unresolved = []

    providers = [
        ("greenhouse", _try_greenhouse),
        ("lever", _try_lever),
        ("ashby", _try_ashby),
    ]

    for company, slug in TARGET_COMPANIES:
        found = False
        for provider_name, fn in providers:
            try:
                result = fn(company, slug)
            except Exception as e:
                logger.debug(f"{company} via {provider_name}: {e}")
                continue
            if result is not None:
                resolved.append(f"{company} -> {provider_name} ({len(result)} matching)")
                all_jobs.extend(result)
                found = True
                break
            time.sleep(0.3)
        if not found:
            unresolved.append(company)
        time.sleep(0.3)

    logger.info("=" * 50)
    logger.info("ATS BOARD DISCOVERY RESULTS")
    logger.info("=" * 50)
    for line in resolved:
        logger.info(f"  OK   {line}")
    if unresolved:
        logger.info(f"  MISS no public board found for: {', '.join(unresolved)}")
    logger.info("=" * 50)

    return all_jobs


# --- Best-effort scrapers -------------------------------------------------

def fetch_recruithaus() -> List[Dict]:
    """Recruit Haus Singapore. Best effort."""
    jobs = []
    try:
        r = requests.get(
            "https://recruithaus.com.sg/joblistings/",
            headers={"User-Agent": UA},
            timeout=20,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("div.job-block, article.job-listing, h4.title a"):
            title = card.get_text(strip=True)
            link = card.get("href") if card.name == "a" else (
                card.find("a")["href"] if card.find("a") else ""
            )
            if not title or not link or not _title_matches(title):
                continue
            jobs.append({
                "source": "recruithaus",
                "title": title,
                "company": "via Recruit Haus",
                "location": "Singapore",
                "url": link,
                "description": "",
                "posted_date": "",
                "is_remote": False,
            })
    except Exception as e:
        logger.warning(f"Recruit Haus failed: {e}")
    return jobs


def fetch_jobstreet_sg() -> List[Dict]:
    """JobStreet Singapore. Best effort, often returns 403."""
    jobs = []
    try:
        r = requests.get(
            "https://sg.jobstreet.com/product-owner-jobs",
            headers={"User-Agent": UA},
            timeout=20,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for article in soup.select(
            "article[data-card-type='JobCard'], article[data-automation='job-card']"
        ):
            title_tag = article.select_one(
                "a[data-automation='job-title'], a[data-automation='jobTitle']"
            )
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not _title_matches(title):
                continue
            company_tag = article.select_one(
                "a[data-automation='jobCompany'], span[data-automation='jobCompany']"
            )
            location_tag = article.select_one(
                "a[data-automation='jobLocation'], span[data-automation='jobLocation']"
            )
            link = title_tag.get("href", "")
            if link and not link.startswith("http"):
                link = "https://sg.jobstreet.com" + link
            jobs.append({
                "source": "jobstreet_sg",
                "title": title,
                "company": company_tag.get_text(strip=True) if company_tag else "",
                "location": location_tag.get_text(strip=True) if location_tag else "Singapore",
                "url": link,
                "description": "",
                "posted_date": "",
                "is_remote": False,
            })
    except Exception as e:
        logger.warning(f"JobStreet SG failed: {e}")
    return jobs


# --- Orchestrator ---------------------------------------------------------

def fetch_all() -> List[Dict]:
    """Run every fetcher. If one fails, the others continue."""
    all_jobs = []
    fetchers = [
        ("Company ATS boards", fetch_company_boards),
        ("JobSpy", fetch_jobspy_sources),
        ("Remotive", fetch_remotive),
        ("Arbeitnow", fetch_arbeitnow),
        ("Jobicy", fetch_jobicy),
        ("Himalayas", fetch_himalayas),
        ("RemoteOK", fetch_remoteok),
        ("WeWorkRemotely", fetch_weworkremotely),
        ("Recruit Haus", fetch_recruithaus),
        ("JobStreet SG", fetch_jobstreet_sg),
    ]
    for name, fn in fetchers:
        try:
            results = fn()
            logger.info(f"{name}: {len(results)} jobs")
            all_jobs.extend(results)
        except Exception as e:
            logger.error(f"{name} crashed entirely: {e}")
    return all_jobs
