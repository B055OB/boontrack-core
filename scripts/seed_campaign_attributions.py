"""scripts/seed_campaign_attributions.py
Script untuk melakukan seeding data contoh atribusi iklan HANYA untuk tenant demo ('onlineboost').
Dapat dijalankan langsung melalui CLI:
python scripts/seed_campaign_attributions.py
"""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.services.campaign_analytics_service import campaign_analytics_service, ONLINEBOOST_DEMO_CAMPAIGNS


def main():
    print("==========================================================")
    print("[SEEDING] Campaign Attributions for Demo Tenant 'onlineboost'")
    print("==========================================================")
    
    result = campaign_analytics_service.seed_onlineboost_demo_data()
    print(f"Status        : {result['status']}")
    print(f"Tenant Target : {result['tenant_slug']}")
    print(f"Records Seeded: {result['records_seeded']}")
    print("Data Items:")
    for idx, c in enumerate(result["campaigns"], 1):
        print(f"  {idx}. [{c['platform']}] {c['campaign_name']}")
        print(f"     Clicks: {c['clicks']} | Leads WA: {c['leads_wa']} | Closings: {c['closings']} | CR: {c['cr_pct']}% | Omset: Rp {c['omset_closing']:,.0f} | Status: {c['status']}")
    
    print("==========================================================")
    print("[SUCCESS] Seeding Berhasil Selesai!")


if __name__ == "__main__":
    main()
