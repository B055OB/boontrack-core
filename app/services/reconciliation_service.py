import os
import time
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger(__name__)

# Penyimpanan Payment Intent di memori (bisa disambung ke SQLite/DB)
PAYMENT_INTENTS: Dict[str, Dict[str, Any]] = {}

INVOICE_TTL_MINUTES = 30
MAX_FUZZY_DIFF_RUPIAH = 5  # Toleransi selisih typo maksimal Rp5


def generate_unique_payment_intent(tenant_id: str, base_amount: int, product_id: str, user_id: str) -> Dict[str, Any]:
    """Membuat Payment Intent dengan 3-digit kode unik yang dijamin unik di antara invoice aktif."""
    now = datetime.now()

    # Bersihkan intent expired
    for inv_id, data in list(PAYMENT_INTENTS.items()):
        exp_time = data.get("expires_at")
        if data.get("status") == "PENDING" and exp_time and exp_time < now:
            data["status"] = "EXPIRED"

    active_amounts = {
        data["total_amount"]
        for data in PAYMENT_INTENTS.values()
        if data.get("status") == "PENDING" and data.get("expires_at", now) >= now
    }

    attempts = 0
    unique_code = random.randint(101, 899)
    candidate_total = base_amount + unique_code

    while candidate_total in active_amounts and attempts < 100:
        unique_code = random.randint(101, 899)
        candidate_total = base_amount + unique_code
        attempts += 1

    invoice_id = f"BT-{int(time.time()) % 100000:05d}-{unique_code}"
    expires_at = now + timedelta(minutes=INVOICE_TTL_MINUTES)

    intent_record = {
        "id": invoice_id,
        "invoice_id": invoice_id,
        "tenant_id": tenant_id,
        "user_id": str(user_id),
        "product_id": product_id,
        "base_amount": base_amount,
        "unique_code": unique_code,
        "total_amount": candidate_total,
        "status": "PENDING",
        "expires_at": expires_at,
        "created_at": now,
        "paid_at": None,
        "transaction_reference": None,
        "match_score": 0
    }

    PAYMENT_INTENTS[invoice_id] = intent_record
    logger.info(f"[PAYMENT INTENT] {invoice_id} created for {user_id}: Rp{candidate_total:,}")
    return intent_record


async def reconcile_incoming_mutation(incoming_amount: int, raw_text: str = "", tenant_id: Optional[str] = None) -> Tuple[str, Optional[Dict[str, Any]], int]:
    """
    Mencocokkan mutasi masuk dari reader:
    - EXACT_MATCH: nominal 100% tepat -> langsung kirim produk.
    - NEAR_MATCH: typo beda tipis (<= Rp5) -> beri tahu user & tahan untuk review.
    - AMBIGUOUS: lebih dari 1 invoice cocok.
    - UNMATCHED: tidak ada kecocokan.
    """
    now = datetime.now()
    exact_matches: List[Dict[str, Any]] = []
    near_matches: List[Tuple[int, Dict[str, Any]]] = []

    for inv_id, intent in PAYMENT_INTENTS.items():
        if intent["status"] != "PENDING" or intent["expires_at"] < now:
            continue
        if tenant_id and tenant_id not in ["all", ""] and intent["tenant_id"] != tenant_id:
            continue

        expected = intent["total_amount"]
        diff = abs(incoming_amount - expected)

        # 1. Exact Match
        if diff == 0:
            exact_matches.append(intent)
        # 2. Fuzzy / Near Match (Selisih <= Rp5 dan basis harga sama)
        elif diff <= MAX_FUZZY_DIFF_RUPIAH and abs(incoming_amount - intent["base_amount"]) < 1000:
            near_matches.append((diff, intent))

    # Kasus 1: Exact Match Sempurna
    if len(exact_matches) == 1:
        target = exact_matches[0]
        target["status"] = "PAID"
        target["paid_at"] = now
        target["match_score"] = 100
        target["transaction_reference"] = raw_text
        return "EXACT_MATCH", target, 0

    # Kasus 2: Exact Match Ambiguous (tabrakan 2 invoice identik)
    if len(exact_matches) > 1:
        for t in exact_matches:
            t["status"] = "REVIEW"
        return "AMBIGUOUS", exact_matches[0], 0

    # Kasus 3: Near Match (Typo Beda Tipis)
    if len(near_matches) == 1:
        diff, target = near_matches[0]
        target["status"] = "REVIEW"
        target["transaction_reference"] = f"TYPO_MUTATION: Rp{incoming_amount:,} (Diff: Rp{diff})"
        return "NEAR_MATCH", target, diff

    if len(near_matches) > 1:
        return "AMBIGUOUS", near_matches[0][1], near_matches[0][0]

    return "UNMATCHED", None, 0
