"""Property Lookup API — direct endpoint for property data queries."""
import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.property_lookup import lookup_property

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/property", tags=["property"])


@router.get("/lookup")
def property_lookup(
    address: str = Query(..., description="Property address to look up"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Look up property data for an address. Uses all available free sources."""
    result = lookup_property(address, db)
    return result
