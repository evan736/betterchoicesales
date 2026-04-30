"""Weekly A/B test digest — emailed to evan@ every Friday at 8 AM CT.

Summarizes:
  - Last 7 days of quote activity (per-arm sent / replied / bound / lost)
  - Rolling 30-day stats (so trends emerge as data accumulates)
  - Win/loss callout: which arm is leading, and by how much

Sent only when there's at least one quote with a variant in the last 7
days. Skip empty weeks to avoid noisy 'nothing to report' emails.
"""
import os
import logging
from datetime import datetime, timedelta

import requests as http_requests
from sqlalchemy.orm import Session

from app.models.campaign import Quote

logger = logging.getLogger(__name__)


def _summarize(quotes):
    sent = len(quotes)
    replied = sum(1 for q in quotes if q.reply_received)
    bound = sum(1 for q in quotes if q.converted_sale_id)
    lost = sum(1 for q in quotes if (q.status or "") == "lost")
    return {
        "sent": sent,
        "replied": replied,
        "bound": bound,
        "lost": lost,
        "reply_rate": (replied / sent * 100) if sent else 0.0,
        "bind_rate": (bound / sent * 100) if sent else 0.0,
    }


def _verdict(arm_a, arm_b, metric_key, label):
    """Build a human-readable callout for which arm is winning a metric.

    Only declares a winner when both arms have at least 5 sends — small
    samples are too noisy to be meaningful. Returns an HTML snippet.
    """
    if arm_a["sent"] < 5 or arm_b["sent"] < 5:
        return (
            f'<span style="color:#94a3b8;font-size:12px;">{label}: not enough '
            f'data yet (need 5+ sends per arm).</span>'
        )
    a_val = arm_a[metric_key]
    b_val = arm_b[metric_key]
    if a_val == b_val:
        return f'<span style="color:#94a3b8;font-size:12px;">{label}: tied at {a_val:.1f}%.</span>'
    if a_val > b_val:
        diff = a_val - b_val
        return (
            f'<span style="color:#a855f7;font-size:12px;font-weight:600;">'
            f'{label}: <strong>Variant A leads</strong> by {diff:.1f} pts '
            f'({a_val:.1f}% vs {b_val:.1f}%).</span>'
        )
    diff = b_val - a_val
    return (
        f'<span style="color:#10b981;font-size:12px;font-weight:600;">'
        f'{label}: <strong>Variant B leads</strong> by {diff:.1f} pts '
        f'({b_val:.1f}% vs {a_val:.1f}%).</span>'
    )


def build_digest_html(week_a, week_b, month_a, month_b) -> str:
    """Compose the digest HTML using both 7-day and 30-day windows."""
    app_url = os.environ.get("APP_URL", "https://better-choice-web.onrender.com")

    def arm_table(label, color, week, month):
        return f"""
        <div style="flex:1;min-width:240px;padding:16px;background:#f8fafc;border:1px solid {color}30;border-radius:10px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};"></span>
            <span style="font-size:14px;font-weight:700;color:{color};">{label}</span>
          </div>
          <table style="width:100%;border-collapse:collapse;font-size:12px;color:#475569;">
            <tr><td style="padding:3px 0;width:55%;">Sent (last 7d):</td><td style="text-align:right;font-weight:600;color:#0f172a;">{week["sent"]}</td></tr>
            <tr><td style="padding:3px 0;">Replied:</td><td style="text-align:right;font-weight:600;color:#f59e0b;">{week["replied"]} ({week["reply_rate"]:.1f}%)</td></tr>
            <tr><td style="padding:3px 0;">Bound:</td><td style="text-align:right;font-weight:600;color:#10b981;">{week["bound"]} ({week["bind_rate"]:.1f}%)</td></tr>
            <tr><td style="padding:3px 0;">Lost:</td><td style="text-align:right;font-weight:600;color:#dc2626;">{week["lost"]}</td></tr>
            <tr><td colspan="2" style="padding-top:10px;border-top:1px dashed #cbd5e1;"></td></tr>
            <tr><td style="padding:3px 0;color:#94a3b8;font-size:11px;">30-day reply rate:</td><td style="text-align:right;color:#475569;font-size:11px;">{month["reply_rate"]:.1f}%</td></tr>
            <tr><td style="padding:3px 0;color:#94a3b8;font-size:11px;">30-day bind rate:</td><td style="text-align:right;color:#475569;font-size:11px;">{month["bind_rate"]:.1f}%</td></tr>
            <tr><td style="padding:3px 0;color:#94a3b8;font-size:11px;">30-day total sent:</td><td style="text-align:right;color:#475569;font-size:11px;">{month["sent"]}</td></tr>
          </table>
        </div>"""

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;">
      <div style="background:#1e293b;color:#fff;padding:20px;border-radius:10px 10px 0 0;">
        <div style="font-size:12px;letter-spacing:2px;font-weight:700;">ORBIT · QUOTE EMAIL A/B TEST</div>
        <div style="font-size:18px;font-weight:600;margin-top:6px;">📊 Weekly Digest</div>
      </div>
      <div style="background:#fff;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 10px 10px;">
        <p style="color:#475569;font-size:14px;margin-top:0;">Hi Evan,</p>
        <p style="color:#475569;font-size:14px;">
          Here's how your quote email A/B test performed in the last 7 days,
          alongside rolling 30-day stats for trend context.
        </p>

        <div style="display:flex;gap:12px;margin:20px 0;flex-wrap:wrap;">
          {arm_table('Variant A · Branded + Coverage', '#a855f7', week_a, month_a)}
          {arm_table('Variant B · Plain-text Personal', '#10b981', week_b, month_b)}
        </div>

        <div style="background:#f1f5f9;border-radius:8px;padding:14px 16px;margin:16px 0;">
          <div style="font-size:11px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
            30-day verdict
          </div>
          <div style="margin-bottom:6px;">{_verdict(month_a, month_b, "reply_rate", "Reply rate")}</div>
          <div>{_verdict(month_a, month_b, "bind_rate", "Bind rate")}</div>
        </div>

        <p style="color:#64748b;font-size:12px;line-height:1.5;margin:16px 0;">
          Reply rate measures how often a customer replies to your email.
          Bind rate measures how often a quote ultimately converts to a sale.
          Variants are assigned 50/50 at first send and stick through all 5
          follow-ups (initial + day 3, 7, 14, 30).
        </p>

        <p style="margin:20px 0 0 0;text-align:center;">
          <a href="{app_url}/quotes" style="background:#0ea5e9;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block;font-size:14px;">
            Open Quote Pipeline →
          </a>
        </p>
      </div>
    </div>
    """


def send_weekly_digest(db: Session) -> dict:
    """Send the weekly A/B test digest. Returns a dict describing what was sent."""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # 7-day window
    week_quotes = (
        db.query(Quote)
        .filter(Quote.email_sent == True)
        .filter(Quote.email_sent_at >= week_ago)
        .filter(Quote.email_variant.isnot(None))
        .all()
    )

    # If nothing happened in the last 7 days, skip the email entirely.
    if not week_quotes:
        logger.info("A/B weekly digest: no quotes in last 7 days — skipping send")
        return {"sent": False, "reason": "no_activity"}

    week_a = _summarize([q for q in week_quotes if (q.email_variant or "").upper() == "A"])
    week_b = _summarize([q for q in week_quotes if (q.email_variant or "").upper() == "B"])

    # 30-day rolling window for trend
    month_quotes = (
        db.query(Quote)
        .filter(Quote.email_sent == True)
        .filter(Quote.email_sent_at >= month_ago)
        .filter(Quote.email_variant.isnot(None))
        .all()
    )
    month_a = _summarize([q for q in month_quotes if (q.email_variant or "").upper() == "A"])
    month_b = _summarize([q for q in month_quotes if (q.email_variant or "").upper() == "B"])

    html = build_digest_html(week_a, week_b, month_a, month_b)

    mg_key = os.environ.get("MAILGUN_API_KEY")
    mg_domain = os.environ.get("MAILGUN_DOMAIN")
    if not mg_key or not mg_domain:
        logger.warning("A/B weekly digest: Mailgun not configured")
        return {"sent": False, "reason": "no_mailgun"}

    try:
        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{mg_domain}/messages",
            auth=("api", mg_key),
            data={
                "from": f"ORBIT A/B Test <noreply@{mg_domain}>",
                "to": "evan@betterchoiceins.com",
                "subject": f"📊 Quote A/B test weekly digest — A:{week_a['sent']} B:{week_b['sent']}",
                "html": html,
            },
            timeout=15,
        )
        ok = resp.status_code == 200
        logger.info(f"A/B weekly digest sent — week:A={week_a['sent']} B={week_b['sent']}, status={resp.status_code}")
        return {
            "sent": ok,
            "week_a": week_a,
            "week_b": week_b,
            "month_a": month_a,
            "month_b": month_b,
        }
    except Exception as e:
        logger.error(f"A/B weekly digest send error: {e}")
        return {"sent": False, "reason": str(e)}
