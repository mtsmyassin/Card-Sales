Inspect and manage the Pharmacy Director SQLite database.

Action: $ARGUMENTS
Examples: `/db show schema`, `/db count audits`, `/db query last 10 audits`, `/db add column`

### Database location:
The database path depends on OneDrive:
- If OneDrive exists: `%OneDrive%/PharmacyData/pharmacy_director.db`
- Fallback: Same directory as app.py

### Schema:
```sql
CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY,
    date TEXT,
    reg TEXT,
    staff TEXT,
    gross REAL,
    net REAL,
    variance REAL,
    payload TEXT  -- Full JSON blob of audit data
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Default: password = '1234'
```

### The payload JSON contains:
```json
{
    "date": "2026-02-09",
    "reg": "Reg 1",
    "staff": "Manager",
    "gross": 1500.00,
    "net": 1400.00,
    "variance": "-5.00",
    "breakdown": {
        "cash": 800, "ath": 200, "athm": 50, "visa": 100, "mc": 50,
        "amex": 0, "disc": 0, "wic": 100, "mcs": 50, "sss": 150,
        "payouts": 100, "taxState": 84, "taxCity": 8, "float": 150, "actual": 145
    }
}
```

### To query with Python:
```python
import sqlite3, json
db_path = r"C:\Users\mtsmy\OneDrive\PharmacyData\pharmacy_director.db"
with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM audits ORDER BY date DESC LIMIT 10").fetchall()
    for r in rows:
        data = json.loads(r['payload'])
        print(f"{r['date']}: gross=${r['gross']}, var=${r['variance']}")
```

### To add schema changes:
1. Add ALTER TABLE or CREATE TABLE in `init_db()` function
2. Use `CREATE TABLE IF NOT EXISTS` or `ALTER TABLE ... ADD COLUMN` (catch error if exists)
3. Update any affected API routes
4. Update the JavaScript data handling in MAIN_UI

App: C:\Users\mtsmy\OneDrive\Desktop\PharmacyApp\app.py
