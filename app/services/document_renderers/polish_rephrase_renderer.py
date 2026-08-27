"""app/services/document_renderers/polish_rephrase_renderer.py
Template renderer for Academic Polish & Paraphrase (Naskah_Hasil_Parafrase.docx).
"""

import io
from typing import Dict, Any, List
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


def render_polish_rephrase_docx(data: Dict[str, Any]) -> bytes:
    """Merender hasil parafrase akademik ke file Word (.docx) berstandar karya ilmiah formal."""
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
    return out_io.getvalue()
