Build the Pharmacy Director app as a standalone Windows executable using PyInstaller.

Steps:

1. **Verify prerequisites**:
   - Python installed and in PATH
   - PyInstaller installed: `pip install pyinstaller`
   - app.py exists and has no syntax errors
   - logo.png exists in the same directory

2. **Build**:
```bash
cd C:\Users\mtsmy\OneDrive\Desktop\PharmacyApp
pyinstaller --onefile --add-data "logo.png;." --name PharmacyDirector app.py
```

Or use the existing spec file:
```bash
pyinstaller PharmacyDirector.spec
```

3. **Verify**:
   - Check dist/PharmacyDirector.exe exists
   - Report file size
   - Test run: `dist\PharmacyDirector.exe`

### Important notes:
- The app uses `sys._MEIPASS` for frozen (PyInstaller) path resolution
- logo.png must be bundled with `--add-data`
- Database is created at OneDrive/PharmacyData/ (not bundled)
- The exe opens a browser automatically after 1.5 seconds
- `console=True` in the spec file (shows terminal for debugging)

### If build fails:
- Missing modules: add to `hiddenimports` in spec file
- File not found: check `--add-data` paths
- Import errors: verify all pip packages are installed

Spec file: C:\Users\mtsmy\OneDrive\Desktop\PharmacyApp\PharmacyDirector.spec
App: C:\Users\mtsmy\OneDrive\Desktop\PharmacyApp\app.py
