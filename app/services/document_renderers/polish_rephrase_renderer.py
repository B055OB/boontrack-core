"""app/services/document_renderers/polish_rephrase_renderer.py
Template renderer for Academic Polish & Paraphrase (Naskah_Hasil_Parafrase.docx).
"""

import io
import logging
from typing import Dict, Any, List, Union
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.services.document_renderers.common import (
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_DARK,
    COLOR_MUTED,
    set_document_margins,
    add_section_header,
    add_bullet_item,
    add_compliance_footer
)

logger = logging.getLogger("DOCX_RENDERER.POLISH")


def _normalize_data(data: Union[Dict[str, Any], str, None]) -> Dict[str, Any]:
    """Normalizes renderer input: handles plain-string, dict with string values, and missing keys gracefully."""
    if isinstance(data, str):
        # Plain text passed directly: wrap into proper schema
        return {
            "title": "Naskah Hasil Parafrase Akademis",
            "sections": [{"heading": "Naskah Hasil Penyempurnaan", "content": data}],
            "full_text": data,
            "full_paraphrased_text": data,
        }
    if not isinstance(data, dict):
        return {}
    # If sections contains strings instead of dicts, normalize them
    sections = data.get("sections") or []
    normalized_sections = []
    for sec in sections:
        if isinstance(sec, dict):
            normalized_sections.append(sec)
        elif isinstance(sec, str):
            normalized_sections.append({"heading": "", "content": sec})
    data = dict(data)
    data["sections"] = normalized_sections
    return data


def render_polish_rephrase_docx(data: Union[Dict[str, Any], str]) -> bytes:
    """Merender hasil parafrase akademik ke file Word (.docx) berstandar karya ilmiah formal."""
    data = _normalize_data(data)

    doc = Document()
    set_document_margins(doc, 1.0)  # Standard 1 inch academic margin

    title = data.get("title") or "Naskah Hasil Parafrase Akademis"
    tone = data.get("tone") or "Akademik Formal (EYD V)"
    orig_words = data.get("original_word_count") or 0
    final_words = data.get("paraphrased_word_count") or 0
    full_text = data.get("full_text") or data.get("full_paraphrased_text") or ""
    sections = data.get("sections") or []

    # 1. Header Judul Naskah
    p_badge = doc.add_paragraph()
    p_badge.paragraph_format.space_before = Pt(0)
    p_badge.paragraph_format.space_after = Pt(2)
    p_badge.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_badge = p_badge.add_run("★ BOONTRACK ACADEMIC EDITING & REPHRASE ★")
    r_badge.font.name = 'Calibri'
    r_badge.font.size = Pt(9.5)
    r_badge.font.bold = True
    r_badge.font.color.rgb = COLOR_SECONDARY

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_after = Pt(4)
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_title = p_title.add_run(str(title).upper())
    r_title.font.name = 'Calibri'
    r_title.font.size = Pt(15)
    r_title.font.bold = True
    r_title.font.color.rgb = COLOR_PRIMARY

    # Metadata Penyempurnaan (Tone & Word Count)
    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(12)
    p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_text = f"Standar: {tone}"
    if orig_words > 0 and final_words > 0:
        meta_text += f" | Panjang Naskah: {final_words} kata (Input: {orig_words} kata)"
    elif final_words > 0:
        meta_text += f" | Panjang Naskah: {final_words} kata"
    r_meta = p_meta.add_run(meta_text)
    r_meta.font.name = 'Calibri'
    r_meta.font.size = Pt(9.5)
    r_meta.font.color.rgb = COLOR_MUTED

    # 2. Key Takeaways / Catatan Kualitas Naskah
    takeaways = data.get("key_takeaways") or []
    if isinstance(takeaways, list) and takeaways:
        add_section_header(doc, "Catatan Penyempurnaan Naskah", color_rgb=COLOR_SECONDARY)
        for t in takeaways:
            add_bullet_item(doc, str(t), bold_prefix="✓ ")

    # 3. Isi Naskah Akademis (Sections / Full Text)
    add_section_header(doc, "Naskah Hasil Penyempurnaan (EYD V)", color_rgb=COLOR_PRIMARY)

    # Determine effective body text length for diagnostic logging
    body_char_count = sum(len(sec.get("content", "")) for sec in sections if isinstance(sec, dict))
    if body_char_count == 0:
        body_char_count = len(full_text)
    logger.info(f"[PolishRephraseRenderer] Rendering polish docx with text length: {body_char_count} chars, {len(sections)} sections")

    if not body_char_count:
        logger.warning("[PolishRephraseRenderer] WARNING: Both sections and full_text are empty — output will be header-only!")

    if isinstance(sections, list) and sections:
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            heading = sec.get("heading")
            content = sec.get("content") or ""

            if heading and len(sections) > 1:
                p_h = doc.add_paragraph()
                p_h.paragraph_format.space_before = Pt(8)
                p_h.paragraph_format.space_after = Pt(2)
                r_h = p_h.add_run(heading)
                r_h.font.name = 'Calibri'
                r_h.font.size = Pt(11)
                r_h.font.bold = True
                r_h.font.color.rgb = COLOR_SECONDARY

            # Pecah content per paragraf
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            if not paragraphs and content.strip():
                # Single-line content without double newlines
                paragraphs = [content.strip()]
            for para in paragraphs:
                p_body = doc.add_paragraph(para)
                p_body.paragraph_format.space_before = Pt(2)
                p_body.paragraph_format.space_after = Pt(6)
                p_body.paragraph_format.line_spacing = 1.25
                for r in p_body.runs:
                    r.font.name = 'Calibri'
                    r.font.size = Pt(10.5)
                    r.font.color.rgb = COLOR_DARK

    elif full_text:
        paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
        if not paragraphs and full_text.strip():
            paragraphs = [full_text.strip()]
        for para in paragraphs:
            p_body = doc.add_paragraph(para)
            p_body.paragraph_format.space_before = Pt(2)
            p_body.paragraph_format.space_after = Pt(6)
            p_body.paragraph_format.line_spacing = 1.25
            for r in p_body.runs:
                r.font.name = 'Calibri'
                r.font.size = Pt(10.5)
                r.font.color.rgb = COLOR_DARK

    add_compliance_footer(doc)

    out_io = io.BytesIO()
    doc.save(out_io)
    result_bytes = out_io.getvalue()
    logger.info(f"[PolishRephraseRenderer] Output docx size: {len(result_bytes)} bytes")
    return result_bytes
