#!/usr/bin/env python3
"""
Setup and initialization script for Pharmacy Management System.
Helps configure the application for first-time use.
"""
import sys
import os
from pathlib import Path

try:
    from security import PasswordHasher, generate_secret_key
except ImportError:
    print("Error: Required modules not found. Please run: pip install -r requirements.txt")
    sys.exit(1)


def create_env_file():
    """Create .env file from .env.example."""
    env_example = Path('.env.example')
    env_file = Path('.env')
    
    if env_file.exists():
        response = input('.env file already exists. Overwrite? (yes/no): ')
        if response.lower() != 'yes':
            print("Keeping existing .env file.")
            return False
    
    if not env_example.exists():
        print("Error: .env.example not found!")
        return False
    
    # Copy example file
    with open(env_example, 'r') as src:
        content = src.read()
    
    # Generate secure secret key
    secret_key = generate_secret_key()
    content = content.replace(
        'generate-a-strong-random-secret-key-here-minimum-32-characters',
        secret_key
    )
    
    with open(env_file, 'w') as dst:
        dst.write(content)
    
    print(f"✅ Created .env file with generated secret key")
    return True


def setup_emergency_admin():
    """Set up emergency admin accounts with hashed passwords."""
    print("\n" + "=" * 60)
    print("EMERGENCY ADMIN ACCOUNT SETUP")
    print("=" * 60)
    print("\nThese accounts will work even if the database is offline.")
    print("You need to set passwords for two accounts:")
    print("  1. super (Super Admin - full access)")
    print("  2. admin (Admin - cannot unlock days)")
    
    # Super admin
    print("\n--- Super Admin Account ---")
    super_password = input("Enter password for 'super' account: ")
    if len(super_password) < 8:
        print("Warning: Password is shorter than 8 characters!")
    
    super_hash = PasswordHasher.hash_password(super_password)
    
    # Regular admin
    print("\n--- Admin Account ---")
    admin_password = input("Enter password for 'admin' account: ")
    if len(admin_password) < 8:
        print("Warning: Password is shorter than 8 characters!")
    
    admin_hash = PasswordHasher.hash_password(admin_password)
    
    # Update .env file
    env_file = Path('.env')
    if not env_file.exists():
        print("Error: .env file not found! Run setup first.")
        return False
    
    with open(env_file, 'r') as f:
        lines = f.readlines()
    
    # Replace the emergency account lines
    new_lines = []
    for line in lines:
        if line.startswith('EMERGENCY_ADMIN_SUPER='):
            new_lines.append(f'EMERGENCY_ADMIN_SUPER=super:{super_hash}\n')
        elif line.startswith('EMERGENCY_ADMIN_BASIC='):
            new_lines.append(f'EMERGENCY_ADMIN_BASIC=admin:{admin_hash}\n')
        else:
            new_lines.append(line)
    
    with open(env_file, 'w') as f:
        f.writelines(new_lines)
    
    print("\n✅ Emergency admin accounts configured!")
    print("\nYou can now login with:")
    print(f"  Username: super")
    print(f"  Username: admin")
    
    return True


def setup_supabase():
    """Configure Supabase connection."""
    print("\n" + "=" * 60)
    print("SUPABASE DATABASE CONFIGURATION")
    print("=" * 60)
    print("\nYou need your Supabase project credentials.")
    print("Get these from: https://supabase.com/dashboard/project/_/settings/api")
    
    url = input("\nEnter Supabase URL (e.g., https://xxx.supabase.co): ").strip()
    key = input("Enter Supabase Anon/Public Key: ").strip()
    
    if not url or not key:
        print("Error: Both URL and Key are required!")
        return False
    
    # Update .env file
    env_file = Path('.env')
    if not env_file.exists():
        print("Error: .env file not found! Run setup first.")
        return False
    
    with open(env_file, 'r') as f:
        lines = f.readlines()
    
    new_lines = []
    for line in lines:
        if line.startswith('SUPABASE_URL='):
            new_lines.append(f'SUPABASE_URL={url}\n')
        elif line.startswith('SUPABASE_KEY='):
            new_lines.append(f'SUPABASE_KEY={key}\n')
        else:
            new_lines.append(line)
    
    with open(env_file, 'w') as f:
        f.writelines(new_lines)
    
    print("\n✅ Supabase configuration saved!")
    return True


def verify_setup():
    """Verify that setup is complete."""
    print("\n" + "=" * 60)
    print("VERIFYING SETUP")
    print("=" * 60)
    
    try:
        from config import Config
        errors = Config.validate()
        
        if errors:
            print("\n❌ Configuration has errors:")
            for error in errors:
                print(f"  - {error}")
            return False
        else:
            print("\n✅ Configuration is valid!")
            print(f"\nSettings:")
            print(f"  Port: {Config.PORT}")
            print(f"  Session Timeout: {Config.SESSION_TIMEOUT_MINUTES} minutes")
            print(f"  Max Login Attempts: {Config.MAX_LOGIN_ATTEMPTS}")
            print(f"  Lockout Duration: {Config.LOCKOUT_DURATION_MINUTES} minutes")
            return True
    
    except Exception as e:
        print(f"\n❌ Error verifying setup: {e}")
        return False


def main():
    """Main setup flow."""
    print("\n" + "=" * 60)
    print("PHARMACY MANAGEMENT SYSTEM - SETUP WIZARD")
    print("=" * 60)
    print("\nThis wizard will help you configure the application.")
    print("You'll need:")
    print("  - Supabase project credentials")
    print("  - Passwords for emergency admin accounts")
    
    input("\nPress Enter to continue...")
    
    # Step 1: Create .env file
    print("\n[Step 1/4] Creating configuration file...")
    if not create_env_file():
        print("Skipped .env creation")
    
    # Step 2: Configure Supabase
    print("\n[Step 2/4] Configuring database connection...")
    setup = input("Configure Supabase now? (yes/no): ")
    if setup.lower() == 'yes':
        if not setup_supabase():
            print("Warning: Supabase configuration incomplete!")
    else:
        print("Skipped. You'll need to manually edit .env later.")
    
    # Step 3: Setup admin accounts
    print("\n[Step 3/4] Setting up admin accounts...")
    setup_admin = input("Set up emergency admin accounts now? (yes/no): ")
    if setup_admin.lower() == 'yes':
        if not setup_emergency_admin():
            print("Warning: Admin accounts not configured!")
    else:
        print("Skipped. You'll need to manually edit .env later.")
    
    # Step 4: Verify
    print("\n[Step 4/4] Verifying setup...")
    if verify_setup():
        print("\n" + "=" * 60)
        print("✅ SETUP COMPLETE!")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Ensure your Supabase database has the required tables")
        print("     (See DatabaseSchema.txt for SQL commands)")
        print("  2. Run: python app.py")
        print("  3. The application will open in your browser")
        print("\nTo build a Windows executable:")
        print("  pyinstaller --noconsole --onefile --add-data \"logo.png;.\" --add-data \"carthage.png;.\" --add-data \".env;.\" app.py")
    else:
        print("\n" + "=" * 60)
        print("⚠️  SETUP INCOMPLETE")
        print("=" * 60)
        print("\nPlease fix the errors above and run this script again.")
        print("Or manually edit the .env file.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
