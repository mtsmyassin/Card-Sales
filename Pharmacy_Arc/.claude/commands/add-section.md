Add a new section/feature to the Pharmacy Director app.

What to add: $ARGUMENTS
Examples: `/add-section expense tracking`, `/add-section employee management`, `/add-section monthly report`

### Architecture of this app:
This is a SINGLE FILE Flask app (app.py) with everything embedded:
- Python backend (Flask routes, SQLite database)
- HTML/CSS/JS frontend (in triple-quoted Python strings: LOGIN_UI, MAIN_UI)
- JavaScript app object with all client-side functions

### To add a new feature, you need to modify these areas in app.py:

1. **Database** (section 2):
   - Add new CREATE TABLE in `init_db()`
   - Use `conn.execute()` with parameterized `?` queries

2. **API Routes** (section 3):
   - Add new `@app.route()` endpoints
   - Always check `session.get('logged_in')` for protected routes
   - Use `sqlite3.connect(get_db_path())` context manager
   - Return `jsonify()` responses

3. **UI Tab** (in MAIN_UI string, section 4):
   - Add new tab button: `<div class="tab-btn" onclick="app.tab('newId')">Tab Name</div>`
   - Add new view div: `<div id="newId" class="view"><div class="panel">...</div></div>`

4. **JavaScript** (in the `<script>` block inside MAIN_UI):
   - Add functions to the `app` object
   - Use `fetch('/api/endpoint')` for API calls
   - DOM manipulation with `document.getElementById()`

### Style conventions:
- Primary color: `var(--p)` = `#0097b2` (teal)
- Danger: `var(--danger)` = `#ef4444`
- Success: `var(--success)` = `#22c55e`
- Background: `var(--bg)` = `#f8fafc`
- Panel class: `.panel` (white bg, rounded, shadow)
- Grid form: `.grid-form` (3-column grid)
- Section headers: `.section` (uppercase, teal, bordered)
- Button: `.btn-main` (teal, full-width, bold)

### CRITICAL: String escaping
Since all HTML/JS is inside a Python triple-quoted string:
- Use `\\n` for literal newlines in JS strings (or avoid them)
- Jinja2 template variables: `{{variable}}`
- Dollar signs in JS: use `\\$` if inside f-strings (this app uses regular strings, so `$` is fine)
- Backticks in JS template literals work fine inside Python triple quotes

App: C:\Users\mtsmy\OneDrive\Desktop\PharmacyApp\app.py
