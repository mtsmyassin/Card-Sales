#!/usr/bin/env python3
"""
Password Migration Utility for Pharmacy Management System

This script helps migrate existing plaintext passwords in the database
to secure bcrypt hashes.

WARNING: This script modifies the database directly. Always backup first!
"""

import sys

try:
    from config import Config
    from security import PasswordHasher
    from supabase import create_client
except ImportError:
    print("Error: Required modules not found. Please run: pip install -r requirements.txt")
    sys.exit(1)


def migrate_passwords(dry_run=True):
    """
    Migrate all plaintext passwords to bcrypt hashes.

    Args:
        dry_run: If True, only shows what would be done without making changes
    """
    print("\n" + "=" * 70)
    print("PASSWORD MIGRATION UTILITY")
    print("=" * 70)

    # Load configuration
    try:
        Config.startup_check()
    except SystemExit:
        print("\nConfiguration error. Please fix .env file and try again.")
        return False

    # Connect to database
    print("\n[1/4] Connecting to database...")
    try:
        supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return False

    # Get all users
    print("\n[2/4] Fetching users...")
    try:
        from helpers.supabase_types import rows

        response = supabase.table("users").select("*").execute()
        users = rows(response)
        print(f"✅ Found {len(users)} user(s)")
    except Exception as e:
        print(f"❌ Failed to fetch users: {e}")
        return False

    if not users:
        print("\nNo users found in database.")
        return True

    # Analyze passwords
    print("\n[3/4] Analyzing passwords...")
    plaintext_users = []
    hashed_users = []

    for user in users:
        username = user["username"]
        password = user["password"]

        if password.startswith("$2b$"):
            hashed_users.append(username)
            print(f"  ✓ {username:20} - Already hashed")
        else:
            plaintext_users.append(user)
            print(f"  ⚠️  {username:20} - PLAINTEXT (needs migration)")

    print("\nSummary:")
    print(f"  Already secure: {len(hashed_users)}")
    print(f"  Need migration: {len(plaintext_users)}")

    if not plaintext_users:
        print("\n✅ All passwords are already hashed. No migration needed!")
        return True

    if dry_run:
        print("\n" + "=" * 70)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 70)
        print("\nTo actually perform the migration, run:")
        print("  python migrate_passwords.py --execute")
        return True

    # Perform migration
    print("\n[4/4] Migrating passwords...")
    print("\n⚠️  WARNING: This will modify the database!")
    response = input("Are you sure you want to continue? (type 'yes' to confirm): ")

    if response.lower() != "yes":
        print("\nMigration cancelled.")
        return False

    hasher = PasswordHasher()
    success_count = 0
    failed_users = []

    for user in plaintext_users:
        username = user["username"]
        plaintext_password = user["password"]

        try:
            # Hash the password
            hashed_password = hasher.hash_password(plaintext_password)

            # Update in database
            supabase.table("users").update({"password": hashed_password}).eq("username", username).execute()

            print(f"  ✅ {username:20} - Migrated successfully")
            success_count += 1

        except Exception as e:
            print(f"  ❌ {username:20} - Failed: {e}")
            failed_users.append(username)

    print("\n" + "=" * 70)
    print("MIGRATION COMPLETE")
    print("=" * 70)
    print(f"  Successfully migrated: {success_count}")
    print(f"  Failed: {len(failed_users)}")

    if failed_users:
        print(f"\nFailed users: {', '.join(failed_users)}")
        print("Please check the error messages above and try again.")
        return False

    print("\n✅ All passwords have been migrated to secure bcrypt hashes!")
    print("\nNext steps:")
    print("  1. Verify you can still log in with existing accounts")
    print("  2. All new users will automatically use hashed passwords")
    print("  3. Emergency admin accounts are also hashed in .env file")

    return True


def backup_database():
    """Create a backup before migration."""
    print("\n" + "=" * 70)
    print("DATABASE BACKUP")
    print("=" * 70)
    print("\nBefore migrating passwords, it's recommended to backup your database.")
    print("\nOptions:")
    print("  1. Use Supabase Dashboard:")
    print("     https://supabase.com/dashboard/project/_/database/backups")
    print("  2. Export users table manually:")
    print("     - Go to Supabase SQL Editor")
    print("     - Run: SELECT * FROM users;")
    print("     - Save the results")
    print("  3. Create a full database backup using pg_dump")

    response = input("\nHave you backed up the database? (yes/no): ")
    return response.lower() == "yes"


def main():
    """Main entry point."""
    print("\n" + "=" * 70)
    print("PHARMACY MANAGEMENT SYSTEM - PASSWORD MIGRATION")
    print("=" * 70)
    print("\nThis utility will migrate all plaintext passwords to secure bcrypt hashes.")
    print("This is a one-time operation that improves security.")

    # Check for command line arguments
    dry_run = True
    if "--execute" in sys.argv:
        dry_run = False

        # Require backup confirmation for actual migration
        if not backup_database():
            print("\n❌ Migration aborted. Please backup first!")
            return 1
    else:
        print("\n📋 Running in DRY RUN mode (no changes will be made)")

    try:
        success = migrate_passwords(dry_run=dry_run)
        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\nMigration cancelled by user.")
        return 1

    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
