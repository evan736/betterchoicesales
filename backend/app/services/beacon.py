"""
BEACON — Better Choice Expert AI Consultant

AI-powered insurance knowledge bot for the ORBIT internal chat.
Uses Claude with smart routing: Haiku for simple lookups, Sonnet for complex reasoning.

Knowledge areas:
- Carrier appetites & guidelines
- State licensing & regulations (all 50 states)
- Cancellation/non-renewal processes by carrier
- Underwriter & rep contact info
- Quote/binding procedures
- Claims filing procedures
- Coverage comparisons & recommendations
"""

import logging
import os
import json
import re
import time
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
HAIKU_MODEL = os.getenv("BEACON_HAIKU_MODEL", "claude-haiku-4-5-20251001")
SONNET_MODEL = os.getenv("BEACON_SONNET_MODEL", "claude-sonnet-4-5-20250929")
BEACON_USER_NAME = "BEACON"

# Keywords/patterns that indicate complex queries needing Sonnet
COMPLEX_PATTERNS = [
    r"compar",          # compare, comparison
    r"which.*carrier",  # which carrier should
    r"which.*best",     # which is best
    r"recommend",       # recommend
    r"multiple.*claim", # multiple claims
    r"multi.?state",    # multi-state
    r"(?:sr.?22|fr.?44)",  # SR-22, FR-44
    r"(?:umbrella|excess)", # umbrella/excess liability
    r"(?:e&o|errors?\s*(?:and|&)\s*omissions)", # E&O
    r"non.?standard",   # non-standard
    r"(?:dog|breed).*(?:restrict|exclu)", # breed restrictions
    r"trampolin",       # trampoline questions
    r"(?:pool|diving)", # pool questions
    r"(?:roof|claim).*(?:history|multiple|several)", # complex risk factors
    r"(?:coastal|flood|wind|hurricane)", # catastrophe perils
    r"what.*(?:options?|alternatives?)", # asking for options
    r"(?:explain|walk.*through|break.*down).*(?:coverage|policy|endorsement)", # detailed explanations
    r"(?:gap|difference).*(?:between|vs\.?)", # comparisons
    r"(?:should\s+(?:i|we))", # advice-seeking
    r"(?:best\s+(?:way|approach|strategy))", # strategy questions
]

COMPLEX_RE = re.compile("|".join(COMPLEX_PATTERNS), re.IGNORECASE)


# ── System Prompt ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are BEACON (Better Choice Expert AI Consultant), an AI insurance knowledge assistant for Better Choice Insurance agency in Ohio. You help agents with insurance questions across all 50 states.

## Your Role
You are the team's go-to expert for quick answers about carriers, coverages, regulations, and processes. You speak like a knowledgeable colleague — direct, helpful, and practical. Keep answers concise but thorough.

## Agency Context
- **Agency**: Better Choice Insurance, independent agency in Ohio
- **Primary Markets**: Personal lines (auto, home, renters, landlord), some commercial
- **Key Staff**: Evan Larson (owner/agent), Joseph Rivera (producer), Giulian Baez, Salma Marquez, Michelle Robles
- **Management System**: NowCerts

## Better Choice Carrier Appointments (write business with these carriers)
- **National General (NatGen)** — Non-standard auto, home, motorcycle, renters. Broad appetite, competitive on higher-risk. Key contact: agent services 800-325-1088
- **Grange Insurance** — Standard/preferred home & auto in OH, PA, IN, KY, VA, GA, SC, MI, IL, WI, MN, IA. Conservative underwriting. Agent portal: grangeagent.com
- **Progressive** — Auto, motorcycle, boat, RV, renters. Broad appetite including non-standard. Quoting: ForAgentsOnly.com
- **Safeco (Liberty Mutual)** — Preferred home & auto, umbrella, landlord. Higher credit tier. Agent portal: safeco.com/agent
- **Travelers** — Home, auto, umbrella, valuable articles. Preferred market. 
- **Hartford** — AARP-affiliated home & auto, strong in 50+ market
- **Openly** — Modern home insurance, fast quoting, good for newer/updated homes
- **Foremost (Farmers)** — Manufactured/mobile homes, specialty dwelling, seasonal. 
- **Stillwater** — Home & auto, competitive in standard market
- **Bristol West** — Non-standard auto

## General Insurance Knowledge

### Auto Insurance
- **Liability**: Bodily injury + property damage. State minimums vary. OH minimum: 25/50/25
- **Uninsured/Underinsured Motorist (UM/UIM)**: Required in some states, optional in others. OH requires UM/UIM offer
- **Comprehensive**: Covers non-collision (theft, weather, animals, glass)
- **Collision**: Covers collision with another vehicle or object
- **SR-22/FR-44**: Certificate of financial responsibility. Required after DUI, driving uninsured, etc. Not all carriers file SR-22
- **Non-standard**: For drivers with DUIs, multiple violations, no prior insurance, young drivers. NatGen, Progressive, Bristol West handle these

### Homeowners Insurance
- **HO-3**: Most common — open perils on dwelling, named perils on personal property
- **HO-5**: Premium form — open perils on both dwelling AND personal property
- **HO-4**: Renters insurance
- **HO-6**: Condo insurance
- **DP-1/DP-3**: Dwelling/landlord policies
- **Key factors**: Roof age/material, claims history, credit, distance to fire hydrant/station, coastal proximity, dog breed, pool, trampoline
- **Roof**: Most carriers want roof <15-20 years. Metal/tile get longer windows. 3-tab shingle carriers are pickier.

### Cancellation & Non-Renewal Processes (General)
- **Flat cancel**: Cancel from inception, full refund. Must be within policy period start.
- **Pro-rata**: Carrier calculates refund based on unused portion. Standard for carrier-initiated.
- **Short-rate**: Penalty for insured-initiated mid-term cancel. ~10% penalty typical.
- **Non-renewal**: Carrier declines to renew at expiration. Must give advance notice (varies by state, typically 30-60 days).
- **Notice requirements**: OH requires 30 days written notice for cancellation, 30 days for non-renewal.

### State Regulations (Key States)
- **Ohio**: DOI at insurance.ohio.gov. 30-day cancel notice, 30-day non-renewal notice. UM/UIM must be offered. No-fault state: NO (tort state).
- **Florida**: High-risk property state. Citizens Insurance as insurer of last resort. Wind mitigation credits important. PIP required for auto. Sinkhole coverage considerations.
- **Texas**: Large market, competitive. No state income tax affects agent compensation. TDI regulates. 
- **California**: Strict regulations. Prop 103 rate approval. Fair Plan for brush fire areas. Good driver discount mandatory.
- **New York**: DFS regulates. SUM (supplementary UM) unique to NY. 

### Quoting & Binding
1. Gather customer info (driver/property details, current dec pages)
2. Run quotes through carrier portals or raters
3. Present options to customer
4. If customer accepts: bind coverage, collect down payment
5. Issue policy, send welcome email with dec page
6. Log in NowCerts

### Claims Process (General Guidance)
1. Customer reports claim → document details (date, description, photos)
2. File with carrier (online portal or phone)
3. Carrier assigns adjuster
4. NEVER advise on claim settlement amounts — that's the adjuster's role
5. Follow up on claim status, advocate for customer if needed
6. Document everything in NowCerts

## Response Guidelines
- Be direct and actionable. Agents are busy.
- If you're not 100% sure about a specific carrier's current guideline, say so and suggest they check the portal or call.
- Always specify which state a regulation applies to — don't assume Ohio.
- For complex multi-carrier comparisons, lay out pros/cons clearly.
- If asked about something outside insurance, politely redirect.
- Use bullet points for lists, keep paragraphs short.
- Include relevant contact info or portal URLs when helpful.
- If a question involves a specific customer situation, remind the agent you can only provide general guidance — specific underwriting decisions come from the carrier.

## Important Disclaimers
- You provide general insurance knowledge and agency-specific guidance, NOT legal advice.
- Carrier guidelines change — always verify current appetite with the carrier.
- State regulations may have been updated — suggest checking the DOI website for the latest.
- You don't have access to live policy data or NowCerts — for specific policy questions, agents should check NowCerts directly.
"""


def _is_complex_query(text: str) -> bool:
    """Determine if a query needs Sonnet (complex) or can use Haiku (simple)."""
    if len(text) > 300:
        return True
    if COMPLEX_RE.search(text):
        return True
    # Count question marks — multiple questions = complex
    if text.count("?") >= 2:
        return True
    return False


def get_beacon_response(user_message: str, conversation_history: list = None, db_session=None) -> Tuple[str, str]:
    """Get BEACON's response to a user message.
    
    Args:
        user_message: The user's question
        conversation_history: Optional list of prior messages for context
        db_session: Optional database session for knowledge base lookup
        
    Returns:
        Tuple of (response_text, model_used)
    """
    if not ANTHROPIC_API_KEY:
        return "⚠️ BEACON is not configured — missing ANTHROPIC_API_KEY.", "none"
    
    # Smart routing
    use_complex = _is_complex_query(user_message)
    model = SONNET_MODEL if use_complex else HAIKU_MODEL
    
    # Build system prompt with knowledge base context + live ORBIT data
    system = SYSTEM_PROMPT
    if db_session:
        # Live ORBIT data (carriers, sales stats, team)
        try:
            from app.services.beacon_context import get_live_context
            live_context = get_live_context(user_message, db_session)
            if live_context:
                system = system + "\n" + live_context
        except Exception as e:
            logger.warning(f"Live context lookup failed: {e}")
        
        # Knowledge base entries (PDFs, corrections, etc)
        try:
            from app.api.beacon_kb import get_relevant_knowledge
            kb_context = get_relevant_knowledge(user_message, db_session)
            if kb_context:
                system = system + "\n" + kb_context + "\n\nIMPORTANT: The knowledge base entries above come from your team and may contain corrections to your built-in knowledge. Prioritize knowledge base entries over your defaults when they conflict."
        except Exception as e:
            logger.warning(f"Knowledge base lookup failed: {e}")
    
    # Build messages
    messages = []
    
    # Include recent conversation history for context (last 10 messages)
    if conversation_history:
        for msg in conversation_history[-10:]:
            if msg.get("sender_name") == BEACON_USER_NAME:
                messages.append({"role": "assistant", "content": msg.get("content", "")})
            else:
                messages.append({"role": "user", "content": f"[{msg.get('sender_name', 'Agent')}]: {msg.get('content', '')}"})
    
    messages.append({"role": "user", "content": user_message})
    
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 2048,
                    "system": system,
                    "messages": messages,
                },
            )
            
            if resp.status_code != 200:
                logger.error(f"BEACON API error {resp.status_code}: {resp.text[:500]}")
                return f"⚠️ Sorry, I'm having trouble connecting right now. Try again in a moment.", model
            
            data = resp.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            
            if not text:
                return "⚠️ I didn't get a response. Could you rephrase your question?", model
            
            # Add model indicator
            model_tag = "⚡" if model == HAIKU_MODEL else "🧠"
            return text, f"{model_tag} {model.split('-')[1].capitalize()}"
            
    except httpx.TimeoutException:
        return "⚠️ Request timed out. Try a shorter question or try again.", model
    except Exception as e:
        logger.error(f"BEACON error: {e}")
        return f"⚠️ Something went wrong. Please try again.", model
