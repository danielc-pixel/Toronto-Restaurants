# New Toronto Restaurants

A static site fed by a daily GitHub Action that pulls the City of Toronto business licence data.

## Deploy
1. Create a GitHub repo and push this folder.
2. Settings > Pages > Deploy from branch > main, folder /docs.
3. Actions tab > "Update restaurant data" > Run workflow (first fill). It then runs daily at 11:00 UTC.

## Config (env vars read by scripts/update.py)
- PACKAGE_ID: CKAN dataset id. Change this if the City has replaced the retired dataset.
- CATEGORY_KEYWORDS: comma-separated licence category matches.
- LOOKBACK_DAYS: how far back to keep (default 120).

Test locally: python scripts/update.py, then cd docs and run python -m http.server
