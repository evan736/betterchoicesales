import pandas as pd
import PyPDF2
from typing import List, Dict, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from datetime import datetime
from decimal import Decimal
from app.models.statement import StatementImport, StatementLine, StatementFormat, StatementStatus, CarrierType
from app.models.sale import Sale


class StatementImportService:
    """
    Service for importing and processing carrier commission statements
    Supports CSV, XLSX, and PDF formats
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_import_record(
        self,
        filename: str,
        file_path: str,
        carrier: CarrierType,
        file_format: StatementFormat,
        file_size: int
    ) -> StatementImport:
        """Create initial import record"""
        import_record = StatementImport(
            filename=filename,
            file_path=file_path,
            carrier=carrier,
            file_format=file_format,
            file_size=file_size,
            status=StatementStatus.UPLOADED
        )
        self.db.add(import_record)
        self.db.commit()
        self.db.refresh(import_record)
        return import_record
    
    def parse_csv_statement(self, file_path: str, carrier: CarrierType) -> List[Dict]:
        """Parse CSV commission statement"""
        df = pd.read_csv(file_path)
        
        # Carrier-specific column mapping
        if carrier == CarrierType.NATIONAL_GENERAL:
            column_map = {
                'Policy Number': 'policy_number',
                'Premium': 'premium_amount',
                'Commission': 'commission_amount',
                'Transaction Type': 'transaction_type',
                'Transaction Date': 'transaction_date'
            }
        elif carrier == CarrierType.PROGRESSIVE:
            column_map = {
                'PolicyNum': 'policy_number',
                'WrittenPremium': 'premium_amount',
                'CommissionAmt': 'commission_amount',
                'TransType': 'transaction_type',
                'EffectiveDate': 'transaction_date'
            }
        else:
            # Generic mapping - attempt to auto-detect
            column_map = {}
            for col in df.columns:
                col_lower = col.lower()
                if 'policy' in col_lower and 'number' in col_lower:
                    column_map[col] = 'policy_number'
                elif 'premium' in col_lower:
                    column_map[col] = 'premium_amount'
                elif 'commission' in col_lower:
                    column_map[col] = 'commission_amount'
                elif 'trans' in col_lower and 'type' in col_lower:
                    column_map[col] = 'transaction_type'
                elif 'date' in col_lower:
                    column_map[col] = 'transaction_date'
        
        # Rename columns
        df = df.rename(columns=column_map)
        
        # Convert to list of dicts
        records = df.to_dict('records')
        return records
    
    def parse_xlsx_statement(self, file_path: str, carrier: CarrierType) -> List[Dict]:
        """Parse Excel commission statement"""
        df = pd.read_excel(file_path)
        # Use same logic as CSV
        return self.parse_csv_statement(file_path.replace('.xlsx', '_temp.csv'), carrier)
    
    def parse_pdf_statement(self, file_path: str) -> List[Dict]:
        """
        Parse PDF commission statement
        This is a basic implementation - production would use more sophisticated PDF parsing
        """
        records = []
        
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text()
            
            # Very basic parsing - would need to be customized per carrier format
            lines = text.split('\n')
            for line in lines:
                # Skip empty lines
                if not line.strip():
                    continue
                
                # Attempt to extract policy number (basic pattern matching)
                # This would need to be carrier-specific in production
                parts = line.split()
                if len(parts) >= 3:
                    records.append({
                        'policy_number': parts[0],
                        'premium_amount': parts[1] if len(parts) > 1 else None,
                        'commission_amount': parts[2] if len(parts) > 2 else None,
                        'raw_line': line
                    })
        
        return records
    
    def process_import(self, import_id: int) -> StatementImport:
        """Process imported statement file"""
        import_record = self.db.query(StatementImport).filter(
            StatementImport.id == import_id
        ).first()
        
        if not import_record:
            raise ValueError("Import record not found")
        
        # Update status
        import_record.status = StatementStatus.PROCESSING
        import_record.processing_started_at = datetime.utcnow()
        self.db.commit()
        
        try:
            # Parse based on format
            if import_record.file_format == StatementFormat.CSV:
                records = self.parse_csv_statement(
                    import_record.file_path,
                    import_record.carrier
                )
            elif import_record.file_format == StatementFormat.XLSX:
                records = self.parse_xlsx_statement(
                    import_record.file_path,
                    import_record.carrier
                )
            elif import_record.file_format == StatementFormat.PDF:
                records = self.parse_pdf_statement(import_record.file_path)
            else:
                raise ValueError(f"Unsupported format: {import_record.file_format}")
            
            # Create statement lines
            import_record.total_rows = len(records)
            matched_count = 0
            unmatched_count = 0
            error_count = 0
            
            for record in records:
                try:
                    # Extract policy number
                    policy_number = record.get('policy_number', '').strip()
                    
                    if not policy_number:
                        error_count += 1
                        continue
                    
                    # Try to match with existing sale
                    sale = self.db.query(Sale).filter(
                        Sale.policy_number == policy_number
                    ).first()
                    
                    # Create statement line
                    line = StatementLine(
                        statement_import_id=import_record.id,
                        policy_number=policy_number,
                        premium_amount=self._parse_decimal(record.get('premium_amount')),
                        commission_amount=self._parse_decimal(record.get('commission_amount')),
                        transaction_type=record.get('transaction_type'),
                        transaction_date=self._parse_date(record.get('transaction_date')),
                        is_matched=sale is not None,
                        matched_sale_id=sale.id if sale else None,
                        raw_data=str(record)
                    )
                    
                    if sale:
                        matched_count += 1
                        line.matched_at = datetime.utcnow()
                        
                        # Update sale with recognized premium
                        if line.premium_amount:
                            sale.recognized_premium = line.premium_amount
                    else:
                        unmatched_count += 1
                    
                    self.db.add(line)
                
                except Exception as e:
                    error_count += 1
                    print(f"Error processing line: {e}")
            
            # Update import record
            import_record.matched_rows = matched_count
            import_record.unmatched_rows = unmatched_count
            import_record.error_rows = error_count
            
            if matched_count == len(records):
                import_record.status = StatementStatus.MATCHED
            elif matched_count > 0:
                import_record.status = StatementStatus.PARTIALLY_MATCHED
            else:
                import_record.status = StatementStatus.FAILED
                import_record.error_message = "No matches found"
            
            import_record.processing_completed_at = datetime.utcnow()
            self.db.commit()
            
        except Exception as e:
            import_record.status = StatementStatus.FAILED
            import_record.error_message = str(e)
            import_record.processing_completed_at = datetime.utcnow()
            self.db.commit()
            raise
        
        return import_record
    
    def _parse_decimal(self, value) -> Optional[Decimal]:
        """Safely parse decimal value"""
        if value is None:
            return None
        try:
            # Remove currency symbols and commas
            if isinstance(value, str):
                value = value.replace('$', '').replace(',', '').strip()
            return Decimal(str(value))
        except:
            return None
    
    def _parse_date(self, value) -> Optional[datetime]:
        """Safely parse date value"""
        if value is None:
            return None
        try:
            if isinstance(value, str):
                return pd.to_datetime(value)
            return value
        except:
            return None
