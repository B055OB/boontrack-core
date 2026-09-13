import asyncio
import hashlib
import json
import httpx

merchant_code = "DS35323"
api_key = "c5f58318113beff62d4944e7e7de44e5"
order_id = "ORDER-BOON-777"
amount = 10000

# Rumus MD5 resmi v2/inquiry:
# MD5(merchantcode + merchantOrderId + paymentAmount + apiKey)
raw_signature = f"{merchant_code}{order_id}{amount}{api_key}"
signature = hashlib.md5(raw_signature.encode("utf-8")).hexdigest()

payload = {
    "merchantcode": merchant_code,
    "paymentAmount": amount,
    "paymentMethod": "NQ",  # Nobu QRIS
    "merchantOrderId": order_id,
    "productDetails": "BoonTrack Service",
    "additionalParam": "",
    "merchantUserInfo": "",
    "customerVaName": "Aldi Rinaldiawan",
    "email": "support@boontrack.com",
    "phoneNumber": "081234567890",
    "itemDetails": [
        {
            "name": "BoonTrack Service",
            "price": amount,
            "quantity": 1
        }
    ],
    "callbackUrl": "https://api.boontrack.com/api/v1/payments/duitku/callback",
    "returnUrl": "https://shop.boontrack.com",
    "signature": signature,
    "expiryPeriod": 15
}

url = "https://sandbox.duitku.com/webapi/api/merchant/v2/inquiry"

async def test():
    print("Testing dengan Kode Merchant Benar:", merchant_code)
    print("Raw string:", raw_signature)
    print("Signature :", signature)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print("\nStatus HTTP:", resp.status_code)
        try:
            print("Response JSON:\n", json.dumps(resp.json(), indent=2))
        except Exception:
            print("Response Body:\n", resp.text)

if __name__ == "__main__":
    asyncio.run(test())