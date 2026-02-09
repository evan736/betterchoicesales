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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours (work day)
    MIN_PASSWORD_LENGTH: int = 8
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    
    # File Upload
    UPLOAD_DIR: str = "/app/uploads"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
    
    # WeSignature API (placeholder)
    WESIGNATURE_API_KEY: Optional[str] = None
    WESIGNATURE_API_URL: str = "https://api.wesignature.com/v1"
    
    # NowCerts AMS (placeholder)
    NOWCERTS_API_KEY: Optional[str] = None
    NOWCERTS_API_URL: str = "https://api.nowcerts.com/v1"
    
    # Anthropic API for PDF extraction
    ANTHROPIC_API_KEY: Optional[str] = None
    
    # BoldSign API for e-signatures (legacy, not used)
    BOLDSIGN_API_KEY: Optional[str] = None
    
    # DocuSeal API for e-signatures
    DOCUSEAL_API_KEY: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
