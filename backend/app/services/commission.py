from decimal import Decimal
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime
from app.models.commission import Commission, CommissionTier, CommissionStatus
from app.models.sale import Sale
from app.models.user import User


class CommissionCalculationService:
    """
    Commission calculation logic:
    1. Tier is determined by WRITTEN premium for the month
    2. Commission is PAID based on RECOGNIZED premium
    3. Negative carry-forward if chargebacks exceed sales
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_tier_for_written_premium(self, written_premium: Decimal) -> CommissionTier:
        """
        Determine commission tier based on total written premium for the period
        """
        tier = (
            self.db.query(CommissionTier)
            .filter(
                CommissionTier.is_active == True,
                CommissionTier.min_written_premium <= written_premium,
                (CommissionTier.max_written_premium >= written_premium) | 
                (CommissionTier.max_written_premium == None)
            )
            .order_by(CommissionTier.tier_level.desc())
            .first()
        )
        
        if not tier:
            # Default to tier 1 if no tier found
            tier = (
                self.db.query(CommissionTier)
                .filter(CommissionTier.is_active == True)
                .order_by(CommissionTier.tier_level)
                .first()
            )
        
        return tier
    
    def calculate_monthly_written_premium(self, producer_id: int, period: str) -> Decimal:
        """
        Calculate total written premium for a producer in a given period
        Period format: "YYYY-MM"
        """
        year, month = period.split("-")
        
        total = (
            self.db.query(func.sum(Sale.written_premium))
            .filter(
                Sale.producer_id == producer_id,
                func.extract('year', Sale.sale_date) == int(year),
                func.extract('month', Sale.sale_date) == int(month)
            )
            .scalar()
        )
        
        return total or Decimal("0")
    
    def calculate_commission_for_sale(
        self,
        sale: Sale,
        period: str
    ) -> Commission:
        """
        Calculate commission for a single sale
        """
        # Get total written premium for the month to determine tier
        monthly_written = self.calculate_monthly_written_premium(sale.producer_id, period)
        
        # Determine tier
        tier = self.get_tier_for_written_premium(monthly_written)
        
        if not tier:
            raise ValueError("No commission tier configured")
        
        # Calculate commission based on RECOGNIZED premium
        recognized = sale.recognized_premium or sale.written_premium
        commission_amount = recognized * tier.commission_rate
        
        # Check for existing commission
        existing = (
            self.db.query(Commission)
            .filter(
                Commission.sale_id == sale.id,
                Commission.period == period
            )
            .first()
        )
        
        if existing:
            # Update existing
            existing.written_premium = sale.written_premium
            existing.recognized_premium = recognized
            existing.tier_level = tier.tier_level
            existing.commission_rate = tier.commission_rate
            existing.commission_amount = commission_amount
            existing.net_commission = commission_amount
            existing.calculated_at = datetime.utcnow()
            existing.status = CommissionStatus.CALCULATED
            self.db.commit()
            return existing
        
        # Create new commission
        commission = Commission(
            sale_id=sale.id,
            producer_id=sale.producer_id,
            period=period,
            written_premium=sale.written_premium,
            recognized_premium=recognized,
            tier_level=tier.tier_level,
            commission_rate=tier.commission_rate,
            commission_amount=commission_amount,
            net_commission=commission_amount,
            status=CommissionStatus.CALCULATED,
            calculated_at=datetime.utcnow()
        )
        
        self.db.add(commission)
        self.db.commit()
        self.db.refresh(commission)
        
        return commission
    
    def calculate_producer_period_commissions(
        self,
        producer_id: int,
        period: str
    ) -> Dict:
        """
        Calculate all commissions for a producer for a given period
        Includes carry-forward logic for negative balances
        """
        # Get all sales for the period
        year, month = period.split("-")
        sales = (
            self.db.query(Sale)
            .filter(
                Sale.producer_id == producer_id,
                func.extract('year', Sale.sale_date) == int(year),
                func.extract('month', Sale.sale_date) == int(month)
            )
            .all()
        )
        
        # Calculate commission for each sale
        commissions = []
        for sale in sales:
            comm = self.calculate_commission_for_sale(sale, period)
            commissions.append(comm)
        
        # Calculate totals
        total_written = sum(c.written_premium for c in commissions)
        total_recognized = sum(c.recognized_premium for c in commissions)
        total_commission = sum(c.commission_amount for c in commissions)
        
        # Check for chargebacks (negative recognized premium)
        chargebacks = [c for c in commissions if c.recognized_premium < 0]
        chargeback_total = sum(abs(c.commission_amount) for c in chargebacks)
        
        # Calculate net after chargebacks
        net_commission = total_commission
        carry_forward = Decimal("0")
        
        if net_commission < 0:
            # Negative balance - carry forward to next period
            carry_forward = abs(net_commission)
            net_commission = Decimal("0")
        
        return {
            "period": period,
            "producer_id": producer_id,
            "total_written_premium": total_written,
            "total_recognized_premium": total_recognized,
            "total_commission": total_commission,
            "chargeback_total": chargeback_total,
            "net_commission": net_commission,
            "carry_forward": carry_forward,
            "commissions": commissions
        }
    
    def process_chargeback(
        self,
        sale_id: int,
        chargeback_amount: Decimal,
        reason: str
    ) -> Commission:
        """
        Process a chargeback for a sale
        """
        sale = self.db.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            raise ValueError("Sale not found")
        
        # Create chargeback commission record
        period = datetime.now().strftime("%Y-%m")
        
        commission = Commission(
            sale_id=sale.id,
            producer_id=sale.producer_id,
            period=period,
            written_premium=Decimal("0"),
            recognized_premium=-chargeback_amount,
            tier_level=1,
            commission_rate=Decimal("0"),
            commission_amount=-chargeback_amount,
            net_commission=-chargeback_amount,
            status=CommissionStatus.CHARGEBACK,
            is_chargeback=True,
            adjustment_reason=reason,
            calculated_at=datetime.utcnow()
        )
        
        self.db.add(commission)
        self.db.commit()
        self.db.refresh(commission)
        
        return commission
