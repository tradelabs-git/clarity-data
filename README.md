# clarity-data

Data files for the [Clarity](https://github.com/tradelabs-git) underwater-visibility app, built from the
Copernicus Marine Service and published to GitHub Pages:

- `cyprus/waves.json`: Mediterranean Sea Waves forecast (`cmems_mod_med_wav_anfc_4.2km_PT1H-i`, ~4 km,
  hourly) for sea cells within ~8 km of the Cyprus coast.
- `cyprus/clarity.json`: satellite water clarity (Kd490, ~1 km) for pixels 1–4 km off the coast: the
  20th-percentile (clear-day) value for each month over the last five full years, plus the latest
  cloud-free reading from the past five days.

A GitHub Actions job (`.github/workflows/update.yml`) rebuilds them every hour and publishes only when the
data has changed. It needs two repository secrets, `COPERNICUSMARINE_SERVICE_USERNAME` and
`COPERNICUSMARINE_SERVICE_PASSWORD`, for a free Copernicus Marine account.

Run locally:

```
python -m venv .venv
.venv\Scripts\pip install -r pipeline\requirements.txt
.venv\Scripts\copernicusmarine login
.venv\Scripts\python pipeline\build.py --out site\cyprus
```

Generated using E.U. Copernicus Marine Service Information.
