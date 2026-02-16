# Quick Start Guide - E2E Testing

This is a quick reference for running end-to-end tests. For complete documentation, see [E2E_TESTING_README.md](E2E_TESTING_README.md).

## Prerequisites
- Node.js 18+ installed
- Python 3.8+ with dependencies installed
- Supabase database configured

## Quick Start

### Option 1: Use the convenience script (recommended)
```bash
./run-tests.sh           # Run all tests
./run-tests.sh headed    # Run with visible browser
./run-tests.sh debug     # Run in debug mode
./run-tests.sh ui        # Run in UI mode
```

### Option 2: Manual steps
```bash
# 1. Install dependencies
npm install
npx playwright install chromium

# 2. Configure .env file (if not already done)
cp Pharmacy_Arc/.env.test Pharmacy_Arc/.env
# Edit .env with your Supabase credentials

# 3. Seed test data
python3 seed-test-data.py seed

# 4. Run tests
npm test

# 5. View report
npm run test:report

# 6. Cleanup
python3 seed-test-data.py cleanup
```

## Test Coverage
- ✅ Edit flow navigation and form pre-population
- ✅ Save changes and verify updates in list
- ✅ Users tab auto-sync on tab open
- ✅ User creation/deletion with auto-refresh

## Test Users
The seed script creates these test accounts:
- `test_admin` / `TestAdmin123!` - Admin role
- `test_manager` / `TestManager123!` - Manager role  
- `test_staff` / `TestStaff123!` - Staff role
- `playwright_user` / `PlaywrightTest123!` - Admin role

## CI Integration
Tests run automatically in GitHub Actions on push/PR.

Required secrets in GitHub:
- `TEST_SUPABASE_URL`
- `TEST_SUPABASE_KEY`
- `TEST_FLASK_SECRET_KEY`

## Troubleshooting

### Can't connect to database
- Verify `.env` file exists in `Pharmacy_Arc/` directory
- Check Supabase credentials are correct
- Ensure database tables exist (users, audits)

### Tests timeout
- Check if Flask server started on port 5013
- Verify no other process is using port 5013
- Increase timeout in `playwright.config.js`

### Can't find test data
- Run `python3 seed-test-data.py seed` before tests
- Verify Supabase connection is working
- Check database tables have correct schema

## More Information
See [E2E_TESTING_README.md](E2E_TESTING_README.md) for:
- Detailed test descriptions
- Advanced configuration
- Writing new tests
- CI/CD setup details
- Full troubleshooting guide
