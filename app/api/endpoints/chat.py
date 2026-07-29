from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_pipeline import run_chat_pipeline

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat_with_agent(request: ChatRequest, db: Session = Depends(get_db)):
    result = await run_chat_pipeline(request.message, request.session_id)
    return ChatResponse(**result)
