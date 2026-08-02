import json
import os
import sys
from google.oauth2 import service_account
from googleapiclient.discovery import build

# CONFIGURATION
CREDENTIALS_PATH = "credentials.json"
FOLDER_ID = "1uIBTCa4SMCPXgSfZoUJpnJ6hn1yr3rwI"  # ID Folder Drive Kamu
OUTPUT_JSON_PATH = "data/assets.json"


def auto_generate_assets():
    print("🚀 Memulai proses Auto-Generate Knowledge Catalog...")

    # 1. Cek keberadaan file credentials.json
    if not os.path.exists(CREDENTIALS_PATH):
        print(
            f"❌ ERROR: File '{CREDENTIALS_PATH}' tidak ditemukan di folder root project!"
        )
        print(
            "   Pastikan kamu sudah menaruh file kunci Service Account Google Cloud dengan nama 'credentials.json'."
        )
        sys.exit(1)

    try:
        # 2. Inisialisasi Google Drive API Client
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        service = build("drive", "v3", credentials=creds)

        print(
            f"🔍 Memindai seluruh file di dalam folder Drive ID: {FOLDER_ID}..."
        )

        # 3. Query pencarian seluruh file di dalam folder
        query = f"'{FOLDER_ID}' in parents and trashed = false"
        results = (
            service.files()
            .list(
                q=query,
                pageSize=200,
                fields="files(id, name, mimeType, webViewLink)",
            )
            .execute()
        )

        items = results.get("files", [])

        if not items:
            print(
                "⚠️ WARN: Tidak ada file yang ditemukan di dalam folder Google Drive tersebut."
            )
            print(
                "   Pastikan kamu sudah meletakkan file materi dan folder tersebut sudah di-SHARE ke email Service Account sebagai Viewer."
            )
            return

        print(f"📦 Ditemukan {len(items)} file! Menyusun Knowledge Catalog...")

        assets = []
        counter = 101

        # 4. Parsing otomatis tiap file menjadi metadata terstruktur
        for item in items:
            file_id = item["id"]
            file_name = item["name"]
            name_lower = file_name.lower()

            industry = "general"
            role = "general"
            intent = "DOWNLOAD_FILE"
            goal = "GET_JOB"

            # Logika Otomatis Pemetaan Metadata dari Nama File
            if "cv" in name_lower or "resume" in name_lower:
                intent = "DOWNLOAD_CV_ATS"
                if "pharma" in name_lower or "farmasi" in name_lower:
                    industry = "pharmaceutical"
                    role = "marketing"
                elif "tech" in name_lower or "it" in name_lower:
                    industry = "technology"
                    role = "software_engineering"
                elif "kreatif" in name_lower or "design" in name_lower:
                    industry = "creative"
                    role = "graphic_design"
                elif "finance" in name_lower or "bank" in name_lower:
                    industry = "banking_and_bumn"
                    role = "admin_and_finance"

            elif "interview" in name_lower or "wawancara" in name_lower:
                intent = "DOWNLOAD_INTERVIEW_GUIDE"
                goal = "PREPARE_INTERVIEW"
                if "pharma" in name_lower or "farmasi" in name_lower:
                    industry = "pharmaceutical"

            elif "psikotes" in name_lower or "bumn" in name_lower:
                intent = "DOWNLOAD_PSIKOTES"
                goal = "PREPARE_TEST"
                industry = "banking_and_bumn"

            elif "live" in name_lower or "host" in name_lower:
                intent = "DOWNLOAD_HOST_SCRIPT"
                goal = "INCREASE_SALES"
                industry = "e_commerce"
                role = "sales_and_live_host"

            elif "cover" in name_lower or "lamaran" in name_lower:
                intent = "DOWNLOAD_COVER_LETTER"
                goal = "APPLY_JOB"

            elif "tracker" in name_lower or "excel" in name_lower:
                intent = "DOWNLOAD_JOB_TRACKER"
                goal = "TRACK_APPLICATIONS"

            # Menyusun format JSON sesuai CTO Decision #102
            asset_obj = {
                "asset_uuid": f"AST-000{counter}",
                "title": file_name,
                "industry": industry,
                "role": role,
                "level": "fresh_graduate",
                "goal": goal,
                "intent": intent,
                "delivery_provider": "google_drive",
                "delivery_reference": file_id,
                "status": "READY",
            }

            assets.append(asset_obj)
            counter += 1

        # 5. Simpan otomatis ke data/assets.json
        if os.path.dirname(OUTPUT_JSON_PATH):
            os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)

        with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(assets, f, indent=2, ensure_ascii=False)

        print("-" * 50)
        print(f"🎉 SUCCESS 100%!")
        print(
            f"✅ File '{OUTPUT_JSON_PATH}' berhasil dibuat otomatis dengan {len(assets)} data aset!"
        )
        print(
            "   Kamu tidak perlu lagi isi ID manual satu per satu. Semuanya sudah beres!"
        )
        print("-" * 50)

    except Exception as e:
        print(f"❌ ERROR saat menghubungkan ke Google Drive API: {str(e)}")


if __name__ == "__main__":
    auto_generate_assets()
