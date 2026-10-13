# LLM Token Price Index

A static dashboard of LLM API token prices across labs, refreshed daily by a GitHub Action and served on GitHub Pages. It has no server, no API keys and no dependencies beyond the Python standard library.

```
.github/workflows/update-prices.yml   daily cron: fetch, snapshot, commit, deploy to Pages
scripts/build_data.py                 OpenRouter /models → $/1M → snapshots, history, change log
scripts/seed_openrouter_2026-10-12.json  offline seed (partial: 60 models) used for the first build
data/snapshots/YYYY-MM-DD.json        one compact snapshot per day (source of truth)
data/latest.json, data/data.js        what the page loads (rebuilt every run)
data/history.csv                      long-format export: date, model, input, output, cache_read
index.html                            the dashboard (vanilla JS, inline SVG charts)
```

## Setup (about 5 minutes)

1. Create a **public** GitHub repo, for example `llm-price-index`, and push this folder to `main`.
2. Go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
3. Go to **Settings → Actions → General → Workflow permissions** and choose **Read and write**.
4. Under **Actions → Update LLM prices**, click **Run workflow** once. That pulls the full live catalogue (300+ models) and replaces the partial seed.
5. The site goes live at `https://<user>.github.io/llm-price-index/`. For a custom domain, add it under Settings → Pages and a CNAME record at your DNS provider.

From then on the job runs every day at 06:15 UTC.

## Local run

```bash
python3 scripts/build_data.py          # live fetch
python3 -m http.server 8000            # open http://localhost:8000
```

## Notes and gotchas

- **The history starts on the first run.** The OpenRouter API exposes only current prices, so the Δ30d column and the step charts fill in over time. Don't backfill from memory; it would undermine the page's credibility.
- **Scheduled workflows pause after 60 days without repo activity.** The daily data commit counts as activity, so this only matters if the job breaks for two months.
- **Sanity guard:** the script refuses to overwrite data if the API returns fewer than 40 models, so one bad pull can't blank the site.
- **Repo growth:** each snapshot is about 25 KB at full catalogue size, so about 9 MB a year. If that's too much later, prune snapshots older than 12 months and keep only `history.csv`.
- **Attribution:** the footer credits OpenRouter as the source. Check their ToS before any commercial use of the data.

## Extending

- **Major-labs list:** edit `MAJOR` in `index.html`. It matches on the model-ID prefix, e.g. `anthropic/…`.
- **Throughput and latency:** OpenRouter's `/api/v1/models/{id}/endpoints` returns per-provider pricing and uptime. Add it in `build_data.py` if you later want the "pricing + performance" view.
