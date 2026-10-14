import sys
import os

project_root = r"c:\boontrack-core"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db_connection
from app.services.whatsapp_service import get_supabase
from app.services.ctwa_state_engine import ctwa_state_engine
from app.services.rotary_routing_service import rotary_routing_service
from app.services.cv_state_engine import GLOBAL_USER_STATES
from app.services.whatsapp_service import (
    user_tenant_sessions,
    user_session_states,
    user_cart_sessions,
    normalize_phone_number
)

TESTER_NUMBERS = [
    "081237450222",
    "6281237450222",
    "081977655099",
    "6281977655099",
]

def reset_testers():
    print("--- 1. RESETTING TESTER NUMBERS STATE ---")
    
    # 1. Clear in-memory state
    for num in TESTER_NUMBERS:
        clean = normalize_phone_number(num) or num
        ctwa_state_engine.reset_session(num)
        ctwa_state_engine.reset_session(clean)
        GLOBAL_USER_STATES.pop(num, None)
        GLOBAL_USER_STATES.pop(clean, None)
        user_tenant_sessions.pop(num, None)
        user_tenant_sessions.pop(clean, None)
        user_session_states.pop(num, None)
        user_session_states.pop(clean, None)
        user_cart_sessions.pop(num, None)
        print(f"Cleared in-memory state for {num} / {clean}")

    # 2. Update PostgreSQL database
    conn = get_db_connection()
    with conn.cursor() as cur:
        # A. Update orders: Cancel all PENDING orders for tester numbers
        for num in TESTER_NUMBERS:
            cur.execute(
                """
                UPDATE orders 
                SET status = 'CANCELLED', updated_at = NOW() 
                WHERE customer_phone = %s AND status = 'PENDING'
                """,
                (num,)
            )
            print(f"Postgres orders cancelled for {num}: {cur.rowcount} rows")

        # B. Clean conversation_sessions
        for num in TESTER_NUMBERS:
            cur.execute(
                """
                DELETE FROM conversation_sessions 
                WHERE user_identifier = %s OR session_id LIKE %s
                """,
                (num, f"%{num}%")
            )
            print(f"Postgres conversation_sessions deleted for {num}: {cur.rowcount} rows")

        # C. Clean demo_user_sessions
        for num in TESTER_NUMBERS:
            cur.execute(
                """
                DELETE FROM demo_user_sessions 
                WHERE phone = %s
                """,
                (num,)
            )
            print(f"Postgres demo_user_sessions deleted for {num}: {cur.rowcount} rows")

        # D. Reset conversations table
        for num in TESTER_NUMBERS:
            try:
                cur.execute(
                    """
                    DELETE FROM conversations 
                    WHERE phone_number = %s OR customer_phone = %s
                    """,
                    (num, num)
                )
                print(f"Postgres conversations deleted for {num}: {cur.rowcount} rows")
            except Exception as e:
                print(f"Postgres conversations delete note: {e}")

        # E. Ensure whatsapp_connections has onlineboost WABA configuration set!
        cur.execute(
            """
            UPDATE whatsapp_connections 
            SET status = 'active', channel_type = 'WABA', provider = 'OFFICIAL_META',
                phone_number_id = '1419090974617162', phone_number = '+6288226098088', is_connected = TRUE 
            WHERE tenant_slug = 'onlineboost'
            """
        )
        print(f"Postgres whatsapp_connections onlineboost updated: {cur.rowcount} rows")

        conn.commit()
    conn.close()

    # 3. Update Supabase
    sb = get_supabase()
    if sb:
        for num in TESTER_NUMBERS:
            try:
                sb.table("orders").update({"status": "CANCELLED"}).eq("customer_phone", num).eq("status", "PENDING").execute()
                print(f"Supabase orders cancelled for {num}")
            except Exception as e:
                print(f"Supabase orders update error: {e}")

            try:
                sb.table("conversation_sessions").delete().eq("user_identifier", num).execute()
                print(f"Supabase conversation_sessions deleted for {num}")
            except Exception as e:
                print(f"Supabase conversation_sessions delete error: {e}")

            try:
                sb.table("conversations").delete().or_(f"phone_number.eq.{num},customer_phone.eq.{num}").execute()
                print(f"Supabase conversations deleted for {num}")
            except Exception as e:
                print(f"Supabase conversations delete error: {e}")

        try:
            sb.table("whatsapp_connections").update({
                "status": "active",
                "channel_type": "WABA",
                "provider": "OFFICIAL_META",
                "phone_number_id": "1419090974617162",
                "phone_number": "+6288226098088",
                "is_connected": True
            }).eq("tenant_slug", "onlineboost").execute()
            print("Supabase whatsapp_connections onlineboost updated to WABA active")
        except Exception as e:
            print(f"Supabase whatsapp_connections update error: {e}")

    print("--- RESET COMPLETED SUCCESSFULLY ---")

if __name__ == "__main__":
    reset_testers()
