"""BEACON Knowledge Base — learnable knowledge from PDFs, screenshots, corrections, and conversations."""
import logging
import os
import re
import base64
import hashlib
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/beacon-kb", tags=["beacon-knowledge"])

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


# ── Models ───────────────────────────────────────────────────────

class BeaconKnowledge(Base):
    __tablename__ = "beacon_knowledge"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String, nullable=False)       # pdf, screenshot, correction, conversation
    title = Column(String, nullable=False)              # Display title
    content = Column(Text, nullable=False)              # Extracted/written text content
    summary = Column(Text, nullable=True)               # AI-generated summary for quick matching
    tags = Column(String, nullable=True)                # Comma-separated: "natgen,auto,florida"
    carrier = Column(String, nullable=True)             # Carrier name if applicable
    status = Column(String, default="pending")          # pending, approved, rejected
    submitted_by = Column(Integer, nullable=True)       # User ID who submitted
    submitted_by_name = Column(String, nullable=True)   # User name
    reviewed_by = Column(Integer, nullable=True)        # Manager who approved/rejected
    reviewed_by_name = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(Text, nullable=True)           # Manager's note on approval/rejection
    original_filename = Column(String, nullable=True)   # Original upload filename
    file_hash = Column(String, nullable=True)           # SHA256 of uploaded file (dedup)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ── Helpers ──────────────────────────────────────────────────────

def _serialize(k: BeaconKnowledge) -> dict:
    return {
        "id": k.id,
        "source_type": k.source_type,
        "title": k.title,
        "content": k.content[:500] + ("..." if len(k.content) > 500 else ""),
        "full_content": k.content,
        "summary": k.summary,
        "tags": k.tags,
        "carrier": k.carrier,
        "status": k.status,
        "submitted_by": k.submitted_by,
        "submitted_by_name": k.submitted_by_name,
        "reviewed_by_name": k.reviewed_by_name,
        "reviewed_at": k.reviewed_at.isoformat() if k.reviewed_at else None,
        "review_note": k.review_note,
        "original_filename": k.original_filename,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


def _is_manager(user: User) -> bool:
    return user.role.lower() in ("admin", "manager", "owner")


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber or fallback."""
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
    except ImportError:
        logger.warning("pdfplumber not installed, trying PyPDF2")
    try:
        import PyPDF2
        import io
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def _extract_text_from_image(image_bytes: bytes, media_type: str = "image/png") -> str:
    """Use Claude vision to extract text/info from a screenshot."""
    if not ANTHROPIC_API_KEY:
        return "[Image uploaded but no API key for extraction]"
    
    try:
        import httpx
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 2048,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": "Extract ALL text and important information from this insurance-related screenshot. Include carrier names, policy details, guidelines, rates, rules, contact info, and any other relevant data. Format clearly with headers and bullet points.",
                            },
                        ],
                    }],
                },
            )
            
            if resp.status_code == 200:
                data = resp.json()
                text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text += block["text"]
                return text
            else:
                logger.error(f"Vision API error: {resp.status_code}")
                return "[Failed to extract text from image]"
    except Exception as e:
        logger.error(f"Image extraction failed: {e}")
        return f"[Image extraction error: {str(e)[:100]}]"


def _extract_text_from_excel(file_bytes: bytes, filename: str = "") -> str:
    """Extract text from Excel files (.xlsx/.xls)."""
    try:
        import openpyxl
        import io
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            headers = [str(h) if h is not None else "" for h in rows[0]]
            parts.append(f"=== Sheet: {sheet_name} ===")
            parts.append(f"Columns: {', '.join(h for h in headers if h)}")
            parts.append("")
            for row in rows[1:]:
                row_data = "; ".join(
                    f"{headers[j]}: {row[j]}"
                    for j in range(len(row))
                    if j < len(headers) and headers[j] and row[j] is not None
                )
                if row_data.strip():
                    parts.append(row_data)
            parts.append("")
        wb.close()
        return "\n".join(parts)
    except ImportError:
        logger.warning("openpyxl not installed — cannot parse Excel")
        return ""
    except Exception as e:
        logger.error(f"Excel extraction failed: {e}")
        return ""


def _extract_text_from_csv(file_bytes: bytes) -> str:
    """Extract text from CSV files."""
    try:
        import csv
        import io
        text = file_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return ""
        headers = rows[0]
        parts = [f"Columns: {', '.join(headers)}", ""]
        for row in rows[1:]:
            row_data = "; ".join(
                f"{headers[j]}: {row[j]}"
                for j in range(len(row))
                if j < len(headers) and row[j]
            )
            if row_data.strip():
                parts.append(row_data)
        return "\n".join(parts)
    except Exception as e:
        logger.error(f"CSV extraction failed: {e}")
        return ""


def _generate_summary(content: str, title: str) -> str:
    """Generate a short summary + tags using AI."""
    if not ANTHROPIC_API_KEY or len(content) < 50:
        return ""
    
    try:
        import httpx
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages": [{
                        "role": "user",
                        "content": f"Summarize this insurance knowledge entry in 1-2 sentences for quick reference. Title: {title}\n\nContent:\n{content[:3000]}",
                    }],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        return block["text"]
        return ""
    except Exception:
        return ""


def _generate_smart_title(content: str, carrier: str, filename: str) -> str:
    """Generate a meaningful title from PDF/document content."""
    first_500 = content[:500].upper()
    
    # Detect state
    STATES = [
        'ALABAMA', 'ALASKA', 'ARIZONA', 'ARKANSAS', 'CALIFORNIA', 'COLORADO',
        'CONNECTICUT', 'DELAWARE', 'FLORIDA', 'GEORGIA', 'HAWAII', 'IDAHO',
        'ILLINOIS', 'INDIANA', 'IOWA', 'KANSAS', 'KENTUCKY', 'LOUISIANA',
        'MAINE', 'MARYLAND', 'MASSACHUSETTS', 'MICHIGAN', 'MINNESOTA',
        'MISSISSIPPI', 'MISSOURI', 'MONTANA', 'NEBRASKA', 'NEVADA',
        'NEW HAMPSHIRE', 'NEW JERSEY', 'NEW MEXICO', 'NEW YORK',
        'NORTH CAROLINA', 'NORTH DAKOTA', 'OHIO', 'OKLAHOMA', 'OREGON',
        'PENNSYLVANIA', 'RHODE ISLAND', 'SOUTH CAROLINA', 'SOUTH DAKOTA',
        'TENNESSEE', 'TEXAS', 'UTAH', 'VERMONT', 'VIRGINIA', 'WASHINGTON',
        'WEST VIRGINIA', 'WISCONSIN', 'WYOMING', 'COUNTRYWIDE',
    ]
    state = ""
    for s in STATES:
        if s in first_500:
            state = s.title()
            break
    
    # Detect product type
    content_lower = content[:2000].lower()
    product = ""
    if 'personal auto' in content_lower and 'rv' in content_lower:
        product = "Auto & RV"
    elif 'personal auto' in content_lower:
        product = "Auto"
    elif 'homeowner' in content_lower and 'auto' in content_lower:
        product = "Auto & Home"
    elif 'homeowner' in content_lower or 'dwelling' in content_lower:
        product = "Home"
    elif 'rv' in content_lower or 'motorhome' in content_lower:
        product = "RV"
    elif 'motorcycle' in content_lower:
        product = "Motorcycle"
    elif 'commercial' in content_lower:
        product = "Commercial"
    
    # Detect carrier from content if not provided
    carrier_label = carrier or _detect_carrier_from_content(content)
    
    # Build carrier short name
    CARRIER_SHORT = {
        'national general': 'NatGen', 'travelers': 'Travelers', 'safeco': 'Safeco',
        'progressive': 'Progressive', 'grange': 'Grange', 'geico': 'GEICO',
        'hartford': 'Hartford', 'openly': 'Openly', 'foremost': 'Foremost',
    }
    short = carrier_label
    for full, abbr in CARRIER_SHORT.items():
        if full in carrier_label.lower():
            short = abbr
            break
    
    parts = [p for p in [short, state, product, "Guidelines"] if p]
    title = " ".join(parts) if len(parts) > 1 else filename.rsplit(".", 1)[0].replace("_", " ").title()
    return title[:120]


def _detect_carrier_from_content(content: str) -> str:
    """Try to detect carrier name from document content."""
    first_1000 = content[:1000].lower()
    CARRIERS = {
        'national general': 'National General',
        'integon': 'National General',
        'encompass': 'National General',
        'new south insurance': 'National General',
        'imperial fire': 'National General',
        'travelers': 'Travelers',
        'safeco': 'Safeco',
        'progressive': 'Progressive',
        'grange': 'Grange',
        'geico': 'GEICO',
        'hartford': 'Hartford',
        'openly': 'Openly',
        'foremost': 'Foremost',
        'bristol west': 'Bristol West',
    }
    for pattern, name in CARRIERS.items():
        if pattern in first_1000:
            return name
    return ""


# ── Knowledge Retrieval (used by BEACON) ─────────────────────────

def get_relevant_knowledge(query: str, db: Session, limit: int = 5) -> str:
    """Search approved knowledge entries relevant to a query.
    Returns formatted context string to inject into BEACON's prompt."""
    
    # Get all approved entries (exclude superseded)
    entries = db.query(BeaconKnowledge).filter(
        BeaconKnowledge.status == "approved"
    ).order_by(BeaconKnowledge.created_at.desc()).all()
    
    if not entries:
        return ""
    
    # Deduplicate: if multiple entries have the same title+carrier, keep only the newest
    seen_titles = {}
    deduped = []
    for entry in entries:
        dedup_key = f"{(entry.title or '').lower()}|{(entry.carrier or '').lower()}"
        if dedup_key not in seen_titles:
            seen_titles[dedup_key] = True
            deduped.append(entry)
    entries = deduped
    
    # Simple keyword matching (fast, no vector DB needed)
    query_lower = query.lower()
    query_words = set(re.findall(r'\w+', query_lower))
    
    scored = []
    for entry in entries:
        score = 0
        searchable = f"{entry.title} {entry.content} {entry.tags or ''} {entry.carrier or ''} {entry.summary or ''}".lower()
        
        # Exact phrase fragments
        for word in query_words:
            if len(word) >= 3:  # Skip tiny words
                count = searchable.count(word)
                score += count * 2
        
        # Carrier name match (big boost)
        if entry.carrier and entry.carrier.lower() in query_lower:
            score += 20
        
        # Tag matches
        if entry.tags:
            for tag in entry.tags.split(","):
                tag = tag.strip().lower()
                if tag and tag in query_lower:
                    score += 10
        
        # Correction entries get a boost (they're specific fixes)
        if entry.source_type == "correction":
            score += 5
        
        if score > 0:
            scored.append((score, entry))
    
    # Sort by score, take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    
    if not top:
        return ""
    
    # Format as context
    parts = ["\n## Agency Knowledge Base (approved entries from your team)\n"]
    for score, entry in top:
        source_label = {
            "pdf": "📄 PDF",
            "screenshot": "📸 Screenshot",
            "correction": "✏️ Correction",
            "conversation": "💬 Learned",
            "spreadsheet": "📊 Spreadsheet",
            "document": "📝 Document",
        }.get(entry.source_type, "📝 Note")
        
        parts.append(f"### {source_label}: {entry.title}")
        
        content = entry.content
        if len(content) <= 6000:
            # Small enough to send whole
            parts.append(content)
        else:
            # Large document — extract relevant chunks around query keywords
            chunks = _extract_relevant_chunks(content, query_words, max_total=8000)
            if chunks:
                parts.append(f"[Relevant sections from {len(content):,} character document]\n")
                parts.append(chunks)
            else:
                # Fallback: first chunk for context
                parts.append(content[:4000] + "\n[... document continues, use specific questions to find more]")
        parts.append("")
    
    return "\n".join(parts)


def _extract_relevant_chunks(content: str, query_words: set, max_total: int = 8000) -> str:
    """Extract sections of a large document that contain query keywords.
    Uses synonym expansion, phrase matching, and section awareness."""
    
    lines = content.split('\n')
    
    # Synonym expansions for insurance terms
    SYNONYMS = {
        'claim': ['claim', 'claims', 'loss', 'losses', 'chargeable', 'loss history'],
        'limit': ['limit', 'limits', 'maximum', 'max', 'exceed', 'exceeding', 'ineligible'],
        'many': ['many', 'number', 'count', 'how many', 'maximum'],
        'home': ['home', 'homeowner', 'homeowners', 'dwelling', 'residence'],
        'auto': ['auto', 'automobile', 'vehicle', 'car', 'driver'],
        'cancel': ['cancel', 'cancellation', 'non-renewal', 'nonrenewal'],
        'cover': ['cover', 'coverage', 'covered', 'covers'],
        'deduct': ['deduct', 'deductible', 'deductibles'],
        'eligible': ['eligible', 'eligibility', 'ineligible', 'qualify', 'acceptable'],
        'require': ['require', 'requirement', 'requirements', 'required'],
    }
    
    expanded = set(query_words)
    for word in query_words:
        for key, syns in SYNONYMS.items():
            if word.startswith(key) or key.startswith(word):
                expanded.update(syns)
    
    scored_lines = []
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if not line_lower.strip():
            continue
        score = 0
        matched = set()
        for word in expanded:
            if len(word) >= 3 and word in line_lower:
                score += 2
                matched.add(word)
        # Section header bonus
        stripped = line.strip()
        if stripped and (stripped.isupper() or stripped.startswith(('I.', 'II.', 'III.', 'IV.', 'A.', 'B.', 'C.', 'D.'))):
            if matched:
                score += 5
        # Multi-word proximity bonus
        if len(matched) >= 3:
            score += 10
        elif len(matched) >= 2:
            score += 5
        # Key phrase bonus
        for phrase in ['ineligible', 'loss history', 'claim count', 'exceeding', 'chargeable loss', 'experience period', 'not eligible']:
            if phrase in line_lower:
                score += 8
        if score > 0:
            scored_lines.append((i, score))
    
    if not scored_lines:
        return ""
    
    scored_lines.sort(key=lambda x: x[1], reverse=True)
    
    CONTEXT_LINES = 20
    chunks = []
    used_lines = set()
    total_chars = 0
    
    for line_idx, score in scored_lines[:15]:
        start = max(0, line_idx - CONTEXT_LINES)
        end = min(len(lines), line_idx + CONTEXT_LINES + 1)
        overlap = sum(1 for i in range(start, end) if i in used_lines)
        if overlap > (end - start) * 0.5:
            continue
        chunk_text = '\n'.join(lines[start:end])
        if total_chars + len(chunk_text) > max_total:
            break
        chunks.append(f"[...section near line {start+1}...]\n{chunk_text}")
        used_lines.update(range(start, end))
        total_chars += len(chunk_text)
    
    return "\n\n".join(chunks)



# ── API Endpoints ────────────────────────────────────────────────

@router.post("/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    title: str = Form(""),
    carrier: str = Form(""),
    tags: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a PDF or screenshot to the knowledge base."""
    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    
    # Check for exact duplicate (same file hash)
    existing = db.query(BeaconKnowledge).filter(BeaconKnowledge.file_hash == file_hash).first()
    if existing:
        return {"error": "This exact file has already been uploaded", "existing_id": existing.id}
    
    # Check for superseding — same title+carrier means this is an updated version
    # Mark older entries as superseded so only the newest is used
    if title and carrier:
        older = db.query(BeaconKnowledge).filter(
            BeaconKnowledge.title == title,
            BeaconKnowledge.carrier == carrier,
            BeaconKnowledge.status.in_(["approved", "pending"]),
        ).all()
        for old in older:
            old.status = "superseded"
            logger.info(f"Superseded older knowledge entry: {old.title} (id={old.id})")
        if older:
            db.commit()
    
    filename = file.filename or "upload"
    content_type = file.content_type or ""
    
    # Determine source type and extract text
    if "pdf" in content_type or filename.lower().endswith(".pdf"):
        source_type = "pdf"
        content = _extract_text_from_pdf(file_bytes)
        if not content:
            return {"error": "Could not extract text from PDF. The file may be scanned or empty."}
    elif any(ext in filename.lower() for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]) or "image" in content_type:
        source_type = "screenshot"
        media = content_type if content_type else "image/png"
        content = _extract_text_from_image(file_bytes, media)
        if not content or content.startswith("["):
            return {"error": "Could not extract information from image."}
    elif filename.lower().endswith((".xlsx", ".xls")) or "spreadsheet" in content_type or "excel" in content_type:
        source_type = "spreadsheet"
        content = _extract_text_from_excel(file_bytes, filename)
        if not content:
            return {"error": "Could not extract data from Excel file."}
    elif filename.lower().endswith(".csv") or "csv" in content_type:
        source_type = "spreadsheet"
        content = _extract_text_from_csv(file_bytes)
        if not content:
            return {"error": "Could not extract data from CSV file."}
    elif filename.lower().endswith((".txt", ".md", ".text")):
        source_type = "document"
        content = file_bytes.decode("utf-8", errors="replace")
        if not content.strip():
            return {"error": "Text file is empty."}
    else:
        return {"error": f"Unsupported file type: {content_type or filename}. Supported: PDF, images (PNG/JPG), Excel (XLSX/XLS), CSV, text files."}
    
    # Auto-generate title if not provided or if filename is generic
    is_generic_filename = (
        not title or 
        title.lower().startswith("download") or 
        title.lower().startswith("untitled") or
        re.match(r'^[\d\s\(\)]+$', title)
    )
    if is_generic_filename:
        title = _generate_smart_title(content, carrier, filename)
    elif not title:
        title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
    
    # Auto-detect carrier from content if not provided
    if not carrier:
        carrier = _detect_carrier_from_content(content)
    
    # Generate summary
    summary = _generate_summary(content, title)
    
    # Auto-approve if manager, otherwise pending
    status = "approved" if _is_manager(current_user) else "pending"
    
    entry = BeaconKnowledge(
        source_type=source_type,
        title=title,
        content=content,
        summary=summary,
        tags=tags,
        carrier=carrier,
        status=status,
        submitted_by=current_user.id,
        submitted_by_name=current_user.full_name or current_user.username,
        original_filename=filename,
        file_hash=file_hash,
        reviewed_by=current_user.id if status == "approved" else None,
        reviewed_by_name=(current_user.full_name or current_user.username) if status == "approved" else None,
        reviewed_at=datetime.utcnow() if status == "approved" else None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    logger.info(f"Knowledge uploaded: {title} ({source_type}) by {current_user.username} → {status}")
    return _serialize(entry)


@router.post("/correction")
def add_correction(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a correction from chat (BEACON was wrong about something)."""
    content = data.get("content", "").strip()
    title = data.get("title", "").strip()
    carrier = data.get("carrier", "")
    tags = data.get("tags", "")
    
    if not content:
        raise HTTPException(400, "Content is required")
    if not title:
        title = f"Correction: {content[:60]}..."
    
    status = "approved" if _is_manager(current_user) else "pending"
    
    entry = BeaconKnowledge(
        source_type="correction",
        title=title,
        content=content,
        summary=content[:200],
        tags=tags,
        carrier=carrier,
        status=status,
        submitted_by=current_user.id,
        submitted_by_name=current_user.full_name or current_user.username,
        reviewed_by=current_user.id if status == "approved" else None,
        reviewed_by_name=(current_user.full_name or current_user.username) if status == "approved" else None,
        reviewed_at=datetime.utcnow() if status == "approved" else None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    logger.info(f"Correction added: {title} by {current_user.username} → {status}")
    return _serialize(entry)


@router.post("/from-conversation")
def add_from_conversation(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a useful BEACON conversation exchange as knowledge."""
    content = data.get("content", "").strip()
    title = data.get("title", "").strip()
    carrier = data.get("carrier", "")
    tags = data.get("tags", "")
    
    if not content:
        raise HTTPException(400, "Content is required")
    if not title:
        title = f"Learned: {content[:60]}..."
    
    summary = _generate_summary(content, title)
    status = "approved" if _is_manager(current_user) else "pending"
    
    entry = BeaconKnowledge(
        source_type="conversation",
        title=title,
        content=content,
        summary=summary,
        tags=tags,
        carrier=carrier,
        status=status,
        submitted_by=current_user.id,
        submitted_by_name=current_user.full_name or current_user.username,
        reviewed_by=current_user.id if status == "approved" else None,
        reviewed_by_name=(current_user.full_name or current_user.username) if status == "approved" else None,
        reviewed_at=datetime.utcnow() if status == "approved" else None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    
    logger.info(f"Conversation knowledge saved: {title} by {current_user.username}")
    return _serialize(entry)


@router.get("/entries")
def list_entries(
    status: str = Query(None),
    source_type: str = Query(None),
    search: str = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List knowledge base entries with optional filters."""
    q = db.query(BeaconKnowledge)
    
    if status:
        q = q.filter(BeaconKnowledge.status == status)
    if source_type:
        q = q.filter(BeaconKnowledge.source_type == source_type)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            (BeaconKnowledge.title.ilike(pattern)) |
            (BeaconKnowledge.content.ilike(pattern)) |
            (BeaconKnowledge.tags.ilike(pattern)) |
            (BeaconKnowledge.carrier.ilike(pattern))
        )
    
    # Non-managers only see their own pending + all approved
    if not _is_manager(current_user):
        q = q.filter(
            (BeaconKnowledge.status == "approved") |
            (BeaconKnowledge.submitted_by == current_user.id)
        )
    # Managers see everything including superseded
    
    entries = q.order_by(BeaconKnowledge.created_at.desc()).limit(100).all()
    
    # Count pending for badge
    pending_count = db.query(BeaconKnowledge).filter(
        BeaconKnowledge.status == "pending"
    ).count()
    
    return {
        "entries": [_serialize(e) for e in entries],
        "pending_count": pending_count,
    }


@router.get("/entries/{entry_id}")
def get_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full details of a knowledge entry."""
    entry = db.query(BeaconKnowledge).filter(BeaconKnowledge.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    return _serialize(entry)


@router.post("/entries/{entry_id}/approve")
def approve_entry(
    entry_id: int,
    data: dict = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a pending knowledge entry (managers only)."""
    if not _is_manager(current_user):
        raise HTTPException(403, "Only managers can approve knowledge entries")
    
    entry = db.query(BeaconKnowledge).filter(BeaconKnowledge.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    
    entry.status = "approved"
    entry.reviewed_by = current_user.id
    entry.reviewed_by_name = current_user.full_name or current_user.username
    entry.reviewed_at = datetime.utcnow()
    entry.review_note = (data or {}).get("note", "")
    db.commit()
    
    logger.info(f"Knowledge approved: {entry.title} by {current_user.username}")
    return _serialize(entry)


@router.post("/entries/{entry_id}/reject")
def reject_entry(
    entry_id: int,
    data: dict = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reject a pending knowledge entry (managers only)."""
    if not _is_manager(current_user):
        raise HTTPException(403, "Only managers can reject knowledge entries")
    
    entry = db.query(BeaconKnowledge).filter(BeaconKnowledge.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    
    entry.status = "rejected"
    entry.reviewed_by = current_user.id
    entry.reviewed_by_name = current_user.full_name or current_user.username
    entry.reviewed_at = datetime.utcnow()
    entry.review_note = (data or {}).get("note", "")
    db.commit()
    
    logger.info(f"Knowledge rejected: {entry.title} by {current_user.username}")
    return _serialize(entry)


@router.put("/entries/{entry_id}")
def update_entry(
    entry_id: int,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a knowledge entry (managers, or original submitter if still pending)."""
    entry = db.query(BeaconKnowledge).filter(BeaconKnowledge.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    
    if not _is_manager(current_user) and entry.submitted_by != current_user.id:
        raise HTTPException(403, "Not authorized to edit this entry")
    
    for field in ("title", "content", "tags", "carrier"):
        if field in data:
            setattr(entry, field, data[field])
    
    db.commit()
    return _serialize(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a knowledge entry (managers only)."""
    if not _is_manager(current_user):
        raise HTTPException(403, "Only managers can delete knowledge entries")
    
    entry = db.query(BeaconKnowledge).filter(BeaconKnowledge.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    
    db.delete(entry)
    db.commit()
    return {"deleted": True}


@router.get("/stats")
def kb_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get knowledge base statistics."""
    total = db.query(BeaconKnowledge).filter(BeaconKnowledge.status != "superseded").count()
    approved = db.query(BeaconKnowledge).filter(BeaconKnowledge.status == "approved").count()
    pending = db.query(BeaconKnowledge).filter(BeaconKnowledge.status == "pending").count()
    superseded = db.query(BeaconKnowledge).filter(BeaconKnowledge.status == "superseded").count()
    
    by_type = {}
    for st in ("pdf", "screenshot", "correction", "conversation", "spreadsheet", "document"):
        by_type[st] = db.query(BeaconKnowledge).filter(
            BeaconKnowledge.source_type == st,
            BeaconKnowledge.status == "approved",
        ).count()
    
    return {
        "total": total,
        "approved": approved,
        "pending": pending,
        "superseded": superseded,
        "by_type": by_type,
    }
