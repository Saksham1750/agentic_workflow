from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth.jwt_handler import create_access_token
from src.auth.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

_users: dict[str, dict] = {}


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=100)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


class UserResponse(BaseModel):
    user_id: str
    username: str
    created_at: str


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest):
    for uid, user in _users.items():
        if user["username"] == body.username:
            raise HTTPException(status_code=409, detail="Username already exists")

    import uuid
    user_id = str(uuid.uuid4())
    _users[user_id] = {
        "username": body.username,
        "password": body.password,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return UserResponse(user_id=user_id, username=body.username, created_at=_users[user_id]["created_at"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    for uid, user in _users.items():
        if user["username"] == body.username and user["password"] == body.password:
            token = create_access_token(subject=uid, extra={"username": body.username})
            return TokenResponse(access_token=token, user_id=uid)

    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/me", response_model=UserResponse)
async def me(user_id: str = Depends(get_current_user)):
    user = _users.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(user_id=user_id, username=user["username"], created_at=user["created_at"])
