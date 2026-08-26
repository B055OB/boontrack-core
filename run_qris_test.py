import io
import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import StreamingResponse, HTMLResponse

from app.utils.qris_generator import generate_dynamic_qris_payload, generate_qris_image_bytes

# 1. Load environment variables dari .env
load_dotenv()

# 2. Inisialisasi FastAPI Application
app = FastAPI(
    title="BoonTrack Dynamic QRIS Test Server",
    description="Standalone testing runner untuk modul Native Dynamic QRIS Generator",
    version="1.0.0"
)


@app.get("/", response_class=HTMLResponse)
async def root_home():
    """Halaman petunjuk testing langsung di browser."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>BoonTrack Dynamic QRIS Tester</title>
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; text-align: center; padding: 40px; background: #f8fafc; color: #1e293b; }
            .card { max-width: 500px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }
            h1 { font-size: 24px; color: #0f172a; margin-bottom: 8px; }
            p { color: #64748b; margin-bottom: 24px; }
            .links a { display: inline-block; margin: 6px; padding: 10px 16px; background: #2563eb; color: white; text-decoration: none; border-radius: 8px; font-weight: 500; }
            .links a:hover { background: #1d4ed8; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🚀 BoonTrack Dynamic QRIS Tester</h1>
            <p>Pilih nominal untuk melihat & scan QRIS Dinamis langsung:</p>
            <div class="links">
                <a href="/api/v1/payment/qris/test/4900" target="_blank">Test Rp4.900</a>
                <a href="/api/v1/payment/qris/test/9900" target="_blank">Test Rp9.900</a>
                <a href="/api/v1/payment/qris/test/19000" target="_blank">Test Rp19.000</a>
                <a href="/api/v1/payment/qris/test/25000" target="_blank">Test Rp25.000</a>
                <a href="/api/v1/payment/qris/test/39000" target="_blank">Test Rp39.000</a>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/api/v1/payment/qris/test/{amount}", summary="Generate Dynamic QRIS PNG")
async def test_dynamic_qris_endpoint(amount: int = Path(..., description="Nominal transaksi dalam Rupiah")):
    """Merender dan mengembalikan gambar Dynamic QRIS (PNG) secara langsung sesuai nominal amount."""
    static_qris = os.getenv("BOONTRACK_STATIC_QRIS", "").strip()
    if not static_qris:
        raise HTTPException(
            status_code=500,
            detail="Variabel BOONTRACK_STATIC_QRIS belum terdefinisi di file .env"
        )
    
    try:
        # Generate dynamic payload string
        dynamic_payload = generate_dynamic_qris_payload(static_qris, amount)
        
        # Render PNG image bytes
        img_bytes = generate_qris_image_bytes(dynamic_payload)
        
        return StreamingResponse(
            io.BytesIO(img_bytes),
            media_type="image/png",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Gagal generate dynamic QRIS: {str(err)}")


# 4. Standalone Runner via Uvicorn
if __name__ == "__main__":
    print("\n" + "="*50)
    print("[STARTING] BoonTrack Dynamic QRIS Test Server")
    print("URL         : http://127.0.0.1:8000")
    print("Direct Test : http://127.0.0.1:8000/api/v1/payment/qris/test/25000")
    print("="*50 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
