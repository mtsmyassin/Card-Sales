# End-to-End Testing with Playwright

This directory contains Playwright end-to-end tests for the Pharmacy Sales Tracker application.

## 🎯 Test Coverage

### 1. Edit Flow Test (`tests/edit-flow.spec.js`)
Tests the complete edit workflow:
- ✅ Login authentication
- ✅ Navigate to History/List page
- ✅ Click Edit button on a record
- ✅ Assert navigation to edit view
- ✅ Assert form fields pre-populate correctly
- ✅ Modify field values
- ✅ Save changes
- ✅ Assert list shows updated values after refresh
- ✅ Cancel edit and verify form reset

### 2. Users Tab Auto-Sync Test (`tests/users-tab.spec.js`)
Tests the Users tab auto-sync functionality:
- ✅ Login as admin
- ✅ Open Users tab
- ✅ Assert users fetch request is fired automatically
- ✅ Assert DOM shows expected users
- ✅ Create a new user
- ✅ Assert list updates without manual refresh
- ✅ Delete a user
- ✅ Assert list updates after deletion
- ✅ Edit user and verify changes reflected immediately

## 📋 Prerequisites

1. **Python 3.8+** with dependencies installed:
   ```bash
   cd Pharmacy_Arc
   pip install -r requirements.txt
   ```

2. **Node.js 18+** installed on your system

3. **Supabase database** configured with:
   - `users` table
   - `audits` table
   - Valid credentials in `.env` file

4. **Environment configuration** (`.env` file in `Pharmacy_Arc/` directory):
   ```bash
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key-here
   FLASK_SECRET_KEY=your-secret-key-minimum-32-chars
   FLASK_PORT=5013
   # ... other config values
   ```

## 🚀 Installation

1. **Install Node dependencies**:
   ```bash
   npm install
   ```

2. **Install Playwright browsers**:
   ```bash
   npm run install:playwright
   # or
   npx playwright install --with-deps chromium
   ```

3. **Seed test data**:
   ```bash
   python3 seed-test-data.py seed
   ```
   
   This creates test users:
   - `test_admin` / `TestAdmin123!` (admin role)
   - `test_manager` / `TestManager123!` (manager role)
   - `test_staff` / `TestStaff123!` (staff role)
   - `playwright_user` / `PlaywrightTest123!` (admin role)
   
   And test audit entries for testing edit functionality.

## 🧪 Running Tests

### Run all tests
```bash
npm test
```

### Run tests in headed mode (see browser)
```bash
npm run test:headed
```

### Run tests in debug mode
```bash
npm run test:debug
```

### Run tests in UI mode (interactive)
```bash
npm run test:ui
```

### Run specific test file
```bash
npx playwright test tests/edit-flow.spec.js
npx playwright test tests/users-tab.spec.js
```

### Run with different browsers
```bash
npx playwright test --project=chromium
npx playwright test --project=firefox
npx playwright test --project=webkit
```

### View test report
```bash
npm run test:report
# or
npx playwright show-report
```

## 📊 Test Results

After running tests, results are available in:
- **HTML Report**: `playwright-report/index.html`
- **Test Results**: `test-results/` directory
- **Screenshots**: Captured on failures in `test-results/`
- **Videos**: Recorded on failures in `test-results/`

## 🔧 Configuration

Test configuration is in `playwright.config.js`:

```javascript
{
  baseURL: 'http://127.0.0.1:5013',  // Flask server URL
  timeout: 30000,                      // Test timeout
  retries: 2,                          // Retry failed tests in CI
  workers: 1,                          // Run tests sequentially
  webServer: {
    command: 'cd Pharmacy_Arc && python3 app.py',
    url: 'http://127.0.0.1:5013',
    reuseExistingServer: true
  }
}
```

## 🧹 Cleanup

After testing, clean up test data:
```bash
python3 seed-test-data.py cleanup
```

This removes:
- All test users (test_admin, test_manager, test_staff, playwright_user)
- Any users created during tests

## 🐛 Troubleshooting

### Server won't start
- Check if port 5013 is already in use
- Verify `.env` file exists in `Pharmacy_Arc/` directory
- Check Python dependencies are installed

### Tests fail to login
- Verify test data is seeded: `python3 seed-test-data.py seed`
- Check Supabase credentials in `.env`
- Ensure users table exists in database

### Tests timeout
- Increase timeout in `playwright.config.js`
- Check network connection to Supabase
- Run tests in headed mode to see what's happening

### Can't find elements
- Check if the application structure has changed
- Run tests in debug mode: `npm run test:debug`
- Use Playwright Inspector to step through tests

## 🔄 CI/CD Integration

Tests run automatically in GitHub Actions on:
- Push to `main` branch
- Push to feature branches
- Pull requests

Required secrets in GitHub:
- `TEST_SUPABASE_URL` - Test database URL
- `TEST_SUPABASE_KEY` - Test database key
- `TEST_FLASK_SECRET_KEY` - Secret key for Flask sessions

## 📝 Writing New Tests

Use the test helpers in `tests/helpers.js`:

```javascript
const { test, navigateToTab, waitForApiResponse } = require('./helpers');

test.describe('My Test Suite', () => {
  test('should do something', async ({ authenticatedPage: page }) => {
    // authenticatedPage fixture handles login automatically
    
    // Navigate to a tab
    await navigateToTab(page, 'logs');
    
    // Wait for API response
    const response = await waitForApiResponse(page, '/api/list');
    
    // Make assertions
    expect(response.status()).toBe(200);
  });
});
```

## 🎭 Test Data Management

### Seed Data Structure
- **Users**: 4 test users with different roles
- **Audit Entries**: 2 sample entries for edit testing

### Custom Test Data
Add more test data in `seed-test-data.py`:

```python
test_entries = [
    {
        "date": "2026-02-15",
        "store": "Carimas #1",
        "gross": 1500.00,
        # ... more fields
    }
]
```

## 🔒 Security Considerations

- Test data uses separate test users
- Tests run in isolated environment
- Cleanup removes all test data after tests
- No production credentials in code
- CI uses GitHub Secrets for credentials

## 📚 Resources

- [Playwright Documentation](https://playwright.dev/docs/intro)
- [Playwright Best Practices](https://playwright.dev/docs/best-practices)
- [Writing Tests](https://playwright.dev/docs/writing-tests)
- [Debugging Tests](https://playwright.dev/docs/debug)

## 🤝 Contributing

When adding new tests:
1. Use the existing helper functions
2. Follow the page object pattern
3. Add cleanup steps for any test data created
4. Update this README with new test coverage
5. Ensure tests pass locally before committing

## 📞 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Playwright documentation
3. Check test logs in `playwright-report/`
4. Run tests in debug mode for detailed insights
