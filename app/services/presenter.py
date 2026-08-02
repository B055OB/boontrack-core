import json

def format_solution_response(user_message: str, asset: dict) -> str:
    """
    Membentuk pesan bot yang natural, conversational, dan relevan dengan konteks pertanyaan user.
    """
    user_msg_lower = user_message.lower()
    title = asset.get("title", "Aset Digital")
    description = asset.get("description", "")
    outcomes = asset.get("outcomes", [])
    
    if any(kw in user_msg_lower for kw in ["cv", "resume"]):
        opening = "Siap! Buat urusan CV, ini aku ada template ATS-friendly yang udah teruji dan rapi bener:"
    elif any(kw in user_msg_lower for kw in ["gaji", "nego", "offering"]):
        opening = "Pertanyaan krusial nih! Soal gaji emang perlu strategi biar gak canggung. Ini panduan taktisnya:"
    elif any(kw in user_msg_lower for kw in ["interview", "wawancara", "hrd"]):
        opening = "Menghadapi interview emang bikin grogi, tapi tenang! Ini bocoran pertanyaan & kunci jawabannya:"
    else:
        opening = "Nih, aku ketemu solusi yang pas banget buat bantu kamu:"

    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []
            
    outcomes_text = ""
    if outcomes:
        outcomes_text = "\n" + "\n".join([f"✓ {item}" for item in outcomes])

    message = (
        f"{opening}\n\n"
        f"📌 **{title}**\n"
        f"{description}\n"
        f"{outcomes_text}"
    )
    
    return message
