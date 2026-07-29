from pydantic import BaseModel
from typing import List, Optional

class SearchRequest(BaseModel):
    destination: str
    check_in: str
    check_out: str
    guests: int
    budget: Optional[float] = None
    required_amenities: List[str] = []
    preferred_amenities: List[str] = []

class SearchResponse(BaseModel):
    results: List[dict]
    total_found: int
