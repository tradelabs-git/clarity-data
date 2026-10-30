# clarity-data

Hourly GitHub Actions job that builds Copernicus Marine data files for the Clarity app (Cyprus only) and
publishes them to GitHub Pages (`gh-pages` branch, force-pushed as a single commit, only when data changes).
The app lives in the private repo `tradelabs-git/clarity` (local folder `Documents\Clarity`); its
`CLAUDE.md` describes the whole project.

- `pipeline/build.py` – builds `cyprus/waves.json` (Med-Waves, ~4 km hourly, coastal cells),
  `cyprus/clarity.json` (Kd490 per coastal pixel: monthly clear-day p20 + latest reading) and the
  `clarity_baseline.json` cache (rebuilt every 30 days, ~10 min). `BOX` must match `CopernicusClient` in the app.
- `.github/workflows/update.yml` – runs at :07 every hour. Also sends a daily rejected insert to Supabase
  (03:00 UTC) so the free project doesn't pause.
- Secrets (set by the owner; Claude can't write GitHub secrets): `COPERNICUSMARINE_SERVICE_USERNAME`,
  `COPERNICUSMARINE_SERVICE_PASSWORD`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`.
- Local runs: `.venv\Scripts\copernicusmarine login` (interactive; run in a separate PowerShell window),
  then `.venv\Scripts\python pipeline\build.py --out site\cyprus`.
- GitHub disables scheduled workflows in repos with no activity for 60 days; the data commits to `gh-pages`
  should count as activity, but check the Actions tab if the data stops updating.
