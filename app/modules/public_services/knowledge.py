from typing import Any, Dict, List, Optional
from app.modules.public_services.interfaces import KnowledgeProvider

DUMMY_KNOWLEDGE_BASE: Dict[str, Dict[str, Any]] = {
    "sku": {
        "slug": "sku",
        "name": "Surat Keterangan Usaha (SKU)",
        "description": "Surat keterangan resmi dari kelurahan untuk keperluan izin usaha, perbankan, atau pinjaman modal.",
        "requirements": [
            "Surat Pengantar RT/RW setempat",
            "Fotokopi KTP Pemohon (wajib KTP setempat/domisili)",
            "Fotokopi Kartu Keluarga (KK)",
            "Foto bukti kegiatan usaha / tempat usaha di lokasi",
            "Surat pernyataan usaha bermaterai 10.000 (disediakan di kelurahan jika belum bawa)"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit di Loket Pelayanan Kelurahan"
    },
    "domisili": {
        "slug": "domisili",
        "name": "Surat Keterangan Domisili Warga / Lembaga",
        "description": "Surat bukti tempat tinggal atau kedudukan badan hukum/yayasan.",
        "requirements": [
            "Surat Pengantar RT/RW",
            "KTP & KK Pemohon (Asli & Fotokopi)",
            "Surat Bukti Kepemilikan Rumah / Perjanjian Sewa Kontrak"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "15 - 30 Menit"
    },
    "sktm": {
        "slug": "sktm",
        "name": "Surat Keterangan Tidak Mampu (SKTM)",
        "description": "Surat keterangan untuk keperluan beasiswa, keringanan biaya RS, atau bantuan sosial.",
        "requirements": [
            "Surat Pengantar RT/RW dengan catatan kondisi ekonomi",
            "Fotokopi KTP dan KK",
            "Foto rumah tampak depan dan ruang tamu"
        ],
        "cost": "Gratis (Rp 0)",
        "processing_time": "1x24 Jam Kerja"
    }
}


class LocalKnowledgeProvider(KnowledgeProvider):
    async def get_service_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        return DUMMY_KNOWLEDGE_BASE.get(slug)

    async def search_relevant_services(self, query: str) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for service in DUMMY_KNOWLEDGE_BASE.values():
            if (
                query_lower in service["name"].lower()
                or query_lower in service["description"].lower()
                or any(query_lower in req.lower() for req in service["requirements"])
                or service["slug"] in query_lower
            ):
                results.append(service)

        return results if results else list(DUMMY_KNOWLEDGE_BASE.values())