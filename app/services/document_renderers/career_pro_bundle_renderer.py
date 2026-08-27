"""app/services/document_renderers/career_pro_bundle_renderer.py
Template renderer for Career Pro Bundle (CV ATS + HR Recommendations + Cover Letter).
Updated to support complete employment history without omitting past roles.
"""

import io
import logging
from typing import Dict, Any, Union
from docx import Document
from docx.shared import Pt, Inches
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

logger = logging.getLogger("DOCX_RENDERER.CAREER_BUNDLE")


def render_career_pro_bundle_docx(data: Union[Dict[str, Any], str]) -> bytes:
    """Merender paket Career Pro Bundle ke file Word (.docx) dengan data lengkap dan halaman terpisah."""
    if not isinstance(data, dict):
        data = {"full_name": "Kandidat Profesional"}

    doc = Document()
    set_document_margins(doc, 1.0)

    # ==========================================
    # PILAR 1: CV ATS TAILORED (Halaman 1)
    # ==========================================
    p_badge = doc.add_paragraph()
    p_badge.paragraph_format.space_before = Pt(0)
    p_badge.paragraph_format.space_after = Pt(2)
    p_badge.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_badge = p_badge.add_run("★ BOONTRACK CAREER PRO BUNDLE ★")
    r_badge.font.name = 'Calibri'
    r_badge.font.size = Pt(9.5)
    r_badge.font.bold = True
    r_badge.font.color.rgb = COLOR_SECONDARY

    full_name = data.get("full_name", "Kandidat Profesional")
    p_name = doc.add_paragraph()
    p_name.paragraph_format.space_after = Pt(2)
    p_name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_name = p_name.add_run(str(full_name).upper())
    r_name.font.name = 'Calibri'
    r_name.font.size = Pt(16)
    r_name.font.bold = True
    r_name.font.color.rgb = COLOR_PRIMARY

    target_pos = data.get("target_position", "Professional Role")
    p_pos = doc.add_paragraph()
    p_pos.paragraph_format.space_after = Pt(4)
    p_pos.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_pos = p_pos.add_run(target_pos)
    r_pos.font.name = 'Calibri'
    r_pos.font.size = Pt(11)
    r_pos.font.bold = True
    r_pos.font.color.rgb = COLOR_DARK

    # Kontak Info
    email = data.get("email", "")
    phone = data.get("phone", "")
    location = data.get("location", "")
    linkedin = data.get("linkedin", "")
    portfolio = data.get("portfolio", "")
    contact_parts = [p for p in [email, phone, location, linkedin, portfolio] if p]
    
    if contact_parts:
        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(12)
        p_contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_contact = p_contact.add_run("  |  ".join(contact_parts))
        r_contact.font.name = 'Calibri'
        r_contact.font.size = Pt(9.5)
        r_contact.font.color.rgb = COLOR_MUTED

    # Professional Summary
    summary = data.get("summary", "")
    if summary:
        add_section_header(doc, "PROFESSIONAL SUMMARY", color_rgb=COLOR_PRIMARY)
        p_sum = doc.add_paragraph(summary)
        p_sum.paragraph_format.space_after = Pt(8)
        p_sum.paragraph_format.line_spacing = 1.15
        for r in p_sum.runs:
            r.font.name = 'Calibri'
            r.font.size = Pt(10)

    # Core Competencies & Skills
    skills = data.get("skills", {})
    if skills and isinstance(skills, dict):
        add_section_header(doc, "CORE COMPETENCIES & SKILLS", color_rgb=COLOR_PRIMARY)
        for cat, items in skills.items():
            cat_name = cat.replace('_', ' ').title()
            items_str = ", ".join(items) if isinstance(items, list) else str(items)
            add_bullet_item(doc, f"{cat_name}: {items_str}", bold_prefix="• ")
        doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # Professional Experience (Lengkap Kronologis Terbalik)
    experiences = data.get("experience", [])
    if experiences and isinstance(experiences, list):
        add_section_header(doc, "PROFESSIONAL EXPERIENCE", color_rgb=COLOR_PRIMARY)
        for exp in experiences:
            role = exp.get("role", "Role")
            company = exp.get("company", "Company")
            period = exp.get("period", "")
            loc = exp.get("location", "")
            
            p_exp = doc.add_paragraph()
            p_exp.paragraph_format.space_before = Pt(4)
            p_exp.paragraph_format.space_after = Pt(1)
            r_role = p_exp.add_run(role)
            r_role.font.name = 'Calibri'
            r_role.font.size = Pt(10)
            r_role.font.bold = True
            r_role.font.color.rgb = COLOR_DARK

            if period or loc:
                p_sub = doc.add_paragraph()
                p_sub.paragraph_format.space_after = Pt(3)
                r_sub = p_sub.add_run(f"{period}  |  {company} | {loc}".strip(" |"))
                r_sub.font.name = 'Calibri'
                r_sub.font.size = Pt(9.5)
                r_sub.font.italic = True
                r_sub.font.color.rgb = COLOR_MUTED

            bullets = exp.get("bullets", [])
            for b in bullets:
                add_bullet_item(doc, str(b), bold_prefix="• ")

    # Education
    education = data.get("education", [])
    if education and isinstance(education, list):
        add_section_header(doc, "EDUCATION", color_rgb=COLOR_PRIMARY)
        for edu in education:
            degree = edu.get("degree", "")
            inst = edu.get("institution", "")
            year = edu.get("year", "")
            gpa = edu.get("gpa", "")
            edu_str = degree
            if gpa:
                edu_str += f" | GPA: {gpa}"
            if year:
                edu_str += f" | {year}"
            add_bullet_item(doc, f"{edu_str} — {inst}", bold_prefix="• ")

    # ==========================================
    # PILAR 2: REKOMENDASI HR & STAR (Halaman 2)
    # ==========================================
    doc.add_page_break()

    add_section_header(doc, "REKOMENDASI HR & CAREER STRATEGY", color_rgb=COLOR_PRIMARY)
    
    hr_rec = data.get("hr_recommendations", {})
    if isinstance(hr_rec, dict):
        readiness = hr_rec.get("profile_readiness", "Tinggi")
        add_bullet_item(doc, f"Kesiapan Profil: {readiness}", bold_prefix="• Kesiapan Profil: ")

        strengths = hr_rec.get("key_strengths", [])
        if strengths:
            p_s = doc.add_paragraph()
            p_s.paragraph_format.space_before = Pt(4)
            p_s.paragraph_format.space_after = Pt(2)
            r_s = p_s.add_run("Kekuatan Utama:")
            r_s.font.bold = True
            r_s.font.size = Pt(10)
            for st in strengths:
                add_bullet_item(doc, str(st), bold_prefix="- ")

        improvements = hr_rec.get("strategic_improvements", [])
        if improvements:
            p_i = doc.add_paragraph()
            p_i.paragraph_format.space_before = Pt(4)
            p_i.paragraph_format.space_after = Pt(2)
            r_i = p_i.add_run("Rekomendasi Peningkatan:")
            r_i.font.bold = True
            r_i.font.size = Pt(10)
            for imp in improvements:
                add_bullet_item(doc, str(imp), bold_prefix="- ")

        tips = hr_rec.get("interview_tips", [])
        if tips:
            p_t = doc.add_paragraph()
            p_t.paragraph_format.space_before = Pt(4)
            p_t.paragraph_format.space_after = Pt(2)
            r_t = p_t.add_run("Panduan Wawancara (Metode STAR):")
            r_t.font.bold = True
            r_t.font.size = Pt(10)
            for tip in tips:
                add_bullet_item(doc, str(tip), bold_prefix="- ")

    # ==========================================
    # PILAR 3: SURAT LAMARAN / COVER LETTER (Halaman 3)
    # ==========================================
    doc.add_page_break()

    add_section_header(doc, "SURAT LAMARAN KERJA (COVER LETTER)", color_rgb=COLOR_PRIMARY)
    
    cover = data.get("cover_letter", {})
    if isinstance(cover, dict):
        recipient = cover.get("recipient", "Yth. Hiring Manager")
        subject = cover.get("subject", "Aplikasi Lamaran Pekerjaan")
        salutation = cover.get("salutation", "Dengan hormat,")
        opening = cover.get("opening", "")
        body_paras = cover.get("body_paragraphs", [])
        closing = cover.get("closing", "")
        sign_off = cover.get("sign_off", f"Hormat saya,\n{full_name}")

        for meta_line in [recipient, f"Perihal: {subject}"]:
            if meta_line:
                p_m = doc.add_paragraph(meta_line)
                p_m.paragraph_format.space_after = Pt(2)
                for r in p_m.runs:
                    r.font.name = 'Calibri'
                    r.font.size = Pt(10)
                    r.font.bold = True

        doc.add_paragraph().paragraph_format.space_after = Pt(4)
        
        p_sal = doc.add_paragraph(salutation)
        p_sal.paragraph_format.space_after = Pt(6)
        
        if opening:
            p_op = doc.add_paragraph(opening)
            p_op.paragraph_format.space_after = Pt(6)
            p_op.paragraph_format.line_spacing = 1.15

        for bp in body_paras:
            p_bp = doc.add_paragraph(str(bp))
            p_bp.paragraph_format.space_after = Pt(6)
            p_bp.paragraph_format.line_spacing = 1.15

        if closing:
            p_cl = doc.add_paragraph(closing)
            p_cl.paragraph_format.space_after = Pt(12)
            p_cl.paragraph_format.line_spacing = 1.15

        p_so = doc.add_paragraph(sign_off)
        p_so.paragraph_format.space_after = Pt(12)

    # Catatan Catatan Kaki Estimasi Data
    p_note = doc.add_paragraph()
    p_note.paragraph_format.space_before = Pt(12)
    r_n = p_note.add_run("* Tanggal untuk PT. Titian Abadi Lestari dan PT. Shidai Export and Import merupakan estimasi berdasarkan urutan kronologis pada CV asli — mohon dikonfirmasi ulang dengan kandidat.")
    r_n.font.size = Pt(8.5)
    r_n.font.italic = True
    r_n.font.color.rgb = COLOR_MUTED

    add_compliance_footer(doc)

    out_io = io.BytesIO()
    doc.save(out_io)
    return out_io.getvalue()