"""Time Clock API — clock in/out, attendance tracking, commission adjustment.

Rules:
- 0–1 late days (unexcused) in month → +0.5% commission bonus
- 2–3 late days → no adjustment
- 4+ late days → −0.5% commission penalty

"Late" = clocked in after expected start time (default 9:00 AM CT).
Admin can excuse late entries (excused days don't count against the employee).
"""
import logging
from datetime import datetime, date, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.timeclock import TimeClockEntry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/timeclock", tags=["timeclock"])

# Default expected start: 9:00 AM
DEFAULT_START = time(9, 0, 0)
LATE_GRACE_MINUTES = 5  # 5 minute grace period

# Office location — Better Choice Insurance, 300 Cardinal Dr, St Charles IL
# ── Office Location (South Elgin, IL) ────────────────────────────────
# TODO: Set these to your exact office address coordinates
# Currently set to South Elgin village center — update with exact address
OFFICE_LAT = 41.9942    # Better Choice Insurance office latitude
OFFICE_LNG = -88.3123   # Better Choice Insurance office longitude
GEOFENCE_RADIUS_METERS = 150  # Must be within 150m of office


def _haversine_distance(lat1, lng1, lat2, lng2):
    """Calculate distance in meters between two GPS coordinates."""
    import math
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Debug / Health ─────────────────────────────────────────────────

@router.get("/health")
def timeclock_health(db: Session = Depends(get_db)):
    """Check if timeclock table exists and is accessible."""
    try:
        from sqlalchemy import text
        result = db.execute(text("SELECT COUNT(*) FROM timeclock_entries")).scalar()
        return {"status": "ok", "table": "timeclock_entries", "rows": result}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── Clock In ─────────────────────────────────────────────────────────

@router.post("/clock-in")
def clock_in(
    note: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    gps_accuracy: Optional[float] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clock in for the current day."""
    from fastapi.responses import JSONResponse
    try:
        now = datetime.utcnow()
        today = now.date()

        # Check if already clocked in today
        existing = db.query(TimeClockEntry).filter(
            TimeClockEntry.user_id == current_user.id,
            TimeClockEntry.work_date == today,
            TimeClockEntry.clock_out.is_(None),
        ).first()

        if existing:
            raise HTTPException(status_code=400, detail="Already clocked in today. Clock out first.")

        # Check if already completed a shift today
        completed = db.query(TimeClockEntry).filter(
            TimeClockEntry.user_id == current_user.id,
            TimeClockEntry.work_date == today,
            TimeClockEntry.clock_out.isnot(None),
        ).first()

        if completed:
            raise HTTPException(status_code=400, detail="Already completed a shift today.")

        # Determine if late (simple comparison)
        expected = DEFAULT_START
        clock_in_time = now.time()
        is_late = False
        minutes_late = 0
        try:
            grace_minutes = expected.minute + LATE_GRACE_MINUTES
            grace_hour = expected.hour + (grace_minutes // 60)
            grace_minutes = grace_minutes % 60
            grace_time = time(grace_hour, grace_minutes, 0)
            is_late = clock_in_time > grace_time
            if is_late:
                expected_dt = datetime.combine(today, expected)
                minutes_late = int((now - expected_dt).total_seconds() / 60)
        except Exception as late_err:
            logger.warning(f"Late calculation error (ignoring): {late_err}")

        # Geofence check
        is_at_office = None
        distance_from_office = None
        if latitude is not None and longitude is not None:
            try:
                distance_from_office = _haversine_distance(latitude, longitude, OFFICE_LAT, OFFICE_LNG)
                is_at_office = distance_from_office <= GEOFENCE_RADIUS_METERS
            except Exception as geo_err:
                logger.warning(f"Geofence error (ignoring): {geo_err}")

        entry = TimeClockEntry(
            user_id=current_user.id,
            work_date=today,
            clock_in=now,
            expected_start=expected,
            is_late=is_late,
            minutes_late=minutes_late,
            note=note,
            latitude=latitude,
            longitude=longitude,
            gps_accuracy=gps_accuracy,
            is_at_office=is_at_office,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        location_msg = ""
        if is_at_office is True:
            location_msg = " · At office"
        elif is_at_office is False and distance_from_office is not None:
            location_msg = f" · {int(distance_from_office)}m from office (remote)"
        elif latitude is None:
            location_msg = " · Location not shared"

        return {
            "id": entry.id,
            "status": "clocked_in",
            "clock_in": entry.clock_in.isoformat(),
            "is_late": entry.is_late,
            "minutes_late": entry.minutes_late,
            "is_at_office": is_at_office,
            "distance_from_office": int(distance_from_office) if distance_from_office is not None else None,
            "message": f"Clocked in at {now.strftime('%I:%M %p')}" + (
                f" — {minutes_late} min late" if is_late else " — on time!"
            ) + location_msg,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"CLOCK-IN CRASH: {type(e).__name__}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Clock in error: {type(e).__name__}: {str(e)[:300]}"}
        )


# ── Clock Out ────────────────────────────────────────────────────────

@router.post("/clock-out")
def clock_out(
    note: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    gps_accuracy: Optional[float] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clock out for the current day."""
    now = datetime.utcnow()
    today = now.date()

    entry = db.query(TimeClockEntry).filter(
        TimeClockEntry.user_id == current_user.id,
        TimeClockEntry.work_date == today,
        TimeClockEntry.clock_out.is_(None),
    ).first()

    if not entry:
        raise HTTPException(
            status_code=400,
            detail="Not clocked in today."
        )

    entry.clock_out = now
    if note:
        entry.note = (entry.note + " | " + note) if entry.note else note

    db.commit()

    hours_worked = (now - entry.clock_in).total_seconds() / 3600.0

    return {
        "id": entry.id,
        "status": "clocked_out",
        "clock_in": entry.clock_in.isoformat(),
        "clock_out": entry.clock_out.isoformat(),
        "hours_worked": round(hours_worked, 2),
        "message": f"Clocked out at {now.strftime('%I:%M %p')} — {hours_worked:.1f} hours today",
    }


# ── Current Status ───────────────────────────────────────────────────

@router.get("/status")
def get_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current clock status for the logged-in user."""
    now = datetime.utcnow()
    today = now.date()

    # Today's active entry
    active = db.query(TimeClockEntry).filter(
        TimeClockEntry.user_id == current_user.id,
        TimeClockEntry.work_date == today,
        TimeClockEntry.clock_out.is_(None),
    ).first()

    # Today's completed entry
    completed = db.query(TimeClockEntry).filter(
        TimeClockEntry.user_id == current_user.id,
        TimeClockEntry.work_date == today,
        TimeClockEntry.clock_out.isnot(None),
    ).first()

    if active:
        elapsed = (now - active.clock_in).total_seconds() / 3600.0
        return {
            "status": "clocked_in",
            "entry_id": active.id,
            "clock_in": active.clock_in.isoformat(),
            "is_late": active.is_late,
            "minutes_late": active.minutes_late,
            "hours_elapsed": round(elapsed, 2),
            "is_at_office": active.is_at_office,
            "latitude": float(active.latitude) if active.latitude else None,
            "longitude": float(active.longitude) if active.longitude else None,
        }
    elif completed:
        hours = (completed.clock_out - completed.clock_in).total_seconds() / 3600.0
        return {
            "status": "clocked_out",
            "entry_id": completed.id,
            "clock_in": completed.clock_in.isoformat(),
            "clock_out": completed.clock_out.isoformat(),
            "hours_worked": round(hours, 2),
            "is_late": completed.is_late,
            "minutes_late": completed.minutes_late,
        }
    else:
        return {
            "status": "not_clocked_in",
        }


# ── My History ───────────────────────────────────────────────────────

@router.get("/my-history")
def get_my_history(
    month: Optional[str] = None,  # "2026-01" format
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get clock history for the logged-in user, optionally filtered by month."""
    query = db.query(TimeClockEntry).filter(
        TimeClockEntry.user_id == current_user.id,
    )

    if month:
        year, m = map(int, month.split("-"))
        start = date(year, m, 1)
        if m == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, m + 1, 1)
        query = query.filter(
            TimeClockEntry.work_date >= start,
            TimeClockEntry.work_date < end,
        )

    entries = query.order_by(TimeClockEntry.work_date.desc()).limit(60).all()

    # Monthly summary
    if month:
        year, m = map(int, month.split("-"))
    else:
        year, m = datetime.utcnow().year, datetime.utcnow().month

    summary = _get_attendance_summary(db, current_user.id, year, m)

    return {
        "entries": [_entry_to_dict(e) for e in entries],
        "summary": summary,
    }


# ── Admin: All Employees ─────────────────────────────────────────────

@router.get("/admin/summary")
def admin_attendance_summary(
    month: Optional[str] = None,  # "2026-01"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get attendance summary for all employees (admin only)."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    if month:
        year, m = map(int, month.split("-"))
    else:
        year, m = datetime.utcnow().year, datetime.utcnow().month

    # Get all active users
    users = db.query(User).filter(User.is_active == True).all()

    results = []
    for u in users:
        if u.role.lower() == "admin":
            continue  # Skip admin from attendance tracking
        summary = _get_attendance_summary(db, u.id, year, m)
        summary["user_id"] = u.id
        summary["name"] = u.full_name or u.username
        summary["role"] = u.role
        results.append(summary)

    results.sort(key=lambda x: x["late_days_unexcused"], reverse=True)

    return {
        "period": f"{year:04d}-{m:02d}",
        "employees": results,
    }


# ── Admin: Excuse a Late Entry ───────────────────────────────────────

@router.post("/admin/excuse/{entry_id}")
def excuse_late(
    entry_id: int,
    note: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a late entry as excused (admin only)."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    entry = db.query(TimeClockEntry).filter(TimeClockEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    entry.excused = True
    entry.excused_by = current_user.id
    entry.excused_note = note
    db.commit()

    return {"id": entry.id, "excused": True, "message": "Entry marked as excused"}


# ── Admin: Unexcuse a Late Entry ─────────────────────────────────────

@router.post("/admin/unexcuse/{entry_id}")
def unexcuse_late(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove excused status from a late entry (admin only)."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    entry = db.query(TimeClockEntry).filter(TimeClockEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    entry.excused = False
    entry.excused_by = None
    entry.excused_note = None
    db.commit()

    return {"id": entry.id, "excused": False, "message": "Excused status removed"}


# ── Admin: Get Employee Detail ───────────────────────────────────────

@router.get("/admin/employee/{user_id}")
def admin_employee_detail(
    user_id: int,
    month: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed clock entries for a specific employee (admin only)."""
    if current_user.role.lower() not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")

    if month:
        year, m = map(int, month.split("-"))
    else:
        year, m = datetime.utcnow().year, datetime.utcnow().month

    start = date(year, m, 1)
    if m == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, m + 1, 1)

    entries = db.query(TimeClockEntry).filter(
        TimeClockEntry.user_id == user_id,
        TimeClockEntry.work_date >= start,
        TimeClockEntry.work_date < end,
    ).order_by(TimeClockEntry.work_date.desc()).all()

    user = db.query(User).filter(User.id == user_id).first()
    summary = _get_attendance_summary(db, user_id, year, m)

    return {
        "user_id": user_id,
        "name": user.full_name or user.username if user else "Unknown",
        "period": f"{year:04d}-{m:02d}",
        "summary": summary,
        "entries": [_entry_to_dict(e) for e in entries],
    }


# ── Commission Adjustment Helper (used by reconciliation service) ────

def get_attendance_commission_adjustment(db: Session, user_id: int, year: int, month: int) -> dict:
    """Calculate the commission rate adjustment based on attendance.

    Returns:
        {
            "adjustment": Decimal,  # +0.005, 0, or -0.005
            "late_days": int,
            "late_days_unexcused": int,
            "total_days": int,
            "label": str,  # "bonus", "neutral", "penalty"
        }
    """
    from decimal import Decimal

    summary = _get_attendance_summary(db, user_id, year, month)
    unexcused = summary["late_days_unexcused"]

    if unexcused <= 1:
        adjustment = Decimal("0.005")  # +0.5%
        label = "bonus"
    elif unexcused <= 3:
        adjustment = Decimal("0")
        label = "neutral"
    else:
        adjustment = Decimal("-0.005")  # -0.5%
        label = "penalty"

    return {
        "adjustment": adjustment,
        "late_days": summary["late_days"],
        "late_days_unexcused": unexcused,
        "excused_days": summary["excused_days"],
        "total_days": summary["total_days"],
        "label": label,
    }


# ── Internal Helpers ─────────────────────────────────────────────────

def _get_attendance_summary(db: Session, user_id: int, year: int, month: int) -> dict:
    """Compute attendance summary for a user in a given month."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    entries = db.query(TimeClockEntry).filter(
        TimeClockEntry.user_id == user_id,
        TimeClockEntry.work_date >= start,
        TimeClockEntry.work_date < end,
    ).all()

    total_days = len(entries)
    late_days = sum(1 for e in entries if e.is_late)
    excused_days = sum(1 for e in entries if e.is_late and e.excused)
    late_unexcused = late_days - excused_days
    on_time_days = total_days - late_days

    total_hours = 0.0
    for e in entries:
        if e.clock_in and e.clock_out:
            total_hours += (e.clock_out - e.clock_in).total_seconds() / 3600.0

    # Determine commission adjustment
    if late_unexcused <= 1:
        commission_impact = "+0.5%"
        impact_label = "bonus"
    elif late_unexcused <= 3:
        commission_impact = "no change"
        impact_label = "neutral"
    else:
        commission_impact = "−0.5%"
        impact_label = "penalty"

    return {
        "total_days": total_days,
        "on_time_days": on_time_days,
        "late_days": late_days,
        "excused_days": excused_days,
        "late_days_unexcused": late_unexcused,
        "total_hours": round(total_hours, 1),
        "commission_impact": commission_impact,
        "impact_label": impact_label,
    }


def _entry_to_dict(e: TimeClockEntry) -> dict:
    hours = None
    if e.clock_in and e.clock_out:
        hours = round((e.clock_out - e.clock_in).total_seconds() / 3600.0, 2)

    return {
        "id": e.id,
        "user_id": e.user_id,
        "work_date": e.work_date.isoformat(),
        "clock_in": e.clock_in.isoformat() if e.clock_in else None,
        "clock_out": e.clock_out.isoformat() if e.clock_out else None,
        "is_late": e.is_late,
        "minutes_late": e.minutes_late,
        "hours_worked": hours,
        "note": e.note,
        "excused": e.excused,
        "excused_note": e.excused_note,
        "latitude": float(e.latitude) if e.latitude else None,
        "longitude": float(e.longitude) if e.longitude else None,
        "gps_accuracy": float(e.gps_accuracy) if e.gps_accuracy else None,
        "is_at_office": e.is_at_office,
    }
