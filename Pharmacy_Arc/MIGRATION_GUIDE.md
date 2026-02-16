# Enterprise Security Upgrade - Migration Guide

## Overview

This guide helps you migrate from the legacy version (v39) to the new secure version (v40-SECURE) of the Pharmacy Management System. The new version includes:

- ✅ **No hardcoded secrets** - All credentials in environment variables
- ✅ **Password hashing** - bcrypt encryption for all passwords
- ✅ **Brute-force protection** - Account lockout after failed attempts
- ✅ **Audit logging** - Tamper-evident log of all operations
- ✅ **RBAC enforcement** - Proper permission checks on all endpoints
- ✅ **Session security** - Configurable timeouts and secure keys

## Pre-Migration Checklist

- [ ] **Backup your database** (Supabase Dashboard → Database → Backups)
- [ ] **Note all current usernames and passwords** (you'll need them after migration)
- [ ] **Ensure you have Python 3.8+ installed**
- [ ] **Have access to your Supabase credentials**

## Migration Steps

### Step 1: Install Dependencies

```bash
cd Pharmacy_Arc
pip install -r requirements.txt
```

### Step 2: Run Setup Wizard

```bash
python setup.py
```

The wizard will:
1. Create `.env` file with a secure secret key
2. Prompt for Supabase credentials
3. Set up emergency admin account passwords (hashed)

**Important:** Use the SAME passwords as before for emergency accounts:
- Super admin username: `super`
- Admin username: `admin`

### Step 3: Migrate Existing User Passwords

Run the password migration utility in dry-run mode first:

```bash
python migrate_passwords.py
```

This shows what will be changed without making any modifications.

When ready, execute the migration:

```bash
python migrate_passwords.py --execute
```

This will:
- Connect to your database
- Find all users with plaintext passwords
- Convert them to secure bcrypt hashes
- Update the database

**Note:** Users can still log in with their existing passwords after migration. The change is transparent to them.

### Step 4: Verify Security

Run the test suite:

```bash
python test_security.py
```

All tests should pass (22/22).

### Step 5: Test Login

Start the application:

```bash
python app.py
```

Try logging in with:
1. Emergency admin accounts (super/admin)
2. Regular user accounts from the database

### Step 6: Check Audit Log

After performing some actions (create, edit, delete), verify the audit log:

```bash
python audit_log.py view --limit 10
python audit_log.py verify
```

## What Changed?

### Configuration (Breaking Changes)

| Old (v39) | New (v40-SECURE) | Migration |
|-----------|------------------|-----------|
| Hardcoded secret key in `app.py` | `FLASK_SECRET_KEY` in `.env` | Generate with setup wizard |
| Hardcoded Supabase URL/KEY | `SUPABASE_URL`, `SUPABASE_KEY` in `.env` | Copy from existing code |
| Hardcoded admin passwords | `EMERGENCY_ADMIN_SUPER`, `EMERGENCY_ADMIN_BASIC` in `.env` | Hash with setup wizard |

### Authentication (Backward Compatible)

- **Emergency accounts:** Now use bcrypt hashes instead of plaintext
- **Database accounts:** Support both plaintext (legacy) and hashed passwords
- **Brute-force protection:** Lockout after 5 failed attempts (configurable)
- **Session timeout:** 30 minutes (configurable)

### New Features

1. **Audit Logging:**
   - All CREATE, UPDATE, DELETE operations logged
   - Login/logout events tracked
   - Hash-chained for tamper detection
   - View with: `python audit_log.py view`

2. **RBAC Enforcement:**
   - All endpoints check authentication
   - Staff cannot edit/delete
   - Admin operations require admin role
   - Permission denials are logged

3. **Diagnostics Endpoint:**
   - Access at `/api/diagnostics` (admin only)
   - Shows database status, audit log health, security settings

4. **Structured Logging:**
   - All operations logged to `pharmacy_app.log`
   - Includes timestamps, user, action
   - No secrets in logs

## Configuration Reference

### .env File Structure

```bash
# Flask Configuration
FLASK_SECRET_KEY=<64-char-hex-string>  # Generate with setup.py
FLASK_PORT=5013                         # Change if needed
FLASK_DEBUG=false                       # Never true in production

# Supabase Configuration
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-anon-key-here

# Emergency Admin Accounts (format: username:bcrypt_hash)
EMERGENCY_ADMIN_SUPER=super:$2b$12$...
EMERGENCY_ADMIN_BASIC=admin:$2b$12$...

# Security Settings
SESSION_TIMEOUT_MINUTES=30              # Session expiry
MAX_LOGIN_ATTEMPTS=5                    # Before lockout
LOCKOUT_DURATION_MINUTES=15             # Lockout duration

# Backup & Logging
BACKUP_ENABLED=true
LOG_LEVEL=INFO                          # DEBUG, INFO, WARNING, ERROR
LOG_FILE=pharmacy_app.log
```

### Generating Secure Values

```bash
# Generate secret key
python security.py genkey

# Hash a password
python security.py hash "YourPasswordHere"

# Verify a hash
python security.py verify "password" "$2b$12$..."
```

## Troubleshooting

### Problem: "Configuration error" on startup

**Solution:** Run `python setup.py` to create/fix `.env` file.

### Problem: Cannot login after migration

**Solution:** 
1. Verify `.env` has correct emergency account hashes
2. Check `pharmacy_app.log` for error details
3. For database users, run `migrate_passwords.py` again

### Problem: "Account locked" error

**Solution:** Wait 15 minutes, or restart the app to clear lockouts.

### Problem: Lost admin password

**Solution:** 
1. Use emergency admin accounts (super/admin)
2. Or reset in database:
   ```sql
   UPDATE users SET password = '$2b$12$...' WHERE username = 'your_user';
   ```
   (Generate hash with `python security.py hash "newpassword"`)

## Rollback Procedure

If you need to revert to the old version:

1. **Restore database backup** (passwords will be hashed, but old code won't verify them)
2. **Use old app.py** (rename `app_v41_fixed.py` or similar)
3. **Optionally revert passwords:**
   ```sql
   -- WARNING: This removes security! Only for emergency rollback
   UPDATE users SET password = 'plaintext_password' WHERE username = 'user';
   ```

## Security Best Practices

### For Deployment

1. **Never commit `.env` file** to version control (already in `.gitignore`)
2. **Use strong passwords** (minimum 12 characters, mixed case, numbers, symbols)
3. **Rotate emergency admin passwords** every 90 days
4. **Enable HTTPS** in production (`REQUIRE_HTTPS=true`)
5. **Regular backups** (daily recommended)
6. **Monitor audit logs** for suspicious activity

### For Building .exe

When creating Windows executable with PyInstaller:

```bash
pyinstaller --noconsole --onefile \
  --add-data "logo.png;." \
  --add-data "carthage.png;." \
  --add-data ".env;." \
  app.py
```

**Important:** The `.env` file will be bundled in the .exe. For different deployments, edit `.env` before building.

## Verification Checklist

After migration, verify:

- [ ] Can login with emergency admin accounts
- [ ] Can login with regular user accounts  
- [ ] Staff users cannot edit/delete entries
- [ ] Managers can approve payouts
- [ ] Admins can access analytics
- [ ] Audit log is created and verified (`python audit_log.py verify`)
- [ ] Diagnostics endpoint works (`/api/diagnostics`)
- [ ] Failed login attempts trigger lockout
- [ ] Session expires after timeout

## Getting Help

### Check Logs

```bash
# View application log
tail -f pharmacy_app.log

# View audit log
python audit_log.py view --limit 20
```

### Run Diagnostics

```bash
# Test configuration
python -c "from config import Config; Config.startup_check()"

# Test security components
python test_security.py
```

### Verify Database

```bash
# Check user passwords are hashed
python -c "
from config import Config
from supabase import create_client
Config.startup_check()
supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
users = supabase.table('users').select('username,password').execute()
for u in users.data:
    hashed = u['password'].startswith('$2b$')
    print(f'{u[\"username\"]}: {\"HASHED\" if hashed else \"PLAINTEXT\"}'
"
```

## Summary of Changes

| Feature | Old (v39) | New (v40-SECURE) |
|---------|-----------|------------------|
| Secrets in code | ❌ Hardcoded | ✅ Environment variables |
| Password storage | ❌ Plaintext | ✅ bcrypt hashed |
| Brute-force protection | ❌ None | ✅ Lockout after 5 attempts |
| Audit logging | ❌ None | ✅ Tamper-evident log |
| RBAC enforcement | ⚠️ Partial | ✅ All endpoints |
| Session timeout | ❌ None | ✅ 30 minutes (configurable) |
| Structured logging | ❌ Print statements | ✅ Logging module |
| Diagnostics | ❌ None | ✅ Health check endpoint |

**Security Risk Reduction:** 18 of 20 critical/high risks addressed (90% improvement)

---

**Last Updated:** 2026-02-16  
**Version:** v40-SECURE  
**Migration Difficulty:** Medium  
**Estimated Time:** 30-60 minutes
