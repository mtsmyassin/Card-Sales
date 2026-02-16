"""
Configuration management with environment variable loading.
Provides secure defaults and validation.
"""
import os
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)


class Config:
    """Application configuration loaded from environment variables."""
    
    # Flask Configuration
    SECRET_KEY: str = os.getenv('FLASK_SECRET_KEY', '')
    PORT: int = int(os.getenv('FLASK_PORT', '5013'))
    DEBUG: bool = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    # Supabase Configuration
    SUPABASE_URL: str = os.getenv('SUPABASE_URL', '')
    SUPABASE_KEY: str = os.getenv('SUPABASE_KEY', '')
    
    # Emergency Admin Accounts (format: username:bcrypt_hash)
    EMERGENCY_ADMIN_SUPER: str = os.getenv('EMERGENCY_ADMIN_SUPER', '')
    EMERGENCY_ADMIN_BASIC: str = os.getenv('EMERGENCY_ADMIN_BASIC', '')
    
    # Security Settings
    SESSION_TIMEOUT_MINUTES: int = int(os.getenv('SESSION_TIMEOUT_MINUTES', '30'))
    MAX_LOGIN_ATTEMPTS: int = int(os.getenv('MAX_LOGIN_ATTEMPTS', '5'))
    LOCKOUT_DURATION_MINUTES: int = int(os.getenv('LOCKOUT_DURATION_MINUTES', '15'))
    REQUIRE_HTTPS: bool = os.getenv('REQUIRE_HTTPS', 'false').lower() == 'true'
    
    # Backup Configuration
    BACKUP_ENABLED: bool = os.getenv('BACKUP_ENABLED', 'true').lower() == 'true'
    BACKUP_ROTATION_DAYS: int = int(os.getenv('BACKUP_ROTATION_DAYS', '30'))
    
    # Logging Configuration
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = os.getenv('LOG_FILE', 'pharmacy_app.log')
    
    # Offline queue file
    OFFLINE_FILE: str = 'offline_queue.json'
    
    @classmethod
    def validate(cls) -> list[str]:
        """
        Validate configuration and return list of errors.
        
        Returns:
            List of error messages. Empty list if valid.
        """
        errors = []
        
        # Check required fields
        if not cls.SECRET_KEY or len(cls.SECRET_KEY) < 32:
            errors.append(
                "FLASK_SECRET_KEY is missing or too short (minimum 32 characters). "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        
        if not cls.SUPABASE_URL:
            errors.append("SUPABASE_URL is required")
        
        if not cls.SUPABASE_KEY:
            errors.append("SUPABASE_KEY is required")
        
        # Validate numeric ranges
        if cls.PORT < 1024 or cls.PORT > 65535:
            errors.append(f"FLASK_PORT must be between 1024-65535, got {cls.PORT}")
        
        if cls.SESSION_TIMEOUT_MINUTES < 5:
            errors.append("SESSION_TIMEOUT_MINUTES must be at least 5")
        
        if cls.MAX_LOGIN_ATTEMPTS < 1:
            errors.append("MAX_LOGIN_ATTEMPTS must be at least 1")
        
        if cls.LOCKOUT_DURATION_MINUTES < 1:
            errors.append("LOCKOUT_DURATION_MINUTES must be at least 1")
        
        return errors
    
    @classmethod
    def load_emergency_accounts(cls) -> dict[str, str]:
        """
        Load emergency admin accounts from environment.
        
        Returns:
            Dictionary mapping username to bcrypt hash
        """
        accounts = {}
        
        if cls.EMERGENCY_ADMIN_SUPER:
            try:
                username, hash_val = cls.EMERGENCY_ADMIN_SUPER.split(':', 1)
                accounts[username.strip()] = hash_val.strip()
            except ValueError:
                print(f"WARNING: Invalid format for EMERGENCY_ADMIN_SUPER", file=sys.stderr)
        
        if cls.EMERGENCY_ADMIN_BASIC:
            try:
                username, hash_val = cls.EMERGENCY_ADMIN_BASIC.split(':', 1)
                accounts[username.strip()] = hash_val.strip()
            except ValueError:
                print(f"WARNING: Invalid format for EMERGENCY_ADMIN_BASIC", file=sys.stderr)
        
        return accounts
    
    @classmethod
    def startup_check(cls) -> None:
        """
        Perform startup validation and exit if critical errors found.
        """
        errors = cls.validate()
        
        if errors:
            print("\n" + "="*70, file=sys.stderr)
            print("CONFIGURATION ERRORS DETECTED:", file=sys.stderr)
            print("="*70, file=sys.stderr)
            for error in errors:
                print(f"  ❌ {error}", file=sys.stderr)
            print("="*70, file=sys.stderr)
            print("\nPlease fix the above errors in your .env file.", file=sys.stderr)
            print("Copy .env.example to .env and fill in the correct values.\n", file=sys.stderr)
            sys.exit(1)
        
        print("✅ Configuration validated successfully")
        print(f"   Port: {cls.PORT}")
        print(f"   Debug: {cls.DEBUG}")
        print(f"   Session Timeout: {cls.SESSION_TIMEOUT_MINUTES} minutes")
        print(f"   Max Login Attempts: {cls.MAX_LOGIN_ATTEMPTS}")
