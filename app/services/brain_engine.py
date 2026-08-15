import re
from app.models.session import ConversationState
from app.services.goal_detector import RuleBasedGoalDetector
from app.engines.intent_engine import intent_engine, IntentType

class BrainEngine:

    def __init__(self, session_repo, ai_gateway=None):
        self.session_repo = session_repo
        self.ai_gateway = ai_gateway
        self.goal_detector = RuleBasedGoalDetector()

    async def handle_message(
        self,
        user_id: str = None,
        channel: str = "telegram",
        text: str = None,
        is_owner: bool = False,
        user_message: str = None,
        context: dict = None,
    ) -> dict | str:
        # 1. Normalisasi Input (Kompatibel dengan pemanggilan dari main.py maupun caller lama)
        clean_text = (text or user_message or "").strip()
        context = context or {}
        uid = str(user_id or context.get("user_id", "default_user"))
        lower_text = clean_text.lower()

        # 2. Load atau Create Session User
        session = await self.session_repo.get_or_create(uid, channel)

        # 2b. RESET STATE FILTER: Jika user minta batal / balik menu / nanya hal umum berformat pertanyaan
        is_question = any(q in lower_text for q in ["bagaimana", "gimana", "apa", "berapa", "kenapa", "mengapa", "cara", "?"])
        if any(kw in lower_text for kw in ["batal", "cancel", "menu utama", "kembali"]) or (is_question and session.state != ConversationState.START.value):
            session.state = ConversationState.START.value
            await self.session_repo.save(session)
            print(f"[BRAIN] Session state reset to START for user {uid}", flush=True)

        # 3. Deteksi Intent Lewat IntentEngine (Traffic Controller)
        intent_res = await intent_engine.detect_intent(clean_text, is_owner=is_owner)
        intent = intent_res.get("intent")
        print(f"[BRAIN] detected_intent={intent} via {intent_res.get('method')}", flush=True)

        # 4. Jika user sedang di pertengahan Flow pembuatan CV (Dan BUKAN bertanya hal umum)
        if session.state != ConversationState.START.value and not is_question:
            return await self._process_state_flow(session, clean_text)

        # 5. PRE-ROUTING: PERTANYAAN UMUM / DIPLOMATIK -> LANGSUNG KE AI GATEWAY!
        # Jangan biarkan Goal Detector membajak pertanyaan umum yang ada kata "kerja"
        if is_question or intent in [IntentType.CASUAL, IntentType.GENERAL_QUERY]:
            print("[BRAIN] Direct routing question/casual to AI Gateway", flush=True)
            if self.ai_gateway:
                try:
                    ctx = session.context_json or {}
                    ctx.update(context)
                    ctx["intent"] = intent
                    ctx["user_id"] = uid

                    ai_response = await self.ai_gateway.generate(
                        user_message=clean_text, context=ctx
                    )

                    if ai_response:
                        return ai_response
                except Exception as e:
                    print(f"[BRAIN][AI ERROR] {type(e).__name__}: {e}", flush=True)

        # 6. Routing Berdasarkan Intent Khusus / Goal
        detected_res = await self.goal_detector.detect(clean_text)
        detected_goal = (
            detected_res.get("goal")
            if isinstance(detected_res, dict)
            else detected_res
        )
        print(f"[BRAIN] detected_goal={detected_goal}", flush=True)

        # Flow Buat CV (HANYA Trigger jika Intent BENAR-BENAR CV_CREATION atau perintah spesifik)
        if intent == IntentType.CV_CREATION or detected_goal == "CREATE_CV":
            session.state = ConversationState.CREATE_CV_NAME.value
            session.goal = "CREATE_CV"
            await self.session_repo.save(session)

            return (
                "Halo! Saya bantu buatkan CV ATS-friendly sampai beres ya. 🚀\n"
                "Kita mulai dari yang paling mudah, tidak usah terburu-buru.\n\n"
                "📍 *Progress: [1/6] Data Diri*\n"
                "Siapa **nama lengkap** yang ingin kamu tampilkan di CV?"
            )

        # Flow Career Page
        elif intent == IntentType.CAREER_PAGE:
            return (
                "🌟 <b>Punya Career Page Profesional Sendiri!</b>\n\n"
                "Tampilkan ringkasan CV, portofolio, dan keahlianmu dalam satu halaman web siap bagi ke recruiter.\n\n"
                "Silakan pilih menu Career Page di Menu Utama."
            )

        # Flow Support / Venting
        elif detected_goal == "CAREER_SUPPORT":
            session.state = ConversationState.VENT_MODE.value
            await self.session_repo.save(session)
            return (
                "Wajar banget merasa capek dan bingung dalam proses cari kerja. "
                "Kamu tidak sendirian kok di titik ini. ☕\n\n"
                "Mau cerita dulu apa yang paling bikin ganjel saat ini? Atau mau "
                "langsung kita bedah ulang strategi CV/interview kamu?"
            )

        # 7. Fallback General Query -> Teruskan ke AI Gateway jika belum ter-handle
        print("[BRAIN] Routing fallback to AI Gateway", flush=True)
        if self.ai_gateway:
            try:
                ctx = session.context_json or {}
                ctx.update(context)
                ctx["user_id"] = uid
                ai_response = await self.ai_gateway.generate(
                    user_message=clean_text, context=ctx
                )
                if ai_response:
                    return ai_response
            except Exception as e:
                print(f"[BRAIN][AI ERROR] {type(e).__name__}: {e}", flush=True)

        # Fallback Statis Jika AI Gateway Mati Total
        return (
            "Saya siap bantu kamu sampai dapat kerja! Pilih langkah pertama kamu:\n\n"
            "1️⃣ Ketik **'Bikin CV'** untuk buat CV ATS-friendly\n"
            "2️⃣ Ketik **'Latihan Interview'** untuk simulasi wawancara\n"
            "3️⃣ Ketik **'Curhat'** kalau lagi merasa mentok/stres cari kerja"
        )

    async def _process_state_flow(self, session, text: str) -> str:
        state = session.state
        ctx = session.context_json or {}

        # FLOW STEP 1: NAMA -> TANYA KONTAK (Progress 2/6)
        if state == ConversationState.CREATE_CV_NAME.value:
            ctx["name"] = text
            session.context_json = ctx
            session.state = ConversationState.CREATE_CV_CONTACT.value
            await self.session_repo.save(session)
            return (
                f"Sip, salam kenal **{text}**! ✨\n\n"
                "📍 *Progress: [2/6] Kontak*\n"
                "Tolong tulis **nomor HP (WhatsApp) & email** aktif kamu."
            )

        # FLOW STEP 2: KONTAK -> TANYA TARGET POSISI (Progress 3/6)
        elif state == ConversationState.CREATE_CV_CONTACT.value:
            ctx["contact"] = text
            session.context_json = ctx
            session.state = ConversationState.CREATE_CV_TARGET_ROLE.value
            await self.session_repo.save(session)
            return (
                "Sip, kontak sudah tersimpan! 📝\n\n"
                "📍 *Progress: [3/6] Target Posisi*\n"
                "**Posisi/pekerjaan apa** yang sedang kamu incar? (Contoh: *Admin Sales, Digital Marketer, Software Engineer*)"
            )

        return "Terima kasih infonya. Mari kita lanjutkan prosesnya!"