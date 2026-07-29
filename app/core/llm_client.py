"""
Wrapper LLM tipis di atas Groq, supaya agent (query_agent, ranking_agent, chat.py)
tidak perlu tahu detail request/response API-nya - cukup panggil
llm.generate(prompt, json_mode=...) -> punya .text.

Groq dipilih (bukan Gemini) karena: gratis, cepat, signup email/Google tanpa
kartu kredit, dan API-nya kompatibel format OpenAI. Daftar & ambil key di
https://console.groq.com/keys
"""
from app.core.config import settings


class LLMResult:
    def __init__(self, text: str):
        self.text = text


class GroqLLM:
    """Groq pakai endpoint yang kompatibel format OpenAI (chat completions),
    jadi tidak perlu SDK khusus - cukup httpx biasa.
    Dokumentasi: https://console.groq.com/docs/quickstart"""

    def generate(self, prompt: str, json_mode: bool = False) -> LLMResult:
        import httpx
        if not settings.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY belum diisi di .env. Daftar gratis di "
                "https://console.groq.com lalu ambil key di https://console.groq.com/keys"
            )
        payload = {
            "model": settings.GROQ_MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        if json_mode:
            # Groq (seperti OpenAI) mewajibkan kata "json" muncul di pesan supaya
            # response_format json_object bisa dipakai - prompt kita sudah selalu
            # menyebut "JSON" secara eksplisit jadi ini aman.
            payload["response_format"] = {"type": "json_object"}

        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return LLMResult(text)


def get_llm_client():
    return GroqLLM()
