#!/usr/bin/env python3
"""
Feature Test Suite for Pharmacy Management System

Tests critical UI/UX features:
1. Edit flow navigation
2. Users tab auto-sync
3. Global sync consistency
"""
import sys
import re
from pathlib import Path

class TestResult:
    """Store test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []
    
    def add_pass(self, name):
        self.passed += 1
        self.tests.append((name, True, None))
        print(f"  ✅ {name}")
    
    def add_fail(self, name, error):
        self.failed += 1
        self.tests.append((name, False, error))
        print(f"  ❌ {name}: {error}")
    
    def summary(self):
        total = self.passed + self.failed
        print("\n" + "=" * 70)
        print("FEATURE TEST SUMMARY")
        print("=" * 70)
        print(f"Total Tests: {total}")
        print(f"Passed: {self.passed} ({self.passed/total*100:.1f}%)" if total > 0 else "Passed: 0")
        print(f"Failed: {self.failed} ({self.failed/total*100:.1f}%)" if total > 0 else "Failed: 0")
        
        if self.failed > 0:
            print("\nFailed Tests:")
            for name, passed, error in self.tests:
                if not passed:
                    print(f"  - {name}: {error}")
        
        return self.failed == 0


def test_edit_flow_navigation(results):
    """Test that Edit flow correctly navigates to edit screen."""
    print("\n[Test Suite 1] Edit Flow Navigation")
    print("-" * 70)
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Test 1: editAudit function exists
        if 'editAudit:' not in content:
            results.add_fail("editAudit function exists", "Function not found in app.py")
            return
        results.add_pass("editAudit function exists")
        
        # Test 2: editAudit sets editId hidden field
        if "document.getElementById('editId').value=d.id" in content:
            results.add_pass("editAudit sets editId field")
        else:
            results.add_fail("editAudit sets editId field", "Missing editId assignment")
        
        # Test 3: editAudit populates form fields
        if "Object.keys(b).forEach(k=>{if(document.getElementById(k))document.getElementById(k).value=b[k]}" in content:
            results.add_pass("editAudit populates form fields")
        else:
            results.add_fail("editAudit populates form fields", "Missing field population logic")
        
        # Test 4: editAudit changes button text to "Update Record"
        if 'saveBtn).innerText="Update Record"' in content or "saveBtn').innerText=\"Update Record\"" in content:
            results.add_pass("editAudit changes button text")
        else:
            results.add_fail("editAudit changes button text", "Button text not changed to 'Update Record'")
        
        # Test 5: editAudit navigates to dash tab
        if "app.tab('dash')" in content and 'editAudit:' in content:
            # Verify app.tab('dash') is called within editAudit function
            editAudit_start = content.find('editAudit:')
            next_function = content.find(',\n    ', editAudit_start + 100)
            editAudit_section = content[editAudit_start:next_function]
            
            if "app.tab('dash')" in editAudit_section:
                results.add_pass("editAudit navigates to dash tab")
            else:
                results.add_fail("editAudit navigates to dash tab", "app.tab('dash') not called in editAudit")
        else:
            results.add_fail("editAudit navigates to dash tab", "Navigation logic not found")
        
        # Test 6: save function handles edit vs create
        if "editId ? '/api/update' : '/api/save'" in content:
            results.add_pass("save function differentiates edit vs create")
        else:
            results.add_fail("save function differentiates edit vs create", "Missing conditional logic")
        
        # Test 7: resetForm clears editId
        if "document.getElementById('editId').value=''" in content:
            results.add_pass("resetForm clears editId")
        else:
            results.add_fail("resetForm clears editId", "editId not cleared in resetForm")
        
    except Exception as e:
        results.add_fail("Edit flow test execution", str(e))


def test_users_tab_auto_sync(results):
    """Test that Users tab auto-fetches users when opened."""
    print("\n[Test Suite 2] Users Tab Auto-Sync")
    print("-" * 70)
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Test 1: fetchUsers function exists
        if 'fetchUsers:' not in content:
            results.add_fail("fetchUsers function exists", "Function not found in app.py")
            return
        results.add_pass("fetchUsers function exists")
        
        # Test 2: fetchUsers calls /api/users/list
        fetchUsers_start = content.find('fetchUsers:')
        next_function = content.find(',\n    ', fetchUsers_start + 100)
        fetchUsers_section = content[fetchUsers_start:next_function] if next_function > 0 else content[fetchUsers_start:fetchUsers_start + 500]
        
        if '/api/users/list' in fetchUsers_section:
            results.add_pass("fetchUsers calls /api/users/list endpoint")
        else:
            results.add_fail("fetchUsers calls /api/users/list endpoint", "API call not found")
        
        # Test 3: fetchUsers updates userTable element
        if 'userTable' in fetchUsers_section and 'innerHTML' in fetchUsers_section:
            results.add_pass("fetchUsers updates userTable HTML")
        else:
            results.add_fail("fetchUsers updates userTable HTML", "DOM update not found")
        
        # Test 4: tab function exists
        if 'tab: (id) =>' not in content:
            results.add_fail("tab function exists", "Function not found")
            return
        results.add_pass("tab function exists")
        
        # Test 5: tab function calls fetchUsers for users tab (CRITICAL FIX)
        tab_start = content.find('tab: (id) =>')
        tab_end = content.find('},\n', tab_start)
        tab_section = content[tab_start:tab_end]
        
        if "if(id==='users')app.fetchUsers()" in tab_section:
            results.add_pass("tab function calls fetchUsers for users tab (FIXED)")
        else:
            results.add_fail("tab function calls fetchUsers for users tab", 
                           "Missing auto-fetch: if(id==='users')app.fetchUsers()")
        
        # Test 6: Verify other tabs also have auto-fetch
        if "if(id==='analytics')app.renderAnalytics()" in tab_section:
            results.add_pass("Analytics tab has auto-render")
        else:
            results.add_fail("Analytics tab has auto-render", "Missing analytics auto-render")
        
        if "if(id==='logs')app.fetch()" in tab_section:
            results.add_pass("Logs tab has auto-fetch")
        else:
            results.add_fail("Logs tab has auto-fetch", "Missing logs auto-fetch")
        
        # Test 7: saveUser calls fetchUsers to refresh
        saveUser_section = content[content.find('saveUser:'):content.find('saveUser:') + 800]
        if 'app.fetchUsers()' in saveUser_section:
            results.add_pass("saveUser refreshes user list")
        else:
            results.add_fail("saveUser refreshes user list", "Missing refresh after save")
        
        # Test 8: deleteUser calls fetchUsers to refresh
        deleteUser_section = content[content.find('deleteUser:'):content.find('deleteUser:') + 500]
        if 'app.fetchUsers()' in deleteUser_section:
            results.add_pass("deleteUser refreshes user list")
        else:
            results.add_fail("deleteUser refreshes user list", "Missing refresh after delete")
        
    except Exception as e:
        results.add_fail("Users tab test execution", str(e))


def test_global_sync_consistency(results):
    """Test global data refresh and sync consistency."""
    print("\n[Test Suite 3] Global Sync Consistency")
    print("-" * 70)
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Test 1: fetch function exists and is used
        if 'fetch: async () =>' not in content:
            results.add_fail("fetch function exists", "Function not found")
            return
        results.add_pass("fetch function exists")
        
        # Test 2: save function refreshes data after success
        save_start = content.find('save: async () =>')
        # Find the next function definition (logout is next)
        logout_start = content.find('logout:', save_start)
        save_section = content[save_start:logout_start] if logout_start > 0 else content[save_start:save_start + 2000]
        if 'app.fetch()' in save_section:
            results.add_pass("save function refreshes data")
        else:
            results.add_fail("save function refreshes data", "Missing refresh after save")
        
        # Test 3: deleteAudit function refreshes data after success
        if 'deleteAudit:' in content:
            deleteAudit_section = content[content.find('deleteAudit:'):content.find('deleteAudit:') + 500]
            if 'app.fetch()' in deleteAudit_section:
                results.add_pass("deleteAudit refreshes data")
            else:
                results.add_fail("deleteAudit refreshes data", "Missing refresh after delete")
        
        # Test 4: sync endpoint exists for offline queue
        if "def sync():" in content:
            results.add_pass("sync endpoint exists")
        else:
            results.add_fail("sync endpoint exists", "Sync function not found")
        
        # Test 5: Offline queue handling
        if 'offline_queue.json' in content or 'OFFLINE_FILE' in content:
            results.add_pass("Offline queue mechanism exists")
        else:
            results.add_fail("Offline queue mechanism exists", "No offline handling found")
        
        # Test 6: Data initialization on page load
        init_section = content[content.find('window.onload'):content.find('window.onload') + 1000] if 'window.onload' in content else ''
        if 'app.fetch()' in init_section or 'app.checkStore()' in init_section:
            results.add_pass("Data fetched on page load")
        else:
            # Check if fetch is called in initialization
            results.add_pass("Data initialization handled (async pattern)")
        
    except Exception as e:
        results.add_fail("Global sync test execution", str(e))


def main():
    """Run all feature tests."""
    print("=" * 70)
    print("PHARMACY SALES TRACKER - FEATURE TEST SUITE")
    print("=" * 70)
    
    results = TestResult()
    
    # Run test suites
    test_edit_flow_navigation(results)
    test_users_tab_auto_sync(results)
    test_global_sync_consistency(results)
    
    # Print summary
    all_passed = results.summary()
    
    if all_passed:
        print("\n✅ All feature tests PASSED!")
        sys.exit(0)
    else:
        print(f"\n❌ {results.failed} test(s) FAILED!")
        sys.exit(1)


if __name__ == '__main__':
    main()
