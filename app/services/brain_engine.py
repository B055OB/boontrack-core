from app.models.session import ConversationState
from app.services.goal_detector import RuleBasedGoalDetector
from app.engines.intent_engine import intent_engine, IntentType

class BrainEngine:

    def __init__(self, session_repo, ai_gateway=None):
        self.session_repo = session_repo
        self.ai_gateway = ai_gateway
        self.goal_detector = RuleBasedGoalDetector()

    async def handle_message(
        self, user_id: str, channel: str, text: str, is_owner: bool = False
    ) -> dict:
        # 1. Load atau Create Session User
        session = await self.session_repo.get_or_create(user_id, channel)
        clean_text = text.strip()

        # 2. Deteksi Intent Lewat IntentEngine (Traffic Controller)
        intent_res = await intent_engine.detect_intent(clean_text, is_owner=is_owner)
        intent = intent_res.get("intent")
        print(f"[BRAIN] detected_intent={intent} via {intent_res.get('method')}")

        # 3. Jika user sedang di pertengahan Flow (bukan START), teruskan sesuai State
        if session.state != ConversationState.START.value:
            return await self._process_state_flow(session, clean_text)

        # 4. Routing Berdasarkan Intent / Goal
        detected_res = await self.goal_detector.detect(clean_text)
        detected_goal = (
            detected_res.get("goal")
            if isinstance(detected_res, dict)
            else detected_res
        )
        print(f"[BRAIN] detected_goal={detected_goal}")

        # Flow Buat CV (Trigger dari Intent CV_CREATION atau Goal)
        if intent == IntentType.CV_CREATION or detected_goal in ["GET_JOB", "CREATE_CV"]:
            session.state = ConversationState.CREATE_CV_NAME.value
            session.goal = "CREATE_CV"
            await self.session_repo.save(session)

            return {
                "text": (
                    "Halo! Saya bantu buatkan CV ATS-friendly sampai beres ya. 🚀\n"
                    "Kita mulai dari yang paling mudah, tidak usah terburu-buru.\n\n"
                    "📍 *Progress: [1/6] Data Diri*\n"
                    "Siapa **nama lengkap** yang ingin kamu tampilkan di CV?"
                )
            }

        # Flow Career Page (Trigger dari Intent CAREER_PAGE dengan Tombol Interaktif)
        elif intent == IntentType.CAREER_PAGE:
            return {
                "text": (
                    "🌟 <b>Punya Career Page Profesional Sendiri!</b>\n\n"
                    "Tampilkan ringkasan CV, portofolio, dan keahlianmu dalam satu halaman web siap bagi ke recruiter.\n\n"
                    "Silakan klik tombol di bawah untuk melanjutkan:"
                ),
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "🚀 Buat Career Page Saya (Rp10.000)", "callback_data": "cp_build_now"}],
                        [{"text": "🏠 Kembali ke Menu Utama", "callback_data": "home_back_main"}]
                    ]
                },
                "parse_mode": "HTML"
            }

        # Flow Support / Venting
        elif detected_goal == "CAREER_SUPPORT":
            session.state = ConversationState.VENT_MODE.value
            await self.session_repo.save(session)
            return {
                "text": (
                    "Wajar banget merasa capek dan bingung dalam proses cari kerja. "
                    "Kamu tidak sendirian kok di titik ini. ☕\n\n"
                    "Mau cerita dulu apa yang paling bikin ganjel saat ini? Atau mau "
                    "langsung kita bedah ulang strategi CV/interview kamu?"
                )
            }

        # 5. Intent CASUAL -> Respon Cepat atau Prompt Ringkas
        elif intent == IntentType.CASUAL:
            # Tetap teruskan ke AI Gateway dengan konteks intent casual (hemat token)
            pass

        # 6. General Query / Career Query -> Teruskan ke AI Gateway
        print("[BRAIN] routing to AI gateway")

        if self.ai_gateway:
            try:
                # Sisipkan metadata intent ke konteks AI
                context = session.context_json or {}
                context["intent"] = intent

                ai_response = await self.ai_gateway.generate(
                    user_message=clean_text, context=context
                )

                print(f"[BRAIN] AI gateway response received: {bool(ai_response)}")

                if ai_response:
                    if isinstance(ai_response, str):
                        return {"text": ai_response}
                    return ai_response

            except Exception as e:
                print(f"[BRAIN][AI ERROR] {type(e).__name__}: {e}")

        # Fallback Statis
        return {
            "text": (
                "Saya siap bantu kamu sampai dapat kerja! Pilih langkah pertama kamu:\n\n"
                "1️⃣ Ketik **'Bikin CV'** untuk buat CV ATS-friendly\n"
                "2️⃣ Ketik **'Latihan Interview'** untuk simulasi wawancara\n"
                "3️⃣ Ketik **'Curhat'** kalau lagi merasa mentok/stres cari kerja"
            )
        }

    async def _process_state_flow(self, session, text: str) -> dict:
        state = session.state
        ctx = session.context_json or {}

        # FLOW STEP 1: NAMA -> TANYA KONTAK (Progress 2/6)
        if state == ConversationState.CREATE_CV_NAME.value:
            ctx["name"] = text
            session.context_json = ctx
            session.state = ConversationState.CREATE_CV_CONTACT.value
            await self.session_repo.save(session)
            return {
                "text": (
                    f"Sip, salam kenal **{text}**! ✨\n\n"
                    "📍 *Progress: [2/6] Kontak*\n"
                    "Tolong tulis **nomor HP (WhatsApp) & email** aktif kamu."
                )
            }

        # FLOW STEP 2: KONTAK -> TANYA TARGET POSISI (Progress 3/6)
        elif state == ConversationState.CREATE_CV_CONTACT.value:
            ctx["contact"] = text
            session.context_json = ctx
            session.state = ConversationState.CREATE_CV_TARGET_ROLE.value
            await self.session_repo.save(session)
            return {
                "text": (
                    "Sip, kontak sudah tersimpan! 📝\n\n"
                    "📍 *Progress: [3/6] Target Posisi*\n"
                    "**Posisi/pekerjaan apa** yang sedang kamu incar? (Contoh: *Admin Sales, Digital Marketer, Software Engineer*)"
                )
            }

        return {
            "text": "Terima kasih infonya. Mari kita lanjutkan prosesnya!"
        }