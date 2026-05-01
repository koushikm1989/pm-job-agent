# PM Job Agent

Weekly automated job digest for Lead Product Owner / Senior PM roles. Runs on GitHub Actions, scores matches with Claude Haiku, emails curated picks every Monday.

## What it does

1. Fetches Product Manager / Product Owner jobs from LinkedIn, Indeed, Glassdoor, Naukri, ZipRecruiter, Google Jobs, RemoteOK, WeWorkRemotely, Recruit Haus, and JobStreet SG
2. Filters by seniority keywords and location rules (remote for IN/US/EU/UK/AU/JP/NZ, on-site OK for SG)
3. Scores survivors against the candidate profile using Claude Haiku
4. Emails the top 15 matches as a curated digest
5. Tracks seen jobs so the same role never appears twice

## Schedule

Runs every Monday at 09:00 IST (03:30 UTC). Trigger manually anytime from the Actions tab.

## Setup

### Required GitHub Secrets

| Secret | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude Haiku scoring |
| `GMAIL_SENDER` | Gmail address sending the digest |
| `GMAIL_APP_PASSWORD` | 16-char app password (not regular Gmail password) |
| `EMAIL_RECIPIENT` | Where the digest lands |

### Local testing

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export GMAIL_SENDER=you@gmail.com
export GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
export EMAIL_RECIPIENT=you@gmail.com
python -m src.main
```

## Tuning

| What | Where | Default |
|---|---|---|
| Score threshold | `src/scorer.py` → `MIN_SCORE_TO_INCLUDE` | 65 |
| Final job count | `src/scorer.py` → `TARGET_OUTPUT_COUNT` | 15 |
| Max jobs scored | `src/scorer.py` → `MAX_JOBS_TO_SCORE` | 60 |
| Seniority keywords | `src/filters.py` → `SENIORITY_KEYWORDS` | — |
| Candidate profile | `data/profile.md` | — |

## Files
