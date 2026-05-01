"""Deterministic pre-filters. Run cheap rule-based filtering before AI scoring."""
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Set

logger = logging.getLogger(__name__)

# Titles we want
SENIORITY_KEYWORDS = [
    "senior product manager", "sr product manager", "sr. product manager",
    "lead product manager", "lead product owner",
    "principal product owner",
    "senior product owner", "sr product owner",
]

# Titles to reject outright (junior/adjacent roles)
REJECT_TITLE_KEYWORDS = [
    "associate product manager", "apm", "junior product manager",
    "product marketing", "product analyst", "product designer",
    "technical product manager intern", "intern", "graduate",
    "product specialist", "product coordinator",
]

# Geographies where we ONLY want remote roles
REMOTE_ONLY_REGIONS = [
    "india", "united states", "usa", "us-", "u.s.", "united kingdom", "uk",
    "europe", "eu ", "germany", "france", "netherlands", "spain", "ireland",
    "australia", "japan", "new zealand", "canada",
]

# Singapore allows both remote and on-site
SINGAPORE_KEYWORDS = ["singapore", "sg ", " sg,"]

# Phrases that signal "must be physically in country X" → reject for remote-only regions
LOCATION_LOCK_PHRASES = [
    "must be based in the us", "must be based in the united states",
    "us citizens only", "us citizens and green card",
    "authorized to work in the us", "authorization to work in the united states",
    "must reside in the us", "must reside in the united states",
    "us-based only", "usa-based only", "us residents only",
    "must be located in the uk", "uk-based only", "must reside in the uk",
    "must be based in europe", "eu-based only", "eea only",
    "must be based in australia", "australian citizens only",
    "must be based in japan", "japanese nationals only",
    "must be a us person", "us work authorization required",
]


def _load_seen(seen_path: Path) -> Set[str]:
    """Load the set of job URLs we've already emailed about."""
    if not seen_path.exists():
        return set()
    try:
        data = json.loads(seen_path.read_text())
        return set(data.keys())
    except Exception as e:
        logger.warning(f"Could not read seen file: {e}")
        return set()


def _save_seen(seen_path: Path, seen: Set[str], new_urls: List[str]) -> None:
    """Append new job URLs to the seen file with a timestamp."""
    from datetime import datetime
    existing = {}
    if seen_path.exists():
        try:
            existing = json.loads(seen_path.read_text())
        except Exception:
            existing = {}
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for url in new_urls:
        if url and url not in existing:
            existing[url] = today
    seen_path.write_text(json.dumps(existing, indent=2))


def _has_seniority_match(title: str) -> bool:
    t = title.lower()
    if any(reject in t for reject in REJECT_TITLE_KEYWORDS):
        return False
    return any(kw in t for kw in SENIORITY_KEYWORDS)


def _is_singapore(location: str) -> bool:
    loc = location.lower()
    return any(kw in loc for kw in SINGAPORE_KEYWORDS)


def _is_remote_only_region(location: str) -> bool:
    loc = location.lower()
    return any(kw in loc for kw in REMOTE_ONLY_REGIONS)


def _has_location_lock(description: str) -> bool:
    """Check if the role explicitly excludes India residents."""
    desc = description.lower()
    return any(phrase in desc for phrase in LOCATION_LOCK_PHRASES)


def _passes_location_rules(job: Dict) -> bool:
    """
    Singapore: remote OR on-site → keep.
    Other regions: only if remote AND not locked to local residents.
    """
    location = job.get("location", "")
    description = job.get("description", "")
    is_remote = job.get("is_remote", False)
    
    if _is_singapore(location):
        return True
    
    if _has_location_lock(description):
        return False
    
    if _is_remote_only_region(location):
        if not is_remote:
            text_blob = (location + " " + description).lower()
            if "remote" not in text_blob and "work from home" not in text_blob:
                return False
        return True
    
    if is_remote or "remote" in location.lower():
        return True
    
    return False


def _dedupe(jobs: List[Dict]) -> List[Dict]:
    """Remove duplicate jobs across sources by URL, then by (title, company)."""
    seen_urls = set()
    seen_pairs = set()
    unique = []
    for job in jobs:
        url = job.get("url", "").strip().lower()
        pair = (job.get("title", "").strip().lower(), job.get("company", "").strip().lower())
        if url and url in seen_urls:
            continue
        if pair[0] and pair[1] and pair in seen_pairs:
            continue
        if url:
            seen_urls.add(url)
        if pair[0] and pair[1]:
            seen_pairs.add(pair)
        unique.append(job)
    return unique


def apply_filters(jobs: List[Dict], seen_path: Path) -> List[Dict]:
    """
    Pipeline:
      1. Seniority match
      2. Location rules
      3. Dedupe within this run
      4. Drop anything we've already emailed about
    """
    seen = _load_seen(seen_path)
    
    after_seniority = [j for j in jobs if _has_seniority_match(j.get("title", ""))]
    logger.info(f"After seniority filter: {len(after_seniority)}/{len(jobs)}")
    
    after_location = [j for j in after_seniority if _passes_location_rules(j)]
    logger.info(f"After location filter: {len(after_location)}/{len(after_seniority)}")
    
    after_dedupe = _dedupe(after_location)
    logger.info(f"After dedupe: {len(after_dedupe)}/{len(after_location)}")
    
    fresh = [j for j in after_dedupe if j.get("url", "").strip().lower() not in seen]
    logger.info(f"After seen filter: {len(fresh)}/{len(after_dedupe)}")
    
    return fresh


def mark_as_seen(jobs: List[Dict], seen_path: Path) -> None:
    """Call this after the email is sent successfully."""
    urls = [j.get("url", "") for j in jobs if j.get("url")]
    seen = _load_seen(seen_path)
    _save_seen(seen_path, seen, urls)
