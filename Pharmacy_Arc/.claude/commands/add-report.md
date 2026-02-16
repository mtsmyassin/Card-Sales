Add a new printable report to the Pharmacy Director app.

What report: $ARGUMENTS
Examples: `/add-report weekly summary`, `/add-report tax report`, `/add-report payout summary`

### How printing works in this app:

The app uses a hidden `#printReport` div that gets shown during `window.print()`.
CSS `@media print` hides everything except `#printReport`.

```html
<div id="printReport" style="display:none; padding:20px;">
    <h1>Farmacia Carimas</h1>
    <h3 style="text-align:center; border-bottom:1px solid black">Report Title</h3>
    <div id="printContent"></div>
    <br><br><br>
    <div style="display:flex; justify-content:space-between;">
        <span>_____________________<br>Manager</span>
        <span>_____________________<br>Date</span>
    </div>
</div>
```

### Print content format:
Use `.print-row` divs for line items:
```html
<div class="print-row"><span>Label:</span><span>$Value</span></div>
```

### To add a new report:
1. Add a JavaScript function to the `app` object that:
   - Gathers data from `app.data` (the cached audit list)
   - Builds HTML using `.print-row` divs
   - Sets `document.getElementById('printContent').innerHTML = html`
   - Calls `window.print()`
2. Add a button somewhere in the UI to trigger it

### Data available in `app.data`:
Each audit entry has:
```javascript
{
    id, date, reg, staff, gross, net, variance,
    breakdown: {
        cash, ath, athm, visa, mc, amex, disc, wic, mcs, sss,
        payouts, taxState, taxCity, float, actual
    }
}
```

### Currency formatting:
```javascript
value.toFixed(2)  // Always 2 decimal places
```

App: C:\Users\mtsmy\OneDrive\Desktop\PharmacyApp\app.py
