"""BEACON Live Context — pull real-time data from ORBIT for BEACON to reference."""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

logger = logging.getLogger(__name__)


def get_live_context(query: str, db: Session) -> str:
    """Pull relevant live data from ORBIT based on the user's query.
    Returns formatted context string to inject into BEACON's prompt."""
    
    parts = []
    query_lower = query.lower()
    
    # Always include carrier list — BEACON should know what we sell
    try:
        carrier_context = _get_carrier_context(db)
        if carrier_context:
            parts.append(carrier_context)
    except Exception as e:
        logger.warning(f"Failed to get carrier context: {e}")
    
    # Sales stats if asking about performance, volume, production
    sales_keywords = ["sales", "production", "volume", "how many", "sold", "premium", "written",
                      "month", "this week", "today", "top", "leading", "performance", "numbers"]
    if any(kw in query_lower for kw in sales_keywords):
        try:
            sales_context = _get_sales_context(db)
            if sales_context:
                parts.append(sales_context)
        except Exception as e:
            logger.warning(f"Failed to get sales context: {e}")
    
    # Agent/team info if asking about team, agents, producers
    team_keywords = ["agent", "producer", "team", "who", "staff", "employee"]
    if any(kw in query_lower for kw in team_keywords):
        try:
            team_context = _get_team_context(db)
            if team_context:
                parts.append(team_context)
        except Exception as e:
            logger.warning(f"Failed to get team context: {e}")
    
    if not parts:
        return ""
    
    return "\n\n## Live ORBIT Data (real-time from your system)\n" + "\n\n".join(parts)


def _get_carrier_context(db: Session) -> str:
    """Get list of carriers the agency actually writes with, from the database."""
    try:
        from app.models.agency_config import AgencyConfig
        from app.models.sale import Sale
        
        # Carriers from config table
        configs = db.query(AgencyConfig).filter(
            AgencyConfig.config_type == "carrier",
            AgencyConfig.is_active == True,
        ).all()
        
        carrier_names = set()
        for c in configs:
            carrier_names.add(c.display_name or c.name)
        
        # Also get carriers from actual sales (in case config is incomplete)
        in_use = db.query(distinct(Sale.carrier)).filter(
            Sale.carrier.isnot(None),
            Sale.carrier != "",
        ).all()
        for row in in_use:
            name = row[0].replace("_", " ").title() if row[0] else ""
            if name:
                carrier_names.add(name)
        
        if not carrier_names:
            return ""
        
        # Get sale counts per carrier for the last 90 days
        ninety_days = datetime.utcnow() - timedelta(days=90)
        carrier_counts = db.query(
            Sale.carrier, func.count(Sale.id)
        ).filter(
            Sale.carrier.isnot(None),
            Sale.created_at >= ninety_days,
        ).group_by(Sale.carrier).all()
        
        count_map = {}
        for carrier, count in carrier_counts:
            display = carrier.replace("_", " ").title() if carrier else ""
            count_map[display] = count
        
        lines = ["### Carriers We Write (from ORBIT database)"]
        lines.append("These are the carriers Better Choice Insurance has active appointments with:")
        for name in sorted(carrier_names):
            count = count_map.get(name, 0)
            suffix = f" — {count} policies written last 90 days" if count > 0 else ""
            lines.append(f"- **{name}**{suffix}")
        
        lines.append("\nIMPORTANT: If an agent asks 'do we sell X carrier?' — check this list. If a carrier is listed here, the answer is YES.")
        
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Carrier context error: {e}")
        return ""


def _get_sales_context(db: Session) -> str:
    """Get recent sales stats."""
    try:
        from app.models.sale import Sale
        
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Today's sales
        today_count = db.query(func.count(Sale.id)).filter(
            Sale.created_at >= today_start
        ).scalar() or 0
        
        today_premium = db.query(func.coalesce(func.sum(Sale.premium), 0)).filter(
            Sale.created_at >= today_start
        ).scalar() or 0
        
        # This week
        week_count = db.query(func.count(Sale.id)).filter(
            Sale.created_at >= week_start
        ).scalar() or 0
        
        week_premium = db.query(func.coalesce(func.sum(Sale.premium), 0)).filter(
            Sale.created_at >= week_start
        ).scalar() or 0
        
        # This month
        month_count = db.query(func.count(Sale.id)).filter(
            Sale.created_at >= month_start
        ).scalar() or 0
        
        month_premium = db.query(func.coalesce(func.sum(Sale.premium), 0)).filter(
            Sale.created_at >= month_start
        ).scalar() or 0
        
        # Top carriers this month
        top_carriers = db.query(
            Sale.carrier, func.count(Sale.id), func.coalesce(func.sum(Sale.premium), 0)
        ).filter(
            Sale.created_at >= month_start,
            Sale.carrier.isnot(None),
        ).group_by(Sale.carrier).order_by(func.count(Sale.id).desc()).limit(5).all()
        
        # Top producers this month
        top_producers = db.query(
            Sale.agent_name, func.count(Sale.id), func.coalesce(func.sum(Sale.premium), 0)
        ).filter(
            Sale.created_at >= month_start,
            Sale.agent_name.isnot(None),
        ).group_by(Sale.agent_name).order_by(func.count(Sale.id).desc()).limit(5).all()
        
        lines = ["### Sales Stats (live from ORBIT)"]
        lines.append(f"- **Today**: {today_count} policies, ${today_premium:,.0f} premium")
        lines.append(f"- **This week**: {week_count} policies, ${week_premium:,.0f} premium")
        lines.append(f"- **This month**: {month_count} policies, ${month_premium:,.0f} premium")
        
        if top_carriers:
            lines.append("\n**Top carriers this month:**")
            for carrier, count, premium in top_carriers:
                display = (carrier or "").replace("_", " ").title()
                lines.append(f"- {display}: {count} policies, ${float(premium):,.0f}")
        
        if top_producers:
            lines.append("\n**Top producers this month:**")
            for agent, count, premium in top_producers:
                lines.append(f"- {agent}: {count} policies, ${float(premium):,.0f}")
        
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Sales context error: {e}")
        return ""


def _get_team_context(db: Session) -> str:
    """Get active team members info."""
    try:
        from app.models.user import User
        
        users = db.query(User).filter(User.is_active == True).all()
        
        lines = ["### Team Members (from ORBIT)"]
        for u in users:
            if u.username == "beacon.ai":
                continue
            role = (u.role or "agent").title()
            lines.append(f"- **{u.full_name or u.username}** — {role}")
        
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Team context error: {e}")
        return ""
