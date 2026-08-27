"""app/services/doc_builder.py
Document Builder & Text Chunking Service for BoonTrack Core.

Delegates DOCX rendering to modular template renderers in app.services.document_renderers.
Maintains backward compatibility for legacy callers and unit tests.
"""

import re
import logging
from typing import Dict, Any, List

from app.services.document_renderers import (
    render_document,
    render_cv_ats_docx,
    render_cv_review_docx,
    render_polish_rephrase_docx,
    render_career_pro_bundle_docx
)
from app.services.document_renderers.common import (
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_DARK,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    set_document_margins,
    add_section_header,
    add_bullet_item,
    add_compliance_footer
)

logger = logging.getLogger(__name__)

# Legacy aliases for backward compatibility
render_cv_rewrite_docx = render_cv_ats_docx
render_ats_review_docx = render_cv_review_docx
render_paraphrase_docx = render_polish_rephrase_docx
build_document_result = render_document

# Legacy internal aliases
_set_document_margins = set_document_margins
_add_section_header = add_section_header
_add_bullet_item = add_bullet_item
_add_compliance_footer = add_compliance_footer


def chunk_document_text(text: str, max_chunk_words: int = 650) -> List[Dict[str, Any]]:
    """Membagi naskah panjang per sub-bab/paragraf (500-700 kata) dengan mempertahankan kutipan, teori, & sitasi.
    
    Returns:
        List of chunks with 'chunk_index', 'heading', 'text', 'word_count'.
    """
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) == 1 and "\n" in paragraphs[0]:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks: List[Dict[str, Any]] = []
    current_paragraphs: List[str] = []
    current_word_count = 0
    chunk_idx = 1
    current_heading = "Pendahuluan / Bagian Awal"

    # Pattern deteksi heading bab / section (e.g. "BAB I", "1.1", "Metodologi", "A. Latar Belakang")
    heading_pattern = re.compile(
        r"^(bab\s+[ivxlcdm\d]+|(\d+\.){1,3}\d*|[a-z]\.\s+|abstrak|pendahuluan|metode|tinjauan pustaka|pembahasan|kesimpulan|daftar pustaka)",
        re.IGNORECASE
    )

    for p in paragraphs:
        p_words = len(p.split())
        is_heading = bool(heading_pattern.match(p)) and len(p.split()) < 12

        if is_heading and current_paragraphs:
            if current_word_count >= 350:
                chunks.append({
                    "chunk_index": chunk_idx,
                    "heading": current_heading,
                    "text": "\n\n".join(current_paragraphs),
                    "word_count": current_word_count
                })
                chunk_idx += 1
                current_paragraphs = []
                current_word_count = 0
            current_heading = p

        if current_word_count + p_words > max_chunk_words and current_paragraphs:
            chunks.append({
                "chunk_index": chunk_idx,
                "heading": current_heading,
                "text": "\n\n".join(current_paragraphs),
                "word_count": current_word_count
            })
            chunk_idx += 1
            current_paragraphs = [p]
            current_word_count = p_words
        else:
            current_paragraphs.append(p)
            current_word_count += p_words

    if current_paragraphs:
        chunks.append({
            "chunk_index": chunk_idx,
            "heading": current_heading,
            "text": "\n\n".join(current_paragraphs),
            "word_count": current_word_count
        })

    return chunks
