"""Deterministic pre-filters. Run cheap rule-based filtering before AI scoring."""
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Set

logger = logging.getLogger(__name__)

# --- Title matching -------------------------------------------------------

# Product Owner variants we want. Matched as substrings.
PO_KEYWORDS = [
    "lead product owner",
    "senior product owner",
    "sr product owner",
    "sr. product owner",
    "ai product owner",
    "technical product owner",
    "product owner",
]

# Product Manager: EXACT title only. No seniority prefixes or suffixes.
PM_EXACT_TITLES = [
    "product manager",
]

# Anything containing these is rejected outright, even if it also
# contains a wanted keyword. Order matters: this runs first.
REJECT_TITLE_KEYWORDS = [
    # PM seniority variants explicitly excluded by the candidate
    "senior product manager", "sr product manager", "sr. product manager",
    "lead product manager", "principal product manager", "staff product manager",
    "group product manager", "product manager ii", "product manager iii",
    "director of product", "director, product", "head of product",
    "vp product", "vp of product", "vice president of product",
    "chief product officer",
    # Junior / adjacent roles
    "associate product owner", "junior product owner", "assistant product owner",
    "associate product manager", "junior product manager", "apm",
    "product marketing", "product analyst", "product designer",
    "product specialist", "product coordinator", "product support",
    "intern", "internship", "graduate", "trainee", "fresher",
]

# --- Location matching ----------------------------------------------------

# Remote is acceptable from these regions
REMOTE_OK_REGIONS = [
    # India
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad",
    "pune", "chennai", "kolkata", "gurgaon", "gurugram", "noida",
    # Singapore
    "singapore",
    # US
    "united states", "usa", "u.s.", "us-", "new york", "california",
    "san francisco", "seattle", "austin", "boston", "chicago", "denver",
    # UK
    "united kingdom", "uk", "london", "manchester", "edinburgh", "bristol",
    # EU
    "europe", "eu ", "germany", "berlin", "munich", "france", "paris",
    "netherlands", "amsterdam", "spain", "madrid", "barcelona",
    "ireland", "dublin", "poland", "warsaw", "portugal", "lisbon",
    "sweden", "stockholm", "denmark", "copenhagen", "belgium", "brussels",
    "italy", "milan", "austria", "vienna", "switzerland", "zurich",
    "czech", "prague", "romania", "bucharest", "finland", "helsinki",
    "norway", "oslo", "hungary", "budapest", "greece", "athens",
    # Australia / NZ
    "australia", "sydney", "melbourne", "brisbane", "perth",
    "new zealand", "auckland", "wellington",
]

# On-site is ONLY acceptable in these places
ONSITE_OK_LOCATIONS = [
    "kolkata", "calcutta",
    "singapore",
]

# Phrases that mean "you must physically live here" for places
# where the candidate cannot relocate
LOCATION_LOCK_PHRASES = [
    "must be based in the us", "must be based in the united states",
    "us citizens only", "us citizens and green card", "green card holders only",
    "authorized to work in the us", "authorization to work in the united states",
    "must reside in the us", "must reside in the united states",
    "us-based only", "usa-based only", "us residents only", "must be a us person",
    "us work authorization required", "requires us work authorization",
    "must be located in the uk", "uk-based only", "must reside in the uk",
    "right to work in the uk", "uk work authorization",
    "must be based in europe", "eu-based only", "eea only",
    "must have eu work", "eu work permit required", "right to work in the eu",
    "must be based in australia", "australian citizens only",
    "australian work rights", "must have australian work rights",
    "must be based in new zealand", "nz work visa required",
    "must be based in canada", "canadian work authorization",
    "no visa sponsorship", "we do not sponsor", "cannot sponsor",
    "sponsorship not available", "unable to sponsor",
]

REMOTE_SIGNALS = ["remote", "work from home", "wfh", "distributed", "anywhere"]


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


def _normalize_title(title: str) -> str:
    """Lowercase and collapse punctuation/whitespace for reliable matching."""
    t = title.lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)   # strip punctuation
    t = re.sub(r"\s+", " ", t)        # collapse whitespace
    return t


def _has_title_match(title: str) -> bool:
    """
    Strict title matching:
      1. Reject if any blocked keyword appears
      2. Accept if any Product Owner variant appears
      3. Accept if the title is EXACTLY 'Product Manager' (with optional
         leading/trailing noise like a department, but no seniority words)
    """
    t = _normalize_title(title)
    if not t:
        return False

    # Step 1: hard rejects win
    for blocked in REJECT_TITLE_KEYWORDS:
        if _normalize_title(blocked) in t:
            return False

    # Step 2: Product Owner variants
    for kw in PO_KEYWORDS:
        if _normalize_title(kw) in t:
            return True

    # Step 3: bare Product Manager only
    for kw in PM_EXACT_TITLES:
        if _normalize_title(kw) in t:
            return True

    return False


def _is_onsite_ok(location: str) -> bool:
    loc = location.lower()
    return any(kw in loc for kw in ONSITE_OK_LOCATIONS)


def _is_remote_ok_region(location: str) -> bool:
    loc = location.lower()
    return any(kw in loc for kw in REMOTE_OK_REGIONS)


def _looks_remote(job: Dict) -> bool:
    if job.get("is_remote"):
        return True
    blob = (job.get("location", "") + " " + job.get("title", "")).lower()
    return any(sig in blob for sig in REMOTE_SIGNALS)


def _has_location_lock(description: str) -> bool:
    """Check if the role explicitly excludes India-based candidates."""
    desc = description.lower()
    return any(phrase in desc for phrase in LOCATION_LOCK_PHRASES)


def _passes_location_rules(job: Dict) -> bool:
    """
    Accept if EITHER:
      A) On-site in Kolkata or Singapore, OR
      B) Remote, in an approved region, with no residency lock
    """
    location = job.get("location", "")
    description = job.get("description", "")

    # Path A: on-site in an acceptable city
    if _is_onsite_ok(location):
        return True

    # Path B: remote roles
    if _has_location_lock(description):
        return False

    if _looks_remote(job):
        # Remote with no region info at all: let it through, Haiku will judge
        if not location.strip():
            return True
        if _is_remote_ok_region(location):
            return True
        # Remote but region unclear: let it through for scoring
        return True

    # Not remote, not Kolkata/Singapore
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
      1. Strict title match
      2. Location rules
      3. Dedupe within this run
      4. Drop anything we've already emailed about
    """
    seen = _load_seen(seen_path)

    after_title = [j for j in jobs if _has_title_match(j.get("title", ""))]
    logger.info(f"After title filter: {len(after_title)}/{len(jobs)}")

    after_location = [j for j in after_title if _passes_location_rules(j)]
    logger.info(f"After location filter: {len(after_location)}/{len(after_title)}")

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
