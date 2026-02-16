#!/usr/bin/env python3
"""
Test data seeding script for E2E tests.
Creates test users and audit entries in the database.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent / 'Pharmacy_Arc'))

try:
    from config import Config
    from security import PasswordHasher
    from supabase import create_client
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure you're in the project root and have installed requirements.txt")
    sys.exit(1)

def seed_test_data():
    """Seed database with test data."""
    print("🌱 Seeding test data...")
    
    # Initialize Supabase client
    try:
        supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return False
    
    password_hasher = PasswordHasher()
    
    # Test users to create
    test_users = [
        {
            "username": "test_admin",
            "password": "TestAdmin123!",
            "role": "admin",
            "store": "All"
        },
        {
            "username": "test_manager",
            "password": "TestManager123!",
            "role": "manager",
            "store": "Carimas #1"
        },
        {
            "username": "test_staff",
            "password": "TestStaff123!",
            "role": "staff",
            "store": "Carimas #1"
        },
        {
            "username": "playwright_user",
            "password": "PlaywrightTest123!",
            "role": "admin",
            "store": "All"
        }
    ]
    
    print("\n👤 Creating test users...")
    for user_data in test_users:
        try:
            # Check if user exists
            existing = supabase.table("users").select("*").eq("username", user_data["username"]).execute()
            
            if existing.data:
                print(f"   ⏭️  User '{user_data['username']}' already exists, skipping")
                continue
            
            # Hash password
            hashed_password = password_hasher.hash_password(user_data["password"])
            
            # Insert user
            supabase.table("users").insert({
                "username": user_data["username"],
                "password": hashed_password,
                "role": user_data["role"],
                "store": user_data["store"]
            }).execute()
            
            print(f"   ✅ Created user: {user_data['username']} (role: {user_data['role']})")
        except Exception as e:
            print(f"   ❌ Failed to create user {user_data['username']}: {e}")
    
    # Test audit entries to create
    test_entries = [
        {
            "date": "2026-02-15",
            "reg": "Reg 1",
            "staff": "Test Staff",
            "store": "Carimas #1",
            "gross": 1500.00,
            "net": 1450.00,
            "variance": 5.50,
            "payload": {
                "date": "2026-02-15",
                "reg": "Reg 1",
                "staff": "Test Staff",
                "store": "Carimas #1",
                "gross": 1500.00,
                "net": 1450.00,
                "variance": 5.50,
                "breakdown": {
                    "cash": 800.00,
                    "ath": 200.00,
                    "visa": 300.00,
                    "mc": 150.00,
                    "amex": 50.00,
                    "disc": 0.00,
                    "wic": 0.00,
                    "mcs": 0.00,
                    "athm": 0.00,
                    "sss": 0.00,
                    "payouts": 50.00,
                    "payoutList": [{"r": "Test Payout", "a": 50.00}],
                    "taxState": 84.00,
                    "taxCity": 8.00,
                    "float": 150.00,
                    "actual": 855.50,
                    "ccTips": 0.00
                }
            }
        },
        {
            "date": "2026-02-14",
            "reg": "Reg 2",
            "staff": "Test Manager",
            "store": "Carimas #2",
            "gross": 2000.00,
            "net": 1980.00,
            "variance": -10.00,
            "payload": {
                "date": "2026-02-14",
                "reg": "Reg 2",
                "staff": "Test Manager",
                "store": "Carimas #2",
                "gross": 2000.00,
                "net": 1980.00,
                "variance": -10.00,
                "breakdown": {
                    "cash": 1000.00,
                    "ath": 300.00,
                    "visa": 400.00,
                    "mc": 200.00,
                    "amex": 100.00,
                    "disc": 0.00,
                    "wic": 0.00,
                    "mcs": 0.00,
                    "athm": 0.00,
                    "sss": 0.00,
                    "payouts": 20.00,
                    "payoutList": [],
                    "taxState": 105.00,
                    "taxCity": 10.00,
                    "float": 150.00,
                    "actual": 980.00,
                    "ccTips": 0.00
                }
            }
        }
    ]
    
    print("\n📊 Creating test audit entries...")
    for entry in test_entries:
        try:
            # Check if entry exists for this date and store
            existing = supabase.table("audits").select("*").eq("date", entry["date"]).eq("store", entry["store"]).execute()
            
            if existing.data:
                print(f"   ⏭️  Entry for {entry['date']} at {entry['store']} already exists, skipping")
                continue
            
            # Insert entry
            supabase.table("audits").insert(entry).execute()
            print(f"   ✅ Created audit entry: {entry['date']} - {entry['store']} (${entry['gross']})")
        except Exception as e:
            print(f"   ❌ Failed to create audit entry for {entry['date']}: {e}")
    
    print("\n✅ Test data seeding complete!")
    print("\n📝 Test credentials:")
    print("   Admin:   test_admin / TestAdmin123!")
    print("   Manager: test_manager / TestManager123!")
    print("   Staff:   test_staff / TestStaff123!")
    print("   Playwright: playwright_user / PlaywrightTest123!")
    
    return True

def cleanup_test_data():
    """Remove test data from database."""
    print("🧹 Cleaning up test data...")
    
    try:
        supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return False
    
    test_usernames = ["test_admin", "test_manager", "test_staff", "playwright_user", "test_new_user"]
    
    print("\n👤 Removing test users...")
    for username in test_usernames:
        try:
            supabase.table("users").delete().eq("username", username).execute()
            print(f"   ✅ Removed user: {username}")
        except Exception as e:
            print(f"   ⚠️  Failed to remove user {username}: {e}")
    
    print("\n✅ Cleanup complete!")
    return True

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage test data for E2E tests")
    parser.add_argument("action", choices=["seed", "cleanup"], help="Action to perform")
    
    args = parser.parse_args()
    
    if args.action == "seed":
        success = seed_test_data()
    elif args.action == "cleanup":
        success = cleanup_test_data()
    
    sys.exit(0 if success else 1)
