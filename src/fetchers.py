"""Job fetchers from multiple sources. Each function returns a list of dicts with a common schema."""
import logging
import time
from datetime import datetime
from typing import List, Dict
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
    "Senior Product Manager",
    "Lead Product Manager",
    "Principal Product Owner",
    "Lead Product Owner",
    "Senior Product Owner",
]


def fetch_jobspy_sources() -> List[Dict]:
    """Pulls from LinkedIn, Indeed, Glassdoor, Naukri, ZipRecruiter, Google via JobSpy."""
    from jobspy import scrape_jobs
    
    all_jobs = []
    sites = ["linkedin", "indeed", "glassdoor", "naukri", "zip_recruiter", "google"]
    locations = ["India", "Singapore", "Remote", "United Kingdom", "Australia"]
    
    for term in SEARCH_TERMS[:3]:  # Top 3 terms to keep request volume reasonable
        for location in locations:
            try:
                logger.info(f"JobSpy: '{term}' in '{location}'")
                df = scrape_jobs(
                    site_name=sites,
                    search_term=term,
                    location=location,
                    results_wanted=15,
                    hours_old=168,  # past 7 days
                    country_indeed="India" if location == "India" else "Singapore",
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
                time.sleep(2)  # be polite
            except Exception as e:
                logger.warning(f"JobSpy failed for {term}/{location}: {e}")
                continue
    return all_jobs


def fetch_remoteok() -> List[Dict]:
    """RemoteOK has a clean public JSON API."""
    jobs = []
    try:
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0 (job-agent personal use)"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        for item in data:
            if not isinstance(item, dict) or "position" not in item:
                continue
            title = item.get("position", "").lower()
            if not any(t.lower() in title for t in ["product manager", "product owner", "head of product", "director of product"]):
                continue
            jobs.append({
                "source": "remoteok",
                "title": item.get("position", ""),
                "company": item.get("company", ""),
                "location": item.get("location", "Remote"),
                "url": item.get("url", ""),
                "description": (item.get("description", "") or "")[:3000],
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
            if not any(t.lower() in title.lower() for t in ["product manager", "product owner", "head of product"]):
                continue
            company = title.split(":")[0] if ":" in title else ""
            role = title.split(":", 1)[1].strip() if ":" in title else title
            jobs.append({
                "source": "weworkremotely",
                "title": role,
                "company": company,
                "location": "Remote",
                "url": entry.get("link", ""),
                "description": entry.get("summary", "")[:3000],
                "posted_date": entry.get("published", ""),
                "is_remote": True,
            })
    except Exception as e:
        logger.warning(f"WeWorkRemotely failed: {e}")
    return jobs


def fetch_recruithaus() -> List[Dict]:
    """Recruit Haus Singapore. Best effort. Their featured jobs are rarely PM."""
    jobs = []
    try:
        r = requests.get(
            "https://recruithaus.com.sg/joblistings/",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select("div.job-block, article.job-listing, h4.title a"):
            title = card.get_text(strip=True) if card.name != "a" else card.get_text(strip=True)
            link = card.get("href") if card.name == "a" else (card.find("a")["href"] if card.find("a") else "")
            if not title or not link:
                continue
            if not any(t.lower() in title.lower() for t in ["product manager", "product owner"]):
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
    """JobStreet Singapore. Best effort. Site structure can change."""
    jobs = []
    try:
        url = "https://sg.jobstreet.com/product-manager-jobs"
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=20,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for article in soup.select("article[data-card-type='JobCard'], article[data-automation='job-card']"):
            title_tag = article.select_one("a[data-automation='job-title'], a[data-automation='jobTitle']")
            company_tag = article.select_one("a[data-automation='jobCompany'], span[data-automation='jobCompany']")
            location_tag = article.select_one("a[data-automation='jobLocation'], span[data-automation='jobLocation']")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not any(t.lower() in title.lower() for t in ["product manager", "product owner", "head of product"]):
                continue
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


def fetch_all() -> List[Dict]:
    """Run every fetcher. If one fails, the others continue."""
    all_jobs = []
    fetchers = [
        ("JobSpy", fetch_jobspy_sources),
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
