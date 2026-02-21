from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Insurance Agency OS"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str = "postgresql://insurance_user:insurance_pass@db:5432/insurance_db"
    
    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # File Upload
    UPLOAD_DIR: str = "/app/uploads"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
    
    # Anthropic API for PDF extraction
    ANTHROPIC_API_KEY: Optional[str] = None
    
    # BoldSign API for e-signatures
    BOLDSIGN_API_KEY: Optional[str] = None
    BOLDSIGN_SENDER_EMAIL: Optional[str] = None
    
    # Mailgun for welcome emails
    MAILGUN_API_KEY: Optional[str] = None
    MAILGUN_DOMAIN: Optional[str] = None
    MAILGUN_FROM_EMAIL: str = "welcome@betterchoiceins.com"
    MAILGUN_FROM_NAME: str = "Better Choice Insurance"
    
    # Google Review
    GOOGLE_REVIEW_URL: Optional[str] = None
    
    # App URL (frontend)
    APP_URL: str = "https://better-choice-web.onrender.com"
    
    # Welcome email: CC the selling agent for QA (set to false to disable)
    WELCOME_EMAIL_CC_AGENT: bool = True
    
    # NowCerts API
    NOWCERTS_USERNAME: Optional[str] = None
    NOWCERTS_PASSWORD: Optional[str] = None
    NOWCERTS_API_URL: str = "https://api.nowcerts.com"

    # GoHighLevel webhook URLs
    GHL_NONPAY_WEBHOOK_URL: Optional[str] = None
    GHL_RENEWAL_WEBHOOK_URL: Optional[str] = None
    GHL_ONBOARDING_WEBHOOK_URL: Optional[str] = None
    GHL_QUOTE_WEBHOOK_URL: Optional[str] = None
    GHL_WINBACK_WEBHOOK_URL: Optional[str] = None
    GHL_CROSSSELL_WEBHOOK_URL: Optional[str] = None
    GHL_UW_WEBHOOK_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
