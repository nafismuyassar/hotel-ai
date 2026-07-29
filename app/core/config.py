import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv() # Memaksa memuat file .env

class Settings(BaseSettings):
    PROJECT_NAME: str = "StayWise AI"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # LLM: Groq (gratis, cepat, signup email/Google tanpa kartu kredit).
    # Daftar & ambil key di https://console.groq.com/keys
    GROQ_API_KEY: str = ""
    GROQ_MODEL_NAME: str = "llama-3.3-70b-versatile"
    MAKCORPS_API_KEY: str = ""
    BOOKING_API_KEY: str = ""
    # X-RapidAPI-Key dari dashboard RapidAPI-mu (rapidapi.com/developer/dashboard).
    # Satu key ini berlaku untuk SEMUA API yang kamu subscribe di RapidAPI
    # (termasuk MakCorps & Booking.com yang host-nya sudah ada di MAKCORPS_API_KEY
    # / BOOKING_API_KEY). Dipakai kalau kamu memilih jalur RapidAPI, bukan
    # signup langsung ke makcorps.com.
    RAPIDAPI_KEY: str = ""
    # Alternatif lain di luar MakCorps: SerpApi (Google Hotels). Signup email biasa,
    # tanpa kartu kredit, 250 pencarian gratis/bulan. Kalau ini diisi, dipakai
    # duluan (lihat app/integrations/provider.py) karena datanya paling lengkap.
    SERPAPI_KEY: str = ""
    
    # Database
    DATABASE_URL: str = "sqlite:///./staywise.db"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
