# MANUAL VERIFICATION CHECKLIST
## Pharmacy Sales Tracker - User Acceptance Testing

**Version:** v41-VALIDATED  
**Date:** 2026-02-16  
**Purpose:** Step-by-step verification guide for non-technical users

---

## PRE-TESTING SETUP

### ✅ Requirements Checklist
- [ ] Application is running (open browser, go to http://127.0.0.1:5013)
- [ ] You have test credentials for different roles:
  - Staff user
  - Manager user
  - Admin user
  - Super admin user
- [ ] Database is accessible (check that login page loads)
- [ ] You have a notepad or document to record any issues

---

## TEST SUITE 1: AUTHENTICATION & SECURITY

### Test 1.1: Login with Valid Credentials ✅
**Steps:**
1. Open the application in your web browser
2. Enter a valid username (e.g., `admin`)
3. Enter the correct password
4. Click "Login"

**Expected Result:**
- ✅ You are logged in successfully
- ✅ You see the main dashboard (Audit Entry tab)
- ✅ Your username appears in the top-right corner
- ✅ You see tabs appropriate for your role

**Pass/Fail:** ___________

---

### Test 1.2: Login with Invalid Password ✅
**Steps:**
1. Logout (click "Log Out" button in top-right)
2. Enter a valid username
3. Enter an INCORRECT password
4. Click "Login"

**Expected Result:**
- ✅ Login fails with "Invalid credentials" message
- ✅ You remain on the login page
- ✅ No error details are shown (no stack trace)

**Pass/Fail:** ___________

---

### Test 1.3: Account Lockout Protection ✅
**Steps:**
1. Try to login with wrong password 5 times in a row
2. On the 6th attempt, try logging in

**Expected Result:**
- ✅ After 5 failed attempts, you see "Account locked" message
- ✅ You must wait 15 minutes before trying again

**Pass/Fail:** ___________

---

### Test 1.4: Session Timeout ⏱️
**Steps:**
1. Login successfully
2. Wait 30 minutes without any activity
3. Try to navigate to another tab or refresh the page

**Expected Result:**
- ✅ You are automatically logged out
- ✅ You are redirected to the login page

**Pass/Fail:** ___________ (Note: Takes 30 minutes)

---

## TEST SUITE 2: EDIT FLOW NAVIGATION (P0 CRITICAL)

### Test 2.1: Edit Audit Entry from History Tab ⭐ CRITICAL
**Steps:**
1. Login as manager or admin
2. Go to "History" tab
3. Find any existing audit entry
4. Click the ✏️ (edit) button on that entry

**Expected Result:**
- ✅ App automatically switches to "Audit Entry" tab
- ✅ All form fields are pre-populated with the entry's data
- ✅ Button changes from "Finalize & Upload" to "Update Record" (orange color)
- ✅ "Cancel" button appears
- ✅ Top section shows "EDITING RECORD #123" (with actual ID)

**Pass/Fail:** ___________

---

### Test 2.2: Save Edited Entry ⭐ CRITICAL
**Steps:**
1. After editing (Test 2.1), change any field (e.g., modify cash amount)
2. Click "Update Record" button
3. Wait for confirmation

**Expected Result:**
- ✅ Alert shows "Saved!"
- ✅ Form resets (button returns to "Finalize & Upload", blue color)
- ✅ App switches to "History" tab automatically
- ✅ The updated entry appears in the history list with new values

**Pass/Fail:** ___________

---

### Test 2.3: Cancel Edit ✅
**Steps:**
1. Click edit on any entry
2. Change some fields
3. Click "Cancel" button (appears during edit mode)

**Expected Result:**
- ✅ Form resets without saving changes
- ✅ Button returns to "Finalize & Upload"
- ✅ No data is modified in the database

**Pass/Fail:** ___________

---

## TEST SUITE 3: USERS TAB AUTO-SYNC (P0 CRITICAL)

### Test 3.1: Users Tab Auto-Loads on First Open ⭐ CRITICAL
**Steps:**
1. Login as admin or super admin
2. Click on "Users" tab

**Expected Result:**
- ✅ User table automatically loads and displays all users
- ✅ You see columns: User, Role, Store, Pass (or ••••), Actions
- ✅ No need to click any "Refresh" or "Load" button

**Pass/Fail:** ___________

---

### Test 3.2: Users Tab Refreshes After Creating User ✅
**Steps:**
1. On the Users tab, fill in the form:
   - Username: `testuser123`
   - Password: `TestPass123!`
   - Role: Staff
   - Store: Carimas #1
2. Click "Create User"

**Expected Result:**
- ✅ Alert shows "Saved"
- ✅ User table automatically refreshes
- ✅ New user `testuser123` appears in the table immediately
- ✅ No manual refresh needed

**Pass/Fail:** ___________

---

### Test 3.3: Users Tab Refreshes After Deleting User ✅
**Steps:**
1. Find the user `testuser123` in the table
2. Click the 🗑 (delete) button next to that user
3. Confirm deletion

**Expected Result:**
- ✅ User table automatically refreshes
- ✅ `testuser123` is removed from the table immediately
- ✅ No manual refresh needed

**Pass/Fail:** ___________

---

## TEST SUITE 4: INPUT VALIDATION (SECURITY)

### Test 4.1: Create Audit with Invalid Date ✅
**Steps:**
1. Go to "Audit Entry" tab
2. Enter date as `99-99-9999` (invalid format)
3. Fill in other required fields
4. Click "Finalize & Upload"

**Expected Result:**
- ✅ Error message appears: "Invalid date format. Use YYYY-MM-DD"
- ✅ Entry is NOT saved
- ✅ App does not crash

**Pass/Fail:** ___________

---

### Test 4.2: Create Audit with Negative Gross ✅
**Steps:**
1. Fill in audit form with valid data
2. Set Gross Sales to `-1000` (negative)
3. Click "Finalize & Upload"

**Expected Result:**
- ✅ Error message appears: "Gross must be between 0 and 1,000,000"
- ✅ Entry is NOT saved

**Pass/Fail:** ___________

---

### Test 4.3: Create User with Short Username ✅
**Steps:**
1. Go to "Users" tab (admin only)
2. Try to create user with username: `ab` (only 2 characters)
3. Fill in password, role, store
4. Click "Create User"

**Expected Result:**
- ✅ Error message appears: "Username must be 3-50 characters"
- ✅ User is NOT created

**Pass/Fail:** ___________

---

### Test 4.4: Create User with Weak Password ✅
**Steps:**
1. Try to create user with password: `1234567` (only 7 characters)
2. Fill in username, role, store
3. Click "Create User"

**Expected Result:**
- ✅ Error message appears: "Password must be at least 8 characters"
- ✅ User is NOT created

**Pass/Fail:** ___________

---

### Test 4.5: Prevent Self-Deletion (Admin Safety) ✅
**Steps:**
1. Login as admin user (e.g., `admin`)
2. Go to "Users" tab
3. Find your own username in the list
4. Click the 🗑 (delete) button next to your own account
5. Confirm deletion

**Expected Result:**
- ✅ Error message appears: "Cannot delete your own account"
- ✅ Account is NOT deleted
- ✅ You remain logged in

**Pass/Fail:** ___________

---

## TEST SUITE 5: GLOBAL SYNC & DATA CONSISTENCY

### Test 5.1: History Refreshes After Creating Entry ✅
**Steps:**
1. Go to "Audit Entry" tab
2. Fill in all required fields
3. Click "Finalize & Upload"
4. Wait for "Saved!" alert
5. Observe which tab you are on

**Expected Result:**
- ✅ App automatically switches to "History" tab
- ✅ New entry appears at the top of the history list
- ✅ Data is accurate (matches what you entered)

**Pass/Fail:** ___________

---

### Test 5.2: History Refreshes After Deleting Entry ✅
**Steps:**
1. Go to "History" tab
2. Click 🗑 (delete) button on any entry
3. Confirm deletion

**Expected Result:**
- ✅ Entry disappears from the list immediately
- ✅ No manual refresh needed

**Pass/Fail:** ___________

---

### Test 5.3: Analytics Updates with New Data ✅
**Steps:**
1. Note the current total sales in "Command Center" tab
2. Create a new audit entry with gross = $1000
3. Go to "Command Center" tab
4. Select same date range

**Expected Result:**
- ✅ Total sales increases by $1000
- ✅ Charts update to reflect new data
- ✅ KPIs are accurate

**Pass/Fail:** ___________

---

## TEST SUITE 6: ROLE-BASED ACCESS CONTROL

### Test 6.1: Staff Cannot Edit Entries ✅
**Steps:**
1. Logout, then login as a Staff user
2. Go to "History" tab
3. Look for ✏️ (edit) button on entries

**Expected Result:**
- ✅ No edit button appears (only 🖨 print button)
- ✅ Staff cannot modify existing entries

**Pass/Fail:** ___________

---

### Test 6.2: Staff Cannot Access Users Tab ✅
**Steps:**
1. While logged in as Staff
2. Look at the navigation tabs

**Expected Result:**
- ✅ "Users" tab is NOT visible
- ✅ Staff can only see: Audit Entry, History

**Pass/Fail:** ___________

---

### Test 6.3: Manager Cannot Access Command Center ✅
**Steps:**
1. Logout, then login as Manager
2. Look at the navigation tabs

**Expected Result:**
- ✅ "Command Center" tab is NOT visible
- ✅ "Users" tab is NOT visible
- ✅ Manager can see: Audit Entry, Calendar, History

**Pass/Fail:** ___________

---

### Test 6.4: Admin Can Access Everything ✅
**Steps:**
1. Logout, then login as Admin or Super Admin
2. Look at all tabs

**Expected Result:**
- ✅ All tabs are visible: Audit Entry, Calendar, Command Center, History, Users

**Pass/Fail:** ___________

---

## TEST SUITE 7: OFFLINE MODE & SYNC

### Test 7.1: Save Entry While Offline ⚠️
**Steps:**
1. Disconnect from internet (turn off WiFi or unplug Ethernet)
2. Fill in audit entry form
3. Click "Finalize & Upload"

**Expected Result:**
- ✅ Alert shows "Offline Mode: Saved to Queue"
- ✅ "⚠️ Sync" button appears in top navigation
- ✅ Entry is saved locally (not lost)

**Pass/Fail:** ___________ (Requires internet disconnect)

---

### Test 7.2: Sync Queue When Online ⚠️
**Steps:**
1. After Test 7.1, reconnect to internet
2. Click the "⚠️ Sync" button
3. Wait for sync to complete

**Expected Result:**
- ✅ Sync button disappears after successful sync
- ✅ Entry appears in History tab
- ✅ Entry is saved to database

**Pass/Fail:** ___________ (Requires internet disconnect)

---

## TEST SUITE 8: PRINTING & REPORTS

### Test 8.1: Print Receipt ✅
**Steps:**
1. Go to "History" tab
2. Click 🖨 (print) button on any entry
3. Wait for print preview to open

**Expected Result:**
- ✅ New window opens with formatted receipt
- ✅ Store logo displays correctly
- ✅ All fields are present (Date, Staff, Cash Sales, etc.)
- ✅ Variance is calculated correctly
- ✅ Signature line appears at bottom

**Pass/Fail:** ___________

---

### Test 8.2: Print for Different Stores ✅
**Steps:**
1. Print a receipt for "Carimas #1" entry
2. Print a receipt for "Carthage" entry
3. Compare the logos

**Expected Result:**
- ✅ Carimas stores show Carimas logo
- ✅ Carthage store shows Carthage Express logo
- ✅ Store names are correct in headers

**Pass/Fail:** ___________

---

## TEST SUITE 9: ANALYTICS & CALENDAR

### Test 9.1: View Analytics Dashboard ✅
**Steps:**
1. Login as Admin
2. Go to "Command Center" tab
3. Select date range "Last 30 Days"
4. Observe the KPIs and charts

**Expected Result:**
- ✅ KPI cards show: Total Sales, Average Variance, Total Entries, Active Stores
- ✅ Line chart displays daily sales trend
- ✅ "Best Days" leaderboard shows top performers
- ✅ "Variance Outliers" shows days with significant issues

**Pass/Fail:** ___________

---

### Test 9.2: Calendar View Shows Entries ✅
**Steps:**
1. Go to "Calendar" tab
2. Select current month
3. Look for days with entries

**Expected Result:**
- ✅ Days with entries are highlighted (green for positive, red for negative variance)
- ✅ Each day shows gross sales and variance
- ✅ Clicking a day navigates to History tab filtered to that date

**Pass/Fail:** ___________

---

## TEST SUITE 10: USER MANAGEMENT (ADMIN ONLY)

### Test 10.1: Edit Existing User ✅
**Steps:**
1. Go to "Users" tab (admin only)
2. Click ✏️ (edit) button next to any user
3. Observe the form

**Expected Result:**
- ✅ Form pre-populates with user's current data
- ✅ Button changes to "Update User" (orange color)
- ✅ Page scrolls to top for editing

**Pass/Fail:** ___________

---

### Test 10.2: Change User Role ✅
**Steps:**
1. Edit a user (Test 10.1)
2. Change Role from "Staff" to "Manager"
3. Click "Update User"
4. Wait for confirmation

**Expected Result:**
- ✅ Alert shows "Saved"
- ✅ User table refreshes automatically
- ✅ User's role is updated to "Manager"

**Pass/Fail:** ___________

---

## FINAL CHECKLIST

### All Critical Features Working?
- [ ] Edit flow navigates correctly (Test 2.1, 2.2) ⭐
- [ ] Users tab auto-syncs (Test 3.1, 3.2, 3.3) ⭐
- [ ] Input validation prevents bad data (Tests 4.1-4.5)
- [ ] Data refreshes automatically (Tests 5.1-5.3)
- [ ] RBAC enforced correctly (Tests 6.1-6.4)

### Any Issues Found?
- Total tests run: _____
- Total passed: _____
- Total failed: _____

### Issue Report (if any)
| Test # | Issue Description | Severity |
|--------|-------------------|----------|
|        |                   |          |
|        |                   |          |
|        |                   |          |

---

## SIGN-OFF

**Tester Name:** _______________________________  
**Date:** _______________________________  
**Overall Status:** ⬜ PASS  ⬜ FAIL  ⬜ PASS WITH ISSUES

**Comments:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________

**Recommendation:** ⬜ Ready for Production  ⬜ Needs Fixes

---

**Next Steps (if issues found):**
1. Document all failed tests in issue tracker
2. Assign priority (P0/P1/P2) to each issue
3. Retest after fixes are applied
4. Complete this checklist again until all tests pass

**Deployment Authorization (if all pass):**
⬜ Approved by: _______________________ Date: ___________
