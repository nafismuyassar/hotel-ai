"""
Logika inti chat StayWise AI, dipisah dari endpoint FastAPI (app/api/endpoints/chat.py)
supaya bisa dipakai ulang oleh frontend lain juga - misalnya Streamlit
(streamlit_app.py di root project) - tanpa duplikasi kode ataupun harus lewat
HTTP/network sama sekali (dipanggil langsung sebagai fungsi Python biasa).

Satu-satunya "kontrak" yang dijaga: run_chat_pipeline(message, session_id) -> dict
dengan bentuk yang sama persis dengan ChatResponse (app/schemas/chat.py), supaya
endpoint FastAPI dan Streamlit menampilkan hasil yang identik.
"""
import re
from datetime import date
from typing import Optional

from app.agents.query_agent import QueryUnderstandingAgent
from app.agents.ranking_agent import SmartRankingAgent
from app.agents.itinerary_agent import ItineraryPlannerAgent, ItineraryPlan
from app.services.scoring import calculate_hotel_scores
from app.integrations.provider import get_hotel_client
from app.core.llm_client import get_llm_client
from app.core.memory import get_or_create_session, update_session

# Dibuat sekali di level module (bukan per-request) supaya tidak membuat client
# baru setiap kali chat - dipakai bersama oleh endpoint FastAPI maupun Streamlit.
query_agent = QueryUnderstandingAgent()
ranking_agent = SmartRankingAgent()
itinerary_agent = ItineraryPlannerAgent()
hotel_client = get_hotel_client()

# Kata kunci buat deteksi "user mau itinerary/rencana trip", bukan cuma cari hotel.
# Sengaja berbasis kata kunci (bukan minta LLM klasifikasi intent terpisah) supaya
# tidak nambah 1 lagi panggilan LLM per pesan - cukup murah & cukup akurat untuk kasus ini.
_ITINERARY_KEYWORDS = [
    "itinerary", "rencana perjalanan", "rencana trip", "rencana liburan",
    "susun jadwal", "susun rencana", "buatkan rencana", "buat rencana",
    "jadwal wisata", "jadwal jalan-jalan", "trip plan", "rencanakan",
    "mau kemana aja", "kegiatan selama", "aktivitas selama",
]


def _is_itinerary_request(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _ITINERARY_KEYWORDS)


def _extract_days(message: str, prev_filters: dict) -> int:
    m = re.search(r"(\d+)\s*(?:hari|days?)\b", message.lower())
    if m:
        return max(1, min(int(m.group(1)), 10))  # dibatasi 1-10 hari, biar wajar

    check_in = prev_filters.get("check_in")
    check_out = prev_filters.get("check_out")
    if check_in and check_out:
        try:
            nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
            if nights > 0:
                return min(nights, 10)
        except Exception:
            pass
    return 3  # default kalau tidak disebut sama sekali


def _format_itinerary_text(plan: ItineraryPlan) -> str:
    lines = [f"Berikut rencana perjalanan {len(plan.days)} hari untuk **{plan.destination}**:\n"]
    for day in plan.days:
        lines.append(f"**Hari {day.day}: {day.title}**")
        for act in day.activities:
            lines.append(f"- {act}")
        lines.append("")
    if plan.tips:
        lines.append("**Tips:**")
        for tip in plan.tips:
            lines.append(f"- {tip}")
    return "\n".join(lines)


def _fallback_text(destination: str, ranked_hotels: list) -> str:
    """Jawaban cadangan (tanpa LLM) kalau panggilan LLM untuk merangkum gagal,
    supaya user tetap dapat hasil yang berguna, bukan pesan error mentah."""
    if not ranked_hotels:
        return (
            "Maaf, saya belum menemukan hotel yang cocok dengan kriteria Anda. "
            "Bisa bantu sebutkan kota tujuan, tanggal menginap, atau budget per malam?"
        )

    is_mock = any(h.get("_mock") for h in ranked_hotels)
    is_generic = any(h.get("_mock_generic") for h in ranked_hotels)

    lines = []
    if is_generic:
        lines.append(
            f"Belum ada data hotel live untuk **{destination}** (provider hotel belum "
            "dikonfigurasi/gagal diakses), jadi ini contoh generik saja, BUKAN hotel asli di "
            f"{destination}:\n"
        )
    elif is_mock:
        lines.append(
            f"Belum ada data hotel live yang bisa diakses saat ini, jadi ini contoh untuk "
            f"{destination} (bukan hasil pencarian real-time):\n"
        )
    else:
        lines.append("Berikut beberapa pilihan hotel yang saya temukan:\n")

    for h in ranked_hotels:
        amenities = ", ".join(h.get("amenities", [])) or "-"
        deal_tag = f" 🔥 PROMO ({h['deal_description']})" if h.get("deal") and h.get("deal_description") else (" 🔥 PROMO" if h.get("deal") else "")
        lines.append(
            f"- **{h['name']}**{deal_tag} — ${h['price']:.0f}/malam, rating {h['rating']}⭐, "
            f"± {h['distance_km']} km dari pusat kota. Fasilitas: {amenities}."
        )
        if h.get("vendors"):
            vendor_str = ", ".join(f"{v['vendor']} ${v['price']:.0f}" for v in h["vendors"])
            lines.append(f"  Perbandingan harga per vendor: {vendor_str}")
    top = ranked_hotels[0]
    lines.append(f"\nRekomendasi terbaik: **{top['name']}**, karena kombinasi harga, rating, dan lokasinya paling seimbang.")
    if is_mock:
        lines.append(
            "\n(Untuk hasil live semua kota di dunia, isi SERPAPI_KEY - lihat "
            "https://serpapi.com/manage-api-key)"
        )
    return "\n".join(lines)


def _build_final_answer(user_message: str, destination: str, ranked_hotels: list) -> str:
    """Minta LLM merangkai data hotel yang sudah difilter & diranking menjadi
    jawaban natural berbahasa Indonesia, lengkap dengan perbandingan harga & rekomendasi."""
    def _hotel_line(h):
        vendor_part = ""
        if h.get("vendors"):
            vendor_part = " | harga per vendor: " + ", ".join(
                f"{v['vendor']} ${v['price']:.0f}" for v in h["vendors"]
            )
        amenities_part = f", fasilitas: {', '.join(h.get('amenities', [])) or '-'}" if "amenities" in h else ""
        deal_part = ""
        if h.get("deal"):
            deal_part = f" | SEDANG PROMO ({h['deal_description']})" if h.get("deal_description") else " | SEDANG PROMO"
        return (
            f"- {h['name']} | harga termurah ${h['price']}/malam | rating {h['rating']} | "
            f"jarak {h['distance_km']} km{amenities_part}{vendor_part}{deal_part} | skor kecocokan: {h['final_score']}"
        )

    hotel_block = "\n".join(_hotel_line(h) for h in ranked_hotels) or "(Tidak ada hotel yang cocok dengan kriteria)"

    is_mock = any(h.get("_mock") for h in ranked_hotels)
    is_generic = any(h.get("_mock_generic") for h in ranked_hotels)
    if is_generic:
        data_notice = (
            f"PENTING: Data hotel di atas adalah CONTOH GENERIK (bukan hotel sungguhan di "
            f"{destination}, karena API pencarian hotel live belum berhasil diakses untuk kota "
            "ini). WAJIB sebutkan secara eksplisit di jawabanmu bahwa ini contoh, bukan hasil "
            f"pencarian real untuk {destination}, dan sarankan user mengaktifkan API hotel live "
            "(SERPAPI_KEY) untuk hasil sesungguhnya. Jangan berpura-pura ini hotel asli."
        )
    elif is_mock:
        data_notice = (
            "PENTING: Data hotel di atas adalah data CONTOH (bukan hasil pencarian real-time), "
            "karena API pencarian hotel live belum aktif/gagal diakses. WAJIB sebutkan secara "
            "eksplisit di jawabanmu bahwa ini contoh, bukan data real-time."
        )
    else:
        data_notice = ""

    prompt = f"""Kamu adalah StayWise AI, asisten pencarian hotel yang ramah, ringkas, dan proaktif.

Permintaan pengguna: "{user_message}"

Data hotel yang sudah difilter & diranking sesuai preferensi pengguna (urutan dari yang paling cocok):
{hotel_block}

{data_notice}

Tulis jawaban dalam Bahasa Indonesia dengan format berikut:
1. Satu kalimat pembuka yang menyebutkan kota/tujuan yang kamu pahami.
2. Daftar tiap hotel (gunakan bullet list markdown) berisi: nama, harga termurah per malam, rating, jarak, fasilitas utama (kalau tersedia), dan perbandingan harga antar vendor/OTA kalau datanya ada (mis. Expedia vs Booking.com vs Hotels.com). Kalau ada hotel yang SEDANG PROMO, tonjolkan dengan jelas (mis. emoji 🔥 atau kata "Promo!") beserta keterangan promonya.
3. Perbandingan singkat (misal siapa termurah, siapa rating tertinggi, siapa paling lengkap fasilitasnya, siapa yang sedang promo).
4. Satu rekomendasi akhir beserta alasannya - kalau ada hotel bagus yang juga sedang promo, prioritaskan itu di rekomendasi.
Jika data hotel kosong, minta info tambahan (kota, tanggal, atau budget) dengan sopan.
Jangan mengarang fakta di luar data yang diberikan. Jangan tampilkan JSON mentah. Maksimal sekitar 180-220 kata."""

    try:
        llm = get_llm_client()
        response = llm.generate(prompt, json_mode=False)
        text = (response.text or "").strip()
        return text if text else _fallback_text(destination, ranked_hotels)
    except Exception as e:
        print(f"[chat_pipeline] Gagal merangkum jawaban lewat LLM: {e}")
        return _fallback_text(destination, ranked_hotels)


async def run_chat_pipeline(message: str, session_id: Optional[str] = None) -> dict:
    """Satu fungsi ini menjalankan seluruh alur chat StayWise AI (parsing ->
    cari/filter hotel -> ranking -> jawaban, ATAU cabang ke itinerary), dan
    dipakai baik oleh endpoint FastAPI maupun Streamlit. Return-nya berbentuk
    dict dengan key yang sama persis seperti ChatResponse:
    response, hotels, recommended_hotel_id, session_id, itinerary
    """
    # 0. Ambil (atau buat baru) sesi percakapan.
    session_id, session_ctx = get_or_create_session(session_id)
    context = {"filters": session_ctx.filters, "last_hotels": session_ctx.last_hotels}

    # 1. Pahami permintaan user, digabung dengan konteks sesi sebelumnya.
    filters = query_agent.process(message, context=context)

    # 1b. Cabang ke itinerary kalau itu yang diminta.
    if _is_itinerary_request(message):
        if not filters.destination:
            return {
                "response": (
                    "Tentu, saya bisa bantu susun itinerary! Untuk kota/destinasi mana? "
                    "(misalnya: Jogja, Bali, Bandung)"
                ),
                "hotels": [], "recommended_hotel_id": None,
                "session_id": session_id, "itinerary": None,
            }

        days = _extract_days(message, session_ctx.filters)
        hotel_name = session_ctx.last_hotels[0]["name"] if session_ctx.last_hotels else None
        plan = itinerary_agent.plan(
            destination=filters.destination, days=days,
            hotel_name=hotel_name, interests=filters.preferred or None,
        )
        response_text = _format_itinerary_text(plan)
        update_session(session_id, filters.model_dump(), session_ctx.last_hotels)
        return {
            "response": response_text, "hotels": [], "recommended_hotel_id": None,
            "session_id": session_id, "itinerary": [d.model_dump() for d in plan.days],
        }

    # 2. Tidak ada destinasi -> tanya balik.
    if not filters.destination:
        return {
            "response": (
                "Tentu, saya bisa bantu cari hotel! Boleh sebutkan kota/destinasi tujuan Anda? "
                "(misalnya: Jogja, Bali, Bandung, atau Jakarta)"
            ),
            "hotels": [], "recommended_hotel_id": None,
            "session_id": session_id, "itinerary": None,
        }

    # 3. Ambil kandidat hotel.
    raw_hotels = await hotel_client.fetch_hotels(
        destination=filters.destination,
        check_in=filters.check_in or "2026-08-01",
        check_out=filters.check_out or "2026-08-05",
        rooms=filters.rooms or 1,
        adults=filters.guests or 2,
        currency=filters.currency or "USD",
    )

    # 4. Saring berdasarkan budget & fasilitas wajib.
    candidates = raw_hotels
    if filters.budget:
        within_budget = [h for h in candidates if h["price"] <= filters.budget]
        candidates = within_budget or candidates

    if filters.required:
        required = set(a.lower() for a in filters.required)
        matching = [
            h for h in candidates
            if "amenities" not in h
            or required.issubset(set(a.lower() for a in h.get("amenities", [])))
        ]
        candidates = matching or candidates

    # 5. Bobot ranking.
    weights = ranking_agent.determine_weights(filters.model_dump())

    # 6. Skor & urutkan.
    desired_amenities = list(filters.required) + list(filters.preferred)
    ranked = calculate_hotel_scores(
        candidates, weights.model_dump(),
        max_budget=filters.budget or 150.0, desired_amenities=desired_amenities,
    )

    # 7. Jawaban akhir.
    response_text = _build_final_answer(message, filters.destination, ranked)
    clean_hotels = [{k: v for k, v in h.items() if not k.startswith("_")} for h in ranked]

    # 8. Simpan konteks sesi.
    update_session(session_id, filters.model_dump(), clean_hotels)

    return {
        "response": response_text,
        "hotels": clean_hotels,
        "recommended_hotel_id": ranked[0]["id"] if ranked else None,
        "session_id": session_id,
        "itinerary": None,
    }
