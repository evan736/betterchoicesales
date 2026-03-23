"""
Monthly Agency Report Generator
Aggregates sales, commissions, retention, reshop, carrier, customer growth,
and campaign data into a comprehensive monthly report.

Auto-sends PDF email on the 1st of each month.
Also accessible via API for in-app viewing.
"""

import os
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_

logger = logging.getLogger(__name__)


def generate_monthly_report(db: Session, year: int, month: int) -> dict:
    """Generate comprehensive monthly agency report.
    
    Returns a dict with all report sections ready for PDF generation or API response.
    """
    from app.models.sale import Sale
    from app.models.user import User
    from app.models.reshop import Reshop
    from app.models.customer import Customer, CustomerPolicy
    from app.models.smart_inbox import InboundEmail
    from app.core.config import settings

    # Date range for the month
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    # Previous month for comparisons
    if month == 1:
        prev_start = date(year - 1, 12, 1)
        prev_end = date(year, 1, 1)
    else:
        prev_start = date(year, month - 1, 1)
        prev_end = start_date

    month_name = start_date.strftime("%B %Y")

    report = {
        "period": month_name,
        "year": year,
        "month": month,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "generated_at": datetime.utcnow().isoformat(),
        "sections": {},
    }

    # ══════════════════════════════════════════════════════════════════
    # 1. SALES SUMMARY — by producer
    # ══════════════════════════════════════════════════════════════════
    try:
        sales = db.query(Sale).filter(
            Sale.sale_date >= start_date,
            Sale.sale_date < end_date,
        ).all()

        prev_sales = db.query(Sale).filter(
            Sale.sale_date >= prev_start,
            Sale.sale_date < prev_end,
        ).all()

        total_premium = sum(float(s.written_premium or 0) for s in sales)
        prev_premium = sum(float(s.written_premium or 0) for s in prev_sales)
        premium_change = ((total_premium - prev_premium) / prev_premium * 100) if prev_premium > 0 else 0

        total_items = sum(int(s.items or 1) for s in sales)

        # By producer
        by_producer = defaultdict(lambda: {"sales": 0, "premium": 0.0, "items": 0})
        for s in sales:
            name = s.producer_name or "Unknown"
            by_producer[name]["sales"] += 1
            by_producer[name]["premium"] += float(s.written_premium or 0)
            by_producer[name]["items"] += int(s.items or 1)

        producer_list = sorted(
            [{"name": k, **v} for k, v in by_producer.items()],
            key=lambda x: x["premium"], reverse=True
        )

        # By lead source
        by_source = defaultdict(lambda: {"sales": 0, "premium": 0.0})
        for s in sales:
            src = s.lead_source or "unknown"
            by_source[src]["sales"] += 1
            by_source[src]["premium"] += float(s.written_premium or 0)

        report["sections"]["sales"] = {
            "total_sales": len(sales),
            "total_premium": round(total_premium, 2),
            "total_items": total_items,
            "prev_month_premium": round(prev_premium, 2),
            "premium_change_pct": round(premium_change, 1),
            "by_producer": producer_list,
            "by_lead_source": sorted(
                [{"source": k, **v} for k, v in by_source.items()],
                key=lambda x: x["premium"], reverse=True
            ),
        }
    except Exception as e:
        logger.error("Report sales section failed: %s", e)
        report["sections"]["sales"] = {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 2. COMMISSION EARNINGS — by producer
    # ══════════════════════════════════════════════════════════════════
    try:
        from app.models.commission import Commission
        
        period_str = f"{year}-{month:02d}"
        commissions = db.query(Commission).filter(
            Commission.period == period_str
        ).all()

        by_agent = defaultdict(lambda: {"amount": 0.0, "sales_count": 0})
        for c in commissions:
            agent = c.agent_name or "Unknown"
            by_agent[agent]["amount"] += float(c.commission_amount or 0)
            by_agent[agent]["sales_count"] += 1

        total_commissions = sum(v["amount"] for v in by_agent.values())

        report["sections"]["commissions"] = {
            "total_commissions": round(total_commissions, 2),
            "period": period_str,
            "by_agent": sorted(
                [{"agent": k, **v} for k, v in by_agent.items()],
                key=lambda x: x["amount"], reverse=True
            ),
        }
    except Exception as e:
        logger.error("Report commissions section failed: %s", e)
        report["sections"]["commissions"] = {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 3. RETENTION RATE / LOST CUSTOMERS
    # ══════════════════════════════════════════════════════════════════
    try:
        from app.models.retention import RetentionRecord

        retention_records = db.query(RetentionRecord).filter(
            RetentionRecord.created_at >= start_date,
            RetentionRecord.created_at < end_date,
        ).all()

        renewed = sum(1 for r in retention_records if r.outcome == "renewed")
        lost = sum(1 for r in retention_records if r.outcome == "lost")
        moved = sum(1 for r in retention_records if r.outcome == "carrier_move")
        total_tracked = len(retention_records)
        retention_rate = (renewed / total_tracked * 100) if total_tracked > 0 else 100.0

        report["sections"]["retention"] = {
            "total_tracked": total_tracked,
            "renewed": renewed,
            "lost": lost,
            "carrier_moved": moved,
            "retention_rate": round(retention_rate, 1),
        }
    except Exception as e:
        logger.error("Report retention section failed: %s", e)
        report["sections"]["retention"] = {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 4. RESHOP PIPELINE RESULTS
    # ══════════════════════════════════════════════════════════════════
    try:
        reshops_completed = db.query(Reshop).filter(
            Reshop.completed_at >= start_date,
            Reshop.completed_at < end_date,
        ).all()

        reshops_created = db.query(Reshop).filter(
            Reshop.created_at >= start_date,
            Reshop.created_at < end_date,
        ).all()

        bound = [r for r in reshops_completed if r.stage == "bound"]
        lost = [r for r in reshops_completed if r.stage == "lost"]
        renewed = [r for r in reshops_completed if r.stage == "renewed"]

        total_savings = sum(float(r.premium_savings or 0) for r in bound)

        # Active pipeline
        active_reshops = db.query(Reshop).filter(
            Reshop.stage.in_(["proactive", "new_request", "quoting", "quote_ready", "presenting"])
        ).count()

        report["sections"]["reshop"] = {
            "created_this_month": len(reshops_created),
            "rewrites": len(bound),
            "renewed_stayed": len(renewed),
            "lost": len(lost),
            "total_savings": round(total_savings, 2),
            "active_pipeline": active_reshops,
            "win_rate": round(len(bound) / max(len(bound) + len(lost), 1) * 100, 1),
        }
    except Exception as e:
        logger.error("Report reshop section failed: %s", e)
        report["sections"]["reshop"] = {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 5. REVENUE BY CARRIER
    # ══════════════════════════════════════════════════════════════════
    try:
        by_carrier = defaultdict(lambda: {"premium": 0.0, "sales": 0, "items": 0})
        for s in sales:
            carrier = s.carrier or "Unknown"
            by_carrier[carrier]["premium"] += float(s.written_premium or 0)
            by_carrier[carrier]["sales"] += 1
            by_carrier[carrier]["items"] += int(s.items or 1)

        report["sections"]["carriers"] = {
            "by_carrier": sorted(
                [{"carrier": k, **v} for k, v in by_carrier.items()],
                key=lambda x: x["premium"], reverse=True
            ),
        }
    except Exception as e:
        logger.error("Report carriers section failed: %s", e)
        report["sections"]["carriers"] = {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 6. CUSTOMER GROWTH
    # ══════════════════════════════════════════════════════════════════
    try:
        # New customers this month (from sales)
        new_customers = len(set(s.client_name for s in sales if s.lead_source != "rewrite"))
        rewrites = len([s for s in sales if s.lead_source == "rewrite"])

        # Total active customers from NowCerts
        total_active = db.query(Customer).filter(
            Customer.status.ilike("%active%")
        ).count()

        total_policies = db.query(CustomerPolicy).filter(
            func.lower(CustomerPolicy.status).in_(["active", "in force", "inforce"])
        ).count()

        report["sections"]["growth"] = {
            "new_customers": new_customers,
            "rewrites": rewrites,
            "total_active_customers": total_active,
            "total_active_policies": total_policies,
        }
    except Exception as e:
        logger.error("Report growth section failed: %s", e)
        report["sections"]["growth"] = {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 7. CAMPAIGN PERFORMANCE
    # ══════════════════════════════════════════════════════════════════
    try:
        from app.models.requote_campaign import RequoteCampaign, RequoteLead

        campaigns = db.query(RequoteCampaign).filter(
            RequoteCampaign.status.in_(["active", "paused", "completed"])
        ).all()

        campaign_data = []
        for c in campaigns:
            campaign_data.append({
                "name": c.name,
                "status": c.status,
                "total_leads": c.total_valid or 0,
                "emails_sent": c.emails_sent or 0,
                "responses": c.responses_received or 0,
                "requotes": c.requotes_generated or 0,
                "opted_out": getattr(c, 'opted_out', 0) or 0,
            })

        report["sections"]["campaigns"] = {
            "campaigns": campaign_data,
        }
    except Exception as e:
        logger.error("Report campaigns section failed: %s", e)
        report["sections"]["campaigns"] = {"error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # 8. PREMIUM GROWTH — month over month trend
    # ══════════════════════════════════════════════════════════════════
    try:
        # Get last 6 months of premium data
        months_data = []
        for i in range(5, -1, -1):
            m = month - i
            y = year
            while m <= 0:
                m += 12
                y -= 1

            m_start = date(y, m, 1)
            if m == 12:
                m_end = date(y + 1, 1, 1)
            else:
                m_end = date(y, m + 1, 1)

            m_sales = db.query(Sale).filter(
                Sale.sale_date >= m_start,
                Sale.sale_date < m_end,
            ).all()

            m_premium = sum(float(s.written_premium or 0) for s in m_sales)
            m_count = len(m_sales)

            months_data.append({
                "month": m_start.strftime("%b %Y"),
                "premium": round(m_premium, 2),
                "sales": m_count,
            })

        report["sections"]["premium_growth"] = {
            "months": months_data,
        }
    except Exception as e:
        logger.error("Report premium growth section failed: %s", e)
        report["sections"]["premium_growth"] = {"error": str(e)}

    return report


def send_monthly_report_email(db: Session, year: int, month: int) -> dict:
    """Generate the monthly report and email it as a branded HTML email."""
    from app.core.config import settings
    import requests as http_requests

    report = generate_monthly_report(db, year, month)

    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"status": "error", "reason": "mailgun_not_configured"}

    # Build HTML email from report data
    html = _build_report_html(report)
    subject = "ORBIT Monthly Report — " + report["period"]

    from_email = settings.MAILGUN_FROM_EMAIL or "service@betterchoiceins.com"
    to_email = os.environ.get("REPORT_EMAIL", "evan@betterchoiceins.com")

    try:
        resp = http_requests.post(
            "https://api.mailgun.net/v3/" + settings.MAILGUN_DOMAIN + "/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": "ORBIT Reports <" + from_email + ">",
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
            timeout=30,
        )
        logger.info("Monthly report email: %s -> %s", resp.status_code, to_email)
        return {"status": "sent", "to": to_email, "mailgun_status": resp.status_code}
    except Exception as e:
        logger.error("Monthly report email failed: %s", e)
        return {"status": "error", "reason": str(e)}


def _build_report_html(report: dict) -> str:
    """Build a branded HTML email from the report data."""
    period = report["period"]
    s = report["sections"]

    sales = s.get("sales", {})
    commissions = s.get("commissions", {})
    retention = s.get("retention", {})
    reshop = s.get("reshop", {})
    carriers = s.get("carriers", {})
    growth = s.get("growth", {})
    campaigns = s.get("campaigns", {})
    premium_growth = s.get("premium_growth", {})

    # Producer rows
    producer_rows = ""
    for p in sales.get("by_producer", []):
        producer_rows += (
            '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
            '<td style="padding:10px 12px; font-weight:600; color:#f1f5f9;">' + p["name"] + '</td>'
            '<td style="padding:10px 12px; text-align:center; color:#e2e8f0;">' + str(p["sales"]) + '</td>'
            '<td style="padding:10px 12px; text-align:center; color:#e2e8f0;">' + str(p["items"]) + '</td>'
            '<td style="padding:10px 12px; text-align:right; font-weight:700; color:#34d399;">${:,.0f}</td>'.format(p["premium"]) +
            '</tr>'
        )

    # Carrier rows
    carrier_rows = ""
    for c in carriers.get("by_carrier", [])[:10]:
        carrier_rows += (
            '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
            '<td style="padding:8px 12px; color:#f1f5f9;">' + c["carrier"] + '</td>'
            '<td style="padding:8px 12px; text-align:center; color:#e2e8f0;">' + str(c["sales"]) + '</td>'
            '<td style="padding:8px 12px; text-align:right; font-weight:600; color:#34d399;">${:,.0f}</td>'.format(c["premium"]) +
            '</tr>'
        )

    # Premium trend
    trend_cells = ""
    for m in premium_growth.get("months", []):
        trend_cells += (
            '<td style="padding:8px; text-align:center;">'
            '<div style="font-size:11px; color:#94a3b8;">' + m["month"] + '</div>'
            '<div style="font-size:16px; font-weight:700; color:#f1f5f9;">${:,.0f}</div>'.format(m["premium"]) +
            '<div style="font-size:11px; color:#64748b;">' + str(m["sales"]) + ' sales</div>'
            '</td>'
        )

    # Campaign rows
    campaign_rows = ""
    for c in campaigns.get("campaigns", []):
        campaign_rows += (
            '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">'
            '<td style="padding:8px 12px; color:#f1f5f9; font-size:13px;">' + c["name"] + '</td>'
            '<td style="padding:8px 12px; text-align:center; color:#e2e8f0;">' + str(c["emails_sent"]) + '</td>'
            '<td style="padding:8px 12px; text-align:center; color:#34d399;">' + str(c["responses"]) + '</td>'
            '</tr>'
        )

    premium_change = sales.get("premium_change_pct", 0)
    change_color = "#34d399" if premium_change >= 0 else "#f87171"
    change_arrow = "↑" if premium_change >= 0 else "↓"

    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0; padding:0; background:#0a0e1a; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">'
        '<div style="max-width:680px; margin:0 auto; padding:24px 16px;">'

        # Header
        '<div style="background:linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding:32px; border-radius:16px 16px 0 0; text-align:center;">'
        '<img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="BCI" style="height:40px; margin-bottom:16px;" />'
        '<h1 style="margin:0; color:#fff; font-size:24px; font-weight:800;">Monthly Agency Report</h1>'
        '<p style="margin:6px 0 0; color:#94a3b8; font-size:15px;">' + period + '</p>'
        '</div>'

        # Body
        '<div style="background:#0f1424; padding:32px; border-left:1px solid rgba(255,255,255,0.06); border-right:1px solid rgba(255,255,255,0.06);">'

        # KPI cards
        '<div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-bottom:28px;">'
        
        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:16px; text-align:center;">'
        '<div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px;">Premium</div>'
        '<div style="font-size:26px; font-weight:800; color:#f1f5f9; margin:4px 0;">${:,.0f}</div>'.format(sales.get("total_premium", 0)) +
        '<div style="font-size:12px; color:' + change_color + '; font-weight:600;">' + change_arrow + ' ' + str(abs(premium_change)) + '% vs last month</div>'
        '</div>'

        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:16px; text-align:center;">'
        '<div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px;">Policies Sold</div>'
        '<div style="font-size:26px; font-weight:800; color:#f1f5f9; margin:4px 0;">' + str(sales.get("total_sales", 0)) + '</div>'
        '<div style="font-size:12px; color:#64748b;">' + str(sales.get("total_items", 0)) + ' items</div>'
        '</div>'

        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:16px; text-align:center;">'
        '<div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px;">Retention</div>'
        '<div style="font-size:26px; font-weight:800; color:#34d399; margin:4px 0;">' + str(retention.get("retention_rate", 100)) + '%</div>'
        '<div style="font-size:12px; color:#64748b;">' + str(retention.get("lost", 0)) + ' lost</div>'
        '</div>'
        '</div>'

        # Second row KPIs
        '<div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-bottom:28px;">'
        
        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:16px; text-align:center;">'
        '<div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px;">Reshop Rewrites</div>'
        '<div style="font-size:26px; font-weight:800; color:#60a5fa; margin:4px 0;">' + str(reshop.get("rewrites", 0)) + '</div>'
        '<div style="font-size:12px; color:#64748b;">$' + '{:,.0f}'.format(reshop.get("total_savings", 0)) + ' saved</div>'
        '</div>'

        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:16px; text-align:center;">'
        '<div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px;">New Customers</div>'
        '<div style="font-size:26px; font-weight:800; color:#f1f5f9; margin:4px 0;">' + str(growth.get("new_customers", 0)) + '</div>'
        '<div style="font-size:12px; color:#64748b;">' + str(growth.get("total_active_customers", 0)) + ' total active</div>'
        '</div>'

        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:16px; text-align:center;">'
        '<div style="font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px;">Active Pipeline</div>'
        '<div style="font-size:26px; font-weight:800; color:#fbbf24; margin:4px 0;">' + str(reshop.get("active_pipeline", 0)) + '</div>'
        '<div style="font-size:12px; color:#64748b;">reshops in progress</div>'
        '</div>'
        '</div>'

        # Premium Trend
        '<h2 style="font-size:16px; font-weight:700; color:#f1f5f9; margin:24px 0 12px;">Premium Growth — 6 Month Trend</h2>'
        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; overflow:hidden;">'
        '<table style="width:100%; border-collapse:collapse;"><tr>' + trend_cells + '</tr></table>'
        '</div>'

        # Producer Leaderboard
        '<h2 style="font-size:16px; font-weight:700; color:#f1f5f9; margin:24px 0 12px;">Producer Leaderboard</h2>'
        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; overflow:hidden;">'
        '<table style="width:100%; border-collapse:collapse;">'
        '<thead><tr style="background:rgba(255,255,255,0.03); border-bottom:1px solid rgba(255,255,255,0.08);">'
        '<th style="padding:10px 12px; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase;">Producer</th>'
        '<th style="padding:10px 12px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Sales</th>'
        '<th style="padding:10px 12px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Items</th>'
        '<th style="padding:10px 12px; text-align:right; color:#64748b; font-size:11px; text-transform:uppercase;">Premium</th>'
        '</tr></thead><tbody>' + producer_rows + '</tbody></table></div>'

        # Carrier Breakdown
        '<h2 style="font-size:16px; font-weight:700; color:#f1f5f9; margin:24px 0 12px;">Revenue by Carrier</h2>'
        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; overflow:hidden;">'
        '<table style="width:100%; border-collapse:collapse;">'
        '<thead><tr style="background:rgba(255,255,255,0.03); border-bottom:1px solid rgba(255,255,255,0.08);">'
        '<th style="padding:8px 12px; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase;">Carrier</th>'
        '<th style="padding:8px 12px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Sales</th>'
        '<th style="padding:8px 12px; text-align:right; color:#64748b; font-size:11px; text-transform:uppercase;">Premium</th>'
        '</tr></thead><tbody>' + carrier_rows + '</tbody></table></div>'

        # Campaign Performance
        '<h2 style="font-size:16px; font-weight:700; color:#f1f5f9; margin:24px 0 12px;">Campaign Performance</h2>'
        '<div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:12px; overflow:hidden;">'
        '<table style="width:100%; border-collapse:collapse;">'
        '<thead><tr style="background:rgba(255,255,255,0.03); border-bottom:1px solid rgba(255,255,255,0.08);">'
        '<th style="padding:8px 12px; text-align:left; color:#64748b; font-size:11px; text-transform:uppercase;">Campaign</th>'
        '<th style="padding:8px 12px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Sent</th>'
        '<th style="padding:8px 12px; text-align:center; color:#64748b; font-size:11px; text-transform:uppercase;">Responses</th>'
        '</tr></thead><tbody>' + campaign_rows + '</tbody></table></div>'

        # CTA
        '<div style="text-align:center; margin:28px 0 0;">'
        '<a href="https://orbit.betterchoiceins.com/reports" style="display:inline-block; background:linear-gradient(135deg, #2563eb, #1d4ed8); color:white; padding:14px 36px; border-radius:10px; text-decoration:none; font-weight:700; font-size:15px;">'
        'View Full Report in ORBIT</a></div>'

        '</div>'

        # Footer
        '<div style="background:#0a0e1a; padding:16px; text-align:center; border-radius:0 0 16px 16px; border-top:1px solid rgba(255,255,255,0.06);">'
        '<p style="margin:0; color:#475569; font-size:11px;">Better Choice Insurance Group &middot; ORBIT Agency Management</p>'
        '</div>'

        '</div></body></html>'
    )

    return html
