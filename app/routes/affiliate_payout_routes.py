"""
Fail-closed lock for affiliate/partner payout DISBURSEMENT endpoints.

Until the P0 identity-boundary incident is formally closed, every endpoint that can
disburse or settle money (batch settle, mark-paid) MUST return HTTP 403 with
``PAYOUT_DISBURSEMENT_LOCKED`` and must not touch any payout state.
"""
from fastapi import HTTPException, status

PAYOUT_DISBURSEMENT_LOCKED = "PAYOUT_DISBURSEMENT_LOCKED"


def payout_disbursement_locked() -> HTTPException:
    """Build the canonical 403 exception for locked disbursement endpoints."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": PAYOUT_DISBURSEMENT_LOCKED,
            "message": "Payout disbursement is locked (fail-closed) pending P0 security remediation.",
        },
    )

