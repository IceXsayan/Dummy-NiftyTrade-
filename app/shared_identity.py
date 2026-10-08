import os
import hmac
import hashlib
import re
from typing import Optional, Dict, Any
from app.core.config import settings

def normalize_email(email: Optional[str]) -> str:
    """
    Normalize email: strip leading/trailing whitespace and convert to lowercase.
    Must be used everywhere emails are stored, compared, or returned.
    """
    if not email:
        return ""
    return str(email).strip().lower()

def generate_identity(email: str, full_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate deterministic fake identity for an email using HMAC-SHA256(SHARED_IDENTITY_SALT, normalized_email).
    Produces the exact same fake identity across all 4 broker projects.
    Full name comes from Google name claim when available, otherwise email local-part.
    Never generates real-looking Aadhaar or PAN data.
    """
    norm_email = normalize_email(email)
    salt_val = getattr(settings, "SHARED_IDENTITY_SALT", None) or os.getenv("SHARED_IDENTITY_SALT", "tradeone-shared-identity-salt")
    salt = salt_val.encode("utf-8")
    
    digest = hmac.new(salt, norm_email.encode("utf-8"), hashlib.sha256).hexdigest()
    
    # Deterministic integer chunks from HMAC hash
    seed_client = int(digest[0:8], 16)
    seed_pan = int(digest[8:16], 16)
    seed_aadhaar = int(digest[16:24], 16)
    seed_phone = int(digest[24:32], 16)
    seed_bank = int(digest[32:40], 16)

    # Full Name determination
    if full_name and str(full_name).strip():
        name = str(full_name).strip()
    else:
        local_part = norm_email.split("@")[0] if "@" in norm_email else norm_email
        cleaned = re.sub(r"[._\-+]+", " ", local_part).strip()
        name = cleaned.title() if cleaned else "TradeOne User"

    # PAN: Never generate real-looking PAN data (Real format: [A-Z]{5}[0-9]{4}[A-Z]).
    # Use explicit test/fake prefix format: "TEST-PAN-XXXX" and masked "TEST-PAN-****"
    pan_num = seed_pan % 10000
    fake_pan = f"TEST-PAN-{pan_num:04d}"
    masked_pan = f"TEST-PAN-****{pan_num:04d}"

    # Aadhaar: Never generate real-looking Aadhaar (Real is 12 valid digits).
    # Use "0000-0000-XXXX"
    aadhaar_num = seed_aadhaar % 10000
    fake_aadhaar = f"0000-0000-{aadhaar_num:04d}"
    masked_aadhaar = f"0000-0000-****{aadhaar_num:04d}"

    # Mobile: Deterministic dummy number (starts with 90000)
    phone_num = seed_phone % 100000
    mobile = f"90000{phone_num:05d}"

    # Client ID: e.g. NT followed by 5 digits
    client_id = f"NT{(seed_client % 90000) + 10000}"

    # DP & Demat ID
    dp_id = getattr(settings, "DP_ID", "IN300001")
    dp_name = getattr(settings, "DP_NAME", "NiftyTrade Securities")
    masked_demat = f"{dp_id}********"

    # Bank Details
    bank_acc = f"••••••••{(seed_bank % 9000) + 1000}"

    return {
        "email": norm_email,
        "full_name": name,
        "client_id": client_id,
        "pan": fake_pan,
        "masked_pan": masked_pan,
        "aadhaar": fake_aadhaar,
        "masked_aadhaar": masked_aadhaar,
        "mobile": mobile,
        "dp_id": dp_id,
        "dp_name": dp_name,
        "demat_id": masked_demat,
        "masked_demat": masked_demat,
        "bank_name": "HDFC Bank",
        "bank_account_masked": bank_acc,
        "bank_ifsc": "HDFC0001234"
    }
