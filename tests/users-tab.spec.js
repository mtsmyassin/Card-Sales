// @ts-check
const { expect } = require('@playwright/test');
const { test, navigateToTab, waitForApiResponse } = require('./helpers');

test.describe('Users Tab Auto-Sync', () => {
  test('should auto-fetch users on tab open and auto-refresh after create/delete', async ({ authenticatedPage: page }) => {
    // Step 1: Navigate to Users tab
    console.log('Step 1: Navigating to Users tab...');
    
    // Set up request listener before navigating to track the API call
    let usersApiCalled = false;
    page.on('request', request => {
      if (request.url().includes('/api/users/list')) {
        usersApiCalled = true;
        console.log('✅ API request to /api/users/list detected');
      }
    });
    
    // Navigate to Users tab
    await navigateToTab(page, 'users');
    
    // Step 2: Assert users fetch request was fired
    console.log('Step 2: Verifying API request was fired...');
    
    // Wait a bit for the request to complete
    await page.waitForTimeout(2000);
    
    // Verify the API was called
    expect(usersApiCalled).toBe(true);
    
    // Step 3: Assert DOM shows expected users
    console.log('Step 3: Verifying users are displayed in DOM...');
    
    // Wait for user table to be populated
    await page.waitForSelector('#userTable table', { timeout: 5000 });
    
    // Check that we have user rows
    const userRows = await page.locator('#userTable table tr').count();
    console.log(`Found ${userRows} user rows (including header)`);
    expect(userRows).toBeGreaterThan(1); // At least header + 1 user
    
    // Verify test users are present
    const userTableContent = await page.locator('#userTable').textContent();
    expect(userTableContent).toContain('test_admin');
    console.log('✅ Test users found in table');
    
    // Step 4: Create a new test user
    console.log('Step 4: Creating a new test user...');
    
    const testUsername = `test_new_user_${Date.now()}`;
    const testPassword = 'TestNewUser123!';
    
    // Fill in user form
    await page.locator('#u_name').fill(testUsername);
    await page.locator('#u_pass').fill(testPassword);
    await page.locator('#u_role').selectOption('staff');
    await page.locator('#u_store').selectOption('Carimas #1');
    
    // Set up response listener for the save request
    const saveResponsePromise = waitForApiResponse(page, '/api/users/save');
    
    // Click save button
    await page.locator('#userSaveBtn').click();
    
    // Wait for save response
    const saveResponse = await saveResponsePromise;
    expect(saveResponse.status()).toBe(200);
    
    // Handle alert dialog
    page.once('dialog', async dialog => {
      console.log('Save alert:', dialog.message());
      expect(dialog.message()).toContain('Saved');
      await dialog.accept();
    });
    
    // Step 5: Assert list auto-refreshes (no manual action needed)
    console.log('Step 5: Verifying list auto-refreshed after create...');
    
    // Wait a moment for the refresh
    await page.waitForTimeout(1500);
    
    // Verify the new user appears in the table
    const updatedTableContent = await page.locator('#userTable').textContent();
    expect(updatedTableContent).toContain(testUsername);
    console.log(`✅ New user "${testUsername}" found in table (auto-refreshed)`);
    
    // Verify the form was reset
    const saveButtonText = await page.locator('#userSaveBtn').textContent();
    expect(saveButtonText).toBe('Create User');
    
    // Step 6: Delete the test user
    console.log('Step 6: Deleting the test user...');
    
    // Find the delete button for our test user
    const deleteButton = page.locator(`button.btn-del:near(:text("${testUsername}"))`).first();
    
    // Set up response listener for delete request
    const deleteResponsePromise = waitForApiResponse(page, '/api/users/delete');
    
    // Handle confirmation dialog
    page.once('dialog', async dialog => {
      console.log('Delete confirmation:', dialog.message());
      expect(dialog.message()).toContain('Delete');
      await dialog.accept();
    });
    
    // Click delete button
    await deleteButton.click();
    
    // Wait for delete response
    const deleteResponse = await deleteResponsePromise;
    expect(deleteResponse.status()).toBe(200);
    
    // Step 7: Assert list auto-refreshes after delete
    console.log('Step 7: Verifying list auto-refreshed after delete...');
    
    // Wait a moment for the refresh
    await page.waitForTimeout(1500);
    
    // Verify the user is removed from the table
    const finalTableContent = await page.locator('#userTable').textContent();
    expect(finalTableContent).not.toContain(testUsername);
    console.log(`✅ User "${testUsername}" removed from table (auto-refreshed)`);
    
    console.log('✅ Users tab auto-sync test completed successfully!');
  });
  
  test('should show users immediately on first tab open without manual action', async ({ authenticatedPage: page }) => {
    console.log('Testing immediate user load on tab open...');
    
    // Start on a different tab
    await navigateToTab(page, 'dash');
    await page.waitForTimeout(500);
    
    // Set up to track when API is called
    let apiCallTime = null;
    page.on('request', request => {
      if (request.url().includes('/api/users/list')) {
        apiCallTime = Date.now();
        console.log('API called at:', new Date(apiCallTime).toISOString());
      }
    });
    
    // Record when we click the tab
    const clickTime = Date.now();
    
    // Navigate to Users tab
    await navigateToTab(page, 'users');
    
    // Wait for table to appear
    await page.waitForSelector('#userTable table', { timeout: 5000 });
    
    // Verify API was called
    expect(apiCallTime).toBeTruthy();
    
    // Verify it happened quickly (within 2 seconds of tab click)
    const timeDiff = apiCallTime - clickTime;
    console.log(`API called ${timeDiff}ms after tab click`);
    expect(timeDiff).toBeLessThan(2000);
    
    // Verify users are displayed
    const userRows = await page.locator('#userTable table tr').count();
    expect(userRows).toBeGreaterThan(1);
    
    console.log('✅ Immediate load test completed successfully!');
  });
  
  test('should update user and see changes reflected immediately', async ({ authenticatedPage: page }) => {
    console.log('Testing user update with auto-refresh...');
    
    // Navigate to Users tab
    await navigateToTab(page, 'users');
    await page.waitForSelector('#userTable table', { timeout: 5000 });
    
    // Find test_staff user and click edit
    const editButton = page.locator('button.btn-edit:near(:text("test_staff"))').first();
    await editButton.click();
    
    // Verify form is populated (button should change to "Update User")
    await expect(page.locator('#userSaveBtn')).toHaveText('Update User');
    
    // Change the role
    const originalRole = await page.locator('#u_role').inputValue();
    const newRole = originalRole === 'staff' ? 'manager' : 'staff';
    await page.locator('#u_role').selectOption(newRole);
    
    // Save changes
    const saveResponsePromise = waitForApiResponse(page, '/api/users/save');
    await page.locator('#userSaveBtn').click();
    
    // Wait for response
    await saveResponsePromise;
    
    // Handle alert
    page.once('dialog', async dialog => {
      await dialog.accept();
    });
    
    // Wait for refresh
    await page.waitForTimeout(1500);
    
    // Verify the table shows updated role
    const userRow = page.locator(`tr:has-text("test_staff")`);
    await expect(userRow).toContainText(newRole);
    
    console.log(`✅ User updated from ${originalRole} to ${newRole} and changes reflected`);
  });
});
