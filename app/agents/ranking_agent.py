import json
from pydantic import BaseModel, Field
from app.core.llm_client import get_llm_client

class RankingWeights(BaseModel):
    price: float = Field(..., description="Weight for price (0.0 to 1.0)")
    rating: float = Field(..., description="Weight for review rating (0.0 to 1.0)")
    distance: float = Field(..., description="Weight for distance to center/beach (0.0 to 1.0)")
    amenities: float = Field(..., description="Weight for matching amenities (0.0 to 1.0)")

class SmartRankingAgent:
    def __init__(self, llm_client=None):
        # Client dibuat lazy di determine_weights(), lihat catatan yang sama di query_agent.py
        self._llm_client = llm_client
        self.system_prompt = """
You are a Smart Ranking Agent for a hotel booking platform.
Based on the user's parsed query filters and preferences, determine the relative importance (weights) for:
- price
- rating
- distance
- amenities

The weights MUST sum to exactly 1.0.
Output ONLY valid JSON matching this schema. Do not add markdown formatting.
Schema:
{
  "price": 0.40,
  "rating": 0.30,
  "distance": 0.20,
  "amenities": 0.10
}
"""

    def determine_weights(self, user_filters: dict) -> RankingWeights:
        try:
            llm = self._llm_client or get_llm_client()
            full_prompt = f"{self.system_prompt}\n\nUser Filters: {json.dumps(user_filters)}"

            response = llm.generate(full_prompt, json_mode=True)

            data = json.loads(response.text)
            return RankingWeights(**data)

        except Exception as e:
            # Fallback mock if LLM is invalid or errors out
            print(f"Ranking Agent Error: {e}")
            return RankingWeights(
                price=0.25,
                rating=0.25,
                distance=0.25,
                amenities=0.25
            )
