import json
from typing import List, Optional
from pydantic import BaseModel, Field
from app.core.llm_client import get_llm_client


class DayPlan(BaseModel):
    day: int
    title: str
    activities: List[str]


class ItineraryPlan(BaseModel):
    destination: str
    days: List[DayPlan]
    tips: List[str] = Field(default_factory=list)


class ItineraryPlannerAgent:
    def __init__(self, llm_client=None):
        # Client dibuat lazy di plan(), sama seperti agent lain, supaya kalau LLM
        # gagal, errornya tertangkap try/except dan jatuh ke fallback generik -
        # bukan crash.
        self._llm_client = llm_client
        self.system_prompt = """You are an expert local travel guide AI.
Create a practical, realistic day-by-day itinerary in Bahasa Indonesia for the
given destination and number of days.
Output ONLY valid JSON matching this schema exactly. Do not add markdown formatting.
Schema:
{
  "destination": "string",
  "days": [
    {"day": 1, "title": "short theme for the day, e.g. 'Wisata Sejarah & Kuliner'",
     "activities": ["Pagi: kunjungi Candi Borobudur", "Siang: makan gudeg di ...", "..."]}
  ],
  "tips": ["1-3 practical local tips: transportasi, waktu terbaik berkunjung, dsb."]
}
Rules:
- Each day needs 3-5 concrete activities, roughly ordered Pagi/Siang/Sore/Malam.
- Use REAL, well-known place/food names for that specific destination - not
  generic placeholders like "local attraction" or "popular restaurant".
- Keep total days exactly matching the number requested."""

    def plan(
        self,
        destination: str,
        days: int,
        hotel_name: Optional[str] = None,
        interests: Optional[List[str]] = None,
    ) -> ItineraryPlan:
        try:
            llm = self._llm_client or get_llm_client()
            context_bits = []
            if hotel_name:
                context_bits.append(f"User is staying at: {hotel_name} (factor in rough proximity if you know the area).")
            if interests:
                context_bits.append(f"User's stated interests: {', '.join(interests)}")
            context_str = ("\n" + "\n".join(context_bits)) if context_bits else ""

            prompt = (
                f"{self.system_prompt}\n\n"
                f"Destination: {destination}\nNumber of days: {days}{context_str}"
            )
            response = llm.generate(prompt, json_mode=True)
            data = json.loads(response.text)
            data = {k: v for k, v in data.items() if v is not None}
            plan = ItineraryPlan(**data)
            # Jaga-jaga kalau LLM ngasih jumlah hari yang beda dari yang diminta.
            if len(plan.days) != days:
                plan.days = plan.days[:days] if len(plan.days) > days else plan.days
            return plan
        except Exception as e:
            print(f"[ItineraryPlannerAgent] Gagal memanggil LLM: {e}")
            return self._fallback_plan(destination, days)

    def _fallback_plan(self, destination: str, days: int) -> ItineraryPlan:
        """Template generik kalau LLM gagal - sengaja jujur bilang ini generik,
        bukan berpura-pura tahu tempat spesifik di kota itu (menghindari 'ngawur')."""
        day_plans = [
            DayPlan(
                day=d,
                title=f"Eksplorasi {destination} - Hari {d}",
                activities=[
                    "Pagi: sarapan & jalan santai di sekitar penginapan",
                    f"Siang: kunjungi salah satu tempat wisata populer di {destination}",
                    "Sore: waktu bebas / belanja oleh-oleh khas daerah",
                    "Malam: coba kuliner khas setempat",
                ],
            )
            for d in range(1, days + 1)
        ]
        return ItineraryPlan(
            destination=destination,
            days=day_plans,
            tips=[
                "Rencana ini masih generik karena AI sedang tidak bisa diakses - "
                "cek ulasan/peta lokal untuk rekomendasi tempat yang lebih spesifik."
            ],
        )
