"""
Test Suite: Kelurahan Margasari Public Service Knowledge Base & Service Matching
Memverifikasi respon AI, modul IKD, SKDU, KBS, identitas Lurah, dan Jam Pelayanan.
"""

import pytest
from app.modules.public_services.knowledge import (
    PublicServiceKnowledgeProvider,
    SERVICES_DATABASE,
)
from app.modules.public_services.service import (
    PublicServiceService,
    public_service_service,
)
from app.tenants.pelayanan_publik.config import (
    LOCATION,
    LURAH,
    OPERATIONAL_HOURS,
    TENANT_NAME,
    TENANT_SLUG,
)


def test_tenant_config_margasari():
    assert "Margasari" in TENANT_NAME
    assert "Wahyu A. Affandi, S.IP., M.Si." == LURAH
    assert "Jl. Cipagalo Girang No. 09" in LOCATION
    assert "08:00 - 15:00 WIB" in OPERATIONAL_HOURS


def test_knowledge_base_contains_margasari_services():
    provider = PublicServiceKnowledgeProvider(tenant_id="kelurahan-margasari")
    services = provider.get_all_services()

    assert "ikd" in services
    assert "skdu" in services
    assert "kk-ktp" in services
    assert "kbs-kebersihan" in services
    assert "profil-kelurahan" in services
    assert "jam-pelayanan" in services

    # Verify no legacy strings in descriptions
    for s in services.values():
        assert "Kebon Melati" not in s["description"]
        assert "Jakarta Pusat" not in s["description"]


@pytest.mark.asyncio
async def test_ai_query_ikd_activation():
    res = await PublicServiceService.handle_query("Aktivasi IKD KTP Online")
    reply = res["reply"]
    assert "Identitas Kependudukan Digital (IKD / KTP Online)" in reply
    assert "Jl. Cipagalo Girang No. 09" in reply
    assert "KemenDagri" in reply
    assert "Face Recognition" in reply
    assert "Gratis" in reply


@pytest.mark.asyncio
async def test_ai_query_syarat_domisili():
    res = await PublicServiceService.handle_query("Syarat Domisili Usaha")
    reply = res["reply"]
    assert "Surat Keterangan Domisili & Usaha (SKDU)" in reply
    assert "Wahyu A. Affandi, S.IP., M.Si." in reply
    assert "Jl. Cipagalo Girang No. 09" in reply


@pytest.mark.asyncio
async def test_ai_query_jam_buka():
    res = await PublicServiceService.handle_query("Jam Buka Pelayanan")
    reply = res["reply"]
    assert "08:00 - 15:00 WIB" in reply
    assert "Senin s.d. Jumat" in reply


@pytest.mark.asyncio
async def test_ai_query_lurah_margasari():
    res = await PublicServiceService.handle_query("Siapa Lurah Margasari?")
    reply = res["reply"]
    assert "Wahyu A. Affandi, S.IP., M.Si." in reply
    assert "Kecamatan Buahbatu, Kota Bandung" in reply


@pytest.mark.asyncio
async def test_ai_query_kbs_kebersihan():
    res = await PublicServiceService.handle_query("Program KBS Sampah Margasari")
    reply = res["reply"]
    assert "Kawasan Bebas Sampah (KBS Margasari)" in reply
    assert "Bank Sampah" in reply
    assert "Dinas Lingkungan Hidup (DLH) Kota Bandung" in reply
