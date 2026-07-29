import re
import math
from typing import List, Dict, Optional

import httpx

# Dokumentasi resmi MakCorps: https://docs.makcorps.com
# 1. Mapping API  : GET https://api.makcorps.com/mapping?api_key=...&name=<kota>
#                   -> mencari cityId dari nama kota (cari item dengan type == "GEO")
# 2. City Search   : GET https://api.makcorps.com/city?cityid=...&pagination=0&cur=USD
#                    &rooms=1&adults=2&checkin=YYYY-MM-DD&checkout=YYYY-MM-DD&api_key=...
#                   -> daftar hotel + harga dari sampai 4 vendor OTA (Expedia, Booking.com, dst)
#                      per hotel, jadi datanya sudah "siap" untuk perbandingan harga.
MAKCORPS_MAPPING_URL = "/mapping"
MAKCORPS_CITY_URL = "/city"

# Dataset contoh (mock) dipakai sebagai fallback kalau:
#  - MAKCORPS_API_KEY belum diisi / tidak valid, atau
#  - request ke MakCorps gagal (network / quota habis / kota tidak ditemukan)
# supaya aplikasi tetap bisa dites & tetap memberi jawaban, bukan error kosong.
MOCK_HOTELS_BY_DESTINATION = {
    "jogja": [
        {"id": "hotel_yk1", "name": "The Phoenix Hotel Yogyakarta", "price": 65.0, "rating": 4.6,
         "distance_km": 1.0, "amenities": ["pool", "wifi", "breakfast", "spa"]},
        {"id": "hotel_yk2", "name": "Grand Rohan Jogja", "price": 45.0, "rating": 4.4,
         "distance_km": 6.5, "amenities": ["pool", "wifi", "breakfast", "gym"]},
        {"id": "hotel_yk3", "name": "Hotel Tentrem Yogyakarta", "price": 90.0, "rating": 4.8,
         "distance_km": 3.2, "amenities": ["pool", "wifi", "breakfast", "spa", "gym"]},
        {"id": "hotel_yk4", "name": "Wonderloft Hostel Malioboro", "price": 15.0, "rating": 4.2,
         "distance_km": 0.3, "amenities": ["wifi", "breakfast"]},
    ],
    "bali": [
        {"id": "hotel_123", "name": "Bali Paradise Resort", "price": 110.0, "rating": 4.5,
         "distance_km": 1.2, "amenities": ["pool", "beach", "wifi", "breakfast"]},
        {"id": "hotel_456", "name": "Ubud Jungle Retreat", "price": 85.0, "rating": 4.8,
         "distance_km": 15.0, "amenities": ["pool", "spa", "wifi"]},
    ],
    "bandung": [
        {"id": "hotel_bd1", "name": "The Trans Luxury Hotel Bandung", "price": 95.0, "rating": 4.7,
         "distance_km": 2.0, "amenities": ["pool", "wifi", "breakfast", "spa"]},
        {"id": "hotel_bd2", "name": "GH Universal Hotel", "price": 60.0, "rating": 4.5,
         "distance_km": 8.0, "amenities": ["pool", "wifi", "breakfast"]},
    ],
    "jakarta": [
        {"id": "hotel_jkt1", "name": "Hotel Mulia Senayan", "price": 120.0, "rating": 4.7,
         "distance_km": 4.0, "amenities": ["pool", "wifi", "breakfast", "gym", "spa"]},
        {"id": "hotel_jkt2", "name": "Whiz Prime Hotel Pajajaran", "price": 35.0, "rating": 4.1,
         "distance_km": 2.5, "amenities": ["wifi", "breakfast"]},
    ],
}

DEFAULT_MOCK_HOTELS = [
    {"id": "hotel_generic1", "name": "Grand City Hotel", "price": 70.0, "rating": 4.3,
     "distance_km": 2.5, "amenities": ["pool", "wifi", "breakfast"]},
    {"id": "hotel_generic2", "name": "Cozy Stay Inn", "price": 40.0, "rating": 4.0,
     "distance_km": 5.0, "amenities": ["wifi", "breakfast"]},
]


def _parse_price(raw) -> Optional[float]:
    """MakCorps mengembalikan harga sebagai string seperti '$1,234' atau '€215'.
    Ambil angkanya saja, abaikan simbol mata uang/koma."""
    if raw is None:
        return None
    digits = re.sub(r"[^0-9.]", "", str(raw))
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class MakCorpsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.makcorps.com",
        rapidapi_key: str = "",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.rapidapi_key = rapidapi_key
        # Kalau MAKCORPS_API_KEY di .env ternyata berisi host RapidAPI
        # (pola "xxx.p.rapidapi.com"), pakai itu sebagai X-RapidAPI-Host.
        self.rapidapi_host = api_key if "rapidapi.com" in (api_key or "") else ""
        self._city_id_cache: Dict[str, Optional[str]] = {}

    def _mode(self) -> str:
        if self.rapidapi_key and self.rapidapi_host:
            return "rapidapi"
        if self.api_key and "rapidapi.com" not in self.api_key:
            return "direct"
        return "mock"

    def _request_kwargs(self) -> dict:
        """Base URL & header yang dipakai tergantung mode (direct MakCorps vs RapidAPI)."""
        if self._mode() == "rapidapi":
            return {
                "base_url": f"https://{self.rapidapi_host}",
                "headers": {
                    "X-RapidAPI-Key": self.rapidapi_key,
                    "X-RapidAPI-Host": self.rapidapi_host,
                },
                "extra_params": {},  # auth lewat header, bukan query param api_key
            }
        return {
            "base_url": self.base_url,
            "headers": {},
            "extra_params": {"api_key": self.api_key},
        }

    async def _resolve_city_id(self, client: httpx.AsyncClient, destination: str, req: dict) -> Optional[str]:
        key = destination.strip().lower()
        if key in self._city_id_cache:
            return self._city_id_cache[key]
        try:
            resp = await client.get(
                f"{req['base_url']}{MAKCORPS_MAPPING_URL}",
                params={**req["extra_params"], "name": destination},
                headers=req["headers"],
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            city_id = None
            for item in data:
                if isinstance(item, dict) and item.get("type") == "GEO":
                    city_id = str(item.get("document_id"))
                    break
            self._city_id_cache[key] = city_id
            return city_id
        except Exception as e:
            print(f"[MakCorpsClient] Gagal resolve city id untuk '{destination}': {e}")
            return None

    def _mock_hotels(self, destination: str) -> List[dict]:
        key = (destination or "").strip().lower()
        if key in ("jogja", "yogyakarta", "yogya", "jogjakarta", "diy"):
            key = "jogja"
        is_known_city = key in MOCK_HOTELS_BY_DESTINATION
        raw = MOCK_HOTELS_BY_DESTINATION.get(key, DEFAULT_MOCK_HOTELS)
        # Tandai supaya lapisan atas (chat.py) tahu ini data contoh, bukan data live,
        # dan LLM tidak mengarang seolah-olah ini hotel asli di kota yang diminta -
        # terutama kalau "generic" (kota tidak ada di daftar contoh sama sekali).
        return [
            {**h, "_mock": True, "_mock_generic": not is_known_city}
            for h in raw
        ]

    async def fetch_hotels(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        rooms: int = 1,
        adults: int = 2,
        currency: str = "USD",
    ) -> List[dict]:
        mode = self._mode()
        if mode == "mock":
            print(
                "[MakCorpsClient] Belum ada API key MakCorps yang valid (baik lewat "
                "api.makcorps.com langsung maupun lewat RapidAPI). Pakai data contoh (mock) dulu.\n"
                "  Opsi 1 (RapidAPI, biasanya lebih mudah login): subscribe 'MakCorps Hotel Price "
                "Comparison' di rapidapi.com, lalu isi .env: RAPIDAPI_KEY=<X-RapidAPI-Key kamu>\n"
                "  Opsi 2 (langsung): daftar di makcorps.com/signup.html, isi MAKCORPS_API_KEY=<api_key>"
            )
            return self._mock_hotels(destination)

        req = self._request_kwargs()
        try:
            async with httpx.AsyncClient() as client:
                city_id = await self._resolve_city_id(client, destination, req)
                if not city_id:
                    return self._mock_hotels(destination)

                city_params = {
                    **req["extra_params"],
                    "cityid": city_id,
                    "pagination": 0,
                    "cur": currency,
                    "rooms": rooms,
                    "adults": adults,
                    "checkin": check_in,
                    "checkout": check_out,
                }
                resp = await client.get(
                    f"{req['base_url']}{MAKCORPS_CITY_URL}",
                    params=city_params,
                    headers=req["headers"],
                    timeout=15.0,
                )
                resp.raise_for_status()
                raw = resp.json()

                # Elemen terakhir dari respons berisi info paginasi ([{...}]), bukan data hotel -
                # saring hanya item yang benar-benar punya hotelId.
                raw_hotels = [h for h in raw if isinstance(h, dict) and "hotelId" in h]
                if not raw_hotels:
                    return self._mock_hotels(destination)

                # MakCorps tidak memberi "jarak ke pusat kota" secara langsung, jadi kita
                # perkirakan dengan menghitung titik tengah (centroid) semua hotel yang
                # ditemukan lalu mengukur jarak tiap hotel ke titik itu.
                coords = [
                    (h["geocode"]["latitude"], h["geocode"]["longitude"])
                    for h in raw_hotels if h.get("geocode")
                ]
                centroid = None
                if coords:
                    centroid = (
                        sum(c[0] for c in coords) / len(coords),
                        sum(c[1] for c in coords) / len(coords),
                    )

                results = []
                for h in raw_hotels:
                    vendors = []
                    for i in range(1, 5):
                        vname = h.get(f"vendor{i}")
                        vprice = _parse_price(h.get(f"price{i}"))
                        if vname and vprice is not None:
                            vendors.append({"vendor": vname, "price": vprice})
                    if not vendors:
                        continue  # tidak ada harga sama sekali dari vendor manapun

                    cheapest = min(v["price"] for v in vendors)
                    geocode = h.get("geocode") or {}
                    if centroid and geocode.get("latitude") is not None:
                        distance_km = round(
                            _haversine_km(centroid[0], centroid[1], geocode["latitude"], geocode["longitude"]), 1
                        )
                    else:
                        distance_km = 0.0

                    results.append({
                        "id": str(h.get("hotelId")),
                        "name": h.get("name", "Unknown Hotel"),
                        "price": cheapest,
                        "rating": (h.get("reviews") or {}).get("rating", 0) or 0,
                        "distance_km": distance_km,
                        # Bukti nyata "perbandingan harga": harga hotel yang sama dari
                        # beberapa OTA (Expedia, Booking.com, Hotels.com, dst).
                        "vendors": sorted(vendors, key=lambda v: v["price"]),
                        # Buat link "buka di Google Maps" di frontend.
                        "latitude": geocode.get("latitude"),
                        "longitude": geocode.get("longitude"),
                    })

                return results or self._mock_hotels(destination)

        except Exception as e:
            mode_label = "RapidAPI" if mode == "rapidapi" else "api.makcorps.com langsung"
            print(
                f"[MakCorpsClient] Gagal mengambil data live lewat {mode_label}: {e}. "
                "Fallback ke data contoh. Kalau ini terjadi terus, cek dulu endpoint & response "
                "shape-nya lewat halaman 'Test Endpoint' di RapidAPI (paths bisa saja sedikit "
                "berbeda dari api.makcorps.com langsung)."
            )
            return self._mock_hotels(destination)
