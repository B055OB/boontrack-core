"""scripts/seed_handling_iklan_meta.py
----------------------------------
Populate Single Page Builder Tabs for Tenant `kelasbos`
Product: "Handling Iklan Meta & Scale-Up Funnel (Full Management)"
Slug: "handling-iklan-meta-scale-up"

Compliance:
- ARCHITECTURE.md: Zero Hardcoding, Multi-Tenant Boundary Doctrine
- Standard Schema: Populates single_page_config in tenants.metadata.products and public.products
- Preserves transaction engine, booking engine, QRIS, and Meta CAPI
"""

import os
import sys
import json
import uuid
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from dotenv import load_dotenv

# Load database URL from boontrack-core .env
load_dotenv("C:\\boontrack-core\\.env")
db_url = os.getenv("DATABASE_URL")

if not db_url:
    print("ERROR: DATABASE_URL not found in C:\\boontrack-core\\.env")
    sys.exit(1)

def run():
    print("Connecting to Supabase PostgreSQL...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 1. Fetch tenant kelasbos
        cur.execute("SELECT id, slug, name, metadata FROM public.tenants WHERE slug = 'kelasbos'")
        tenant = cur.fetchone()
        if not tenant:
            raise Exception("Tenant 'kelasbos' not found in database!")

        tenant_id = str(tenant["id"])
        current_meta = tenant["metadata"] or {}
        print(f"Found tenant: {tenant['name']} (ID: {tenant_id})")

        # 2. Bank accounts setup (BCA & Mandiri) for Tab 8 Manual Transfer
        bank_accounts = [
            {
                "bank_name": "BCA",
                "account_number": "7310892111",
                "account_holder": "Fahami Digital"
            },
            {
                "bank_name": "Mandiri",
                "account_number": "1310023889112",
                "account_holder": "Fahami Digital"
            }
        ]

        # 3. Define the 19 client logos across 5 categories
        client_logos = [
            # Beauty
            {"name": "MS Glow", "category": "Beauty", "logo_url": ""},
            {"name": "EmGlow", "category": "Beauty", "logo_url": ""},
            {"name": "Daviena", "category": "Beauty", "logo_url": ""},
            {"name": "Cleora", "category": "Beauty", "logo_url": ""},
            {"name": "Cyskin", "category": "Beauty", "logo_url": ""},
            # F&B
            {"name": "Panjo", "category": "F&B", "logo_url": ""},
            {"name": "Ciomy", "category": "F&B", "logo_url": ""},
            {"name": "Loffle", "category": "F&B", "logo_url": ""},
            {"name": "Chocodot", "category": "F&B", "logo_url": ""},
            # Fashion
            {"name": "Famys", "category": "Fashion", "logo_url": ""},
            {"name": "Vinia", "category": "Fashion", "logo_url": ""},
            {"name": "Evernext", "category": "Fashion", "logo_url": ""},
            {"name": "Milyarda", "category": "Fashion", "logo_url": ""},
            {"name": "Ghazal", "category": "Fashion", "logo_url": ""},
            # Clinic & Treatment
            {"name": "SkinEx", "category": "Clinic & Treatment", "logo_url": ""},
            {"name": "Enhaka", "category": "Clinic & Treatment", "logo_url": ""},
            {"name": "Dentia", "category": "Clinic & Treatment", "logo_url": ""},
            # Travel
            {"name": "Aet Travel", "category": "Travel", "logo_url": ""},
            {"name": "Saihah", "category": "Travel", "logo_url": ""},
        ]

        # 4. Tab 3: Problem & Solve
        problem_title = "Apakah Anda Menghadapi 3 Kendala Eksekusi Iklan Ini?"
        pain_points = [
            "Gak bisa handle sendiri: Waktu tersita habis mengurus operasional bisnis, sementara otak-atik Ads Manager bikin pusing dan boncos tanpa arah yang jelas.",
            "Sulit cari tim eksekusi profesional: Rekrut media buyer & content creator in-house butuh biaya tinggi, turnover cepat, dan belum tentu punya track record winning campaign.",
            "Gak paham buat konten yang connect: Iklan sudah jalan dan budget terpotong, tapi sepi leads atau pembeli karena copywriting dan angle visual tidak relevan dengan target audiens."
        ]
        solution_title = "Solusi Lengkap Handling Iklan Meta Fahami Digital"
        solution_points = [
            "Full Management Meta Ads 1 bulan: Perumusan struktur campaign, targeting, budgeting, dan scale-up harian.",
            "Produksi 4 video kreatif konversi (Reels/TikTok/Feed) dirancang untuk winning hook & CTR tinggi.",
            "Penyusunan scriptwriting hipnotik & rekaman professional voice over berstandar komersial.",
            "Produksi 10 desain konten promosi & carousel beresolusi tinggi siap tayang.",
            "Setup & integrasi Meta Conversions API (CAPI) server-side untuk tracking presisi anti kebocoran data pasca iOS 14.5.",
            "Monitoring & evaluasi berkala untuk stabilitas ROAS dan efisiensi biaya akuisisi (CPA)."
        ]

        # 5. Tab 4: Us vs Them (Cost Comparison)
        comparison_rows = [
            {
                "id": "comp-1",
                "feature": "Biaya Tim & Operasional Bulanan",
                "others": "Rp 19jt - 31jt/bln (Gaji Media Buyer, Video Editor, Graphic Designer, Copywriter + THR & Fasilitas)",
                "us": "Hanya Rp 4,9jt/bln (Hemat & langsung jalan dengan tim spesialis profesional all-in)"
            },
            {
                "id": "comp-2",
                "feature": "Kecepatan Onboarding & Eksekusi",
                "others": "Butuh 1 - 2 bulan untuk proses rekrutmen tim, interview, training, dan adaptasi kerja",
                "us": "Langsung jalan dalam 3-5 hari kerja setelah brief bisnis dan onboarding selesai"
            },
            {
                "id": "comp-3",
                "feature": "Produksi Aset Kreatif & Konten Iklan",
                "others": "Trial-error sendiri, konten sering kaku dan tidak fokus konversi penjualan",
                "us": "Sudah include 4 video kreatif konversi, script & voice over, serta 10 desain konten iklan"
            },
            {
                "id": "comp-4",
                "feature": "Teknologi Tracking & Data Resilience",
                "others": "Hanya pixel browser biasa yang rentan hilang sinyal konversi karena AdBlocker & iOS",
                "us": "Full setup Meta Conversions API (CAPI) server-side untuk sinyal tracking AI Meta maksimal"
            }
        ]

        # 6. Tab 6: Offer & Deliverables / Bonus Box
        bonus_items = [
            {
                "id": "deliv-1",
                "title": "Handling Meta Ads 1 Bulan Penuh",
                "value": 5000000,
                "description": "Manajemen harian, testing audience, split-testing materi iklan, dan scale-up budget terarah."
            },
            {
                "id": "deliv-2",
                "title": "4 Video Kreatif Konversi Tinggi",
                "value": 3000000,
                "description": "Video vertikal format 9:16 dengan formula winning hook-story-offer untuk Reels & IG Ads."
            },
            {
                "id": "deliv-3",
                "title": "Scriptwriting & Professional Voice Over",
                "value": 2000000,
                "description": "Naskah iklan persuasif berstandar komersial lengkap dengan rekaman voice over berkualitas."
            },
            {
                "id": "deliv-4",
                "title": "10 Desain Konten Promosi & Carousel",
                "value": 2500000,
                "description": "Desain visual grafis feed & carousel estetik beresolusi tinggi yang dirancang untuk closing."
            },
            {
                "id": "deliv-5",
                "title": "Direct-Response Copywriting Paket Iklan",
                "value": 1500000,
                "description": "Penyusunan primary text, headline tajam, dan deskripsi penawaran yang memicu aksi klik."
            },
            {
                "id": "deliv-6",
                "title": "Setup & Konfigurasi Meta Conversions API (CAPI)",
                "value": 2000000,
                "description": "Integrasi tracking server-side resmi Meta anti kehilangan data konversi pasca iOS 14.5."
            }
        ]

        # 7. Tab 5: Testimonials & Social Proof
        testimonials = [
            {
                "id": "testi-1",
                "name": "dr. Hani",
                "role": "Owner Aesthetic Clinic",
                "quote": "Setelah di-handle tim Fahami Digital, reservasi klinik kami naik lebih dari 200%. Konten iklannya sangat edukatif dan tepat sasaran.",
                "rating": 5,
                "badge": "Growth +200%"
            },
            {
                "id": "testi-2",
                "name": "Rian Kusuma",
                "role": "Founder Fashion Brand",
                "quote": "Gak perlu pusing lagi mikirin rekrutmen media buyer. CPA jauh lebih stabil dan ROAS konsisten di atas 4x.",
                "rating": 5,
                "badge": "ROAS 4.2x"
            }
        ]

        # 8. Tab 7: FAQs
        faqs = [
            {
                "question": "Berapa lama periode pengerjaan layanan ini?",
                "answer": "Periode layanan adalah 1 bulan penuh (30 hari kalender) mencakup persiapan aset, produksi materi, penayangan kampanye, hingga evaluasi harian.",
                "q": "Berapa lama periode pengerjaan layanan ini?",
                "a": "Periode layanan adalah 1 bulan penuh (30 hari kalender) mencakup persiapan aset, produksi materi, penayangan kampanye, hingga evaluasi harian."
            },
            {
                "question": "Apakah biaya Rp 4.900.000 sudah termasuk anggaran iklan (ad spend)?",
                "answer": "Biaya tersebut adalah biaya jasa manajemen tim profesional (handling fee) dan produksi materi kreatif. Budget iklan (ad spend) dibayarkan langsung oleh klien ke Meta via kartu debit/kredit/invoice Meta.",
                "q": "Apakah biaya Rp 4.900.000 sudah termasuk anggaran iklan (ad spend)?",
                "a": "Biaya tersebut adalah biaya jasa manajemen tim profesional (handling fee) dan produksi materi kreatif. Budget iklan (ad spend) dibayarkan langsung oleh klien ke Meta via kartu debit/kredit/invoice Meta."
            },
            {
                "question": "Bagaimana proses onboarding setelah saya melakukan pembayaran?",
                "answer": "Setelah konfirmasi pembayaran, tim account manager kami akan langsung menghubungi Anda via WhatsApp resmi untuk mengirimkan link brief bisnis dan mengatur jadwal kick-off call.",
                "q": "Bagaimana proses onboarding setelah saya melakukan pembayaran?",
                "a": "Setelah konfirmasi pembayaran, tim account manager kami akan langsung menghubungi Anda via WhatsApp resmi untuk mengirimkan link brief bisnis dan mengatur jadwal kick-off call."
            }
        ]

        # 9. Full Single Page Config (Canonical 8-Section JSON Schema)
        single_page_config = {
            "slug": "handling-iklan-meta-scale-up",
            # Section Toggles
            "enable_hero": True,
            "enable_client_logos": True,
            "enable_problem_solution": True,
            "enable_us_vs_them": True,
            "enable_testimonials": True,
            "enable_offer": True,
            "enable_faq": True,
            "enable_payment": True,

            # Tab 1: Hook & Hero
            "headline": "Handling Iklan Meta & Scale-Up Funnel",
            "subheadline": "Fahami Digital menangani strategi, konten, dan optimasi iklan Meta untuk bisnis Anda. Bukan sekadar jalan, lalu ditinggal.",
            "badge_text": "Full Management Scale-Up",
            "banner_url": "https://images.unsplash.com/photo-1551836022-d5d88e9218df?auto=format&fit=crop&w=1200&q=80",
            "cta_label": "Mulai Scale-Up Sekarang",

            # Tab 2: Client Logos
            "client_logos": client_logos,

            # Tab 3: Problem & Solution
            "problem_title": problem_title,
            "pain_points": pain_points,
            "solution_title": solution_title,
            "solution_points": solution_points,

            # Tab 4: Comparison
            "comparison_rows": comparison_rows,

            # Tab 5: Testimonials
            "testimonials": testimonials,
            "testimonial_images": [],

            # Tab 6: Offer & Bonus / Deliverables
            "bonus_items": bonus_items,

            # Tab 7: FAQ
            "faqs": faqs,

            # Tab 8: Bayar & Voucher
            "enable_qris": True,
            "enable_manual_transfer": True,
            "discount_coupon": "SCALEUP",
            "voucher": {
                "code": "SCALEUP",
                "discount_type": "nominal",
                "discount_value": 0,
                "min_spend": 0,
                "is_active": True
            }
        }

        # 10. Construct new product record
        prod_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "kelasbos-prod-handling-iklan-meta-scale-up"))
        
        new_product = {
            "id": prod_uuid,
            "name": "Handling Iklan Meta & Scale-Up Funnel (Full Management)",
            "title": "Handling Iklan Meta & Scale-Up Funnel (Full Management)",
            "slug": "handling-iklan-meta-scale-up",
            "description": "Fahami Digital menangani strategi, konten, dan optimasi iklan Meta untuk bisnis Anda. Bukan sekadar jalan, lalu ditinggal.",
            "price": 4900000,
            "promo_price": 4900000,
            "original_price": 19000000,
            "originalPrice": 19000000,
            "product_type": "SERVICE",
            "type": "service",
            "category": "Jasa",
            "badge": "Terlaris",
            "promo": "Full Management",
            "is_active": True,
            "is_available": True,
            "stock": 10,
            "is_unlimited": False,
            "image": "https://images.unsplash.com/photo-1551836022-d5d88e9218df?auto=format&fit=crop&w=1200&q=80",
            "cta_label": "Mulai Scale-Up Sekarang",
            "features": [
                "Handling Meta Ads 1 Bulan Penuh",
                "4 Video Kreatif Konversi Tinggi",
                "Script & Professional Voice Over",
                "10 Desain Konten Promosi & Carousel",
                "Direct-Response Copywriting",
                "Setup Meta Conversions API (CAPI)"
            ],
            "single_page_config": single_page_config,
            "fulfillment_metadata": {
                "type": "AGENCY_SERVICE",
                "duration_days": 30,
                "onboarding_channel": "WhatsApp & Google Meet",
                "single_page_config": single_page_config,
                "original_price": 19000000
            }
        }

        # 11. Update tenants.metadata.products
        existing_products = current_meta.get("products") or []
        # Filter out if already present by slug
        filtered_products = [p for p in existing_products if p.get("slug") != "handling-iklan-meta-scale-up"]
        # Append new product
        updated_products = filtered_products + [new_product]

        # Update bot profile knowledge scope
        bot_profile = current_meta.get("bot_profile") or {}
        bot_ks = bot_profile.get("knowledge_scope") or {}
        bot_ks["products"] = [
            {"name": p.get("name") or p.get("title"), "price": p.get("price"), "original_price": p.get("original_price") or p.get("originalPrice")}
            for p in updated_products
        ]
        bot_profile["knowledge_scope"] = bot_ks

        # Merge metadata
        updated_metadata = {
            **current_meta,
            "bank_accounts": bank_accounts,
            "products": updated_products,
            "bot_profile": bot_profile
        }

        print("Updating tenants table in Supabase...")
        cur.execute(
            """
            UPDATE public.tenants
            SET metadata = %s
            WHERE id = %s
            """,
            (Json(updated_metadata), tenant_id)
        )
        print("  -> Tenant metadata updated with bank_accounts and new product.")

        # 12. Upsert into public.products table
        print("Upserting product in public.products table...")
        asset_ref = "SERVICE:META_ADS:handling-iklan-meta-scale-up"
        cur.execute(
            """
            INSERT INTO public.products (
                id, tenant_id, title, slug, description, price, promo_price,
                product_type, asset_reference, is_available, is_unlimited_stock,
                category, stock, image, fulfillment_metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                slug = EXCLUDED.slug,
                description = EXCLUDED.description,
                price = EXCLUDED.price,
                promo_price = EXCLUDED.promo_price,
                product_type = EXCLUDED.product_type,
                asset_reference = EXCLUDED.asset_reference,
                is_available = EXCLUDED.is_available,
                is_unlimited_stock = EXCLUDED.is_unlimited_stock,
                category = EXCLUDED.category,
                stock = EXCLUDED.stock,
                image = EXCLUDED.image,
                fulfillment_metadata = EXCLUDED.fulfillment_metadata;
            """,
            (
                prod_uuid,
                tenant_id,
                new_product["title"],
                new_product["slug"],
                new_product["description"],
                new_product["price"],
                new_product["promo_price"],
                new_product["product_type"],
                asset_ref,
                new_product["is_available"],
                new_product["is_unlimited"],
                new_product["category"],
                new_product["stock"],
                new_product["image"],
                Json(new_product["fulfillment_metadata"])
            )
        )
        print("  -> public.products upserted successfully.")

        conn.commit()
        print("\nAll database mutations committed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR during execution: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
