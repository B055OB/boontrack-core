import os
import sys
import asyncio
from unittest.mock import patch

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fastapi.testclient import TestClient
from app.main import app
from app.services.biteship_service import get_instant_rates, ORIGIN_WAREHOUSE, BiteshipService

def test_all():
    print("--- TEST 1: Direct Service Call (Sandbox/Fallback) ---")
    rates = asyncio.run(get_instant_rates('40287', [{'name': 'Sepatu Kulit', 'value': 150000, 'weight': 1000, 'quantity': 1}]))
    print(f"Rates count: {len(rates)}")
    for r in rates:
        print(f"  - [{r['courier_name']}] {r['service_name']} ({r['service_type']}): Rp{r['price']} | ETD: {r['etd']} | {r['description']}")

    assert len(rates) >= 2, "Should return rates"
    assert all('courier_name' in r and 'service_type' in r and 'price' in r for r in rates)
    print("TEST 1 PASSED!")

    print("\n--- TEST 2: Parsing Mocked Biteship 200 OK Response ---")
    mock_biteship_200 = {
        'success': True,
        'pricing': [
            {
                'company': 'gosend',
                'courier_name': 'GoSend',
                'courier_service_name': 'Instant',
                'type': 'instant',
                'price': 18000,
                'shipment_duration_range': '1 - 2',
                'shipment_duration_unit': 'hours',
                'description': 'Layanan pengiriman kilat GoSend'
            },
            {
                'company': 'grab',
                'courier_name': 'Grab',
                'courier_service_name': 'Same Day',
                'type': 'same_day',
                'price': 14000,
                'shipment_duration_range': '6 - 8',
                'shipment_duration_unit': 'hours',
                'description': 'Layanan pengiriman GrabExpress Sameday'
            },
            {
                'company': 'jne',
                'courier_name': 'JNE',
                'courier_service_name': 'Regular',
                'type': 'standard',
                'price': 10000,
                'shipment_duration_range': '2 - 3',
                'shipment_duration_unit': 'days',
                'description': 'JNE Reguler'
            }
        ]
    }

    class FakeResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json_data = json_data
            self.text = 'ok'
        def json(self):
            return self._json_data

    class FakeAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, json=None, headers=None):
            return FakeResponse(200, mock_biteship_200)

    with patch('httpx.AsyncClient', return_value=FakeAsyncClient()):
        parsed_rates = asyncio.run(get_instant_rates('40287', []))
        print(f"Parsed mocked count: {len(parsed_rates)}")
        for r in parsed_rates:
            print(f"  - [{r['courier_name']}] {r['service_name']} ({r['service_type']}): Rp{r['price']} | ETD: {r['etd']}")
        assert len(parsed_rates) == 2, "Should filter gosend and grab only"
        assert parsed_rates[0]['courier_name'] == 'GoSend'
        assert parsed_rates[0]['service_type'] == 'instant'
        assert parsed_rates[0]['price'] == 18000
        assert parsed_rates[1]['courier_name'] == 'Grab'
        assert parsed_rates[1]['service_type'] == 'same_day'
        assert parsed_rates[1]['price'] == 14000
    print("TEST 2 PASSED!")

    print("\n--- TEST 3: FastAPI Endpoint POST /api/v1/shipping/rates/instant ---")
    client = TestClient(app)
    payload = {
        'tenant_id': 'onlineboost',
        'destination_postal_code': '40287',
        'destination_address': 'Jl. Pluto Barat No. 10, Bandung',
        'items': [
            {
                'name': 'BoonTrack T-Shirt',
                'value': 85000,
                'weight': 500,
                'quantity': 2
            }
        ]
    }
    resp = client.post('/api/v1/shipping/rates/instant', json=payload)
    print('Endpoint status:', resp.status_code)
    data = resp.json()
    print('Origin Warehouse:', data.get('origin'))
    print('Destination Postal:', data.get('destination_postal_code'))
    print('Rates count from API:', len(data.get('rates', [])))
    for r in data.get('rates', []):
        print(f"  - [{r['courier_name']}] {r['service_name']} ({r['service_type']}): Rp{r['price']} | ETD: {r['etd']}")
    assert resp.status_code == 200
    assert data['success'] is True
    assert data['origin']['postal_code'] == 40286
    assert data['destination_postal_code'] == '40287'
    assert len(data['rates']) >= 2
    print("TEST 3 PASSED!")

    print("\n========================================")
    print("ALL 3 TESTS VERIFIED SUCCESSFULLY!")
    print("========================================")

if __name__ == '__main__':
    test_all()
