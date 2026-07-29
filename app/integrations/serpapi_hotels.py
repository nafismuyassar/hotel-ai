import math
from typing import List, Optional

import httpx

from app.integrations.makcorps import MOCK_HOTELS_BY_DESTINATION, DEFAULT_MOCK_HOTELS

# Dokumentasi: https://serpapi.com/google-hotels-api
# Alternatif dari MakCorps: SerpApi men-scrape hasil Google Hotels (bukan API resmi
# Google, tapi legal & datanya sudah terstruktur), termasuk harga dari beberapa
# vendor per hotel -> pas untuk "perbandingan harga".
# Signup: serpapi.com/users/sign_up (email biasa, TIDAK perlu kartu kredit),
# 250 pencarian gratis/bulan. Key ada di serpapi.com/manage-api-key.
SERPAPI_URL = "https://serpapi.com/search.json"


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _mock_hotels(destination: str) -> List[dict]:
    key = (destination or "").strip().lower()
    if key in ("jogja", "yogyakarta", "yogya", "jogjakarta", "diy"):
        key = "jogja"
    is_known_city = key in MOCK_HOTELS_BY_DESTINATION
    raw = MOCK_HOTELS_BY_DESTINATION.get(key, DEFAULT_MOCK_HOTELS)
    return [
        {**h, "_mock": True, "_mock_generic": not is_known_city}
        for h in raw
    ]


class SerpApiHotelsClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_hotels(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        rooms: int = 1,
        adults: int = 2,
        currency: str = "USD",
    ) -> List[dict]:
        if not self.api_key:
            print(
                "[SerpApiHotelsClient] SERPAPI_KEY belum diisi. Daftar gratis (tanpa kartu "
                "kredit) di https://serpapi.com/users/sign_up, ambil key di "
                "https://serpapi.com/manage-api-key, lalu isi .env: SERPAPI_KEY=<key>. "
                "Pakai data contoh (mock) dulu."
            )
            return _mock_hotels(destination)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    SERPAPI_URL,
                    params={
                        "engine": "google_hotels",
                        "q": f"Hotels in {destination}",
                        "check_in_date": check_in,
                        "check_out_date": check_out,
                        "adults": adults,
                        "currency": currency,
                        "api_key": self.api_key,
                    },
                    timeout=20.0,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("search_metadata", {}).get("status") == "Error":
                    print(f"[SerpApiHotelsClient] SerpApi error: {data.get('error')}")
                    return _mock_hotels(destination)

                properties = data.get("properties") or []
                if not properties:
                    return _mock_hotels(destination)

                coords = [
                    (p["gps_coordinates"]["latitude"], p["gps_coordinates"]["longitude"])
                    for p in properties if p.get("gps_coordinates")
                ]
                centroid = None
                if coords:
                    centroid = (
                        sum(c[0] for c in coords) / len(coords),
                        sum(c[1] for c in coords) / len(coords),
                    )

                results = []
                for idx, p in enumerate(properties):
                    rate = (p.get("rate_per_night") or {}).get("extracted_lowest")
                    if rate is None:
                        continue  # tidak ada harga sama sekali, skip

                    vendors = []
                    for price_entry in p.get("prices", []):
                        source = price_entry.get("source")
                        v_rate = (price_entry.get("rate_per_night") or {}).get("extracted_lowest")
                        if source and v_rate is not None:
                            vendors.append({"vendor": source, "price": float(v_rate)})

                    gps = p.get("gps_coordinates") or {}
                    if centroid and gps.get("latitude") is not None:
                        distance_km = round(
                            _haversine_km(centroid[0], centroid[1], gps["latitude"], gps["longitude"]), 1
                        )
                    else:
                        distance_km = 0.0

                    results.append({
                        "id": p.get("property_token") or f"serpapi_{idx}",
                        "name": p.get("name", "Unknown Hotel"),
                        "price": float(rate),
                        "rating": p.get("overall_rating", 0) or 0,
                        "distance_km": distance_km,
                        "amenities": p.get("amenities", []),
                        "vendors": sorted(vendors, key=lambda v: v["price"]) if vendors else [],
                        # Google kadang menandai properti tertentu sebagai promo (mis. "44%
                        # lebih murah dari biasanya") langsung di hasil pencarian. Kalau tidak
                        # ada, bool()/None di sini otomatis False/kosong - tidak nge-fake promo.
                        "deal": bool(p.get("deal")),
                        "deal_description": p.get("deal_description"),
                        # Buat link "buka di Google Maps" di frontend.
                        "latitude": gps.get("latitude"),
                        "longitude": gps.get("longitude"),
                    })

                return results or _mock_hotels(destination)

        except Exception as e:
            print(f"[SerpApiHotelsClient] Gagal mengambil data live dari SerpApi: {e}. Fallback ke data contoh.")
            return _mock_hotels(destination)
