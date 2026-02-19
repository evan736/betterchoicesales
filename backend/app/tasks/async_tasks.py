from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.statement_import import StatementImportService
from app.services.commission import CommissionCalculationService


@celery_app.task(name="process_statement_import")
def process_statement_import(import_id: int):
    """
    Async task to process statement import
    """
    db = SessionLocal()
    try:
        service = StatementImportService(db)
        result = service.process_import(import_id)
        return {
            "import_id": result.id,
            "status": result.status.value,
            "matched_rows": result.matched_rows,
            "unmatched_rows": result.unmatched_rows
        }
    finally:
        db.close()


@celery_app.task(name="calculate_monthly_commissions")
def calculate_monthly_commissions(producer_id: int, period: str):
    """
    Async task to calculate commissions for a producer for a given period
    """
    db = SessionLocal()
    try:
        service = CommissionCalculationService(db)
        result = service.calculate_producer_period_commissions(producer_id, period)
        return result
    finally:
        db.close()


@celery_app.task(name="detect_signatures_in_pdf")
def detect_signatures_in_pdf(sale_id: int, pdf_path: str):
    """
    Async task to detect signature fields in uploaded PDF
    This is a placeholder - would integrate with AI service
    """
    # TODO: Integrate with signature detection AI
    # For now, just return mock data
    return {
        "sale_id": sale_id,
        "pdf_path": pdf_path,
        "signatures_detected": [
            {"page": 1, "x": 100, "y": 500},
            {"page": 3, "x": 150, "y": 600}
        ]
    }


@celery_app.task(name="send_to_wesignature")
def send_to_wesignature(sale_id: int, signature_locations: list):
    """
    Async task to send document to WeSignature for e-signature
    This is a placeholder - would integrate with WeSignature API
    """
    # TODO: Integrate with WeSignature API
    # For now, just return mock data
    return {
        "sale_id": sale_id,
        "request_id": f"WS-{sale_id}-MOCK",
        "status": "sent",
        "signature_url": f"https://wesignature.com/sign/WS-{sale_id}-MOCK"
    }
