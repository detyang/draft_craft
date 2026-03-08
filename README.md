# draft_craft
Draft Craft is an integrated platform for tracking NBA draft results and mock drafts, delivering unique analytic insights to enhance draft evaluation and decision-making.

## Historical Draft Data

The **Teams** tab shows historical draft picks using data from the NBA's official APIs.  During development the network environment may not be able to reach `data.nba.net` due to SSL restrictions or firewall policies.  In that case the application will log errors such as:

```
Error fetching 2023: 400 Client Error: Bad Request for url: https://data.nba.net/prod/v1/2023/draft.json
```

To work around this, Draft Craft supports a local cache file at `src/data/historical_cache.json` (legacy) or, preferably, a **SQLite database**.  A helper script is provided:

```sh
python scripts/fetch_historical.py [--local-dir <path>] [--sample-only]
```

The script does one of three things:

* With no arguments it attempts to fetch each year from the NBA API.  In
  restricted environments the network may be blocked; the script will log
  "failed <year>: 400 Client Error" messages if that happens, and will
  automatically fall back to generating sample data for those years.
* If you already have JSON dumps (one file named `2000.json`, `2001.json`,
  etc.) you can supply `--local-dir` pointing at their directory and the
  script will load them instead of calling the API.  This is useful for
  running on an air‑gapped machine where you've copied the data manually.
* Use `--sample-only` to skip network entirely and generate sample data
  based on real historical picks (limited but functional for testing).

In all cases the final database is written to `src/data/historical.db`.  Copy
that file into any environment where the Streamlit app runs; the app will
load picks from the database and will never attempt a network request.  If
the database is missing, the app prints a warning and the Teams page will be
empty.

This approach ensures the app continues to function even when the NBA APIs are inaccessible.

