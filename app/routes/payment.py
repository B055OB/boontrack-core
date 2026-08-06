from flask import Blueprint, jsonify, request
from utils.extractor import extract_amount

payment_bp = Blueprint("payment", __name__)


@payment_bp.route("/webhook/dana", methods=["POST"])
def dana_webhook():
    data = request.json or {}
    text = data.get("notification_text", "")
    amount = extract_amount(text)

    print(f"\n[NOTIF INCOMING]: {text}")
    print(f"[PARSED AMOUNT]: {amount}\n")

    # Logika verifikasi transaksi & trigger Telegram/Cloudflare di sini...

    return jsonify({"status": "success", "amount_detected": amount}), 200