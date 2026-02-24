"""Input validation helpers for audit entries and user data."""
import re
from config import Config


def validate_audit_entry(data: dict) -> tuple[bool, str]:
    """
    Validate audit entry data.
    Returns (is_valid, error_message).
    """
    # Required fields
    required_fields = ['date', 'reg', 'staff', 'gross', 'net', 'variance']
    for field in required_fields:
        if field not in data or data[field] is None or data[field] == '':
            return False, f"Missing required field: {field}"

    # Validate date format (YYYY-MM-DD)
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(data['date'])):
        return False, "Invalid date format. Use YYYY-MM-DD"

    # Validate actual calendar date (e.g. reject 2026-02-30)
    try:
        from datetime import date as _date
        parsed = _date.fromisoformat(str(data['date']))
        if parsed.year < 2020 or parsed.year > 2030:
            return False, "Date year must be between 2020 and 2030"
    except ValueError:
        return False, "Invalid calendar date"

    # Validate numeric fields
    try:
        gross = float(data['gross'])
        net = float(data['net'])
        variance = float(data['variance'])

        # Range checks
        if gross < 0 or gross > 1000000:
            return False, "Gross must be between 0 and 1,000,000"
        if net < -100000 or net > 1000000:
            return False, "Net must be between -100,000 and 1,000,000"
        if abs(variance) > 100000:
            return False, "Variance must be between -100,000 and 100,000"
    except (ValueError, TypeError):
        return False, "Invalid numeric values in gross, net, or variance"

    # Validate string lengths
    if len(str(data['reg'])) > 50:
        return False, "Register name too long (max 50 characters)"
    if len(str(data['staff'])) > 100:
        return False, "Staff name too long (max 100 characters)"

    # Validate store if provided
    if 'store' in data and data['store']:
        valid_stores = Config.STORES + ['Main']
        if data['store'] not in valid_stores:
            return False, f"Invalid store. Must be one of: {', '.join(valid_stores)}"

    # Math cross-check: if breakdown is present, verify gross/net/variance are consistent
    if 'breakdown' in data and isinstance(data.get('breakdown'), dict):
        b = data['breakdown']
        try:
            card_keys = ['ath', 'athm', 'visa', 'mc', 'amex', 'disc', 'wic', 'mcs', 'sss']
            cash_sales = float(b.get('cash', 0))
            card_sales = sum(float(b.get(k, 0)) for k in card_keys)
            payouts = float(b.get('payouts', 0))
            float_amount = float(b.get('float', 0))
            actual = float(b.get('actual', 0))
            TOLERANCE = Config.MATH_TOLERANCE

            expected_gross = cash_sales + card_sales
            if abs(gross - expected_gross) > TOLERANCE:
                return False, f"Gross mismatch: got {gross:.2f}, expected {expected_gross:.2f} (cash + cards)"

            expected_net = expected_gross - payouts
            if abs(net - expected_net) > TOLERANCE:
                return False, f"Net mismatch: got {net:.2f}, expected {expected_net:.2f} (gross - payouts)"

            expected_variance = (actual - float_amount) - (cash_sales - payouts)
            if abs(variance - expected_variance) > TOLERANCE:
                return False, f"Variance mismatch: got {variance:.2f}, expected {expected_variance:.2f}"
        except (TypeError, ValueError):
            pass  # Malformed breakdown values are caught by earlier validation

    return True, ""


def validate_user_data(data: dict, is_update: bool = False) -> tuple[bool, str]:
    """
    Validate user account data.
    Returns (is_valid, error_message).
    """
    # Username validation
    if 'username' not in data or not data['username']:
        return False, "Username is required"

    username = str(data['username'])
    if len(username) < 3 or len(username) > 50:
        return False, "Username must be 3-50 characters"
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return False, "Username can only contain letters, numbers, hyphens, and underscores"

    # Password validation (only for new users or if password is being changed)
    if 'password' in data and data['password']:
        password = str(data['password'])
        # Skip validation if it's already a bcrypt hash
        if not password.startswith('$2b$'):
            if len(password) < 8:
                return False, "Password must be at least 8 characters"
            if len(password) > 100:
                return False, "Password must be less than 100 characters"
    elif not is_update:
        return False, "Password is required for new users"

    # Role validation
    if 'role' in data and data['role']:
        valid_roles = ['staff', 'manager', 'admin', 'super_admin']
        if data['role'] not in valid_roles:
            return False, f"Invalid role. Must be one of: {', '.join(valid_roles)}"

    # Store validation
    if 'store' in data and data['store']:
        valid_stores = ['All'] + Config.STORES
        if data['store'] not in valid_stores:
            return False, f"Invalid store. Must be one of: {', '.join(valid_stores)}"

    return True, ""
