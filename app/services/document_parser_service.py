import os
import io
import logging
import httpx
from pypdf import PdfReader
from docx import Document

logger = logging.getLogger(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN") or os.getenv("META_WA_TOKEN", "")

async def download_whatsapp_media(media_id: str) -> bytes:
    """Mengambil URL download dari Meta Graph API dan mengunduh filenya."""
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        meta_url = f"https://graph.facebook.com/v19.0/{media_id}"
        res = await client.get(meta_url, headers=headers)
        res.raise_for_status()
        download_url = res.json().get("url")

        file_res = await client.get(download_url, headers=headers)
        file_res.raise_for_status()
        return file_res.content

def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Mengekstrak teks mentah dari file PDF atau DOCX."""
    filename_lower = filename.lower()
    extracted_text = ""

    try:
        if filename_lower.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    extracted_text += text + "\n"
        elif filename_lower.endswith(".docx"):
            doc = Document(io.BytesIO(file_bytes))
            for p in doc.paragraphs:
                if p.text.strip():
                    extracted_text += p.text.strip() + "\n"
    except Exception as e:
        logger.error(f"[Document Parser Error] {e}")

    return extracted_text.strip()

parse_cv_document = extract_text_from_bytes