"""Score jobs against the candidate profile using Claude Haiku."""
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List, Dict
from anthropic import Anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_JOBS_TO_SCORE = 60          # cap to control token spend
MIN_SCORE_TO_INCLUDE = 65       # only jobs scoring 65+ make the email
TARGET_OUTPUT_COUNT = 15        # we'll trim to this many in the end

SYSTEM_PROMPT = """You are a precise job-fit evaluator for a Lead Product Owner / Senior Product Manager candidate.

You will be given:
1. A candidate profile
2. A single job posting

Your task: score the fit on a 0-100 scale and explain why in 2 short sentences.

Scoring rubric:
- 90-100: Excellent fit. Title matches, domain matches (B2B SaaS, ideally HealthTech), seniority matches, location works.
- 75-89: Strong fit. Most criteria met, minor gaps (e.g. adjacent domain, slightly different seniority).
- 65-74: Decent fit worth a look. Title and seniority match but domain is generic B2B.
- 50-64: Weak fit. Some overlap but meaningful gaps.
- Below 50: Poor fit. Wrong seniority, wrong domain, or location-locked.

Hard penalties (cap score at 40):
- Role explicitly requires US/EU/UK/AU/JP work authorization or residency
- Role is below Senior PM seniority (APM, PM, Product Analyst, Product Marketing)
- Role is B2C only with no B2B element
- Compensation, if mentioned, is clearly below INR 35 LPA equivalent

Output ONLY valid JSON in this exact shape, nothing else:
{"score": <int 0-100>, "reason": "<2 sentence explanation>", "red_flags": "<one line, or empty string>"}
"""


def _build_user_message(profile: str, job: Dict) -> str:
    return f"""CANDIDATE PROFILE:
{profile}

---

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Source: {job.get('source', '')}
Remote: {job.get('is_remote', False)}

Description:
{job.get('description', '')[:2500]}

---

Score this job for the candidate. Output JSON only."""


def _parse_response(text: str) -> Dict:
    """Pull JSON out of the response, even if Haiku wraps it in extra text."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: regex out the first {...} block
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"score": 0, "reason": "Could not parse model response", "red_flags": "parse_error"}


def score_jobs(jobs: List[Dict], profile_path: Path) -> List[Dict]:
    """Score every job in the list. Returns jobs sorted by score, descending."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    
    profile = profile_path.read_text()
    client = Anthropic(api_key=api_key)
    
    if len(jobs) > MAX_JOBS_TO_SCORE:
        logger.info(f"Capping scoring at {MAX_JOBS_TO_SCORE} of {len(jobs)} jobs")
        jobs = jobs[:MAX_JOBS_TO_SCORE]
    
    scored = []
    for i, job in enumerate(jobs, 1):
        try:
            logger.info(f"Scoring {i}/{len(jobs)}: {job.get('title', '')[:60]}")
            response = client.messages.create(
                model=MODEL,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_message(profile, job)}],
            )
            text_response = response.content[0].text
            result = _parse_response(text_response)
            
            job_with_score = {
                **job,
                "score": int(result.get("score", 0)),
                "reason": result.get("reason", ""),
                "red_flags": result.get("red_flags", ""),
            }
            scored.append(job_with_score)
            time.sleep(0.5)  # gentle pacing
        except Exception as e:
            logger.warning(f"Scoring failed for job {i}: {e}")
            continue
    
    # Sort by score, highest first
    scored.sort(key=lambda j: j.get("score", 0), reverse=True)
    
    # Filter to keepers
    keepers = [j for j in scored if j.get("score", 0) >= MIN_SCORE_TO_INCLUDE]
    logger.info(f"Jobs above threshold {MIN_SCORE_TO_INCLUDE}: {len(keepers)}")
    
    # Trim to target count
    final = keepers[:TARGET_OUTPUT_COUNT]
    logger.info(f"Final selection: {len(final)} jobs")
    
    return final
