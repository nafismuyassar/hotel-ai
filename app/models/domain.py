from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db.session import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Hotel(Base):
    __tablename__ = "hotels"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    destination = Column(String, index=True)
    base_price = Column(Float)
    rating = Column(Float)
    provider = Column(String)

class SearchHistory(Base):
    __tablename__ = "search_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    query = Column(String)
    parsed_filters = Column(JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class SavedHotel(Base):
    __tablename__ = "saved_hotels"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    hotel_id = Column(String, ForeignKey("hotels.id"))
    saved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    type = Column(String)
    message = Column(String)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class PromotionHistory(Base):
    __tablename__ = "promotion_history"
    id = Column(Integer, primary_key=True, index=True)
    hotel_id = Column(String, ForeignKey("hotels.id"))
    old_price = Column(Float)
    new_price = Column(Float)
    detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
