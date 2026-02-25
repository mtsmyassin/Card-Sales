"""Root pytest configuration — excludes standalone scripts from collection."""

# These root-level files are standalone Python scripts — they use a custom
# TestResult runner class and call sys.exit(), not pytest-compatible.
# Run them directly: python test_sales_math.py etc.
collect_ignore = ["test_fixes.py", "test_sales_math.py", "test_features.py", "test_security.py"]
