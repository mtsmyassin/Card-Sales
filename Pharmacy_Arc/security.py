"""
Security utilities for password hashing and authentication.
"""
import bcrypt
import time
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Dict
from threading import Lock
from config import Config

logger = logging.getLogger(__name__)


class PasswordHasher:
    """Secure password hashing using bcrypt."""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt.
        
        Args:
            password: Plain text password
            
        Returns:
            Bcrypt hash string
        """
        salt = bcrypt.gensalt(rounds=Config.BCRYPT_ROUNDS)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against a bcrypt hash.
        
        Args:
            password: Plain text password to verify
            password_hash: Bcrypt hash to verify against
            
        Returns:
            True if password matches, False otherwise
        """
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except (ValueError, TypeError):
            return False


class LoginAttemptTracker:
    """Track and limit login attempts to prevent brute-force attacks with persistent storage."""

    def __init__(self, max_attempts: int = 5, lockout_duration_minutes: int = 15,
                 state_file: str = 'lockout_state.json'):
        """
        Initialize the login attempt tracker with persistent storage.

        Args:
            max_attempts: Maximum failed attempts before lockout
            lockout_duration_minutes: Duration of lockout in minutes
            state_file: Path to file for persisting lockout state
        """
        self.max_attempts = max_attempts
        self.lockout_duration = timedelta(minutes=lockout_duration_minutes)
        self.state_file = state_file
        self._attempts: Dict[str, list] = {}  # username -> list of attempt timestamps
        self._lockouts: Dict[str, datetime] = {}  # username -> lockout expiry time
        self._lock = Lock()
        self._supabase = None  # Set via configure_db() after Supabase client is ready

        # Load persisted state on initialization (file-based until DB is configured)
        self._load_state()

    def configure_db(self, supabase_client) -> None:
        """
        Switch to Supabase-backed persistence. Call this after the Supabase client
        is initialised in app.py. Re-loads state from the DB immediately so any
        active lockouts are honoured even after a Railway redeploy.

        Required table (run once in Supabase SQL editor):
            CREATE TABLE IF NOT EXISTS login_lockouts (
                username    TEXT PRIMARY KEY,
                attempts    TEXT[] DEFAULT '{}',
                locked_until TIMESTAMPTZ
            );
        """
        self._supabase = supabase_client
        with self._lock:
            self._attempts = {}
            self._lockouts = {}
        self._load_state()
    
    def _load_state(self) -> None:
        """Load lockout state — from Supabase if configured, otherwise from file."""
        if self._supabase:
            self._load_from_db()
        else:
            self._load_from_file()

    def _save_state(self) -> None:
        """Persist lockout state — to Supabase if configured, otherwise to file."""
        if self._supabase:
            self._save_to_db()
        else:
            self._save_to_file()

    @staticmethod
    def _parse_utc(ts: str) -> datetime:
        """Parse an ISO timestamp string into a UTC-aware datetime."""
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _rows(response: Any) -> list[dict[str, Any]]:
        """Extract row list from Supabase response."""
        data = getattr(response, "data", None)
        if isinstance(data, list):
            return data  # type: ignore[return-value]
        return []

    @staticmethod
    def _row0(response: Any) -> dict[str, Any]:
        """Extract first row from Supabase response."""
        data = getattr(response, "data", None)
        if isinstance(data, dict):
            return data  # type: ignore[return-value]
        if isinstance(data, list) and data:
            return data[0]  # type: ignore[return-value]
        return {}

    def _load_from_db(self) -> None:
        """Load lockout state from Supabase login_lockouts table."""
        try:
            resp = self._supabase.table('login_lockouts').select('*').execute()
            now = datetime.now(timezone.utc)
            for row in self._rows(resp):
                username = row['username']
                if row.get('attempts'):
                    self._attempts[username] = [
                        self._parse_utc(ts) for ts in row['attempts']
                    ]
                if row.get('locked_until'):
                    expiry = self._parse_utc(row['locked_until'])
                    if expiry > now:
                        self._lockouts[username] = expiry
        except Exception as e:
            logger.warning(f"Could not load lockout state from DB: {e}")

    def _save_to_db(self) -> None:
        """Persist lockout state to Supabase login_lockouts table."""
        try:
            all_users = set(list(self._attempts.keys()) + list(self._lockouts.keys()))
            for username in all_users:
                self._save_user_to_db(username)
        except Exception as e:
            logger.warning(f"Could not save lockout state to DB: {e}")

    def _save_user_to_db(self, username: str) -> None:
        """Persist state for a single user to Supabase (or file fallback)."""
        if not self._supabase:
            self._save_to_file()
            return
        try:
            attempts_list = [ts.isoformat() for ts in self._attempts.get(username, [])]
            locked_until = (
                self._lockouts[username].isoformat()
                if username in self._lockouts else None
            )
            self._supabase.table('login_lockouts').upsert({
                'username': username,
                'attempts': attempts_list,
                'locked_until': locked_until,
            }).execute()
        except Exception as e:
            logger.warning(f"Could not save lockout state for {username!r} to DB: {e}")

    def _load_from_file(self) -> None:
        """Load lockout state from local JSON file (dev / fallback)."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                for username, timestamps in data.get('attempts', {}).items():
                    self._attempts[username] = [
                        self._parse_utc(ts) for ts in timestamps
                    ]
                for username, expiry in data.get('lockouts', {}).items():
                    expiry_time = self._parse_utc(expiry)
                    if expiry_time > datetime.now(timezone.utc):
                        self._lockouts[username] = expiry_time
        except Exception as e:
            logger.warning(f"Could not load lockout state from file: {e}")
            self._attempts = {}
            self._lockouts = {}

    def _save_to_file(self) -> None:
        """Persist lockout state to local JSON file (dev / fallback)."""
        try:
            data = {
                'attempts': {
                    username: [ts.isoformat() for ts in timestamps]
                    for username, timestamps in self._attempts.items()
                },
                'lockouts': {
                    username: expiry.isoformat()
                    for username, expiry in self._lockouts.items()
                }
            }
            temp_file = self.state_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.state_file)
        except Exception as e:
            logger.warning(f"Could not save lockout state to file: {e}")
    
    def _db_get_user_state(self, username: str) -> tuple[list, Optional[datetime]]:
        """Fetch lockout state for a single user from DB. Returns (attempts, locked_until)."""
        if not self._supabase:
            return self._attempts.get(username, []), self._lockouts.get(username)
        try:
            resp = self._supabase.table('login_lockouts').select('*').eq(
                'username', username).maybe_single().execute()
            row = self._row0(resp)
            if not row:
                return [], None
            attempts = []
            if row.get('attempts'):
                attempts = [self._parse_utc(ts) for ts in row['attempts']]
            locked_until = None
            if row.get('locked_until'):
                locked_until = self._parse_utc(row['locked_until'])
            return attempts, locked_until
        except Exception as e:
            logger.warning(f"[LoginAttemptTracker] DB read failed for {username!r}, using in-memory: {e}")
            return self._attempts.get(username, []), self._lockouts.get(username)

    def is_locked_out(self, username: str) -> bool:
        """
        Check if a username is currently locked out.
        Reads from DB when configured to avoid split-brain across workers.

        Args:
            username: Username to check

        Returns:
            True if locked out, False otherwise
        """
        with self._lock:
            _, locked_until = self._db_get_user_state(username)
            if locked_until and datetime.now(timezone.utc) < locked_until:
                return True
            # Lockout expired or doesn't exist — clean up in-memory and persist
            self._lockouts.pop(username, None)
            self._attempts.pop(username, None)
            self._save_user_to_db(username)
            return False
    
    def get_lockout_remaining(self, username: str) -> Optional[int]:
        """
        Get remaining lockout time in seconds.
        Reads from DB when configured to avoid split-brain across workers.

        Args:
            username: Username to check

        Returns:
            Seconds remaining in lockout, or None if not locked out
        """
        with self._lock:
            _, locked_until = self._db_get_user_state(username)
            if locked_until:
                remaining = (locked_until - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0:
                    return int(remaining)
            return None
    
    def record_failed_attempt(self, username: str) -> tuple[bool, Optional[int]]:
        """
        Record a failed login attempt.
        Loads current state from DB first to avoid split-brain across workers.

        Args:
            username: Username that failed to login

        Returns:
            Tuple of (is_now_locked_out, remaining_attempts_before_lockout)
        """
        with self._lock:
            now = datetime.now(timezone.utc)

            # Load current attempts from DB (not stale in-memory) so all workers
            # see the same count. Falls back to in-memory if DB is unavailable.
            db_attempts, _ = self._db_get_user_state(username)
            self._attempts[username] = db_attempts if db_attempts else []

            # Add this attempt
            self._attempts[username].append(now)

            # Clean up old attempts (older than lockout duration)
            cutoff = now - self.lockout_duration
            self._attempts[username] = [t for t in self._attempts[username] if t > cutoff]

            # Check if we should lock out
            attempt_count = len(self._attempts[username])
            if attempt_count >= self.max_attempts:
                self._lockouts[username] = now + self.lockout_duration
                self._save_state()  # Persist lockout
                return True, 0

            self._save_state()  # Persist attempts
            remaining = self.max_attempts - attempt_count
            return False, remaining
    
    def record_successful_login(self, username: str) -> None:
        """
        Clear failed attempts for a successful login.
        
        Args:
            username: Username that successfully logged in
        """
        with self._lock:
            if username in self._attempts:
                del self._attempts[username]
            if username in self._lockouts:
                del self._lockouts[username]
            self._save_state()  # Persist cleared state
    
    def get_attempt_count(self, username: str) -> int:
        """
        Get current failed attempt count for a username.
        
        Args:
            username: Username to check
            
        Returns:
            Number of recent failed attempts
        """
        with self._lock:
            if username not in self._attempts:
                return 0

            # Clean up old attempts
            now = datetime.now(timezone.utc)
            cutoff = now - self.lockout_duration
            self._attempts[username] = [t for t in self._attempts[username] if t > cutoff]

            return len(self._attempts[username])


def generate_secret_key() -> str:
    """
    Generate a cryptographically secure secret key.
    
    Returns:
        64-character hex string suitable for Flask secret_key
    """
    import secrets
    return secrets.token_hex(32)


if __name__ == '__main__':
    """CLI utility for password hashing."""
    import sys
    
    if len(sys.argv) < 2:
        print("Password Hashing Utility")
        print("=" * 50)
        print("\nUsage:")
        print("  python security.py hash <password>")
        print("  python security.py verify <password> <hash>")
        print("  python security.py genkey")
        print("\nExamples:")
        print("  python security.py hash 'MyP@ssw0rd123'")
        print("  python security.py genkey")
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command == 'hash':
        if len(sys.argv) < 3:
            print("Error: Password required")
            print("Usage: python security.py hash <password>")
            sys.exit(1)
        
        password = sys.argv[2]
        hash_result = PasswordHasher.hash_password(password)
        print(f"\nPassword Hash:")
        print(f"{hash_result}")
        print(f"\nAdd to .env as:")
        print(f"EMERGENCY_ADMIN_SUPER=super:{hash_result}")
    
    elif command == 'verify':
        if len(sys.argv) < 4:
            print("Error: Password and hash required")
            print("Usage: python security.py verify <password> <hash>")
            sys.exit(1)
        
        password = sys.argv[2]
        hash_val = sys.argv[3]
        
        if PasswordHasher.verify_password(password, hash_val):
            print("[OK] Password matches!")
        else:
            print("[FAIL] Password does not match")
    
    elif command == 'genkey':
        key = generate_secret_key()
        print(f"\nGenerated Secret Key:")
        print(f"{key}")
        print(f"\nAdd to .env as:")
        print(f"FLASK_SECRET_KEY={key}")
    
    else:
        print(f"Unknown command: {command}")
        print("Available commands: hash, verify, genkey")
        sys.exit(1)
