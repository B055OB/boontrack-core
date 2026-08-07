import os
import json
import psycopg2
from psycopg2.extras import Json

# 1. DDL SQL Buat Tabel Assets
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS assets (
    asset_uuid VARCHAR(255) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    estimated_time_minutes INT DEFAULT 10,
    outcomes JSONB DEFAULT '[]'::jsonb,
    delivery_url TEXT NOT NULL,
    keywords JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

# 2. Complete 16 Initial Digital Assets
INITIAL_ASSETS = [
  {
    "asset_uuid": "ast_career_001",
    "title": "Panduan & Spreadsheet Job Search Tracker",
    "description": "Spreadsheet Google Sheets interaktif untuk melacak status lamaran kerja, jadwal follow-up HRD, dan dashboard progress interview.",
    "category": "CAREER_MANAGEMENT",
    "estimated_time_minutes": 10,
    "outcomes": [
      "Tracker Lamaran Kerja terorganisir",
      "Jadwal & Template Follow-up HRD",
      "Dashboard Progress Interview"
    ],
    "delivery_url": "https://docs.google.com/spreadsheets/d/1yK3C4cKqG1l3y63EaZ42A6T7_dZJkKq_Zz7l_1s2k00/edit?usp=sharing",
    "keywords": ["cari kerja", "job tracker", "spreadsheet lamaran", "baru lulus", "fresh graduate"]
  },
  {
    "asset_uuid": "ast_career_002",
    "title": "Template CV ATS Friendly & Modern (Word & Canva)",
    "description": "Kumpulan template Curriculum Vitae yang lolos pemindaian sistem ATS (Applicant Tracking System) perusahaan besar.",
    "category": "RESUME_BUILDING",
    "estimated_time_minutes": 15,
    "outcomes": [
      "CV berstandar ATS lolos seleksi awal",
      "Format penulisan pengalaman & skill yang terstruktur",
      "Mudah diedit di Microsoft Word atau Canva"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_ats_cv_template/edit?usp=sharing",
    "keywords": ["bikin cv", "cv ats", "template cv", "resume", "lamaran kerja"]
  },
  {
    "asset_uuid": "ast_career_003",
    "title": "Script & Template Chat Follow-Up HRD via WA & Email",
    "description": "Kumpulan kalimat ramah dan profesional untuk menanyakan status wawancara atau lamaran kerja tanpa terkesan memaksa.",
    "category": "COMMUNICATION",
    "estimated_time_minutes": 5,
    "outcomes": [
      "Draft pesan follow-up siap pakai",
      "Gaya bahasa sopan & profesional",
      "Meningkatkan respon balik dari perekrut/HRD"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_wa_hrd_script/edit?usp=sharing",
    "keywords": ["follow up hrd", "chat hrd", "email lamaran", "tanya hasil interview", "pesan hrd"]
  },
  {
    "asset_uuid": "ast_career_004",
    "title": "Panduan & Simulator Pertanyaan Interview HRD & User",
    "description": "Daftar 30+ pertanyaan interview paling umum beserta contoh jawaban metode STAR (Situation, Task, Action, Result) untuk mengatasi grogi.",
    "category": "INTERVIEW_PREP",
    "estimated_time_minutes": 20,
    "outcomes": [
      "Kunci jawaban pertanyaan jebakan HRD",
      "Formula metode STAR untuk cerita pengalaman",
      "Persiapan mental & trik mengatasi grogi saat wawancara"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_interview_kit/edit?usp=sharing",
    "keywords": ["interview", "wawancara kerja", "tanya hrd", "grogi interview", "metode star", "takut interview"]
  },
  {
    "asset_uuid": "ast_career_005",
    "title": "Script & Panduan Negosiasi Gaji (Salary Negotiation Playbook)",
    "description": "Panduan taktis & contoh kalimat untuk menawar gaji saat penawaran kerja (offering letter) sesuai riset pasar industri.",
    "category": "CAREER_MANAGEMENT",
    "estimated_time_minutes": 10,
    "outcomes": [
      "Cara sopan menolak tawaran gaji terlalu rendah",
      "Script negosiasi gaji via Email & Telepon",
      "Checklist komponen benefit selain gaji pokok"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_salary_nego/edit?usp=sharing",
    "keywords": ["nego gaji", "offering letter", "negosiasi gaji", "tawaran kerja", "gaji minim"]
  },
  {
    "asset_uuid": "ast_career_006",
    "title": "LinkedIn Profile Optimization Checklist & Headline Templates",
    "description": "Panduan langkah demi langkah mengubah profil LinkedIn menjadi magnet bagi para recruiter dan Headhunter.",
    "category": "PROFILE_BUILDING",
    "estimated_time_minutes": 15,
    "outcomes": [
      "10+ Contoh Template Headline LinkedIn yang Menarik",
      "Cara menulis About/Summary section yang menjual",
      "Trik agar profil muncul di pencarian Recruiter"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_linkedin_opt/edit?usp=sharing",
    "keywords": ["linkedin", "profil linkedin", "dilirik hrd", "headhunter", "branding diri"]
  },
  {
    "asset_uuid": "ast_career_007",
    "title": "Template Surat Lamaran Kerja (Cover Letter) Bahasa Indonesia & Inggris",
    "description": "Template Cover Letter profesional yang langsung menarik perhatian recruiter dalam 5 detik pertama pembacaan.",
    "category": "RESUME_BUILDING",
    "estimated_time_minutes": 10,
    "outcomes": [
      "Cover Letter singkat, padat, dan berdampak tinggi",
      "Versi Bahasa Indonesia & Bahasa Inggris",
      "Siap salin untuk body email lamaran kerja"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_cover_letter/edit?usp=sharing",
    "keywords": ["cover letter", "surat lamaran", "body email", "lamaran kerja", "bikin cover letter"]
  },
  {
    "asset_uuid": "ast_career_008",
    "title": "Portfolio Starter Kit (Notion & PDF Template)",
    "description": "Template portofolio interaktif untuk menampilkan hasil karya, proyek perkuliahan, atau pengalaman magang secara visual.",
    "category": "PROFILE_BUILDING",
    "estimated_time_minutes": 25,
    "outcomes": [
      "Template Notion portofolio siap pakai",
      "Struktur penulisan Case Study / Proyek",
      "Panduan menyusun portofolio tanpa pengalaman kerja resmi"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_portfolio_kit/edit?usp=sharing",
    "keywords": ["portofolio", "bikin portofolio", "notion portofolio", "tanpa pengalaman", "hasil karya"]
  },
  {
    "asset_uuid": "ast_career_009",
    "title": "Freelance Rate Calculator & Pitch Proposal Template",
    "description": "Spreadsheet penghitung tarif hourly/project-based freelance serta template pitch proposal untuk menggaet klien pertama.",
    "category": "FREELANCE_REMOTE",
    "estimated_time_minutes": 15,
    "outcomes": [
      "Formula menghitung standar harga jasa freelance",
      "Template surat penawaran (Proposal Pitching)",
      "Draft Invoice & Kontrak Perjanjian Kerjasama sederhana"
    ],
    "delivery_url": "https://docs.google.com/spreadsheets/d/1example_freelance_kit/edit?usp=sharing",
    "keywords": ["freelance", "sambilan", "kerja sampingan", "proposal freelance", "harga jasa", "tarif freelance"]
  },
  {
    "asset_uuid": "ast_career_010",
    "title": "Remote Work Readiness Kit (Upwork & Fiverr Starter)",
    "description": "Panduan penyiapan akun Upwork/Fiverr, trik lolos verifikasi, dan cara membuat Proposal Cover Letter yang disukai klien luar negeri.",
    "category": "FREELANCE_REMOTE",
    "estimated_time_minutes": 20,
    "outcomes": [
      "Checklist profil Upwork/Fiverr yang profesional",
      "Template proposal penawaran bahasa Inggris (Proposal Bid)",
      "Tips pembayaran & penarikan dana dolar ke bank lokal"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_remote_kit/edit?usp=sharing",
    "keywords": ["remote work", "kerja remote", "upwork", "fiverr", "dolar", "kerja luar negeri"]
  },
  {
    "asset_uuid": "ast_career_011",
    "title": "Panduan Menjawab Pertanyaan 'Gaji Yang Diharapkan' saat Interview",
    "description": "Panduan taktis menentukan nominal ekspektasi gaji berdasarkan UMR, pengalaman, dan cara menyampaikan angkanya tanpa blunder.",
    "category": "INTERVIEW_PREP",
    "estimated_time_minutes": 8,
    "outcomes": [
      "Cara menghitung batas bawah dan batas atas ekspektasi gaji",
      "Kalimat jawaban yang fleksibel saat ditanya ekspektasi gaji",
      "Strategi menghadapi HRD yang mematok angka kaku"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_expected_salary/edit?usp=sharing",
    "keywords": ["ekspektasi gaji", "jawaban gaji", "minta gaji berapa", "tanya gaji hrd"]
  },
  {
    "asset_uuid": "ast_career_012",
    "title": "Tech & Software Engineer Coding Interview Cheat Sheet",
    "description": "Rangkuman struktur data, algoritma dasar, dan pola penyelesaian masalah umum untuk wawancara teknis (Technical Coding Test).",
    "category": "TECH_SPECIALIST",
    "estimated_time_minutes": 30,
    "outcomes": [
      "Peta konsep Data Structures & Algorithms paling sering diuji",
      "Framework penyelesaian live coding saat interview",
      "List platform latihan coding gratis terbaik"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_coding_prep/edit?usp=sharing",
    "keywords": ["coding test", "interview tech", "programmer", "software engineer", "tes teknis"]
  },
  {
    "asset_uuid": "ast_career_013",
    "title": "Script Email Resign & Transisi Karir Profesional",
    "description": "Draft surat dan email pengunduran diri (resign) secara sopan, menjaga pilar networking, serta alur penyerahan tugas (handover).",
    "category": "CAREER_MANAGEMENT",
    "estimated_time_minutes": 5,
    "outcomes": [
      "Template Surat Resign One-Month Notice",
      "Panduan komunikasi dengan atasan langsung",
      "Checklist dokumen penyerahan pekerjaan (Handover Form)"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_resign_script/edit?usp=sharing",
    "keywords": ["resign", "surat resign", "pindah kerja", "resign kerja", "pamit kerja"]
  },
  {
    "asset_uuid": "ast_career_014",
    "title": "Checklist Persiapan Magang / Internship untuk Mahasiswa",
    "description": "Panduan melamar posisi magang, konversi SKS, hingga cara mengubah status magang menjadi karyawan tetap (Kartu Merah Putih).",
    "category": "STUDENT_INTERNSHIP",
    "estimated_time_minutes": 12,
    "outcomes": [
      "Daftar platform penyedia magang resmi & terpercaya",
      "Tips performa magang agar diangkat jadi karyawan tetap",
      "Template Laporan Harian / Mingguan Magang"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_internship_prep/edit?usp=sharing",
    "keywords": ["magang", "internship", "mahasiswa", "cari magang", "magang diangkat tetap"]
  },
  {
    "asset_uuid": "ast_career_015",
    "title": "English Business Communication & Email Etiquette Guide",
    "description": "Kumpulan frasa bahasa Inggris profesional untuk komunikasi bisnis harian, mengirim laporan, dan membalas email klien/rekan kerja.",
    "category": "COMMUNICATION",
    "estimated_time_minutes": 10,
    "outcomes": [
      "50+ Frasa Email Bahasa Inggris Siap Pakai",
      "Cara sopan melakukan disagreement / pengingat di tempat kerja",
      "Format email rapat dan penulisan Minutes of Meeting (MoM)"
    ],
    "delivery_url": "https://docs.google.com/document/d/1example_english_biz/edit?usp=sharing",
    "keywords": ["bahasa inggris", "email inggris", "business english", "komunikasi kantor", "kirim email"]
  },
  {
    "asset_uuid": "ast_career_016",
    "title": "Personal Finance Tracker untuk First Jobber & Fresh Graduate",
    "description": "Spreadsheet pengatur keuangan gaji pertama (gaji UMR), pembagian alokasi 50-30-20, serta perencanaan dana darurat.",
    "category": "CAREER_MANAGEMENT",
    "estimated_time_minutes": 15,
    "outcomes": [
      "Spreadsheet alokasi gaji harian & bulanan",
      "Kalkulator Dana Darurat sederhana",
      "Tips mengelola keuangan tanpa stress di awal karir"
    ],
    "delivery_url": "https://docs.google.com/spreadsheets/d/1example_finance_tracker/edit?usp=sharing",
    "keywords": ["kelola gaji", "gaji pertama", "keuangan", "fresh graduate gaji", "pengeluaran bulanan"]
  }
]

def run():
    db_url = os.getenv("DATABASE_URL")
    
    try:
        if db_url:
            conn = psycopg2.connect(db_url)
        else:
            conn = psycopg2.connect(
                host=os.getenv("POSTGRES_HOST", "boontrack_postgres"),
                database=os.getenv("POSTGRES_DB", "boontrack_db"),
                user=os.getenv("POSTGRES_USER", "boontrack"),
                password=os.getenv("POSTGRES_PASSWORD", "boontrack123"),
                port=os.getenv("POSTGRES_PORT", "5432")
            )
            
        cursor = conn.cursor()
        
        # 1. Buat Tabel
        cursor.execute(CREATE_TABLE_SQL)
        print("✅ Tabel 'assets' berhasil dibuat / dipastikan siap.")

        # 2. Upsert Initial Assets
        query = """
        INSERT INTO assets (
            asset_uuid, title, description, category,
            estimated_time_minutes, outcomes, delivery_url, keywords
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (asset_uuid) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            estimated_time_minutes = EXCLUDED.estimated_time_minutes,
            outcomes = EXCLUDED.outcomes,
            delivery_url = EXCLUDED.delivery_url,
            keywords = EXCLUDED.keywords,
            updated_at = NOW();
        """

        for item in INITIAL_ASSETS:
            cursor.execute(query, (
                item["asset_uuid"],
                item["title"],
                item["description"],
                item["category"],
                item["estimated_time_minutes"],
                Json(item["outcomes"]),
                item["delivery_url"],
                Json(item["keywords"])
            ))

        conn.commit()
        cursor.close()
        conn.close()
        print(f"🎉 SUCCESS: Berhasil meng-ingest {len(INITIAL_ASSETS)} aset digital ke PostgreSQL!")

    except Exception as e:
        print(f"❌ Error koneksi/ingestion: {e}")

if __name__ == "__main__":
    run()
