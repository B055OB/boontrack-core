import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.routes.whatsapp_gateway_routes import process_evolution_webhook_payload, check_and_handle_session_handover_and_toggle

def make_evo_payload(
    remote_jid: str,
    incoming_text: str,
    from_me: bool = False,
    instance_name: str = "boontrack-shop",
) -> dict:
    return {
        "event": "messages.upsert",
        "instance": instance_name,
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "id": "test_msg_id_123",
            },
            "message": {
                "conversation": incoming_text
            }
        }
    }

@pytest.mark.asyncio
async def test_2a_broadcast_is_ignored():
    payload = make_evo_payload(
        remote_jid="status@broadcast",
        incoming_text="Status update",
        from_me=False
    )
    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance") as mock_conn:
        mock_conn.return_value = {
            "tenant_id": "boon",
            "tenant_slug": "boon",
            "instance_name": "boontrack-shop",
            "mode": "DEDICATED"
        }
        res = await process_evolution_webhook_payload(payload, tenant_slug="boon")
        assert res.get("status") == "ignored_broadcast"

@pytest.mark.asyncio
async def test_2b_admin_command_pause_and_resume_silent():
    # Admin chats with customer 628123456789 and sends 'pause'
    payload_pause = make_evo_payload(
        remote_jid="628123456789@s.whatsapp.net",
        incoming_text="  #pause  ",
        from_me=True
    )
    mock_conn_data = {
        "tenant_id": "boon",
        "tenant_slug": "boon",
        "instance_name": "boontrack-shop",
        "mode": "DEDICATED"
    }

    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance", return_value=mock_conn_data), \
         patch("app.routes.whatsapp_gateway_routes.check_and_handle_session_handover_and_toggle", new_callable=AsyncMock) as mock_toggle, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock):
        
        mock_toggle.return_value = {
            "handled": True,
            "status": "success",
            "bot_paused": True,
            "action": "MANUAL_PAUSE",
            "is_paused": True,
            "paused_by": "admin_command",
            "reply_text": None,
        }

        res_pause = await process_evolution_webhook_payload(payload_pause, tenant_slug="boon")
        assert res_pause.get("status") == "success"
        assert res_pause.get("action") == "admin_command_pause"
        assert res_pause.get("is_paused") is True
        assert res_pause.get("paused_by") == "admin_command"
        assert res_pause.get("sender_phone") == "628123456789"
        # Must be silent: no reply_text returned to caller that would trigger bot
        assert res_pause.get("reply_text") is None
        mock_toggle.assert_awaited_once_with(
            tenant_slug="boon",
            sender_phone="628123456789",
            incoming_text="pause",
            sender_name="Admin"
        )

    # Admin chats with customer and sends 'resume'
    payload_resume = make_evo_payload(
        remote_jid="628123456789@s.whatsapp.net",
        incoming_text="RESUME",
        from_me=True
    )
    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance", return_value=mock_conn_data), \
         patch("app.routes.whatsapp_gateway_routes.check_and_handle_session_handover_and_toggle", new_callable=AsyncMock) as mock_toggle, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock):
        
        mock_toggle.return_value = {
            "handled": True,
            "status": "success",
            "bot_paused": False,
            "action": "MANUAL_RESUME",
            "is_paused": False,
            "paused_by": "admin_command",
            "reply_text": None,
        }

        res_resume = await process_evolution_webhook_payload(payload_resume, tenant_slug="boon")
        assert res_resume.get("status") == "success"
        assert res_resume.get("action") == "admin_command_resume"
        assert res_resume.get("is_paused") is False
        assert res_resume.get("paused_by") == "admin_command"
        assert res_resume.get("sender_phone") == "628123456789"

@pytest.mark.asyncio
async def test_2b_admin_regular_chat_bypasses():
    payload_chat = make_evo_payload(
        remote_jid="628123456789@s.whatsapp.net",
        incoming_text="Halo kak ini pesanan sedang kami proses ya",
        from_me=True
    )
    mock_conn_data = {
        "tenant_id": "boon",
        "tenant_slug": "boon",
        "instance_name": "boontrack-shop",
        "mode": "DEDICATED"
    }
    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance", return_value=mock_conn_data), \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock):
        res = await process_evolution_webhook_payload(payload_chat, tenant_slug="boon")
        assert res.get("status") == "dropped"
        assert res.get("reason") == "admin_bypass"

@pytest.mark.asyncio
async def test_2c_buyer_escalation_triggers_transition_and_halts_ai():
    payload_buyer = make_evo_payload(
        remote_jid="628123456789@s.whatsapp.net",
        incoming_text="mau cs dong min",
        from_me=False
    )
    mock_conn_data = {
        "tenant_id": "boon",
        "tenant_slug": "boon",
        "instance_name": "boontrack-shop",
        "mode": "DEDICATED",
        "phone_number": "6281215567168"
    }

    transition_msg = (
        "Siap kak, saya langsung hubungkan obrolan ini ke tim Admin / CS manusia kami ya. "
        "Mohon ditunggu sebentar, tim kami akan segera membalas chat Kakak di sini secara langsung. "
        "Terima kasih banyak atas kesabarannya! 🙏"
    )

    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance", return_value=mock_conn_data), \
         patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as mock_ctx, \
         patch("app.routes.whatsapp_gateway_routes.check_and_handle_session_handover_and_toggle", new_callable=AsyncMock) as mock_toggle, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_ctx.return_value = MagicMock(slug="boon", tenant_slug="boon", metadata={})
        mock_toggle.return_value = {
            "handled": True,
            "status": "success",
            "bot_paused": True,
            "action": "HANDOVER_TO_HUMAN",
            "is_paused": True,
            "paused_by": "user_request_human",
            "reply_text": transition_msg,
        }
        mock_post.return_value = MagicMock(status_code=200)

        res = await process_evolution_webhook_payload(payload_buyer, tenant_slug="boon")
        assert res.get("status") == "success"
        assert res.get("action") == "buyer_escalation_handover"
        assert res.get("bot_paused") is True
        assert res.get("reply_text") == transition_msg
        # Evolution API outbound dispatch was called
        mock_post.assert_awaited()

@pytest.mark.asyncio
async def test_2d_active_pause_gate_mutes_ai():
    payload_buyer = make_evo_payload(
        remote_jid="628123456789@s.whatsapp.net",
        incoming_text="Halo ada barang ready?",
        from_me=False
    )
    mock_conn_data = {
        "tenant_id": "boon",
        "tenant_slug": "boon",
        "instance_name": "boontrack-shop",
        "mode": "DEDICATED",
        "phone_number": "6281215567168"
    }

    with patch("app.routes.whatsapp_gateway_routes.get_connection_by_instance", return_value=mock_conn_data), \
         patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as mock_ctx, \
         patch("app.routes.whatsapp_gateway_routes.check_and_handle_session_handover_and_toggle", new_callable=AsyncMock) as mock_toggle, \
         patch("app.routes.whatsapp_gateway_routes.log_to_supabase_messages", new_callable=AsyncMock), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_ctx.return_value = MagicMock(slug="boon", tenant_slug="boon", metadata={})
        mock_toggle.return_value = {
            "handled": True,
            "status": "success",
            "bot_paused": True,
            "action": "DROP_PAUSED",
            "reply_text": None,
        }

        res = await process_evolution_webhook_payload(payload_buyer, tenant_slug="boon")
        assert res.get("status") == "success"
        assert res.get("action") == "DROP_PAUSED"
        assert res.get("bot_paused") is True
        # Zero outbound dispatched to WhatsApp AI / RAG
        mock_post.assert_not_awaited()

@pytest.mark.asyncio
async def test_contact_isolation_a_vs_b():
    # Verify with a deterministic stateful in-memory table double that pausing contact A
    # does not pause contact B (no external Supabase HTTP calls, no silent skip).
    phone_a = "628999111001"
    phone_b = "628999111002"
    tenant = "test_tenant_iso"

    class _FakeResp:
        def __init__(self, data):
            self.data = data

    class _FakeTableQuery:
        def __init__(self, store: list):
            self._store = store
            self._op = "select"
            self._payload = None
            self._on_conflict = None
            self._eq_filters = []
            self._in_filters = []
            self._maybe_single = False

        def select(self, *_cols):
            self._op = "select"
            return self

        def upsert(self, payload: dict, on_conflict: str = ""):
            self._op = "upsert"
            self._payload = dict(payload)
            self._on_conflict = [c.strip() for c in on_conflict.split(",") if c.strip()]
            return self

        def update(self, payload: dict):
            self._op = "update"
            self._payload = dict(payload)
            return self

        def delete(self):
            self._op = "delete"
            return self

        def eq(self, col: str, val):
            self._eq_filters.append((col, val))
            return self

        def in_(self, col: str, vals):
            self._in_filters.append((col, set(vals)))
            return self

        def or_(self, _expr: str):
            return self

        def maybe_single(self):
            self._maybe_single = True
            return self

        def _matches(self, row: dict) -> bool:
            for col, val in self._eq_filters:
                if row.get(col) != val:
                    return False
            for col, vals in self._in_filters:
                if row.get(col) not in vals:
                    return False
            return True

        def execute(self):
            if self._op == "upsert":
                conflict_cols = self._on_conflict or []
                for idx, existing in enumerate(self._store):
                    if conflict_cols and all(existing.get(c) == self._payload.get(c) for c in conflict_cols):
                        updated = dict(existing)
                        updated.update(self._payload)
                        self._store[idx] = updated
                        return _FakeResp([updated])
                row = dict(self._payload)
                self._store.append(row)
                return _FakeResp([row])
            if self._op == "update":
                updated_rows = []
                for row in self._store:
                    if self._matches(row):
                        row.update(self._payload)
                        updated_rows.append(row)
                return _FakeResp(updated_rows)
            if self._op == "delete":
                kept = [r for r in self._store if not self._matches(r)]
                removed = [r for r in self._store if self._matches(r)]
                self._store[:] = kept
                return _FakeResp(removed)
            matched = [dict(r) for r in self._store if self._matches(r)]
            if self._maybe_single:
                return _FakeResp(matched[0] if matched else None)
            return _FakeResp(matched)

    class _InMemorySupabaseDouble:
        def __init__(self):
            self._tables = {"conversation_sessions": [], "conversations": []}

        def table(self, name: str):
            return _FakeTableQuery(self._tables.setdefault(name, []))

    fake_sb = _InMemorySupabaseDouble()

    with (
        patch("app.routes.whatsapp_gateway_routes.get_supabase", return_value=fake_sb),
        patch("app.services.whatsapp_service.get_supabase", return_value=fake_sb),
    ):
        try:
            # Pause contact A
            await check_and_handle_session_handover_and_toggle(
                tenant_slug=tenant,
                sender_phone=phone_a,
                incoming_text="pause",
                sender_name="Admin"
            )

            # Check contact A state -> should be paused
            res_a = await check_and_handle_session_handover_and_toggle(
                tenant_slug=tenant,
                sender_phone=phone_a,
                incoming_text="Halo",
                sender_name="User A"
            )
            assert res_a is not None
            assert res_a.get("bot_paused") is True
            assert res_a.get("action") == "DROP_PAUSED"

            # Check contact B state -> should NOT be paused (returns None, normal flow continues)
            res_b = await check_and_handle_session_handover_and_toggle(
                tenant_slug=tenant,
                sender_phone=phone_b,
                incoming_text="Halo",
                sender_name="User B"
            )
            assert res_b is None

        finally:
            fake_sb.table("conversation_sessions").delete().eq("tenant_id", tenant).in_("user_identifier", [phone_a, phone_b]).execute()
