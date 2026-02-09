from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from decimal import Decimal
from app.models.commission import CommissionStatus


class CommissionBase(BaseModel):
    period: str  # Format: "YYYY-MM"
    written_premium: Decimal
    recognized_premium: Decimal


class CommissionCreate(CommissionBase):
    sale_id: int
    producer_id: int


class CommissionInDB(CommissionBase):
    id: int
    sale_id: int
    producer_id: int
    tier_level: int
    commission_rate: Decimal
    commission_amount: Decimal
    net_commission: Decimal
    status: CommissionStatus
    is_chargeback: bool
    adjustment_amount: Decimal
    adjustment_reason: Optional[str]
    carry_forward_amount: Decimal
    paid_date: Optional[datetime]
    payment_reference: Optional[str]
    created_at: datetime
    calculated_at: Optional[datetime]

    class Config:
        from_attributes = True


class Commission(CommissionInDB):
    pass


class CommissionTierBase(BaseModel):
    tier_level: int
    min_written_premium: Decimal = Field(..., ge=0)
    max_written_premium: Optional[Decimal] = Field(None, ge=0)
    commission_rate: Decimal = Field(..., ge=0, le=1)
    description: Optional[str] = None


class CommissionTierCreate(CommissionTierBase):
    pass


class CommissionTierInDB(CommissionTierBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class CommissionTier(CommissionTierInDB):
    pass
