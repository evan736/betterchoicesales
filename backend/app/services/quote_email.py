"""Quote Email Service — carrier-branded quote emails with PDF attachments.

Sends professional carrier-specific emails with:
- Carrier logo + selling point
- Highlighted premium amount
- Attached quote PDF(s)
- Agent contact info
- CTA to bind (mailto reply)
"""
import logging
import os
import requests
from typing import Optional
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)


POLICY_TYPE_LABELS = {
    "auto": "Auto Insurance",
    "home": "Homeowners Insurance",
    "renters": "Renters Insurance",
    "condo": "Condo Insurance",
    "landlord": "Landlord Insurance",
    "umbrella": "Umbrella Insurance",
    "motorcycle": "Motorcycle Insurance",
    "boat": "Boat Insurance",
    "rv": "RV Insurance",
    "life": "Life Insurance",
    "commercial": "Commercial Insurance",
    "bundled": "Bundled Insurance",
    "other": "Insurance",
}

# ── Carrier selling points ────────────────────────────────────────
CARRIER_SELLING_POINTS = {
    "national_general": (
        "National General has been protecting families for over 80 years. "
        "Rated A+ (Superior) by AM Best, they're known for flexible payment options, "
        "fast claims handling, and affordable bundled coverage — a top choice for home and auto."
    ),
    "progressive": (
        "Progressive is the #3 largest auto insurer in the U.S. and a proven industry leader. "
        "Known for their multi-policy discounts, competitive rates, "
        "and 24/7 claims service, Progressive consistently delivers exceptional value."
    ),
    "travelers": (
        "Travelers is one of the largest and most respected insurers in the country, "
        "with over 160 years of experience. Rated A++ by AM Best, they offer superior "
        "coverage options, industry-leading claim response times, and personalized service."
    ),
    "safeco": (
        "Liberty Mutual (formerly Safeco) is built specifically for independent agents and offers "
        "comprehensive home, auto, and umbrella coverage. With Fortune 100 backing and an "
        "A (Excellent) AM Best rating, Liberty Mutual is a trusted name in personal insurance. "
        "(Note: Safeco rebranded to Liberty Mutual effective April 25, 2026 — same underwriting, new name.)"
    ),
    "grange": (
        "Grange Insurance has been a Midwest staple since 1935, earning an A (Excellent) "
        "AM Best rating. Known for their outstanding local claims service, community focus, "
        "and competitive bundle discounts, Grange is a customer-first company."
    ),
    "hippo": (
        "Hippo is modernizing home insurance with proactive smart home protection. "
        "Their policies include built-in equipment breakdown coverage, home maintenance "
        "monitoring, and a fast digital experience — insurance designed for how you live today."
    ),
    "openly": (
        "Openly specializes in premium homeowners insurance with best-in-class coverage. "
        "Their policies feature guaranteed replacement cost, water backup coverage, and "
        "flexible deductible options — all backed by exceptional customer satisfaction ratings."
    ),
    "bristol_west": (
        "Bristol West, a Farmers Insurance company, specializes in auto coverage for every "
        "driver. With flexible payment plans, a streamlined claims process, and strong "
        "financial backing, Bristol West makes quality coverage accessible to everyone."
    ),
    "branch": (
        "Branch is one of the fastest-growing insurers in America, offering instant quotes "
        "and community-based pricing that rewards responsible neighbors. Their bundled home "
        "and auto packages deliver some of the most competitive rates in the market."
    ),
    "clearcover": (
        "Clearcover offers premium auto insurance at lower prices by using smart technology "
        "to reduce overhead. Their mobile-first experience includes a fast claims process, "
        "great customer ratings, and prices that are often 20%+ below traditional carriers."
    ),
    "gainsco": (
        "Gainsco has been a trusted auto insurer since 1978, specializing in affordable "
        "coverage with flexible payment options. Known for competitive rates and responsive "
        "claims service, Gainsco keeps you protected without breaking the bank."
    ),
    "geico": (
        "GEICO is one of the most recognized names in insurance, serving over 17 million "
        "policyholders. With a AA+ financial strength rating, 24/7 service, and consistently "
        "competitive rates, GEICO continues to be a market leader."
    ),
    "american_modern": (
        "American Modern, a Munich Re company, is the nation's leading specialty insurer. "
        "With an A+ AM Best rating and 50+ years of experience, they provide tailored "
        "coverage for manufactured homes, landlord properties, and unique insurance needs."
    ),
    "covertree": (
        "CoverTree is revolutionizing manufactured home insurance with fast, affordable, "
        "digital-first policies. Their coverage is designed specifically for mobile and "
        "manufactured homes, offering comprehensive protection at competitive prices."
    ),
    "steadily": (
        "Steadily is the #1 landlord insurance provider in the U.S., purpose-built for "
        "rental property owners. With instant quotes, broad coverage including loss of rent, "
        "and competitive pricing, Steadily makes protecting your investment effortless."
    ),
    "next": (
        "NEXT Insurance is the leading digital insurer for small businesses, rated A- "
        "by AM Best. With instant certificates of insurance, affordable premiums, and a "
        "100% online experience, NEXT makes commercial coverage simple and accessible."
    ),
    "integrity": (
        "Integrity Insurance has been a trusted Midwest carrier since 1933. With an A "
        "(Excellent) AM Best rating, they provide personalized coverage, local claims "
        "handling, and the kind of service that keeps customers for life."
    ),
    "universal_property": (
        "Universal Property & Casualty is Florida's #1 homeowners insurer, providing "
        "comprehensive hurricane and windstorm coverage. With rapid claims processing and "
        "competitive rates, they specialize in protecting homes in high-risk areas."
    ),
}

# ── Carrier trust & ratings data ──────────────────────────────────
CARRIER_TRUST = {
    "national_general": {
        "am_best": "A+", "am_best_label": "Superior",
        "claims_stat": "95% claims satisfaction",
        "customers": "Over 3 million policyholders nationwide",
        "highlight": "80+ years protecting families across America",
    },
    "progressive": {
        "am_best": "A+", "am_best_label": "Superior",
        "claims_stat": "#1 in claims satisfaction for bundled policies",
        "customers": "Over 28 million policies in force",
        "highlight": "3rd largest auto insurer in the U.S.",
    },
    "travelers": {
        "am_best": "A++", "am_best_label": "Superior",
        "claims_stat": "Award-winning claims service",
        "customers": "160+ years serving customers",
        "highlight": "One of America's most trusted insurance brands",
    },
    "safeco": {
        "am_best": "A", "am_best_label": "Excellent",
        "claims_stat": "Liberty Mutual's national claims network",
        "customers": "100+ years of insurance experience",
        "highlight": "Liberty Mutual is a Fortune 100 company (formerly marketed as Safeco)",
    },
    "grange": {
        "am_best": "A", "am_best_label": "Excellent",
        "claims_stat": "Local claims adjusters in every market",
        "customers": "Serving the Midwest since 1935",
        "highlight": "90+ years of community-focused insurance",
    },
    "hippo": {
        "am_best": "A-", "am_best_label": "Excellent",
        "claims_stat": "Fast digital claims in as little as 48 hours",
        "customers": "Proactive smart home protection included",
        "highlight": "Named one of Forbes' best startup employers",
    },
    "openly": {
        "am_best": "A", "am_best_label": "Excellent",
        "claims_stat": "Top-rated for customer satisfaction",
        "customers": "Specialists in premium homeowners coverage",
        "highlight": "Guaranteed replacement cost on every policy",
    },
    "bristol_west": {
        "am_best": "A", "am_best_label": "Excellent",
        "claims_stat": "Streamlined claims backed by Farmers Insurance",
        "customers": "Part of the Farmers Insurance Group",
        "highlight": "Flexible coverage for every type of driver",
    },
    "branch": {
        "am_best": "A-", "am_best_label": "Excellent",
        "claims_stat": "Fast, fair claims process",
        "customers": "One of the fastest-growing insurers in America",
        "highlight": "Community-based pricing saves neighbors money together",
    },
    "clearcover": {
        "am_best": "A-", "am_best_label": "Excellent",
        "claims_stat": "Claims processed up to 3x faster than average",
        "customers": "Rated 4.7/5 stars by customers",
        "highlight": "Prices often 20%+ below traditional carriers",
    },
    "geico": {
        "am_best": "A++", "am_best_label": "Superior",
        "claims_stat": "24/7 claims service with fast resolution",
        "customers": "Over 17 million policyholders",
        "highlight": "One of the most recognized names in insurance",
    },
    "american_modern": {
        "am_best": "A+", "am_best_label": "Superior",
        "claims_stat": "Specialized claims expertise for unique properties",
        "customers": "Backed by Munich Re, one of the world's largest reinsurers",
        "highlight": "50+ years as the nation's leading specialty insurer",
    },
    "steadily": {
        "am_best": "A", "am_best_label": "Excellent",
        "claims_stat": "Dedicated landlord claims support",
        "customers": "#1 landlord insurance provider in the U.S.",
        "highlight": "Purpose-built for rental property owners",
    },
    "integrity": {
        "am_best": "A", "am_best_label": "Excellent",
        "claims_stat": "Local claims handling by people who know your area",
        "customers": "Midwest families trust Integrity since 1933",
        "highlight": "90+ years of personalized coverage",
    },
    "universal_property": {
        "am_best": "A", "am_best_label": "Excellent",
        "claims_stat": "Rapid hurricane claims processing",
        "customers": "Florida's #1 homeowners insurer",
        "highlight": "Specialists in high-risk coastal coverage",
    },
}


def build_quote_email_html(
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: str,
    premium_term: str = "6 months",
    effective_date: str = "",
    agent_name: str = "",
    agent_email: str = "",
    agent_phone: str = "",
    additional_notes: str = "",
    is_multi_quote: bool = False,
    quotes_summary: list = None,
    quote_id: int = None,
    unsubscribe_token: str = None,
    # Coverage limits — only rendered when at least one is provided.
    # These come from the Quote row (set during PDF extraction).
    # For home/condo/renters/landlord:
    coverage_dwelling: float = None,
    coverage_personal_property: float = None,
    coverage_liability: float = None,
    # For auto (strings like "100/300"):
    auto_bi_limit: str = None,
    auto_pd_limit: str = None,
    auto_um_limit: str = None,
) -> str:
    """Build carrier-branded quote email HTML."""
    from app.services.welcome_email import CARRIER_INFO, BCI_NAVY, BCI_CYAN

    carrier_key = (carrier or "").lower().replace(" ", "_")
    cinfo = CARRIER_INFO.get(carrier_key, {})
    accent = cinfo.get("accent_color", BCI_CYAN)
    carrier_name = cinfo.get("display_name", (carrier or "Insurance").title())
    policy_label = POLICY_TYPE_LABELS.get(policy_type, "Insurance")
    first_name = prospect_name.split()[0] if prospect_name else "there"

    # Carrier logo URL
    app_url = getattr(settings, 'FRONTEND_URL', None) or "https://better-choice-web.onrender.com"
    carrier_logo_url = f"{app_url}/carrier-logos/{carrier_key}.png"

    # Carrier selling point
    selling_point = CARRIER_SELLING_POINTS.get(carrier_key, "")

    # Effective date display
    eff_html = ""
    if effective_date:
        eff_html = f'<p style="color:#64748B;font-size:13px;margin:4px 0 0 0;">Effective Date: <strong>{effective_date}</strong></p>'

    # ── Coverage Highlights (Variant A feature) ────────────────────
    # Renders ONLY when at least one limit is provided. Three-card row.
    # Home limits prefer dwelling/personal property/liability.
    # Auto limits show BI / PD / UM.
    # Bundled quotes can show both rows stacked.
    coverage_html = ""
    home_has_any = any([coverage_dwelling, coverage_personal_property, coverage_liability])
    auto_has_any = any([auto_bi_limit, auto_pd_limit, auto_um_limit])

    def _fmt_money(v):
        if v is None:
            return None
        try:
            n = float(v)
            return f"${n:,.0f}"
        except (TypeError, ValueError):
            return None

    def _build_3card_row(cards, accent_hex):
        """cards = [(label, value), ...]  — emits a 3-up grid with consistent styling.

        Skips cards with None/empty values so we never show 'N/A' boxes.
        Pads to 3 if needed (with empty boxes) so layout stays even.
        """
        valid = [(lbl, val) for lbl, val in cards if val]
        if not valid:
            return ""
        cells = ""
        for lbl, val in valid:
            cells += f"""
                <td style="padding:6px;text-align:center;width:33%;vertical-align:top;">
                    <div style="background:{accent_hex}10;border:1px solid {accent_hex}25;border-radius:8px;padding:14px 8px;">
                        <p style="margin:0;font-size:18px;font-weight:800;color:#1e293b;letter-spacing:-0.5px;">{val}</p>
                        <p style="margin:4px 0 0 0;font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;">{lbl}</p>
                    </div>
                </td>"""
        # If only 1 or 2 valid cards, pad with empty cells for alignment
        for _ in range(3 - len(valid)):
            cells += '<td style="width:33%;"></td>'
        return f"""
        <table style="width:100%;border-collapse:collapse;margin:8px 0;" cellpadding="0" cellspacing="0">
            <tr>{cells}</tr>
        </table>"""

    if home_has_any or auto_has_any:
        rows_inner = ""
        if home_has_any:
            rows_inner += _build_3card_row(
                [
                    ("Dwelling", _fmt_money(coverage_dwelling)),
                    ("Personal Property", _fmt_money(coverage_personal_property)),
                    ("Personal Liability", _fmt_money(coverage_liability)),
                ],
                accent,
            )
        if auto_has_any:
            # For auto, prepend "$" to numeric-only limits like "100"
            def _fmt_auto(v):
                if not v:
                    return None
                v_str = str(v).strip()
                if not v_str or v_str.lower() == "none":
                    return None
                # If purely numeric, treat as $Nk
                try:
                    float(v_str)
                    return f"${v_str}k"
                except ValueError:
                    pass
                # If split limit (e.g. 100/300), format as $100k/$300k
                if "/" in v_str:
                    parts = v_str.split("/")
                    if all(p.strip().replace(".", "").isdigit() for p in parts):
                        return "/".join(f"${p.strip()}k" for p in parts)
                return v_str  # fallback: as-is

            rows_inner += _build_3card_row(
                [
                    ("Bodily Injury", _fmt_auto(auto_bi_limit)),
                    ("Property Damage", _fmt_auto(auto_pd_limit)),
                    ("Uninsured Motorist", _fmt_auto(auto_um_limit)),
                ],
                accent,
            )

        if rows_inner:  # don't render empty wrapper
            coverage_html = f"""
            <div style="margin:20px 0;">
                <p style="margin:0 0 10px 0;color:#1e293b;font-size:14px;font-weight:700;">Coverage Highlights</p>
                {rows_inner}
            </div>"""

    # Multi-quote comparison table
    multi_html = ""
    if is_multi_quote and quotes_summary:
        rows = ""
        for q in quotes_summary:
            rows += f"""<tr>
                <td style="padding:10px 14px;border-bottom:1px solid #E2E8F0;font-size:14px;font-weight:600;color:#1e293b;">{q.get('carrier','').title()}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #E2E8F0;font-size:14px;color:#334155;">{q.get('policy_type','').title()}</td>
                <td style="padding:10px 14px;border-bottom:1px solid #E2E8F0;font-size:18px;font-weight:700;color:{accent};">{q.get('premium','')}</td>
            </tr>"""
        multi_html = f"""
        <div style="margin:20px 0;">
            <p style="color:#1e293b;font-size:14px;font-weight:bold;margin:0 0 10px 0;">Your Coverage Breakdown:</p>
            <table style="width:100%;border-collapse:collapse;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;">
                <tr style="background:#F8FAFC;">
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#64748B;font-weight:600;">Carrier</th>
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#64748B;font-weight:600;">Coverage</th>
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#64748B;font-weight:600;">Premium</th>
                </tr>
                {rows}
            </table>
        </div>"""

    # Carrier logo + selling point section
    carrier_section = ""
    trust_data = CARRIER_TRUST.get(carrier_key, {})
    if selling_point:
        # Build trust badges row
        trust_badges = ""
        if trust_data:
            am_best = trust_data.get("am_best", "")
            am_label = trust_data.get("am_best_label", "")
            claims = trust_data.get("claims_stat", "")
            customers = trust_data.get("customers", "")
            highlight = trust_data.get("highlight", "")
            trust_badges = f"""
            <div style="margin:16px 0 0 0;padding:16px 0 0 0;border-top:1px solid #E2E8F0;">
                <p style="margin:0 0 12px 0;font-size:12px;color:#64748B;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Why Customers Trust {carrier_name}</p>
                <table style="width:100%;border-collapse:collapse;" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="padding:8px 6px;text-align:center;width:33%;vertical-align:top;">
                            <div style="background:#ECFDF5;border-radius:8px;padding:10px 8px;">
                                <p style="margin:0;font-size:22px;font-weight:800;color:#059669;">{am_best}</p>
                                <p style="margin:2px 0 0 0;font-size:10px;color:#059669;font-weight:600;">AM BEST RATED</p>
                                <p style="margin:2px 0 0 0;font-size:10px;color:#6B7280;">{am_label}</p>
                            </div>
                        </td>
                        <td style="padding:8px 6px;text-align:center;width:33%;vertical-align:top;">
                            <div style="background:#EFF6FF;border-radius:8px;padding:10px 8px;">
                                <p style="margin:0;font-size:14px;font-weight:700;color:#2563EB;">&#9733;</p>
                                <p style="margin:2px 0 0 0;font-size:10px;color:#2563EB;font-weight:600;">CLAIMS</p>
                                <p style="margin:2px 0 0 0;font-size:10px;color:#6B7280;">{claims}</p>
                            </div>
                        </td>
                        <td style="padding:8px 6px;text-align:center;width:33%;vertical-align:top;">
                            <div style="background:#F5F3FF;border-radius:8px;padding:10px 8px;">
                                <p style="margin:0;font-size:14px;font-weight:700;color:#7C3AED;">&#10003;</p>
                                <p style="margin:2px 0 0 0;font-size:10px;color:#7C3AED;font-weight:600;">PROVEN</p>
                                <p style="margin:2px 0 0 0;font-size:10px;color:#6B7280;">{highlight}</p>
                            </div>
                        </td>
                    </tr>
                </table>
            </div>"""

        carrier_section = f"""
        <div style="background:#F8FAFC;border-radius:10px;padding:20px;margin:20px 0;border:1px solid #E2E8F0;text-align:center;">
            <img src="{carrier_logo_url}" alt="{carrier_name}" style="max-height:48px;max-width:200px;margin:0 auto 12px auto;display:block;" />
            <p style="margin:0 0 8px 0;font-size:12px;color:#64748B;text-transform:uppercase;letter-spacing:1px;font-weight:600;">AI Overview of {carrier_name}</p>
            <p style="margin:0;color:#475569;font-size:13px;line-height:1.6;font-style:italic;">
                "{selling_point}"
            </p>
            {trust_badges}
        </div>"""

    # Agent section
    agent_html = ""
    if agent_name:
        # Headshot only renders when producer has one configured (Evan)
        try:
            from app.services.producer_signatures import producer_headshot_html
            _agent_headshot = producer_headshot_html(agent_name, size_px=80)
        except Exception:
            _agent_headshot = ""
        agent_html = f"""
        <div style="background:#F8FAFC;border-radius:8px;padding:16px;margin:20px 0;border:1px solid #E2E8F0;">
            <p style="margin:0 0 4px 0;font-size:12px;color:#64748B;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Your Insurance Advisor</p>
            {_agent_headshot}
            <p style="margin:0;font-size:15px;font-weight:bold;color:#1e293b;">{agent_name}</p>
            {f'<p style="margin:2px 0 0 0;font-size:13px;color:#64748B;">{agent_email}</p>' if agent_email else ''}
            {f'<p style="margin:2px 0 0 0;font-size:13px;color:#64748B;">{agent_phone}</p>' if agent_phone else ''}
        </div>"""

    # Notes
    notes_html = ""
    if additional_notes:
        notes_html = f"""
        <div style="background:#FFFBEB;border-left:4px solid #F59E0B;padding:12px 16px;margin:16px 0;border-radius:0 8px 8px 0;">
            <p style="margin:0;color:#92400E;font-size:13px;"><strong>A note for you:</strong> {additional_notes}</p>
        </div>"""

    # Build the bind confirmation page URL
    api_url = getattr(settings, 'API_URL', None) or "https://better-choice-api.onrender.com"
    bind_url = f"{api_url}/api/bind/{quote_id}" if quote_id else f"mailto:{agent_email or 'service@betterchoiceins.com'}"

    # Unsubscribe link
    unsub_html = ""
    if unsubscribe_token:
        unsub_url = f"{api_url}/api/unsubscribe/{unsubscribe_token}"
        unsub_html = f'<p style="color:#94a3b8;font-size:11px;margin:4px 0 0 0;"><a href="{unsub_url}" style="color:#94a3b8;text-decoration:underline;">Unsubscribe from follow-up emails</a></p>'

    # Calculate monthly premium for any multi-month term
    monthly_display = premium  # fallback to full premium if can't calculate
    if premium:
        try:
            raw = premium.replace("$", "").replace(",", "")
            total = float(raw)
            import re
            months_match = re.search(r'(\d+)', premium_term or "")
            months = int(months_match.group(1)) if months_match else 0
            if months > 1:
                monthly = total / months
                monthly_display = f"${monthly:,.2f}"
        except (ValueError, ZeroDivisionError):
            pass

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg, #1a2b5f 0%, #162249 60%, #0c4a6e 100%);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center;">
    <img src="https://better-choice-web.onrender.com/carrier-logos/bci_header_white.png" alt="Better Choice Insurance Group" width="220" style="display:block;margin:0 auto;max-width:220px;height:auto;" />
    <p style="margin:6px 0 0 0;color:{accent};font-size:13px;font-weight:600;">Your {carrier_name} {policy_label} Quote</p>
  </div>

  <!-- Body -->
  <div style="background:white;padding:32px;border-radius:0 0 12px 12px;border:1px solid #E2E8F0;border-top:none;">

    <p style="color:#1e293b;font-size:16px;margin:0 0 16px 0;">
      Hi {first_name},
    </p>

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 20px 0;">
      Thank you for the opportunity to quote your {policy_label.lower()}!
      {"Here are the options we found for you:" if is_multi_quote else f"We have put together a {carrier_name} quote for your review."}
    </p>

    {multi_html}

    <!-- Premium Highlight Box -->
    <div style="background:linear-gradient(135deg, {accent}12, {accent}08);border:2px solid {accent}40;border-radius:12px;padding:24px;margin:20px 0;text-align:center;">
      <p style="margin:0 0 4px 0;color:#64748B;font-size:12px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;">
        {"Total Bundle" if is_multi_quote else carrier_name} Quote
      </p>
      <p style="margin:0;color:#1e293b;font-size:42px;font-weight:800;letter-spacing:-1px;">
        {monthly_display}
      </p>
      <p style="margin:4px 0 0 0;color:#64748B;font-size:14px;">
        per month
      </p>
      <p style="margin:8px 0 0 0;color:#94a3b8;font-size:13px;">
        {premium} / {premium_term}
      </p>
      {eff_html}
    </div>

    {coverage_html}

    {carrier_section}

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 8px 0;">
      Your full quote details are attached as a PDF. Please review the coverages,
      deductibles, and limits to make sure everything looks good.
    </p>

    <p style="color:#334155;font-size:14px;line-height:1.6;margin:0 0 20px 0;">
      Ready to get covered? Simply reply to this email, give us a call, or click
      the button below.
    </p>

    {notes_html}

    <!-- CTA Buttons -->
    <div style="text-align:center;margin:24px 0;">
      <a href="{bind_url}" style="display:inline-block;background:{accent};color:white;padding:14px 36px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;letter-spacing:0.3px;">
        I am Ready to Bind!
      </a>
    </div>
    <div style="text-align:center;margin:0 0 20px 0;">
      <a href="tel:8479085665" style="color:{accent};font-size:13px;text-decoration:none;">
        Or call us at (847) 908-5665
      </a>
    </div>

    {agent_html}

    <!-- What Happens Next -->
    <div style="border-top:1px solid #E2E8F0;padding-top:20px;margin-top:20px;">
      <p style="color:#1e293b;font-size:14px;font-weight:bold;margin:0 0 10px 0;">What happens next?</p>
      <table style="width:100%;">
        <tr>
          <td style="vertical-align:top;padding:4px 12px 4px 0;width:24px;">
            <div style="width:24px;height:24px;background:{accent}18;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:{accent};">1</div>
          </td>
          <td style="padding:4px 0;color:#334155;font-size:13px;">Review your quote PDF and coverages</td>
        </tr>
        <tr>
          <td style="vertical-align:top;padding:4px 12px 4px 0;">
            <div style="width:24px;height:24px;background:{accent}18;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:{accent};">2</div>
          </td>
          <td style="padding:4px 0;color:#334155;font-size:13px;">Reply or call us to confirm you would like to proceed</td>
        </tr>
        <tr>
          <td style="vertical-align:top;padding:4px 12px 4px 0;">
            <div style="width:24px;height:24px;background:{accent}18;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;color:{accent};">3</div>
          </td>
          <td style="padding:4px 0;color:#334155;font-size:13px;">We will handle the rest and get you covered!</td>
        </tr>
      </table>
    </div>

    <!-- Footer -->
    <div style="border-top:1px solid #E2E8F0;padding-top:16px;margin-top:24px;text-align:center;">
      <p style="color:#94a3b8;font-size:11px;margin:0;">
        Better Choice Insurance Group | (847) 908-5665 | service@betterchoiceins.com
      </p>
      <p style="color:#94a3b8;font-size:11px;margin:4px 0 0 0;">
        This quote is valid for 24 hours. Rates and availability subject to change.
      </p>
      {unsub_html}
    </div>
  </div>
</div>
</body></html>"""


def send_quote_email(
    to_email: str,
    prospect_name: str,
    carrier: str,
    policy_type: str,
    premium: str,
    premium_term: str = "6 months",
    effective_date: str = "",
    agent_name: str = "",
    agent_email: str = "",
    agent_phone: str = "",
    additional_notes: str = "",
    pdf_path: str = None,
    pdf_filename: str = None,
    # Multi-PDF: list of {"path": str, "filename": str}. When provided
    # AND non-empty, this OVERRIDES the single pdf_path/pdf_filename
    # pair and attaches every file in the list.
    pdf_paths: list = None,
    is_multi_quote: bool = False,
    quotes_summary: list = None,
    quote_id: int = None,
    unsubscribe_token: str = None,
    # Coverage limits — passed through to build_quote_email_html.
    coverage_dwelling: float = None,
    coverage_personal_property: float = None,
    coverage_liability: float = None,
    auto_bi_limit: str = None,
    auto_pd_limit: str = None,
    auto_um_limit: str = None,
) -> dict:
    """Send quote email with PDF attachment(s) via Mailgun."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return {"success": False, "error": "Mailgun not configured"}

    from app.services.welcome_email import CARRIER_INFO
    carrier_key = (carrier or "").lower().replace(" ", "_")
    cinfo = CARRIER_INFO.get(carrier_key, {})
    carrier_name = cinfo.get("display_name", (carrier or "Insurance").title())
    policy_label = POLICY_TYPE_LABELS.get(policy_type, "Insurance")

    # Calculate monthly for subject line too
    subject_premium = premium
    try:
        raw = premium.replace("$", "").replace(",", "")
        total = float(raw)
        import re
        months_match = re.search(r'(\d+)', premium_term or "")
        months = int(months_match.group(1)) if months_match else 0
        if months > 1:
            subject_premium = f"${total / months:,.2f}"
    except (ValueError, ZeroDivisionError):
        pass
    subject = f"Your {carrier_name} {policy_label} Quote \u2014 {subject_premium}/month"
    html = build_quote_email_html(
        prospect_name=prospect_name,
        carrier=carrier,
        policy_type=policy_type,
        premium=premium,
        premium_term=premium_term,
        effective_date=effective_date,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_phone=agent_phone,
        additional_notes=additional_notes,
        is_multi_quote=is_multi_quote,
        quotes_summary=quotes_summary,
        quote_id=quote_id,
        unsubscribe_token=unsubscribe_token,
        coverage_dwelling=coverage_dwelling,
        coverage_personal_property=coverage_personal_property,
        coverage_liability=coverage_liability,
        auto_bi_limit=auto_bi_limit,
        auto_pd_limit=auto_pd_limit,
        auto_um_limit=auto_um_limit,
    )

    reply_to = "sales@betterchoiceins.com"
    from_name = f"{agent_name} at Better Choice Insurance" if agent_name else "Better Choice Insurance Group"

    agency_from = "sales@betterchoiceins.com"
    data = {
        "from": f"{from_name} <{agency_from}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "o:tracking-clicks": "yes",
        "o:tracking-opens": "yes",
        "h:Reply-To": reply_to,
        "bcc": [os.environ.get("SMART_INBOX_BCC", "evan@betterchoiceins.com")],
        "v:email_type": "quote",
        "v:variant": "A",
        "v:customer_name": prospect_name or "",
        "v:customer_email": to_email or "",
        "v:carrier": carrier_name or "",
        "v:agent_name": agent_name or "",
        "v:agent_email": agent_email or "",
        "v:quote_id": str(quote_id or ""),
    }

    # Build attachment list. If pdf_paths (the new multi-file list) is
    # provided and non-empty, use that; otherwise fall back to the
    # legacy single pdf_path field. This ensures backwards compat with
    # any callers that haven't migrated.
    files = []
    attach_list = []
    if pdf_paths:
        attach_list = [
            (p.get("path"), p.get("filename") or f"Quote_{i+1}.pdf")
            for i, p in enumerate(pdf_paths)
            if p and p.get("path")
        ]
    elif pdf_path:
        attach_list = [(pdf_path, pdf_filename or f"{carrier_name}_{policy_label}_Quote.pdf")]

    for path, fname in attach_list:
        try:
            files.append(("attachment", (fname, open(path, "rb"), "application/pdf")))
        except Exception as e:
            logger.warning(f"Could not attach PDF {path}: {e}")

    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=data,
            files=files if files else None,
        )

        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info(f"Quote email sent to {to_email} for {carrier_name} - {msg_id}")
            return {"success": True, "message_id": msg_id}
        else:
            logger.error(f"Quote email failed: {resp.status_code} {resp.text}")
            return {"success": False, "error": f"Mailgun returned {resp.status_code}"}
    except Exception as e:
        logger.error(f"Quote email error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        for _, (_, f, _) in files:
            try:
                f.close()
            except:
                pass
