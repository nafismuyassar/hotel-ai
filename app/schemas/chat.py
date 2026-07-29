from pydantic import BaseModel
from typing import List, Optional

class ChatRequest(BaseModel):
    message: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    hotels: List[dict] = []
    recommended_hotel_id: Optional[str] = None
    session_id: str
    itinerary: Optional[List[dict]] = None
