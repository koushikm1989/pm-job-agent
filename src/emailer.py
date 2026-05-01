"""Send the weekly job digest via Gmail SMTP."""
import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import List, Dict

logger = logging.getLogger(__name__)


def _score_style(score: int) -> Dict[str, str]:
    """Return badge styling based on score band."""
    if score >= 85:
        return {"bg": "#dafbe1", "border": "#1a7f37", "text": "#1a7f37", "label": "Strong fit"}
    if score >= 75:
        return {"bg": "#fff8c5", "border": "#9a6700", "text": "#7d4e00", "label": "Good fit"}
    return {"bg": "#eaeef2", "border": "#656d76", "text": "#424a53", "label": "Worth a look"}


def _build_job_card(job: Dict, index: int) -> str:
    score = job.get("score", 0)
    style = _score_style(score)
    title = escape(job.get("title", "Untitled"))
    company = escape(job.get("company", "Unknown"))
    location = escape(job.get("location", ""))
    source = escape(job.get("source", ""))
    url = escape(job.get("url", "#"))
    reason = escape(job.get("reason", ""))
    red_flags = escape(job.get("red_flags", "") or "")
    is_remote = "Remote" if job.get("is_remote") else "On-site / Hybrid"
    
    red_flag_block = ""
    if red_flags and red_flags.lower() not in ("", "none", "n/a", "parse_error", "none identified"):
        red_flag_block = f"""
        <div style="margin-top:12px;padding:10px 12px;background:#fff8f8;border-left:3px solid #cf222e;border-radius:4px;">
          <div style="font-size:12px;font-weight:600;color:#cf222e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Watch out</div>
          <div style="font-size:13px;color:#1f2328;line-height:1.5;">{red_flags}</div>
        </div>
        """
    
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #d0d7de;border-radius:10px;background:#ffffff;margin-bottom:16px;border-collapse:separate;">
      <tr>
        <td style="padding:20px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="padding-bottom:12px;">
                <div style="font-size:11px;color:#656d76;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:6px;">
                  #{index} &middot; {source}
                </div>
                <div style="font-size:18px;font-weight:600;line-height:1.3;margin-bottom:6px;">
                  <a href="{url}" style="color:#0969da;text-decoration:none;">{title}</a>
                </div>
                <div style="font-size:14px;color:#1f2328;">
                  <strong>{company}</strong>
                </div>
                <div style="font-size:13px;color:#656d76;margin-top:2px;">
                  {location} &middot; {is_remote}
                </div>
              </td>
            </tr>
            <tr>
              <td>
                <div style="display:inline-block;background:{style['bg']};border:1px solid {style['border']};color:{style['text']};padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;">
                  {style['label']} &middot; {score}/100
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding-top:14px;">
                <div style="color:#1f2328;font-size:14px;line-height:1.6;">
                  {reason}
                </div>
                {red_flag_block}
              </td>
            </tr>
            <tr>
              <td style="padding-top:16px;">
                <a href="{url}" style="display:inline-block;background:#0969da;color:#ffffff;padding:8px 18px;border-radius:6px;font-size:13px;font-weight:500;text-decoration:none;">View role &rarr;</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """


def _build_email_html(jobs: List[Dict]) -> str:
    today = datetime.utcnow().strftime("%B %d, %Y")
    
    if not jobs:
        body = """
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#fff8c5;border-radius:10px;border:1px solid #d4a72c;">
          <tr>
            <td style="padding:24px;color:#1f2328;font-size:14px;line-height:1.6;">
              <strong style="font-size:15px;">Quiet week.</strong><br/>
              No roles cleared the score threshold this run. Could be a low-volume week, or some sources may have been rate-limited. Check the GitHub Actions log if this happens again.
            </td>
          </tr>
        </table>
        """
        summary = "0 roles this week"
    else:
        cards = "".join(_build_job_card(j, i + 1) for i, j in enumerate(jobs))
        top_score = max(j.get("score", 0) for j in jobs)
        body = cards
        summary = f"{len(jobs)} role{'s' if len(jobs) != 1 else ''} &middot; top match {top_score}/100"
    
    return f"""<!DOCTYPE html>
    <html>
      <head><meta charset="utf-8"/></head>
      <body style="margin:0;padding:0;background:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f6f8fa;padding:32px 16px;">
          <tr>
            <td align="center">
              <table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">
                
                <tr>
                  <td style="background:linear-gradient(135deg,#0969da 0%,#0550ae 100%);border-radius:12px 12px 0 0;padding:28px 28px 24px 28px;">
                    <div style="font-size:11px;color:#cae8ff;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;margin-bottom:6px;">
                      {today}
                    </div>
                    <div style="font-size:24px;font-weight:700;color:#ffffff;line-height:1.2;margin-bottom:8px;">
                      Weekly Open PM Roles
                    </div>
                    <div style="font-size:14px;color:#cae8ff;line-height:1.5;">
                      Curated for your profile &middot; {summary}
                    </div>
                  </td>
                </tr>
                
                <tr>
                  <td style="background:#ffffff;padding:24px;border-radius:0 0 12px 12px;">
                    {body}
                  </td>
                </tr>
                
                <tr>
                  <td style="padding:20px 4px 8px 4px;text-align:center;">
                    <div style="font-size:12px;color:#656d76;line-height:1.6;">
                      Verify Glassdoor / AmbitionBox ratings manually before applying.<br/>
                      Generated by your job agent &middot; <a href="https://github.com" style="color:#656d76;">view on GitHub</a>
                    </div>
                  </td>
                </tr>
                
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """


def send_digest(jobs: List[Dict]) -> None:
    """Send the email. Reads creds from env vars."""
    sender = os.environ.get("GMAIL_SENDER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("EMAIL_RECIPIENT", sender)
    
    if not sender or not app_password:
        raise RuntimeError("GMAIL_SENDER or GMAIL_APP_PASSWORD not set")
    
    today = datetime.utcnow().strftime("%b %d")
    subject = f"Weekly Open PM Roles - {today} - {len(jobs)} matches"
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(_build_email_html(jobs), "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender, app_password)
            server.sendmail(sender, [recipient], msg.as_string())
        logger.info(f"Email sent to {recipient}")
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        raise
