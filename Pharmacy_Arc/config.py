"""
Configuration management with environment variable loading.
Provides secure defaults and validation.
"""
import os
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file.
# When running as a PyInstaller frozen exe, __file__ is unreliable for path
# resolution. Instead: look next to the exe first (user-editable), then fall
# back to the bundled copy inside sys._MEIPASS.
def _find_env() -> Path:
    if getattr(sys, 'frozen', False):
        # Packaged exe: prefer .env sitting next to PharmacyDirector.exe
        beside_exe = Path(sys.executable).parent / '.env'
        if beside_exe.exists():
            return beside_exe
        # Fall back to the file bundled inside the PyInstaller temp dir
        return Path(sys._MEIPASS) / '.env'
    # Development: .env lives in the same folder as config.py
    return Path(__file__).parent / '.env'

env_path = _find_env()
load_dotenv(dotenv_path=env_path)


class Config:
    """Application configuration loaded from environment variables."""

    # ── Canonical Store List ──────────────────────────────────────────────────
    # Single source of truth for all store names. Every validation, whitelist,
    # and dropdown in the app MUST reference this list.
    STORES = ['Carimas #1', 'Carimas #2', 'Carimas #3', 'Carimas #4', 'Carthage']

    # Flask Configuration
    SECRET_KEY: str = os.getenv('FLASK_SECRET_KEY', '')
    PORT: int = int(os.getenv('FLASK_PORT', '5013'))
    DEBUG: bool = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    # Supabase Configuration
    SUPABASE_URL: str = os.getenv('SUPABASE_URL', '')
    SUPABASE_KEY: str = os.getenv('SUPABASE_KEY', '')
    SUPABASE_SERVICE_KEY: str = os.getenv('SUPABASE_SERVICE_KEY', '')
    
    # Emergency Admin Accounts (format: username:bcrypt_hash)
    EMERGENCY_ADMIN_SUPER: str = os.getenv('EMERGENCY_ADMIN_SUPER', '')
    EMERGENCY_ADMIN_BASIC: str = os.getenv('EMERGENCY_ADMIN_BASIC', '')
    
    # Telegram Bot
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv('TELEGRAM_WEBHOOK_SECRET', '')

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

    # ── Business / Operational Constants ───────────────────────────────────────
    VARIANCE_ALERT_THRESHOLD: float = float(os.getenv('VARIANCE_ALERT_THRESHOLD', '5.0'))
    DEFAULT_OPENING_FLOAT: float = float(os.getenv('DEFAULT_OPENING_FLOAT', '100.0'))
    ZREPORT_LOCK_TIMEOUT_MINUTES: int = int(os.getenv('ZREPORT_LOCK_TIMEOUT_MINUTES', '30'))

    # ── Storage ───────────────────────────────────────────────────────────────
    STORAGE_BUCKET: str = os.getenv('STORAGE_BUCKET', 'z-reports')
    STORAGE_URL_EXPIRY_SECONDS: int = int(os.getenv('STORAGE_URL_EXPIRY_SECONDS', '3600'))
    MAX_UPLOAD_SIZE: int = int(os.getenv('MAX_UPLOAD_SIZE', str(5 * 1024 * 1024)))

    # ── Crypto ────────────────────────────────────────────────────────────────
    BCRYPT_ROUNDS: int = int(os.getenv('BCRYPT_ROUNDS', '12'))
    
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
