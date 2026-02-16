Add a new Chart.js visualization to the Pharmacy Director analytics tab.

What chart: $ARGUMENTS
Examples: `/add-chart variance over time`, `/add-chart payment method breakdown`, `/add-chart daily comparison bar chart`

### How charts work in this app:

The app uses Chart.js (loaded from CDN) in the `#analytics` view.
Charts are rendered in the `app.renderAnalytics()` function.

### Existing charts:
- `lineChart` — Sales trend over time (line chart)
- `pieChart` — Payment mix doughnut (Cash, ATH, SSS, Cards)

### Pattern to add a new chart:

1. **Add canvas** in the `#analytics` view inside MAIN_UI:
```html
<div><h3>Chart Title</h3><canvas id="newChart" height="200"></canvas></div>
```

2. **Add rendering** in `app.renderAnalytics()`:
```javascript
const ctx = document.getElementById('newChart').getContext('2d');
if(window.newC) window.newC.destroy(); // Prevent duplicate
window.newC = new Chart(ctx, {
    type: 'bar', // or 'line', 'pie', 'doughnut', 'radar'
    data: {
        labels: app.data.map(d => d.date).reverse(),
        datasets: [{
            label: 'Label',
            data: app.data.map(d => d.someValue).reverse(),
            backgroundColor: '#0097b2'
        }]
    },
    options: { responsive: true }
});
```

### Available data fields for charts:
From `app.data` array: date, gross, net, variance, reg, staff
From `app.data[i].breakdown`: cash, ath, athm, visa, mc, amex, disc, wic, mcs, sss, payouts, taxState, taxCity, float, actual

### Chart.js colors to use:
- Primary: `#0097b2`
- Success: `#22c55e`
- Danger: `#ef4444`
- Blue: `#3b82f6`
- Purple: `#6366f1`
- Amber: `#f59e0b`

App: C:\Users\mtsmy\OneDrive\Desktop\PharmacyApp\app.py
