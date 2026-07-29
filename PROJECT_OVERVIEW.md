# StayWise AI — Dokumentasi Project

Asisten pencarian hotel & perencana perjalanan berbasis AI, dengan arsitektur
multi-agent, memori percakapan, dan integrasi data hotel live.

---

## 1. Gambaran Umum

StayWise AI adalah aplikasi chat berbasis web tempat pengguna bisa:
- Mencari & membandingkan hotel dalam bahasa natural ("cari hotel jogja budget $60 ada kolam renang")
- Melanjutkan percakapan tanpa mengulang info ("yang ada wifi" setelah sudah sebut kota)
- Meminta rencana perjalanan harian ("buatkan itinerary 3 hari")

Semua permintaan diproses lewat satu endpoint chat yang di baliknya menjalankan
beberapa **agent** (komponen AI dengan tugas spesifik) secara berurutan.

---

## 2. Arsitektur & Alur Kerja

```
User mengetik pesan
       │
       ▼
┌─────────────────────┐
│  Session Memory      │  ← ambil konteks sesi sebelumnya (destinasi, budget, dst.)
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│  Query Understanding │  ← pahami pesan + gabung dengan konteks sesi
│  Agent               │
└─────────┬────────────┘
          │
          ├── Kalau minta itinerary? ──► Itinerary Planner Agent ──► jawaban
          │
          ▼ (kalau cari hotel)
┌─────────────────────┐
│  Hotel Data Provider  │  ← SerpApi / MakCorps / data contoh (mock)
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│  Filter (budget,      │
│  fasilitas wajib)     │
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│  Smart Ranking Agent │  ← tentukan bobot: harga vs rating vs jarak vs fasilitas
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│  Scoring & Ranking    │  ← hitung skor akhir tiap hotel, urutkan
└─────────┬────────────┘
          ▼
┌─────────────────────┐
│  Jawaban akhir (LLM)  │  ← rangkai jadi teks natural + kartu hotel
└─────────┬────────────┘
          ▼
   Simpan ke Session Memory (untuk follow-up berikutnya)
          ▼
     Jawaban ke user
```

---

## 3. Agent-Agent yang Ada

### 3.1 Query Understanding Agent
`app/agents/query_agent.py`

Mengubah kalimat bebas jadi data terstruktur: destinasi, tanggal, jumlah tamu,
budget, fasilitas wajib/opsional. Kalau LLM gagal dipanggil, ada fallback
berbasis kata kunci (kota-kota umum di Indonesia, kata kunci fasilitas, pola
angka untuk budget) supaya aplikasi tetap bisa jalan tanpa AI.

### 3.2 Smart Ranking Agent
`app/agents/ranking_agent.py`

Menentukan seberapa penting harga, rating, jarak, dan fasilitas dalam
mengurutkan hasil, berdasarkan apa yang tersirat dari permintaan user (mis.
kalau user sebut budget ketat, bobot harga dinaikkan). Fallback: bobot rata
(25% masing-masing) kalau LLM gagal.

### 3.3 Itinerary Planner Agent
`app/agents/itinerary_agent.py`

Menyusun rencana perjalanan harian (tema per hari + 3-5 aktivitas realistis
dengan nama tempat asli, plus tips lokal) begitu pengguna minta itinerary.
Aktif lewat deteksi kata kunci ("itinerary", "rencana perjalanan", "susun
jadwal", dst.) dan otomatis pakai destinasi dari sesi sebelumnya kalau tidak
disebut ulang. Fallback: template generik yang jujur bilang "ini contoh
generik" kalau LLM tidak bisa diakses (tidak berpura-pura tahu tempat
spesifik).

### 3.4 Session Memory (bukan agent LLM, tapi bagian penting dari "ingatan")
`app/core/memory.py`

Menyimpan konteks percakapan (destinasi, budget, fasilitas, hotel yang
terakhir ditampilkan) per sesi, supaya follow-up seperti "yang lebih murah"
atau "yang ada gym" tidak perlu mengulang seluruh permintaan.
**Keterbatasan:** disimpan di memori proses (bukan database) → hilang kalau
server di-restart, dan tidak cocok untuk multi-worker production tanpa
diganti ke Redis/database.

---

## 4. Otak AI (LLM)

**Provider: Groq** — `app/core/llm_client.py`
- Model: `llama-3.3-70b-versatile`
- Gratis, cepat, API kompatibel format OpenAI
- Butuh `GROQ_API_KEY` di `.env` (daftar di console.groq.com, tanpa kartu kredit)
- Dipakai di ketiga agent LLM di atas (Query Understanding, Smart Ranking, Itinerary Planner) dan penulisan jawaban akhir

Kalau `GROQ_API_KEY` kosong atau gagal, setiap bagian punya fallback masing-masing
(kata kunci untuk pemahaman query, bobot rata untuk ranking, template generik
untuk itinerary) — aplikasi tidak pernah benar-benar mati total.

---

## 5. Sumber Data Hotel

`app/integrations/provider.py` memilih otomatis, urutan prioritas:

| # | Provider | File | Butuh | Cakupan |
|---|---|---|---|---|
| 1 | **SerpApi** (Google Hotels) | `serpapi_hotels.py` | `SERPAPI_KEY` | Semua kota di dunia + fasilitas + rating + **perbandingan harga antar vendor OTA** + **info promo/diskon** + koordinat GPS |
| 2 | **MakCorps** | `makcorps.py` | `MAKCORPS_API_KEY` (langsung) atau `RAPIDAPI_KEY` (via RapidAPI) | Perbandingan harga antar vendor, tanpa data fasilitas |
| 3 | **Data contoh (mock)** | — | — | 4 kota (Jogja/Bali/Bandung/Jakarta) + placeholder generik untuk kota lain, selalu diberi label jujur "ini contoh" di jawaban |

Setiap hotel yang dikembalikan API punya bentuk data seragam terlepas dari
provider mana yang aktif: `id`, `name`, `price`, `rating`, `distance_km`,
`amenities` (kalau tersedia), `vendors` (perbandingan harga per OTA, kalau
tersedia), `latitude`/`longitude` (untuk link Google Maps), `deal`/
`deal_description` (info promo, khusus SerpApi).

---

## 6. Fitur-Fitur di Frontend

`frontend/index.html` — HTML+JS statis, tanpa framework.

- **Chat UI** ala aplikasi pesan, dengan avatar user/AI
- **Kartu hotel** — nama, harga, rating, jarak, fasilitas, perbandingan harga
  per vendor, badge **"Rekomendasi"** untuk hotel terbaik, badge **🔥 Promo**
  kalau sedang diskon
- **Klik kartu hotel → buka Google Maps** langsung ke lokasinya (atau cari
  berdasarkan nama kalau tidak ada koordinat, mis. data mock)
- **Kartu itinerary** — timeline harian dengan tema + daftar aktivitas per hari
- Markdown ringan di jawaban (bold, bullet list) dirender jadi HTML rapi,
  bukan teks/JSON mentah

---

## 7. Struktur Folder

```
staywise-ai/
├── app/
│   ├── agents/              # 3 agent LLM (query, ranking, itinerary)
│   ├── api/endpoints/       # chat.py (endpoint utama), search.py
│   ├── core/
│   │   ├── config.py        # baca .env
│   │   ├── llm_client.py    # wrapper Groq
│   │   └── memory.py        # session/conversation memory
│   ├── integrations/        # provider.py (selector), serpapi_hotels.py, makcorps.py
│   ├── services/scoring.py  # hitung skor & ranking hotel
│   ├── schemas/              # skema request/response (Pydantic)
│   ├── models/                # skema tabel database (belum banyak dipakai)
│   ├── db/                    # koneksi SQLite
│   └── main.py                # entry point FastAPI
├── frontend/index.html      # chat UI
├── requirements.txt
└── .env                       # semua API key & konfigurasi
```

---

## 8. Environment Variables (`.env`)

| Variabel | Untuk apa | Wajib? |
|---|---|---|
| `GROQ_API_KEY` | Otak AI (pemahaman bahasa, ranking, itinerary, jawaban akhir) | Sangat disarankan — tanpa ini semua fallback non-AI yang jalan |
| `SERPAPI_KEY` | Data hotel live, semua kota, + promo + perbandingan vendor | Disarankan — tanpa ini cuma dapat data contoh 4 kota |
| `MAKCORPS_API_KEY` / `RAPIDAPI_KEY` | Alternatif data hotel (dipakai kalau `SERPAPI_KEY` kosong) | Opsional |
| `BOOKING_API_KEY` | Sisa dari draft awal, **tidak dipakai di kode manapun** | Bisa diabaikan/dihapus |
| `DATABASE_URL` | Lokasi file SQLite | Sudah ada default, tidak perlu diubah |

---

## 9. Cara Menjalankan (lokal)

```bash
cd staywise-ai
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Buka `http://127.0.0.1:8000/chat-ui`

---

## 9b. Cara Deploy Publik (Gratis, via Streamlit Community Cloud)

Ada `streamlit_app.py` di root project — versi UI Streamlit yang memanggil
logika chat yang **sama persis** dengan versi FastAPI+HTML (lewat
`app/services/chat_pipeline.py`, jadi tidak ada kode yang diduplikasi).

**Coba lokal dulu:**
```bash
streamlit run streamlit_app.py
```

**Deploy publik (gratis):**
1. Push seluruh folder `staywise-ai` ke repo GitHub (`.gitignore` sudah
   disiapkan supaya `.env` asli tidak ikut ter-push)
2. Buka https://share.streamlit.io → **"New app"** → pilih repo, branch, dan
   file `streamlit_app.py`
3. Di **"Advanced settings" → "Secrets"**, isi API key yang kamu pakai
   (format TOML):
   ```toml
   GROQ_API_KEY = "gsk_xxxxxxxxxxxx"
   SERPAPI_KEY = "xxxxxxxxxxxx"
   ```
4. Klik **"Deploy"** — beberapa menit kemudian dapat URL publik gratis,
   contoh: `https://staywise-ai.streamlit.app`

**Alternatif lain** (kalau tetap mau pakai frontend HTML yang sudah ada,
bukan Streamlit): deploy `app/main.py` (FastAPI) ke layanan seperti
Render.com, Railway, atau Fly.io (semuanya punya free tier) — tapi perlu
sedikit penyesuaian CORS & environment variable di platform tersebut,
sementara jalur Streamlit di atas sudah langsung siap pakai tanpa penyesuaian
tambahan.

---

## 10. Batasan yang Perlu Diketahui (jujur, biar tidak salah ekspektasi)

- **Session memory** disimpan di memori proses, bukan database — hilang kalau
  server di-restart, dan tidak aman untuk multi-worker/production tanpa
  diupgrade ke Redis/DB.
- **Belum ada fitur booking sungguhan** — ini murni pencarian & rekomendasi,
  bukan yang bisa memesan kamar.
- **Data mock** (kalau `SERPAPI_KEY`/`MAKCORPS_API_KEY` kosong) hanya realistis
  untuk 4 kota contoh; kota lain dapat placeholder generik yang selalu diberi
  label jujur, bukan hasil pencarian nyata.
- **Promo/deal** hanya tersedia lewat SerpApi, dan tidak semua hotel selalu
  ada info promonya dari Google (tidak dipaksakan/di-fake kalau memang tidak ada).
- Belum ada autentikasi/akun user — `user_id` di schema ada tapi belum
  dipakai fungsinya.
