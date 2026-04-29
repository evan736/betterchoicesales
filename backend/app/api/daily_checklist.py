"""
Daily Checklist API — tracks daily operational tasks like running non-pay lists.
Simple key-value storage per day. Resets each day automatically.
"""
import logging
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime
from app.core.database import get_db, Base

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/checklist", tags=["checklist"])


# ── Model ────────────────────────────────────────────────────────────────────

class DailyChecklistItem(Base):
    __tablename__ = "daily_checklist_items"
    id = Column(Integer, primary_key=True)
    check_date = Column(Date, nullable=False, default=date.today)
    item_key = Column(String, nullable=False)  # e.g. "nonpay_safeco"
    completed = Column(Boolean, default=False)
    completed_by = Column(String, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)


# ── Default checklist items ──────────────────────────────────────────────────

DEFAULT_NONPAY_ITEMS = [
    # Key kept as nonpay_safeco for backwards compat with existing checked-off
    # rows in the database — Liberty Mutual's portal still ships statements
    # under the Safeco identifier internally.
    {"key": "nonpay_safeco", "label": "Liberty Mutual Non-Pay List", "carrier": "Liberty Mutual"},
    {"key": "nonpay_travelers", "label": "Travelers Non-Pay List", "carrier": "Travelers"},
    {"key": "nonpay_grange", "label": "Grange Non-Pay List", "carrier": "Grange"},
    {"key": "nonpay_natgen", "label": "National General Non-Pay List", "carrier": "National General"},
    {"key": "nonpay_progressive", "label": "Progressive Non-Pay List", "carrier": "Progressive"},
    {"key": "nonpay_geico", "label": "GEICO Non-Pay List", "carrier": "GEICO"},
    {"key": "nonpay_steadily", "label": "Steadily Non-Pay List", "carrier": "Steadily"},
]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/today")
def get_today_checklist(db: Session = Depends(get_db)):
    """Get today's checklist with completion status."""
    today = date.today()

    # Get existing completions for today
    existing = db.query(DailyChecklistItem).filter(
        DailyChecklistItem.check_date == today
    ).all()
    completed_keys = {item.item_key: item for item in existing}

    items = []
    for defn in DEFAULT_NONPAY_ITEMS:
        existing_item = completed_keys.get(defn["key"])
        items.append({
            "key": defn["key"],
            "label": defn["label"],
            "carrier": defn["carrier"],
            "completed": existing_item.completed if existing_item else False,
            "completed_by": existing_item.completed_by if existing_item else None,
            "completed_at": existing_item.completed_at.isoformat() if existing_item and existing_item.completed_at else None,
            "notes": existing_item.notes if existing_item else None,
        })

    completed_count = sum(1 for i in items if i["completed"])
    return {
        "date": today.isoformat(),
        "items": items,
        "completed": completed_count,
        "total": len(items),
        "all_done": completed_count == len(items),
    }


@router.post("/toggle/{item_key}")
def toggle_checklist_item(
    item_key: str,
    db: Session = Depends(get_db),
    username: Optional[str] = None,
    notes: Optional[str] = None,
):
    """Toggle a checklist item for today."""
    today = date.today()

    existing = db.query(DailyChecklistItem).filter(
        DailyChecklistItem.check_date == today,
        DailyChecklistItem.item_key == item_key,
    ).first()

    if existing:
        existing.completed = not existing.completed
        if existing.completed:
            existing.completed_at = datetime.utcnow()
            existing.completed_by = username
        else:
            existing.completed_at = None
            existing.completed_by = None
        if notes:
            existing.notes = notes
    else:
        existing = DailyChecklistItem(
            check_date=today,
            item_key=item_key,
            completed=True,
            completed_by=username,
            completed_at=datetime.utcnow(),
            notes=notes,
        )
        db.add(existing)

    db.commit()
    return {
        "key": item_key,
        "completed": existing.completed,
        "completed_by": existing.completed_by,
        "completed_at": existing.completed_at.isoformat() if existing.completed_at else None,
    }


@router.get("/history")
def get_checklist_history(days: int = 7, db: Session = Depends(get_db)):
    """Get checklist completion history for the last N days."""
    from datetime import timedelta
    start_date = date.today() - timedelta(days=days)

    items = db.query(DailyChecklistItem).filter(
        DailyChecklistItem.check_date >= start_date,
        DailyChecklistItem.completed == True,
    ).all()

    # Group by date
    by_date = {}
    for item in items:
        d = item.check_date.isoformat()
        if d not in by_date:
            by_date[d] = {"date": d, "completed": 0, "total": len(DEFAULT_NONPAY_ITEMS)}
        by_date[d]["completed"] += 1

    return {"history": sorted(by_date.values(), key=lambda x: x["date"], reverse=True)}
