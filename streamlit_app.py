"""
StayWise AI - versi Streamlit, supaya bisa diakses publik gratis lewat
Streamlit Community Cloud (share.streamlit.io) tanpa perlu hosting FastAPI
terpisah.

Jalan LANGSUNG memanggil app/services/chat_pipeline.py sebagai fungsi Python
biasa (tanpa lewat HTTP/network sama sekali) - jadi logikanya identik 100%
dengan versi FastAPI+HTML (app/api/endpoints/chat.py), tidak ada kode yang
diduplikasi.

Cara jalan LOKAL:
    pip install -r requirements.txt
    streamlit run streamlit_app.py

Cara deploy PUBLIK (gratis):
    1. Push project ini ke GitHub (public atau private repo).
    2. Buka https://share.streamlit.io -> "New app" -> pilih repo ini,
       branch, dan file "streamlit_app.py".
    3. Di menu "Advanced settings" -> "Secrets", isi API key yang kamu
       pakai, formatnya TOML, contoh:

           GROQ_API_KEY = "gsk_xxxxxxxxxxxx"
           SERPAPI_KEY = "xxxxxxxxxxxx"

       (Jangan commit file .env asli ke GitHub! Secrets Streamlit ini
       terpisah dan aman, tidak akan terlihat publik.)
    4. Klik "Deploy". Beberapa menit kemudian dapat URL publik gratis,
       contoh: https://staywise-ai.streamlit.app
"""
import asyncio
import os

import streamlit as st

# --- Salin Streamlit secrets ke os.environ SEBELUM import apapun dari `app.` ---
# Kenapa: app/core/config.py baca API key lewat os.environ/python-dotenv (dipakai
# bareng juga oleh versi FastAPI). Streamlit Cloud simpan secrets di st.secrets,
# BUKAN otomatis di os.environ - jadi kita jembatani manual di sini supaya
# app/core/config.py tidak perlu tahu/berubah sama sekali (satu sumber kebenaran
# untuk konfigurasi, dipakai baik oleh FastAPI maupun Streamlit).
if hasattr(st, "secrets"):
    try:
        for key, value in st.secrets.items():
            if key not in os.environ:  # .env/environment asli tetap diutamakan kalau ada
                os.environ[key] = str(value)
    except Exception:
        pass  # tidak ada secrets.toml (mis. waktu run lokal pakai .env biasa) - tidak masalah

from app.services.chat_pipeline import run_chat_pipeline  # noqa: E402

st.set_page_config(page_title="StayWise AI", page_icon="🏨", layout="centered")

st.title("🏨 StayWise AI")
st.caption("Asisten pencarian hotel & perencana perjalanan")

if "messages" not in st.session_state:
    st.session_state.messages = []  # riwayat chat untuk ditampilkan di layar
if "session_id" not in st.session_state:
    st.session_state.session_id = None  # token yang dipakai backend buat "ingat" konteks


def render_hotel_card(hotel: dict, is_best: bool):
    deal = hotel.get("deal")
    title = f"**{hotel['name']}**"
    if is_best:
        title += " 🏆 Rekomendasi"
    if deal:
        title += " 🔥 Promo"

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(title)
            amenities = hotel.get("amenities")
            meta = f"⭐ {hotel['rating']} · {hotel['distance_km']} km dari pusat"
            if amenities:
                meta += f" · {', '.join(amenities)}"
            st.caption(meta)
            if deal and hotel.get("deal_description"):
                st.caption(f"🔥 {hotel['deal_description']}")
            if hotel.get("vendors"):
                vendor_str = " • ".join(f"{v['vendor']} ${v['price']:.0f}" for v in hotel["vendors"])
                st.caption(f"Perbandingan vendor: {vendor_str}")
        with col2:
            st.markdown(f"### ${hotel['price']:.0f}")
            st.caption("/malam")
            lat, lng = hotel.get("latitude"), hotel.get("longitude")
            if lat is not None and lng is not None:
                maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
            else:
                maps_url = f"https://www.google.com/maps/search/?api=1&query={hotel['name']}"
            st.link_button("📍 Buka Maps", maps_url, use_container_width=True)


def render_itinerary(itinerary: list):
    for day in itinerary:
        with st.container(border=True):
            st.markdown(f"**Hari {day['day']}: {day['title']}**")
            for act in day.get("activities", []):
                st.markdown(f"- {act}")


def render_message(msg: dict):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("hotels"):
            best_id = msg.get("recommended_hotel_id")
            for h in msg["hotels"]:
                render_hotel_card(h, is_best=(h.get("id") == best_id))
        if msg.get("itinerary"):
            render_itinerary(msg["itinerary"])


# Render ulang seluruh riwayat chat tiap kali script Streamlit dijalankan ulang
for msg in st.session_state.messages:
    render_message(msg)

prompt = st.chat_input("Ketik pesan Anda di sini... (mis. \"cari hotel jogja budget $60\")")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Mencari..."):
            result = asyncio.run(run_chat_pipeline(prompt, st.session_state.session_id))

        st.session_state.session_id = result["session_id"]
        st.markdown(result["response"])
        if result.get("hotels"):
            for h in result["hotels"]:
                render_hotel_card(h, is_best=(h.get("id") == result.get("recommended_hotel_id")))
        if result.get("itinerary"):
            render_itinerary(result["itinerary"])

    st.session_state.messages.append({
        "role": "assistant",
        "content": result["response"],
        "hotels": result.get("hotels"),
        "recommended_hotel_id": result.get("recommended_hotel_id"),
        "itinerary": result.get("itinerary"),
    })

with st.sidebar:
    st.subheader("Percakapan Baru")
    if st.button("🔄 Mulai Ulang", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_id = None
        st.rerun()
    st.divider()
    st.caption(
        "StayWise AI mencari & membandingkan hotel, plus bisa susun itinerary "
        "perjalanan. Coba: \"cari hotel bali budget $80 ada kolam renang\" atau "
        "\"buatkan itinerary 3 hari di jogja\"."
    )
