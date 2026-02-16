// @ts-check
const { test as base } = require('@playwright/test');

/**
 * Fixture to handle authenticated sessions
 */
const test = base.extend({
  /**
   * Authenticated page fixture - automatically logs in as admin
   */
  authenticatedPage: async ({ page }, use) => {
    // Navigate to login page
    await page.goto('/');
    
    // Wait for login form to be visible
    await page.waitForSelector('input[name="username"]', { timeout: 10000 });
    
    // Login as admin test user
    await page.fill('input[name="username"]', 'test_admin');
    await page.fill('input[name="password"]', 'TestAdmin123!');
    await page.click('button[type="submit"]');
    
    // Wait for successful login - check for dashboard elements
    await page.waitForSelector('.tabs', { timeout: 10000 });
    
    // Provide the authenticated page to the test
    await use(page);
    
    // Cleanup: logout after test
    try {
      await page.click('button:has-text("Log Out")');
    } catch (e) {
      // Ignore if already logged out
    }
  }
});

/**
 * Helper function to login with specific credentials
 */
async function login(page, username, password) {
  await page.goto('/');
  await page.waitForSelector('input[name="username"]');
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('.tabs', { timeout: 10000 });
}

/**
 * Helper function to navigate to a specific tab
 */
async function navigateToTab(page, tabName) {
  const tabSelector = `#tab-${tabName}`;
  await page.click(tabSelector);
  await page.waitForTimeout(500); // Wait for tab transition
}

/**
 * Helper function to wait for network request
 */
async function waitForApiRequest(page, urlPattern) {
  return page.waitForRequest(request => {
    return request.url().includes(urlPattern);
  });
}

/**
 * Helper function to wait for network response
 */
async function waitForApiResponse(page, urlPattern) {
  return page.waitForResponse(response => {
    return response.url().includes(urlPattern);
  });
}

module.exports = {
  test,
  login,
  navigateToTab,
  waitForApiRequest,
  waitForApiResponse
};
