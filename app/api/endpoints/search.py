from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse
from app.agents.ranking_agent import SmartRankingAgent
from app.services.scoring import calculate_hotel_scores
from app.integrations.provider import get_hotel_client
from app.core.config import settings

router = APIRouter()

ranking_agent = SmartRankingAgent()
makcorps_client = get_hotel_client()


@router.post("/", response_model=SearchResponse)
async def search_hotels(request: SearchRequest, db: Session = Depends(get_db)):
    # 1. Ambil daftar kandidat hotel (live MakCorps kalau API key valid, mock kalau tidak;
    #    ganti/override endpoint di app/integrations/makcorps.py kalau perlu)
    raw_hotels = await makcorps_client.fetch_hotels(
        destination=request.destination,
        check_in=request.check_in,
        check_out=request.check_out,
        adults=request.guests or 2,
    )

    # 2. Saring berdasarkan budget & fasilitas wajib
    candidates = raw_hotels
    if request.budget:
        within_budget = [h for h in candidates if h["price"] <= request.budget]
        candidates = within_budget or candidates

    if request.required_amenities:
        required = set(a.lower() for a in request.required_amenities)
        matching = [
            h for h in candidates
            if "amenities" not in h  # data live: fasilitas belum diketahui, jangan langsung dibuang
            or required.issubset(set(a.lower() for a in h.get("amenities", [])))
        ]
        candidates = matching or candidates

    # 3. Tentukan bobot ranking berdasarkan filter yang diberikan
    weights = ranking_agent.determine_weights(request.model_dump())

    # 4. Hitung skor & urutkan
    desired_amenities = list(request.required_amenities) + list(request.preferred_amenities)
    ranked = calculate_hotel_scores(
        candidates,
        weights.model_dump(),
        max_budget=request.budget or 150.0,
        desired_amenities=desired_amenities,
    )

    return SearchResponse(results=ranked, total_found=len(ranked))
