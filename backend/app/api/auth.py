from datetime import timedelta
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user
)
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate, User as UserSchema, Token

logger = logging.getLogger(__name__)

# Rate limiter — keyed by IP address
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/register", response_model=UserSchema)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    # Check if user exists
    existing_user = db.query(User).filter(
        (User.email == user_data.email) | (User.username == user_data.username)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email or username already exists"
        )
    
    # Create user
    user = User(
        email=user_data.email,
        username=user_data.username,
        full_name=user_data.full_name,
        hashed_password=get_password_hash(user_data.password),
        role=user_data.role,
        producer_code=user_data.producer_code
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login and get access token"""
    user = db.query(User).filter(func.lower(User.username) == form_data.username.lower().strip()).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning(f"Failed login attempt for username: {form_data.username} from {get_remote_address(request)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserSchema)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user


@router.post("/forgot-password")
def forgot_password(request_data: dict, db: Session = Depends(get_db)):
    """Send password reset email with temporary password."""
    import logging
    import secrets
    logger = logging.getLogger(__name__)
    
    email = request_data.get("email", "").strip().lower()
    if not email:
        # Always return success to prevent email enumeration
        return {"message": "If an account with that email exists, a reset link has been sent."}
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        logger.info(f"Forgot password request for unknown email: {email}")
        return {"message": "If an account with that email exists, a reset link has been sent."}
    
    # Generate temporary password
    temp_password = secrets.token_urlsafe(10)
    user.hashed_password = get_password_hash(temp_password)
    db.commit()
    
    # Send email via Mailgun
    try:
        import requests
        import os
        from app.core.config import settings
        mailgun_key = settings.MAILGUN_API_KEY or os.getenv("MAILGUN_API_KEY")
        mailgun_domain = settings.MAILGUN_DOMAIN or os.getenv("MAILGUN_DOMAIN", "mg.betterchoiceins.com")
        from_email = settings.MAILGUN_FROM_EMAIL or "welcome@" + mailgun_domain
        
        if mailgun_key:
            resp = requests.post(
                "https://api.mailgun.net/v3/" + mailgun_domain + "/messages",
                auth=("api", mailgun_key),
                data={
                    "from": "Better Choice Insurance <" + from_email + ">",
                    "to": email,
                    "subject": "Your ORBIT Password Has Been Reset",
                    "html": (
                    '<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">'
                        '<div style="background: linear-gradient(135deg, #0f172a, #1e293b); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">'
                            '<h1 style="color: #06b6d4; margin: 0; font-size: 28px;">ORBIT</h1>'
                            '<p style="color: #94a3b8; margin: 8px 0 0;">Better Choice Insurance</p>'
                        '</div>'
                        '<div style="background: #ffffff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">'
                            '<h2 style="color: #1e293b; margin-top: 0;">Password Reset</h2>'
                            '<p style="color: #475569;">Hi ' + (user.full_name or user.username) + ',</p>'
                            '<p style="color: #475569;">Your password has been reset. Use the temporary password below to log in, then change it immediately.</p>'
                            '<div style="background: #f1f5f9; border: 2px solid #06b6d4; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">'
                                '<p style="color: #64748b; margin: 0 0 8px; font-size: 14px;">Your temporary password:</p>'
                                '<p style="color: #0f172a; font-size: 22px; font-weight: bold; margin: 0; letter-spacing: 1px;">' + temp_password + '</p>'
                            '</div>'
                            '<p style="color: #475569;">Login at: <a href="https://orbit.betterchoiceins.com" style="color: #06b6d4;">orbit.betterchoiceins.com</a></p>'
                            '<p style="color: #94a3b8; font-size: 12px; margin-top: 20px;">If you did not request this reset, please contact your administrator immediately.</p>'
                        '</div>'
                        '<div style="background: #f8fafc; padding: 15px; border-radius: 0 0 12px 12px; border: 1px solid #e2e8f0; border-top: none; text-align: center;">'
                            '<p style="color: #94a3b8; font-size: 11px; margin: 0;">(847) 908-5665 &middot; service@betterchoiceins.com</p>'
                        '</div>'
                    '</div>'
                    )
                }
            )
            logger.info("Password reset email sent to %s: %s", email, resp.status_code)
        else:
            logger.warning("MAILGUN_API_KEY not set — cannot send reset email")
    except Exception as e:
        logger.error("Failed to send password reset email: %s", e)
    
    return {"message": "If an account with that email exists, a reset link has been sent."}
