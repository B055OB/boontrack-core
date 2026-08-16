from typing import Any, Dict, List, Optional
from app.modules.public_services.interfaces import KnowledgeProvider


DUMMY_KNOWLEDGE_BASE: Dict[str, Dict[str, Any]] = {
    "surat-keterangan-usaha": {
        "name": "Surat Keterangan Usaha (SKU / NIB)",
        "slug": "surat-keterangan-usaha",
        "description": "Surat keterangan legalitas usaha mikro/kecil dari kelurahan.",
        "requirements": [
            "Fotokopi KTP Pemilik Usaha",
            "Fotokopi Kartu Keluarga (KK)",
            "Surat Pengantar RT/RW setempat",
            "Foto lokasi / kegiatan usaha",
            "Bukti lunas PBB tahun berjalan"
        ],
        "process_description": "Bawa berkas ke loket -> Verifikasi petugas -> Cetak dan tanda tangan Lurah.",
        "estimated_time": "1 hari kerja (Gratis)"
    },
    "surat-keterangan-domisili": {
        "name": "Surat Keterangan Domisili Warga",
        "slug": "surat-keterangan-domisili",
        "description": "Surat bukti tempat tinggal bagi warga domisili atau kebutuhan administratif.",
        "requirements": [
            "Fotokopi KTP & KK Asli",
            "Surat Pengantar RT/RW",
            "Surat pernyataan domisili bermaterai Rp10.000"
        ],
        "process_description": "Verifikasi dokumen di loket kelurahan.",
        "estimated_time": "15 - 30 menit (Gratis)"
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
            ):
                results.append(service)
        return results