"""app/prompts/__init__.py
Strategy-Pattern Prompt Dispatcher for BoonTrack Document Engine v1.

Centralizes prompt generation and structured fallback payloads across all 4 Core Services:
- CV_ATS (CV_BUILD)
- CV_REVIEW
- POLISH_REPHRASE
- CAREER_PRO_BUNDLE
"""

import logging
from typing import Dict, Any, Optional

from app.prompts import cv_ats, cv_review, polish_rephrase, career_pro_bundle

logger = logging.getLogger("PROMPT_STRATEGY")

TASK_CV_BUILD = "CV_BUILD"
TASK_CV_ATS = "CV_ATS"
TASK_CV_REVIEW = "CV_REVIEW"
TASK_POLISH_REPHRASE = "POLISH_REPHRASE"
TASK_CAREER_PRO_BUNDLE = "CAREER_PRO_BUNDLE"

CANONICAL_PROMPT_MAP = {
    # Service 1: CV_BUILD / CV_ATS
    "CV_BUILD": TASK_CV_ATS,
    "CV_ATS": TASK_CV_ATS,
    "CV_POLISH_REWRITE": TASK_CV_ATS,
    "CV_REWRITE": TASK_CV_ATS,

    # Service 2: CV_REVIEW
    "CV_REVIEW": TASK_CV_REVIEW,
    "ATS_DIAGNOSTIC": TASK_CV_REVIEW,
    "ATS_REVIEW": TASK_CV_REVIEW,

    # Service 3: POLISH_REPHRASE
    "POLISH_REPHRASE": TASK_POLISH_REPHRASE,
    "PARAPHRASE": TASK_POLISH_REPHRASE,
    "DOCUMENT_POLISH": TASK_POLISH_REPHRASE,

    # Service 4: CAREER_PRO_BUNDLE
    "CAREER_PRO_BUNDLE": TASK_CAREER_PRO_BUNDLE,
    "BUNDLE_CAREER": TASK_CAREER_PRO_BUNDLE,
    "PRO_BUNDLE": TASK_CAREER_PRO_BUNDLE
}


def normalize_prompt_task(task_type: str) -> str:
    """Mengembalikan canonical task identifier."""
    raw = str(task_type or "").upper().strip()
    return CANONICAL_PROMPT_MAP.get(raw, raw)


def get_prompt_for_task(
    task_type: str,
    raw_text: str,
    filename: str = "Dokumen",
    **kwargs
) -> str:
    """Mengembalikan prompt strategy yang sesuai berdasarkan task_type.
    
    Raises:
        ValueError: Jika task_type tidak didukung.
    """
    canonical = normalize_prompt_task(task_type)

    if canonical == TASK_CV_ATS:
        return cv_ats.get_prompt(raw_text=raw_text, filename=filename)
    elif canonical == TASK_CV_REVIEW:
        return cv_review.get_prompt(raw_text=raw_text, filename=filename)
    elif canonical == TASK_POLISH_REPHRASE:
        chunk_idx = kwargs.get("chunk_idx", 0)
        total_chunks = kwargs.get("total_chunks", 1)
        return polish_rephrase.get_chunk_prompt(chunk_text=raw_text, chunk_idx=chunk_idx, total_chunks=total_chunks)
    elif canonical == TASK_CAREER_PRO_BUNDLE:
        target_role = kwargs.get("target_role", "")
        return career_pro_bundle.get_prompt(raw_text=raw_text, filename=filename, target_role=target_role)
    else:
        raise ValueError(f"Unsupported document task_type for prompt strategy: '{task_type}'")


def get_fallback_for_task(
    task_type: str,
    raw_text: str = ""
) -> Dict[str, Any]:
    """Mengembalikan deterministic fallback structured data yang sesuai dengan aturan strict."""
    canonical = normalize_prompt_task(task_type)

    if canonical == TASK_CV_ATS:
        return cv_ats.get_fallback_data(raw_text=raw_text)
    elif canonical == TASK_CV_REVIEW:
        return cv_review.get_fallback_data(raw_text=raw_text)
    elif canonical == TASK_POLISH_REPHRASE:
        return polish_rephrase.get_fallback_data(raw_text=raw_text)
    elif canonical == TASK_CAREER_PRO_BUNDLE:
        return career_pro_bundle.get_fallback_data(raw_text=raw_text)
    else:
        logger.warning(f"[PromptStrategy] Unknown task_type '{task_type}' in get_fallback_for_task — using CV_ATS schema")
        return cv_ats.get_fallback_data(raw_text=raw_text)
