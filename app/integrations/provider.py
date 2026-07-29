from app.core.config import settings
from app.integrations.makcorps import MakCorpsClient
from app.integrations.serpapi_hotels import SerpApiHotelsClient


def get_hotel_client():
    """Pilih provider data hotel yang tersedia, urutan prioritas:
    1. SerpApi (Google Hotels) - kalau SERPAPI_KEY sudah diisi. Datanya paling lengkap
       (fasilitas + rating + perbandingan harga per vendor sekaligus), signup paling
       mudah (email biasa, tanpa kartu kredit, tanpa city-id mapping).
    2. MakCorps - langsung (api.makcorps.com) atau lewat RapidAPI, kalau salah satu
       key-nya sudah diisi.
    3. Mock - fallback otomatis kalau belum ada key sama sekali, supaya app tetap jalan.
    Semua provider di atas punya method async fetch_hotels(...) dengan signature & bentuk
    hasil (dict) yang sama, jadi endpoint pemanggil tidak perlu tahu provider mana yang aktif.
    """
    if settings.SERPAPI_KEY:
        return SerpApiHotelsClient(api_key=settings.SERPAPI_KEY)
    return MakCorpsClient(api_key=settings.MAKCORPS_API_KEY, rapidapi_key=settings.RAPIDAPI_KEY)
