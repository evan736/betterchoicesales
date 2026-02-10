from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from app.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    role: str = "producer"


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    producer_code: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    producer_code: Optional[str] = None
    commission_tier: Optional[int] = None
    is_active: Optional[bool] = None


class UserInDB(UserBase):
    id: int
    producer_code: Optional[str]
    commission_tier: int
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class User(UserInDB):
    pass


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[int] = None
