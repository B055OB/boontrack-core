"""app/services/document_renderers/__init__.py
Modular DOCX Template Renderers for BoonTrack Document Engine v1.

Maps structured JSON outputs to deterministic python-docx templates for:
- CV_ATS (CV_ATS_Optimasi.docx)
- CV_REVIEW (Laporan_Review_CV_HR.docx)
- POLISH_REPHRASE (Naskah_Hasil_Parafrase.docx)
- CAREER_PRO_BUNDLE (Paket_Lengkap_Karir_Pro.docx)
"""

import logging
from typing import Dict, Any

from app.services.document_renderers.cv_ats_renderer import render_cv_ats_docx
from app.services.document_renderers.cv_review_renderer import render_cv_review_docx
from app.services.document_renderers.polish_rephrase_renderer import render_polish_rephrase_docx
from app.services.document_renderers.career_pro_bundle_renderer import render_career_pro_bundle_docx

logger = logging.getLogger("DOCX_RENDERER")

CANONICAL_RENDERER_MAP = {
    # Service 1: CV_BUILD / CV_ATS
    "CV_BUILD": "CV_ATS",
    "CV_ATS": "CV_ATS",
    "CV_POLISH_REWRITE": "CV_ATS",
    "CV_REWRITE": "CV_ATS",

    # Service 2: CV_REVIEW
    "CV_REVIEW": "CV_REVIEW",
    "ATS_DIAGNOSTIC": "CV_REVIEW",
    "ATS_REVIEW": "CV_REVIEW",

    # Service 3: POLISH_REPHRASE
    "POLISH_REPHRASE": "POLISH_REPHRASE",
    "PARAPHRASE": "POLISH_REPHRASE",
    "DOCUMENT_POLISH": "POLISH_REPHRASE",

    # Service 4: CAREER_PRO_BUNDLE
    "CAREER_PRO_BUNDLE": "CAREER_PRO_BUNDLE",
    "BUNDLE_CAREER": "CAREER_PRO_BUNDLE",
    "PRO_BUNDLE": "CAREER_PRO_BUNDLE"
}


def render_document(task_type: str, structured_data: Dict[str, Any]) -> bytes:
    """Dispatcher utama pembuat file Word (.docx) berbasis template modular."""
    raw = str(task_type or "").upper().strip()
    canonical = CANONICAL_RENDERER_MAP.get(raw, raw)

    if canonical == "CV_REVIEW":
        return render_cv_review_docx(structured_data)
    elif canonical == "CAREER_PRO_BUNDLE":
        return render_career_pro_bundle_docx(structured_data)
    elif canonical == "POLISH_REPHRASE":
        return render_polish_rephrase_docx(structured_data)
    elif canonical == "CV_ATS":
        return render_cv_ats_docx(structured_data)
    else:
        logger.warning(f"[DocumentRenderers] Unknown task_type '{task_type}', defaulting to CV ATS layout.")
        return render_cv_ats_docx(structured_data)


__all__ = [
    "render_document",
    "render_cv_ats_docx",
    "render_cv_review_docx",
    "render_polish_rephrase_docx",
    "render_career_pro_bundle_docx"
]
