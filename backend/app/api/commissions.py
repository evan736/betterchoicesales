from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.commission import Commission, CommissionTier, CommissionTierCreate
from app.services.commission import CommissionCalculationService

router = APIRouter(prefix="/api/commissions", tags=["commissions"])


@router.get("/calculate/{producer_id}/{period}")
def calculate_period_commissions(
    producer_id: int,
    period: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Calculate commissions for a producer for a given period
    Period format: YYYY-MM
    """
    # Producers can only view their own commissions
    if current_user.role == "producer" and current_user.id != producer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized"
        )
    
    service = CommissionCalculationService(db)
    result = service.calculate_producer_period_commissions(producer_id, period)
    
    return result


@router.get("/my-commissions")
def get_my_commissions(
    period: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get commissions for current user"""
    from app.models.commission import Commission
    
    query = db.query(Commission).filter(Commission.producer_id == current_user.id)
    
    if period:
        query = query.filter(Commission.period == period)
    
    commissions = query.order_by(Commission.created_at.desc()).all()
    return commissions


@router.get("/tiers", response_model=List[CommissionTier])
def list_commission_tiers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all active commission tiers"""
    from app.models.commission import CommissionTier as TierModel
    
    tiers = db.query(TierModel).filter(
        TierModel.is_active == True
    ).order_by(TierModel.tier_level).all()
    
    return tiers


@router.post("/tiers", response_model=CommissionTier)
def create_commission_tier(
    tier_data: CommissionTierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new commission tier (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    from app.models.commission import CommissionTier as TierModel
    
    # Check for duplicate tier level
    existing = db.query(TierModel).filter(
        TierModel.tier_level == tier_data.tier_level
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tier level already exists"
        )
    
    tier = TierModel(**tier_data.model_dump())
    db.add(tier)
    db.commit()
    db.refresh(tier)
    
    return tier
