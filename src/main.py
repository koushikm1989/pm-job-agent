"""Entry point. Run: python -m src.main"""
import logging
import sys
from pathlib import Path

from src.fetchers import fetch_all
from src.filters import apply_filters, mark_as_seen
from src.scorer import score_jobs
from src.emailer import send_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("main")

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "data" / "profile.md"
SEEN_PATH = ROOT / "data" / "seen_jobs.json"


def main() -> int:
    logger.info("=" * 60)
    logger.info("Weekly PM Job Agent starting")
    logger.info("=" * 60)
    
    if not PROFILE_PATH.exists():
        logger.error(f"Profile file missing: {PROFILE_PATH}")
        return 1
    
    # 1. Fetch from all sources
    logger.info("Step 1/4: Fetching jobs from all sources")
    raw_jobs = fetch_all()
    logger.info(f"Total raw jobs fetched: {len(raw_jobs)}")
    
    if not raw_jobs:
        logger.warning("No jobs fetched at all. Sending empty digest so you know cron ran.")
        send_digest([])
        return 0
    
    # 2. Apply deterministic filters
    logger.info("Step 2/4: Applying filters")
    filtered = apply_filters(raw_jobs, SEEN_PATH)
    
    if not filtered:
        logger.info("No jobs passed filters. Sending empty digest.")
        send_digest([])
        return 0
    
    # 3. Score with Haiku
    logger.info("Step 3/4: Scoring with Claude Haiku")
    final_jobs = score_jobs(filtered, PROFILE_PATH)
    
    # 4. Email and mark as seen
    logger.info("Step 4/4: Sending email")
    send_digest(final_jobs)
    
    if final_jobs:
        mark_as_seen(final_jobs, SEEN_PATH)
        logger.info(f"Marked {len(final_jobs)} jobs as seen")
    
    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
