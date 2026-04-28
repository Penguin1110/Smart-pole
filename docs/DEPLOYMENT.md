# Deployment

This is a static dashboard project. No build step is required.

## Local Preview

From the repository root:

```powershell
python -m http.server 8080
```

Open:

```text
http://localhost:8080/dashboard_index.html
```

The main dashboard is:

```text
http://localhost:8080/main/wind_pm25_lag_dashboard.html
```

## Data Refresh

Run the preprocessing script from the repository root:

```powershell
python preprocess_wind_pm25.py
```

The script reads:

- `data/timeseries_data.json`
- `main/peak_data.js`
- `CWA_Weather_Final/`

The script writes:

- `main/wind_pm25_data.js`
- `main/event_diagnosis_data.js`

## Publish

Publish the repository as static files. Keep these paths together:

- `dashboard_index.html`
- `main/`
- `data/` if manual inspection files should be included
- `docs/` if project documentation should be included
