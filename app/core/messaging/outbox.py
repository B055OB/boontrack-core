# Kerangka logika Outbox untuk Worker dispatcher
async def dispatch_message_with_outbox(db_session, tenant_id: str, recipient: str, message: str, idempotency_key: str):
    """
    Menyimpan pesan ke Outbox table dengan state PENDING.
    Worker terpisah akan membaca tabel ini dan mengirimkannya ke WhatsApp Gateway.
    Jika gateway down, status tetap PENDING dan dicoba ulang tanpa merusak core order.
    """
    # 1. Cek idempotency apakah message dengan idempotency_key sudah pernah diproses / SENT
    # existing = await db_session.query(OutboxMessage).filter_by(idempotency_key=idempotency_key).first()
    # if existing and existing.status == "SENT": return
    
    # 2. Simpan/Update Outbox dengan state PENDING
    pass