"""
Audit logging system for tracking all critical operations.
Provides tamper-evident logging with hash chaining.
"""
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from threading import Lock
import os


class AuditLogger:
    """
    Append-only audit logger with tamper detection.

    Each audit entry is linked to the previous entry via hash chaining,
    making it difficult to modify historical logs without detection.
    Writes to both a local JSONL file and Supabase when configured.
    """

    def __init__(self, log_file: str = "audit_log.jsonl"):
        """
        Initialize audit logger.

        Args:
            log_file: Path to the audit log file (JSONL format)
        """
        self.log_file = Path(log_file)
        self._lock = Lock()
        self._supabase = None
        self._ensure_log_exists()

    def configure_db(self, supabase_client) -> None:
        """
        Enable Supabase-backed persistence. Call after the Supabase client
        is initialised in app.py so audit events survive Railway redeploys.

        Required table (run migrations/003_app_audit_log.sql in Supabase):
            CREATE TABLE app_audit_log (...)
        """
        self._supabase = supabase_client

    def _write_to_db(self, entry: dict) -> None:
        """Write audit entry to Supabase app_audit_log. Non-blocking; swallows errors."""
        if not self._supabase:
            return
        try:
            self._supabase.table('app_audit_log').insert({
                'ts':          entry['timestamp'],
                'action':      entry['action'],
                'actor':       entry.get('actor'),
                'role':        entry.get('role'),
                'entity_type': entry.get('entity_type'),
                'entity_id':   entry.get('entity_id'),
                'success':     entry.get('success', True),
                'error':       entry.get('error'),
                'before_val':  entry.get('before'),
                'after_val':   entry.get('after'),
                'context':     entry.get('context'),
                'entry_hash':  entry.get('entry_hash'),
            }).execute()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[audit_log] Supabase write failed: {e}")
    
    def _ensure_log_exists(self) -> None:
        """Create log file if it doesn't exist."""
        if not self.log_file.exists():
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self.log_file.touch()
    
    def _get_last_hash(self) -> str:
        """
        Get the hash of the last log entry for chain verification.
        
        Returns:
            Hash string of last entry, or 'GENESIS' if empty log
        """
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if not lines:
                    return 'GENESIS'

                last_line = lines[-1].strip()
                if last_line:
                    last_entry = json.loads(last_line)
                    return last_entry.get('entry_hash', 'GENESIS')
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        return 'GENESIS'
    
    def _compute_entry_hash(self, entry: Dict[str, Any]) -> str:
        """
        Compute cryptographic hash of an entry.
        
        Args:
            entry: Log entry dictionary (without entry_hash)
            
        Returns:
            SHA256 hash string
        """
        # Create deterministic string representation
        content = json.dumps(entry, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def log(
        self,
        action: str,
        actor: str,
        role: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        before: Optional[Dict] = None,
        after: Optional[Dict] = None,
        success: bool = True,
        error: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> None:
        """
        Log an audit event.
        
        Args:
            action: Action performed (CREATE, UPDATE, DELETE, LOGIN, LOGOUT, APPROVE, etc.)
            actor: Username performing the action
            role: User role at time of action
            entity_type: Type of entity affected (USER, AUDIT, DAY_CLOSE, etc.)
            entity_id: ID of the affected entity (if applicable)
            before: State before the action (for UPDATE/DELETE)
            after: State after the action (for CREATE/UPDATE)
            success: Whether the action succeeded
            error: Error message if action failed
            context: Additional context (IP address, store, etc.)
        """
        with self._lock:
            previous_hash = self._get_last_hash()
            
            entry = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'action': action,
                'actor': actor,
                'role': role,
                'entity_type': entity_type,
                'entity_id': entity_id,
                'success': success,
                'previous_hash': previous_hash,
            }
            
            # Add optional fields only if provided
            if before is not None:
                entry['before'] = before
            if after is not None:
                entry['after'] = after
            if error:
                entry['error'] = error
            if context:
                entry['context'] = context
            
            # Compute hash of this entry
            entry_hash = self._compute_entry_hash(entry)
            entry['entry_hash'] = entry_hash
            
            # Write to Supabase first (canonical store; survives Railway redeploys).
            self._write_to_db(entry)

            # Append to local file as fallback / tamper-evident backup.
            # 'a' mode + small writes are atomic on Linux; encoding='utf-8' for Windows.
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
    
    def verify_integrity(self) -> tuple[bool, List[str]]:
        """
        Verify the integrity of the audit log chain.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            if not lines:
                return True, []
            
            expected_prev_hash = 'GENESIS'
            
            for i, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"Line {i}: Invalid JSON")
                    continue
                
                # Check previous hash matches
                if entry.get('previous_hash') != expected_prev_hash:
                    errors.append(
                        f"Line {i}: Hash chain broken. "
                        f"Expected prev_hash={expected_prev_hash}, "
                        f"got {entry.get('previous_hash')}"
                    )
                
                # Verify entry hash
                stored_hash = entry.pop('entry_hash', None)
                computed_hash = self._compute_entry_hash(entry)
                entry['entry_hash'] = stored_hash  # Restore for next iteration
                
                if stored_hash != computed_hash:
                    errors.append(
                        f"Line {i}: Entry hash mismatch. "
                        f"Entry may have been tampered with."
                    )
                
                expected_prev_hash = stored_hash
            
            return len(errors) == 0, errors
        
        except FileNotFoundError:
            return True, []
        except Exception as e:
            return False, [f"Verification failed: {str(e)}"]
    
    def get_entries(
        self,
        limit: Optional[int] = None,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve audit log entries with optional filtering.
        
        Args:
            limit: Maximum number of entries to return (most recent first)
            actor: Filter by actor username
            action: Filter by action type
            entity_type: Filter by entity type
            since: Filter entries after this timestamp
            
        Returns:
            List of matching audit entries
        """
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            entries = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    entry = json.loads(line)
                    
                    # Apply filters
                    if actor and entry.get('actor') != actor:
                        continue
                    if action and entry.get('action') != action:
                        continue
                    if entity_type and entry.get('entity_type') != entity_type:
                        continue
                    if since:
                        entry_time = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
                        if entry_time < since:
                            continue
                    
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
            
            # Return most recent first
            entries.reverse()
            
            if limit:
                entries = entries[:limit]
            
            return entries
        
        except FileNotFoundError:
            return []


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def audit_log(
    action: str,
    actor: str,
    role: str,
    entity_type: str,
    **kwargs
) -> None:
    """
    Convenience function to log an audit event.
    
    See AuditLogger.log() for parameter details.
    """
    logger = get_audit_logger()
    logger.log(action, actor, role, entity_type, **kwargs)


if __name__ == '__main__':
    """CLI utility for audit log management."""
    import sys
    
    if len(sys.argv) < 2:
        print("Audit Log Utility")
        print("=" * 50)
        print("\nUsage:")
        print("  python audit_log.py verify [log_file]")
        print("  python audit_log.py view [log_file] [--limit N]")
        print("  python audit_log.py stats [log_file]")
        print("\nExamples:")
        print("  python audit_log.py verify")
        print("  python audit_log.py view --limit 10")
        sys.exit(0)
    
    command = sys.argv[1]
    log_file = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else 'audit_log.jsonl'
    
    if command == 'verify':
        logger = AuditLogger(log_file)
        is_valid, errors = logger.verify_integrity()
        
        if is_valid:
            print(f"[OK] Audit log integrity verified: {log_file}")
        else:
            print(f"[FAIL] Audit log integrity check FAILED: {log_file}")
            for error in errors:
                print(f"   - {error}")
            sys.exit(1)
    
    elif command == 'view':
        limit = None
        if '--limit' in sys.argv:
            try:
                limit_idx = sys.argv.index('--limit')
                limit = int(sys.argv[limit_idx + 1])
            except (ValueError, IndexError):
                print("Error: --limit requires an integer value")
                sys.exit(1)
        
        logger = AuditLogger(log_file)
        entries = logger.get_entries(limit=limit)
        
        print(f"Audit Log Entries: {log_file}")
        print("=" * 80)
        
        for entry in entries:
            print(f"\n[{entry['timestamp']}] {entry['action']}")
            print(f"  Actor: {entry['actor']} ({entry['role']})")
            print(f"  Entity: {entry['entity_type']} {entry.get('entity_id', '')}")
            print(f"  Success: {entry['success']}")
            if 'error' in entry:
                print(f"  Error: {entry['error']}")
            if 'context' in entry:
                print(f"  Context: {entry['context']}")
    
    elif command == 'stats':
        logger = AuditLogger(log_file)
        entries = logger.get_entries()
        
        # Calculate statistics
        total = len(entries)
        actions = {}
        actors = {}
        failures = 0
        
        for entry in entries:
            action = entry.get('action', 'UNKNOWN')
            actor = entry.get('actor', 'UNKNOWN')
            
            actions[action] = actions.get(action, 0) + 1
            actors[actor] = actors.get(actor, 0) + 1
            
            if not entry.get('success', True):
                failures += 1
        
        print(f"Audit Log Statistics: {log_file}")
        print("=" * 50)
        print(f"Total Entries: {total}")
        print(f"Failed Operations: {failures}")
        print(f"\nTop Actions:")
        for action, count in sorted(actions.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {action}: {count}")
        print(f"\nTop Actors:")
        for actor, count in sorted(actors.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {actor}: {count}")
    
    else:
        print(f"Unknown command: {command}")
        print("Available commands: verify, view, stats")
        sys.exit(1)
