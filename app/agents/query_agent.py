import json
import re
from pydantic import BaseModel, Field
from typing import List, Optional
from app.core.llm_client import get_llm_client

class ExtractedFilters(BaseModel):
    destination: Optional[str] = Field(None, description="The city or location the user wants to visit.")
    check_in: Optional[str] = Field(None, description="Check-in date in YYYY-MM-DD format.")
    check_out: Optional[str] = Field(None, description="Check-out date in YYYY-MM-DD format.")
    guests: int = Field(2, description="Number of guests.")
    rooms: int = Field(1, description="Number of rooms.")
    budget: Optional[float] = Field(None, description="Maximum budget per night.")
    currency: str = Field("USD", description="Currency for the budget.")
    required: List[str] = Field([], description="Required amenities or constraints (e.g. pool, pet-friendly).")
    preferred: List[str] = Field([], description="Soft preferences (e.g. beach view, breakfast).")
    missing: List[str] = Field([], description="List of required fields missing from the query (e.g. destination, dates).")

# Dipakai HANYA sebagai fallback kalau LLM (Groq) benar-benar tidak bisa dihubungi
# (key bermasalah, kuota habis, tidak ada internet, dst.) supaya aplikasi tidak
# "buntu" terus-menerus menanyakan destinasi meski user sudah menjawabnya.
# Bukan pengganti NLU asli - jangkauannya sengaja dibuat sederhana (exact match kota
# + kata kunci umum), bukan pemahaman bahasa natural penuh.
_KNOWN_CITIES = {
    "jogja": "Jogja", "yogyakarta": "Jogja", "yogya": "Jogja", "jogjakarta": "Jogja", "diy": "Jogja",
    "bali": "Bali", "denpasar": "Bali", "ubud": "Bali",
    "bandung": "Bandung",
    "jakarta": "Jakarta",
    "surabaya": "Surabaya",
    "semarang": "Semarang",
    "malang": "Malang",
    "medan": "Medan",
    "makassar": "Makassar",
    "lombok": "Lombok",
    "bogor": "Bogor",
}
_AMENITY_KEYWORDS = {
    "kolam renang": "pool", "pool": "pool", "swimming pool": "pool",
    "sarapan": "breakfast", "breakfast": "breakfast",
    "wifi": "wifi", "wi-fi": "wifi",
    "gym": "gym", "fitness": "gym",
    "spa": "spa",
    "pantai": "beach", "beach": "beach",
}


def _heuristic_extract(query: str, previous: Optional[dict] = None) -> ExtractedFilters:
    text = query.lower()
    previous = previous or {}

    destination = None
    for keyword, canonical in _KNOWN_CITIES.items():
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            destination = canonical
            break
    if destination is None:
        # Tidak disebut lagi di pesan ini -> lanjutkan destinasi dari sesi sebelumnya
        # kalau ada (inti dari "conversation memory").
        destination = previous.get("destination")

    budget = None
    m = re.search(r"(?:budget|max|maksimal)?\s*\$?\s*(\d{2,6})(?:\s*(?:dollar|usd|rb|ribu|k))?", text)
    if m:
        val = float(m.group(1))
        budget = val if val >= 5 else None  # buang angka kecil yang kemungkinan bukan budget (mis. "2 orang")
    if budget is None:
        budget = previous.get("budget")

    amenities = []
    for keyword, canonical in _AMENITY_KEYWORDS.items():
        if keyword in text and canonical not in amenities:
            amenities.append(canonical)
    # Gabungkan (bukan timpa) dengan fasilitas yang sudah diminta di pesan sebelumnya.
    for a in (previous.get("required") or []):
        if a not in amenities:
            amenities.append(a)

    return ExtractedFilters(
        destination=destination,
        check_in=previous.get("check_in"),
        check_out=previous.get("check_out"),
        budget=budget,
        required=amenities,
        preferred=previous.get("preferred") or [],
        missing=[] if destination else ["destination"],
    )


class QueryUnderstandingAgent:
    def __init__(self, llm_client=None):
        # Client dibuat lazy (di dalam process(), bukan di sini) supaya kalau
        # API key kosong/tidak valid, error-nya tertangkap oleh try/except di
        # process() dan jatuh ke fallback -- bukan crash langsung saat agent dibuat.
        self._llm_client = llm_client
        self.system_prompt = """
You are an expert Travel Concierge AI.
Your job is to parse the user's natural language hotel request into a strict JSON object matching the ExtractedFilters schema.
Extract destination, check-in, check-out, guests, budget, and categorize amenities into 'required' and 'preferred'.
If critical information like 'destination' is missing, add it to the 'missing' array.
Output ONLY valid JSON matching this schema. Do not add markdown formatting.
IMPORTANT: "guests", "rooms", and "currency" must NEVER be null - if not mentioned by
the user, use the default values shown below (2, 1, "USD"). Only "destination",
"check_in", "check_out", and "budget" may be null when not mentioned.
Schema:
{
  "destination": "string", "check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD",
  "guests": 2, "rooms": 1, "budget": 100.0, "currency": "USD",
  "required": [], "preferred": [], "missing": []
}
"""

    def process(self, query: str, context: Optional[dict] = None) -> ExtractedFilters:
        try:
            llm = self._llm_client or get_llm_client()
            context_block = ""
            prev_filters = (context or {}).get("filters") or {}
            prev_hotels = (context or {}).get("last_hotels") or []
            if prev_filters or prev_hotels:
                context_block = f"""
Previous conversation context (this is a FOLLOW-UP message, not a fresh request):
Previous filters already established: {json.dumps(prev_filters)}
Hotels shown to the user in the last reply (name/price/rating): {json.dumps(prev_hotels)}

Merge rules:
- If this new message does NOT mention destination/dates/budget, KEEP the previous values for those fields (don't null them out just because they're not repeated).
- If this new message adds a new amenity request (e.g. "yang ada kolam renang"), ADD it to "required" together with any amenities already in the previous filters (combine, don't replace).
- If the user asks for something cheaper (e.g. "yang lebih murah", "budget lebih kecil"), set "budget" below the cheapest price shown above.
- If the user clearly names a different destination, use the new one instead.
"""
            full_prompt = f"{self.system_prompt}\n{context_block}\nUser Request: {query}"
            response = llm.generate(full_prompt, json_mode=True)
            data = json.loads(response.text)
            # Beberapa LLM (terutama Groq/model open-weight) suka mengembalikan
            # `null` secara eksplisit untuk field yang seharusnya punya default
            # (guests, rooms, currency), bukan cuma menghilangkan field itu.
            # Pydantic membedakan "field tidak ada" (pakai default) vs "field ada
            # tapi None" (divalidasi apa adanya) - makanya null bikin error di
            # field ber-tipe int/str yang tidak Optional. Buang key ber-nilai None
            # supaya default dari skema yang dipakai.
            data = {k: v for k, v in data.items() if v is not None}
            return ExtractedFilters(**data)
        except Exception as e:
            # LLM gagal (key bermasalah, kuota habis, dsb) ATAU hasilnya tidak
            # sesuai skema. Log error aslinya di server, lalu coba pemahaman
            # sederhana berbasis kata kunci supaya aplikasi tetap bisa dipakai
            # (bukan langsung nanya destinasi terus). Tetap bawa konteks sesi
            # sebelumnya supaya follow-up tidak "lupa" walau LLM lagi down.
            print(f"[QueryUnderstandingAgent] Gagal memanggil LLM: {e}")
            print("[QueryUnderstandingAgent] Pakai fallback berbasis kata kunci (bukan AI).")
            prev_filters = (context or {}).get("filters")
            return _heuristic_extract(query, prev_filters)
