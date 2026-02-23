"""
Security utilities for password hashing and authentication.
"""
import bcrypt
import time
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict
from threading import Lock


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
        salt = bcrypt.gensalt(rounds=12)
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

    def _load_from_db(self) -> None:
        """Load lockout state from Supabase login_lockouts table."""
        try:
            resp = self._supabase.table('login_lockouts').select('*').execute()
            now = datetime.now()
            for row in resp.data:
                username = row['username']
                if row.get('attempts'):
                    self._attempts[username] = [
                        datetime.fromisoformat(ts) for ts in row['attempts']
                    ]
                if row.get('locked_until'):
                    expiry = datetime.fromisoformat(
                        row['locked_until'].replace('Z', '+00:00')
                    ).replace(tzinfo=None)
                    if expiry > now:
                        self._lockouts[username] = expiry
        except Exception as e:
            print(f"Warning: Could not load lockout state from DB: {e}")

    def _save_to_db(self) -> None:
        """Persist lockout state to Supabase login_lockouts table."""
        try:
            all_users = set(list(self._attempts.keys()) + list(self._lockouts.keys()))
            for username in all_users:
                attempts_list = [
                    ts.isoformat() for ts in self._attempts.get(username, [])
                ]
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
            print(f"Warning: Could not save lockout state to DB: {e}")

    def _load_from_file(self) -> None:
        """Load lockout state from local JSON file (dev / fallback)."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                for username, timestamps in data.get('attempts', {}).items():
                    self._attempts[username] = [
                        datetime.fromisoformat(ts) for ts in timestamps
                    ]
                for username, expiry in data.get('lockouts', {}).items():
                    expiry_time = datetime.fromisoformat(expiry)
                    if expiry_time > datetime.now():
                        self._lockouts[username] = expiry_time
        except Exception as e:
            print(f"Warning: Could not load lockout state from file: {e}")
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
            print(f"Warning: Could not save lockout state to file: {e}")
    
    def is_locked_out(self, username: str) -> bool:
        """
        Check if a username is currently locked out.
        
        Args:
            username: Username to check
            
        Returns:
            True if locked out, False otherwise
        """
        with self._lock:
            if username in self._lockouts:
                if datetime.now() < self._lockouts[username]:
                    return True
                else:
                    # Lockout expired, clear it
                    del self._lockouts[username]
                    if username in self._attempts:
                        del self._attempts[username]
            return False
    
    def get_lockout_remaining(self, username: str) -> Optional[int]:
        """
        Get remaining lockout time in seconds.
        
        Args:
            username: Username to check
            
        Returns:
            Seconds remaining in lockout, or None if not locked out
        """
        with self._lock:
            if username in self._lockouts:
                remaining = (self._lockouts[username] - datetime.now()).total_seconds()
                return max(0, int(remaining))
            return None
    
    def record_failed_attempt(self, username: str) -> tuple[bool, Optional[int]]:
        """
        Record a failed login attempt.
        
        Args:
            username: Username that failed to login
            
        Returns:
            Tuple of (is_now_locked_out, remaining_attempts_before_lockout)
        """
        with self._lock:
            now = datetime.now()
            
            # Initialize attempt list if needed
            if username not in self._attempts:
                self._attempts[username] = []
            
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
            now = datetime.now()
            cutoff = now - self.lockout_duration
            self._attempts[username] = [t for t in self._attempts[username] if t > cutoff]
            
            return len(self._attempts[username])


class SupabaseLoginTracker:
    """Track login attempts via Supabase — process-safe across Gunicorn workers."""

    def __init__(self, supabase_getter, max_attempts: int = 5, lockout_duration_minutes: int = 15):
        """
        Args:
            supabase_getter: callable that returns a Supabase client (late-bound for patching)
            max_attempts: max failed attempts before lockout
            lockout_duration_minutes: lockout window in minutes
        """
        self._get_supabase = supabase_getter
        self.max_attempts = max_attempts
        self.lockout_duration_minutes = lockout_duration_minutes

    def _db(self):
        return self._get_supabase()

    def is_locked_out(self, username: str) -> bool:
        try:
            result = self._db().table("login_lockouts").select("locked_until").eq("username", username).execute()
            if result.data:
                locked_until = datetime.fromisoformat(result.data[0]['locked_until'].replace('Z', '+00:00'))
                if locked_until > datetime.now(locked_until.tzinfo):
                    return True
                # Expired — clean up
                self._db().table("login_lockouts").delete().eq("username", username).execute()
        except Exception:
            pass
        return False

    def get_lockout_remaining(self, username: str) -> Optional[int]:
        try:
            result = self._db().table("login_lockouts").select("locked_until").eq("username", username).execute()
            if result.data:
                locked_until = datetime.fromisoformat(result.data[0]['locked_until'].replace('Z', '+00:00'))
                remaining = (locked_until - datetime.now(locked_until.tzinfo)).total_seconds()
                return max(0, int(remaining))
        except Exception:
            pass
        return None

    def record_failed_attempt(self, username: str) -> tuple:
        try:
            # Record the attempt
            self._db().table("login_attempts").insert({
                "username": username, "success": False
            }).execute()

            # Count recent failures within lockout window
            cutoff = (datetime.utcnow() - timedelta(minutes=self.lockout_duration_minutes)).isoformat()
            result = self._db().table("login_attempts").select("id").eq("username", username).eq("success", False).gte("attempted_at", cutoff).execute()
            count = len(result.data)

            if count >= self.max_attempts:
                locked_until = (datetime.utcnow() + timedelta(minutes=self.lockout_duration_minutes)).isoformat()
                self._db().table("login_lockouts").upsert({
                    "username": username, "locked_until": locked_until
                }).execute()
                return True, 0

            return False, self.max_attempts - count
        except Exception:
            return False, self.max_attempts

    def record_successful_login(self, username: str) -> None:
        try:
            self._db().table("login_attempts").insert({
                "username": username, "success": True
            }).execute()
            # Clear lockout and recent failures
            self._db().table("login_lockouts").delete().eq("username", username).execute()
            self._db().table("login_attempts").delete().eq("username", username).eq("success", False).execute()
        except Exception:
            pass

    def get_attempt_count(self, username: str) -> int:
        try:
            cutoff = (datetime.utcnow() - timedelta(minutes=self.lockout_duration_minutes)).isoformat()
            result = self._db().table("login_attempts").select("id").eq("username", username).eq("success", False).gte("attempted_at", cutoff).execute()
            return len(result.data)
        except Exception:
            return 0


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
            print("✅ Password matches!")
        else:
            print("❌ Password does not match")
    
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
