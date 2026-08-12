from app.models.session import ConversationState
from app.services.goal_detector import GeminiGoalDetector, Goal


class BrainEngine:

    def __init__(self, session_repo, ai_gateway=None):
        self.session_repo = session_repo
        self.ai_gateway = ai_gateway
        # Menggunakan GeminiGoalDetector sesuai class yang di-import
        self.goal_detector = GeminiGoalDetector()

    async def handle_message(
        self, user_id: str, channel: str, text: str
    ) -> dict:
        # 1. Load atau Create Session User
        session = await self.session_repo.get_or_create(user_id, channel)
        clean_text = text.strip()

        # 2. Jika user sedang di pertengahan Flow (bukan START), teruskan sesuai State
        if session.state != ConversationState.START.value:
            return await self._process_state_flow(session, clean_text)

        # 3. Deteksi Goal/Intent Baru
        detected_res = await self.goal_detector.detect(clean_text)
        detected_goal = detected_res.get("goal") if isinstance(detected_res, dict) else detected_res
        print(f"[BRAIN] detected_goal={detected_goal}")

        if detected_goal == Goal.CREATE_CV or detected_goal == "GET_JOB":
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

        # 4. Goal None / General Conversation -> Teruskan ke AI Gateway
        print("[BRAIN] routing to AI gateway for general query")

        if self.ai_gateway:
            try:
                ai_response = await self.ai_gateway.generate(
                    user_message=clean_text, context=session.context_json or {}
                )

                print(f"[BRAIN] AI gateway response received: {bool(ai_response)}")

                if ai_response:
                    if isinstance(ai_response, str):
                        return {"text": ai_response}
                    return ai_response

            except Exception as e:
                print(f"[BRAIN][AI ERROR] {type(e).__name__}: {e}")

        # Fallback Statis (Jika AI Gateway gagal / bernilai None)
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

        # Fallback jika state belum terdefinisi di state flow
        return {
            "text": "Terima kasih infonya. Mari kita lanjutkan prosesnya!"
        }