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
MAX_JOBS_TO_SCORE = 70          # cap to control token spend
MIN_SCORE_TO_INCLUDE = 65       # only jobs scoring 65+ make the email
TARGET_OUTPUT_COUNT = 5         # top 5 per run

SYSTEM_PROMPT = """You are a precise job-fit evaluator for a Lead Product Owner candidate.

You will be given:
1. A candidate profile
2. A single job posting

Your task: score the fit on a 0-100 scale and explain why in 2 short sentences.

TITLE RULES (critical):
The candidate is targeting Product Owner roles specifically, plus bare "Product Manager" titles.
- "Lead Product Owner", "Senior Product Owner", "AI Product Owner", "Technical Product Owner": ideal titles.
- "Product Owner" (no prefix): good, but only score high if the description indicates Lead or Senior scope (team leadership, roadmap ownership, 8+ years experience required, or similar).
- "Product Manager" (exact, no seniority word): acceptable, but only score above 70 if the description clearly indicates senior scope. If it reads like a mid-level IC role, cap at 55.
- Any title with a seniority prefix on Product Manager (Senior PM, Lead PM, Principal PM, Group PM, Director, Head of Product): the candidate has explicitly excluded these. Score 20 or below.

LOCATION RULES (critical):
- Remote roles open to candidates in US, Europe (EU + UK), India, Singapore, Australia, or New Zealand: acceptable.
- On-site roles in Kolkata (India) or Singapore: acceptable.
- On-site anywhere else: score 25 or below.
- Any role requiring work authorization or residency the candidate does not have (US, UK, EU, AU, NZ, Canada), or that states no visa sponsorship: cap the score at 30 and note it in red_flags.
- The candidate is based in India and is open to travel.

Scoring rubric:
- 90-100: Excellent fit. PO title, B2B SaaS (ideally HealthTech, Life Sciences, or AI-first), Lead/Senior scope, location works, no sponsorship blocker.
- 75-89: Strong fit. Most criteria met, minor gaps (adjacent domain, or scope slightly unclear).
- 65-74: Decent fit worth a look. Title and location work but domain is generic B2B.
- 50-64: Weak fit. Some overlap but meaningful gaps.
- Below 50: Poor fit. Wrong title, wrong seniority, location-locked, or sponsorship blocked.

Additional hard penalties (cap score at 40):
- B2C only role with no B2B element
- Compensation, if mentioned, is clearly below INR 35 LPA equivalent
- Contract role shorter than 6 months

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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"score": 0, "reason": "Could not parse model response", "red_flags": "parse_error"}


def score_jobs(jobs: List[Dict], profile_path: Path) -> List[Dict]:
    """Score every job in the list. Returns the top N by score."""
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

    scored.sort(key=lambda j: j.get("score", 0), reverse=True)

    keepers = [j for j in scored if j.get("score", 0) >= MIN_SCORE_TO_INCLUDE]
    logger.info(f"Jobs above threshold {MIN_SCORE_TO_INCLUDE}: {len(keepers)}")

    final = keepers[:TARGET_OUTPUT_COUNT]
    logger.info(f"Final selection: {len(final)} jobs")

    return final
