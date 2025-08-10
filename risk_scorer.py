# risk_scorer.py
import os
import re
from typing import Dict, Any, List, Tuple
from pydantic import BaseModel
from openai import OpenAI

OPENAI_API_KEY = "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"
client = OpenAI(api_key=OPENAI_API_KEY)

class RiskOutput(BaseModel):
    scam: bool
    risk_score: int  # 0-100
    detected_strategies: list[str]
    rationale: str
    recommended_action: str

# Enhanced scam detection patterns for faster initial screening
SCAM_PATTERNS = {
    'high_risk': [
        # Urgency and fear tactics
        r'\b(urgent|immediate|right now|asap|emergency|critical|serious|danger|threat|warrant|arrest|legal action)\b',
        # Financial pressure
        r'\b(gift card|bitcoin|crypto|wire transfer|western union|moneygram|venmo|paypal|zelle)\b',
        # Account compromise
        r'\b(account suspended|locked|compromised|hacked|breach|security|verification|confirm|verify)\b',
        # Personal data requests
        r'\b(ssn|social security|date of birth|dob|address|phone|email|password|pin|otp|code)\b',
        # Authority impersonation
        r'\b(irs|tax|police|fbi|federal|government|bank|paypal|amazon|microsoft|apple|google)\b',
        # Investment scams
        r'\b(guaranteed|risk-free|double your money|quick profit|investment opportunity|trading|forex)\b',
        # Tech support
        r'\b(remote access|teamviewer|anydesk|computer virus|malware|system scan|tech support)\b'
    ],
    'medium_risk': [
        # Suspicious requests
        r'\b(refund|overpayment|prize|lottery|inheritance|unclaimed|free trial|subscription)\b',
        # Pressure tactics
        r'\b(keep secret|don\'t tell|confidential|private|isolated|alone|trust me|believe me)\b',
        # Unusual payment methods
        r'\b(prepaid card|reloadable|anonymous|untraceable|cash|check|money order)\b'
    ]
}

# Language-specific scam patterns for better accuracy
LANGUAGE_PATTERNS = {
    'en': {
        'high_risk': [
            r'\b(irs|social security|ssn|fbi|police|warrant|arrest|legal action)\b',
            r'\b(gift card|bitcoin|crypto|western union|moneygram)\b',
            r'\b(account suspended|compromised|hacked|breach)\b'
        ]
    },
    'es': {
        'high_risk': [
            r'\b(irs|seguridad social|policía|orden de arresto|acción legal)\b',
            r'\b(tarjeta de regalo|bitcoin|western union|moneygram)\b',
            r'\b(cuenta suspendida|comprometida|hackeada|violación)\b'
        ]
    },
    'fr': {
        'high_risk': [
            r'\b(irs|sécurité sociale|police|mandat d\'arrêt|action légale)\b',
            r'\b(carte-cadeau|bitcoin|western union|moneygram)\b',
            r'\b(compte suspendu|compromis|piraté|violation)\b'
        ]
    }
}

SYSTEM_PROMPT = """You are Scam Shield, a multilingual, real-time scam detector for phone conversations.
Judge the *content and intent*, not just keywords. Be concise but precise.

Score 0-100:
- 0-29: Safe
- 30-59: Suspicious  
- 60-100: Likely scam

Use these signals:
1) Urgency/Fear tactics
2) Fake authority (bank/police/tax/etc.)
3) Requests for OTP, PIN, seed phrase, passwords
4) Payment via gift cards/crypto/wires
5) Account compromise / device takeover
6) Refund/overpayment scam
7) Pressure to keep secret / isolation
8) Personal data harvesting (SSN, DOB, address, codes)
9) Investment guarantees or unrealistic returns
10) Prize/lottery fees
11) Tech support remote access
12) Deepfake/voice clone cues

Also consider:
- Brand/number mismatch (claimed org vs caller ID)
- Fluency/tone (hesitation, unusual phrasing) as weak signals
- Language-specific scam patterns

Return JSON only.
"""

def fast_pattern_check(text: str, language: str = 'en') -> Tuple[int, List[str]]:
    """
    Fast initial screening using regex patterns to identify high-risk content.
    Returns (risk_score, detected_strategies) for immediate response.
    """
    text_lower = text.lower()
    risk_score = 0
    detected_strategies = []
    
    # Check high-risk patterns first
    for pattern in SCAM_PATTERNS['high_risk']:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        if matches:
            risk_score += 25  # High weight for high-risk patterns
            if 'gift card' in pattern or 'bitcoin' in pattern or 'crypto' in pattern:
                detected_strategies.append('Payment via gift cards/crypto')
            elif 'ssn' in pattern or 'social security' in pattern:
                detected_strategies.append('Personal data harvesting')
            elif 'irs' in pattern or 'police' in pattern or 'fbi' in pattern:
                detected_strategies.append('Fake authority impersonation')
            elif 'account' in pattern and ('suspended' in pattern or 'compromised' in pattern):
                detected_strategies.append('Account compromise tactics')
            elif 'remote access' in pattern or 'teamviewer' in pattern:
                detected_strategies.append('Tech support remote access')
    
    # Check medium-risk patterns
    for pattern in SCAM_PATTERNS['medium_risk']:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        if matches:
            risk_score += 15  # Medium weight for medium-risk patterns
            if 'refund' in pattern or 'overpayment' in pattern:
                detected_strategies.append('Refund/overpayment scam')
            elif 'prize' in pattern or 'lottery' in pattern:
                detected_strategies.append('Prize/lottery scam')
            elif 'keep secret' in pattern or 'confidential' in pattern:
                detected_strategies.append('Pressure to keep secret')
    
    # Check language-specific patterns
    if language in LANGUAGE_PATTERNS:
        for pattern in LANGUAGE_PATTERNS[language]['high_risk']:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            if matches:
                risk_score += 20  # Additional weight for language-specific patterns
                detected_strategies.append(f'Language-specific scam pattern ({language})')
    
    # Cap the risk score at 80 for pattern matching (leave room for AI analysis)
    risk_score = min(risk_score, 80)
    
    return risk_score, detected_strategies

def detect_claimed_brand(text: str) -> str:
    """Extract claimed brand/organization from text for verification"""
    text_lower = text.lower()
    
    # Common brands that scammers impersonate
    brands = [
        'irs', 'social security', 'fbi', 'police', 'amazon', 'paypal', 'microsoft', 
        'apple', 'google', 'netflix', 'spotify', 'bank of america', 'chase', 'wells fargo',
        'coinbase', 'binance', 'robinhood', 'irs', 'hacienda', 'policía', 'banco'
    ]
    
    for brand in brands:
        if brand in text_lower:
            return brand
    
    return 'unknown'

def score_text(transcript_text: str, meta: Dict[str, Any]) -> RiskOutput:
    """
    Enhanced transcript analysis with fast pattern matching and AI-powered analysis.
    transcript_text: one chunk or joined recent chunks
    meta: { 'from': '+1...', 'to': '+1...', 'claimed_brand': 'Coinbase' (optional) }
    """
    # Fast initial screening for immediate response
    initial_risk, initial_strategies = fast_pattern_check(transcript_text)
    
    # Extract claimed brand if not provided
    claimed_brand = meta.get('claimed_brand') or detect_claimed_brand(transcript_text)
    
    # If high risk detected, return immediate result
    if initial_risk >= 60:
        return RiskOutput(
            scam=True,
            risk_score=initial_risk,
            detected_strategies=initial_strategies,
            rationale=f"High-risk patterns detected: {', '.join(initial_strategies)}",
            recommended_action="Hang up immediately and do not provide any information"
        )
    
    # For lower risk or unclear cases, use AI analysis
    user = {
        "role": "user",
        "content": f"""Caller number: {meta.get('from')}
Callee (your number): {meta.get('to')}
Claimed brand: {claimed_brand}

Initial risk assessment: {initial_risk}/100
Detected strategies: {', '.join(initial_strategies) if initial_strategies else 'None'}

Transcript chunk:
\"\"\"{transcript_text.strip()}\"\"\"

Analyze this transcript considering the initial risk assessment.
Return a JSON with fields: scam (bool), risk_score (0-100), detected_strategies (array), rationale, recommended_action.
"""
    }
    
    try:
        # Use a reliable reasoning model; fallback to gpt-4o-mini if needed
        resp = client.chat.completions.create(
            model="gpt-4o-mini",  # change to a stronger model if you have access
            messages=[{"role":"system","content":SYSTEM_PROMPT}, user],
            response_format={ "type": "json_object" },
            temperature=0.1,  # Lower temperature for more consistent results
            max_tokens=300    # Limit response length for faster processing
        )
        
        import json as _json
        data = _json.loads(resp.choices[0].message.content)
        
        # Combine AI analysis with pattern detection
        final_risk = max(data.get("risk_score", 0), initial_risk)
        final_strategies = list(set(data.get("detected_strategies", []) + initial_strategies))
        
        # Light validation and enhancement
        data.setdefault("scam", final_risk >= 60)
        data["risk_score"] = final_risk
        data["detected_strategies"] = final_strategies
        data.setdefault("rationale", "")
        data.setdefault("recommended_action", "")
        
        return RiskOutput(**data)
        
    except Exception as e:
        print(f"AI analysis error: {e}")
        # Fallback to pattern-based analysis
        return RiskOutput(
            scam=initial_risk >= 60,
            risk_score=initial_risk,
            detected_strategies=initial_strategies,
            rationale=f"Pattern-based detection: {', '.join(initial_strategies) if initial_strategies else 'No clear patterns'}. AI analysis unavailable.",
            recommended_action="Exercise caution and do not provide personal information"
        )

def get_detection_stats() -> Dict[str, Any]:
    """Get statistics about the detection system"""
    return {
        "patterns": {
            "high_risk_count": len(SCAM_PATTERNS['high_risk']),
            "medium_risk_count": len(SCAM_PATTERNS['medium_risk']),
            "languages_supported": list(LANGUAGE_PATTERNS.keys())
        },
        "performance": {
            "fast_pattern_check": "Available for immediate response",
            "ai_analysis": "Available for detailed analysis",
            "fallback_mode": "Pattern-based detection when AI unavailable"
        }
    }
