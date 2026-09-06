import pytest
import os
import json
from unittest.mock import patch, MagicMock
from app.services.session_store import (
    get_user_tenant_session,
    set_user_tenant_session,
    clear_user_tenant_session,
    detect_demo_intent_keyword,
    DISK_CACHE_PATH,
)
from app.services.whatsapp_service import (
    user_tenant_sessions,
    user_session_states,
    reset_whatsapp_user_session,
    resolve_dynamic_tenant_for_whatsapp,
    get_user_session,
    set_user_session,
)
from app.repositories.session_repository import SessionRepository


@pytest.mark.asyncio
async def test_session_persistence_across_memory_wipe():
    phone = "6289911223344"
    tenant = "onlineboost"

    # 1. Set session
    set_user_tenant_session(phone, tenant)
    assert get_user_tenant_session(phone) == tenant

    # 2. Simulate container restart / worker restart (wipe in-memory dict)
    user_tenant_sessions.clear()
    user_session_states.clear()
    assert phone not in user_tenant_sessions

    # 3. Read session again -> must restore from disk or DB
    restored = get_user_tenant_session(phone)
    assert restored == tenant
    assert user_tenant_sessions.get(phone) == tenant

    # Clean up
    clear_user_tenant_session(phone)
    assert get_user_tenant_session(phone) is None


@pytest.mark.asyncio
async def test_session_recovery_from_keyword_detection():
    phone = "6281299887766"
    clear_user_tenant_session(phone)
    user_tenant_sessions.pop(phone, None)

    # User sends text mentioning paid traffic when session was dropped
    text = "Materi Paid Traffic tidak termasuk dalam apa aja ya min?"
    detected = detect_demo_intent_keyword(text)
    assert detected == "onlineboost"

    # get_user_tenant_session should auto-infer and lock session to onlineboost
    session_tenant = get_user_tenant_session(phone, message_text=text)
    assert session_tenant == "onlineboost"
    assert user_tenant_sessions.get(phone) == "onlineboost"

    # Clean up
    clear_user_tenant_session(phone)


@pytest.mark.asyncio
async def test_session_repository_integration():
    repo = SessionRepository()
    phone = "6285544332211"
    tenant = "growthplus"

    # Test static helpers
    SessionRepository.set_user_session(phone, tenant)
    assert SessionRepository.get_user_session(phone) == tenant

    # Test get_or_create and save
    session = await repo.get_or_create(user_id=phone, channel="whatsapp")
    assert session is not None
    session.context_json = {"last_stage": "CONSIDERATION"}
    await repo.save(session)

    # Wipe in-memory cache
    from app.repositories.session_repository import _SESSION_CACHE
    _SESSION_CACHE.clear()

    # Re-fetch
    restored_session = await repo.get_or_create(user_id=phone, channel="whatsapp")
    assert restored_session.context_json.get("last_stage") == "CONSIDERATION"

    # Clean up
    SessionRepository.clear_user_session(phone)


@pytest.mark.asyncio
async def test_om_budi_safeguard_against_demo_keywords():
    from app.tenants.om_budi.service import om_budi_service
    phone = "6287711223344"
    clear_user_tenant_session(phone)

    # Send message with demo intent to Om Budi service directly
    res = await om_budi_service.handle_incoming_message(
        phone_number=phone,
        message_text="Bisa minta silabus paid traffic dan materi suhu ads?",
        button_id="",
        user_name="Budi Demo"
    )

    reply = res.get("reply", "")
    # Must NOT reply with 6 materi utama rejection
    assert "tidak termasuk dalam" not in reply
    assert "OnlineBoost" in reply or "Katalog" in reply
    # Session must be restored to onlineboost
    assert get_user_tenant_session(phone) == "onlineboost"

    # Clean up
    clear_user_tenant_session(phone)
