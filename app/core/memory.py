"""
Penyimpanan konteks percakapan sederhana (in-memory), supaya user bisa lanjut
ngobrol tanpa mengulang info yang sudah disebut sebelumnya - mis:
  User: "cari hotel jogja"
  AI:   [hasil hotel Jogja]
  User: "yang ada kolam renang"   <- tidak perlu sebut "jogja" lagi
  AI:   [hasil hotel Jogja YANG ADA kolam renang]

CATATAN KETERBATASAN (jujur, biar tidak salah ekspektasi):
- Disimpan di memori proses Python, BUKAN database. Artinya hilang kalau
  server di-restart, dan TIDAK cocok kalau nanti dijalankan multi-worker/multi-
  instance (tiap worker punya memori sendiri-sendiri, jadi user bisa "kehilangan
  ingatan" kalau request-nya kebetulan dilempar ke worker lain).
- Cukup untuk MVP/single-instance dev server (`uvicorn app.main:app --reload`).
  Kalau nanti mau production multi-worker, ganti jadi Redis atau tabel database
  (skema `app/models/domain.py` sudah ada, tinggal dipakai).
- Sesi lama tidak otomatis dibersihkan (bisa jadi memory leak kalau server
  jalan lama dengan banyak user unik) - MAX_SESSIONS di bawah membatasi ini
  secara kasar dengan membuang sesi terlama kalau sudah kepenuhan.
"""
import uuid
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field

MAX_SESSIONS = 500  # batas kasar supaya tidak membengkak tanpa henti di dev server


@dataclass
class SessionContext:
    filters: dict = field(default_factory=dict)  # ExtractedFilters terakhir (destinasi, budget, dst)
    last_hotels: List[dict] = field(default_factory=list)  # ringkasan hotel terakhir yang ditampilkan
    updated_at: float = field(default_factory=time.time)


_sessions: Dict[str, SessionContext] = {}


def get_or_create_session(session_id: Optional[str]) -> tuple[str, SessionContext]:
    if session_id and session_id in _sessions:
        ctx = _sessions[session_id]
        ctx.updated_at = time.time()
        return session_id, ctx

    # session_id baru (atau tidak dikenal, mis. server sempat restart) -> mulai fresh
    new_id = session_id or str(uuid.uuid4())
    if len(_sessions) >= MAX_SESSIONS:
        oldest_id = min(_sessions, key=lambda k: _sessions[k].updated_at)
        del _sessions[oldest_id]
    ctx = SessionContext()
    _sessions[new_id] = ctx
    return new_id, ctx


def update_session(session_id: str, filters: dict, hotels: List[dict]) -> None:
    ctx = _sessions.get(session_id)
    if ctx is None:
        ctx = SessionContext()
        _sessions[session_id] = ctx
    ctx.filters = filters
    ctx.last_hotels = [
        {"name": h.get("name"), "price": h.get("price"), "rating": h.get("rating")}
        for h in hotels[:5]
    ]
    ctx.updated_at = time.time()
