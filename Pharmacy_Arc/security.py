"""
Security utilities for password hashing and authentication.
"""
import bcrypt
import time
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
    """Track and limit login attempts to prevent brute-force attacks."""
    
    def __init__(self, max_attempts: int = 5, lockout_duration_minutes: int = 15):
        """
        Initialize the login attempt tracker.
        
        Args:
            max_attempts: Maximum failed attempts before lockout
            lockout_duration_minutes: Duration of lockout in minutes
        """
        self.max_attempts = max_attempts
        self.lockout_duration = timedelta(minutes=lockout_duration_minutes)
        self._attempts: Dict[str, list] = {}  # username -> list of attempt timestamps
        self._lockouts: Dict[str, datetime] = {}  # username -> lockout expiry time
        self._lock = Lock()
    
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
                return True, 0
            
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
