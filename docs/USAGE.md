# Usage

This repo auto-collects recent arXiv papers and writes the results into `README.md` and `docs/index.md`.
Do not edit those files by hand. Run the script or schedule it instead.

## Run once (local)

```powershell
D:/git_website/arxiv_integrability/scripts/run_daily.ps1 -InstallDeps
```

## Run for a specific date (test)

```powershell
D:/git_website/arxiv_integrability/scripts/run_daily.ps1 -Date 2026-03-13 -DaysBack 1
```

## Weekend reorganize (keep table format)

```powershell
D:/git_website/arxiv_integrability/scripts/run_daily.ps1 -Reorganize
```

This performs weekly cleanup/reorganization of stored records and rebuilds `README.md`/`docs/index.md` using the same table layout.

## Timezone-aware date filtering

If arXiv dates look off by one day, set the offset in hours from UTC:

```powershell
C:/Python313/python.exe D:/git_website/arxiv_integrability/daily_arxiv.py --date 2026-03-13 --days_back 1 --tz_offset 8
```

Or filter by published date instead of updated date:

```powershell
C:/Python313/python.exe D:/git_website/arxiv_integrability/daily_arxiv.py --date 2026-03-13 --days_back 1 --use_published_date
```

## Schedule weekday fetch + weekend reorganize (Windows Task Scheduler)

```powershell
D:/git_website/arxiv_integrability/scripts/register_daily_task.ps1 -WeekdayTime 12:30 -WeekendTime 13:00
```

This creates:
- `ArxivWeekdayUpdate` at `12:30` Monday-Friday (fetch from configured filters/categories)
- `ArxivWeekendReorganize` at `13:00` Sunday (reorganize and regenerate markdown tables)

If you only want weekday fetching:

```powershell
D:/git_website/arxiv_integrability/scripts/register_daily_task.ps1 -WeekdayOnly
```

## GitHub Actions

- `.github/workflows/int-arxiv-daily.yml` runs on weekdays and fetches from configured categories.
- `.github/workflows/update_paper_links.yml` runs on Sunday and performs weekly reorganization.
- GitHub cron uses UTC, so weekday `04:30 UTC` equals `12:30 Beijing` (UTC+8).
- After uploading, ensure `Actions` are enabled and this workflow file exists on the repository's default branch.

## GitHub Pages (project site)

This repo is configured for a GitHub Pages project site at:
`https://superqx.github.io/arxiv_integrability`

In the GitHub repo settings, set:
- `Pages` -> `Build and deployment` -> `Source`: `Deploy from a branch`
- `Branch`: `main`
- `Folder`: `/docs`

## Config

Edit `config.yaml` to control behavior:

- `days_back`: number of days to include (1 means last 24 hours)
- `fetch_mode`: `rss_daily` (recommended: papers that newly appear on arXiv daily feeds) or `api_search`
- `rss_feed_base_url`: RSS feed base URL
- `rss_timeout_seconds`: RSS request timeout
- `use_local_keyword_filter`: if true, fetch by category and match keywords locally (recommended to reduce arXiv 429)
- `scan_max_results`: number of newest papers scanned per category before local filtering
- `arxiv_delay_seconds`: delay between arXiv API calls
- `arxiv_num_retries`: arXiv client retries (0 avoids long retry-sleep loops)
- `topic_delay_seconds`: delay between category/topic requests to reduce rate-limit bursts
- `date_override`: override end date for testing (YYYY-MM-DD)
- `store_pdfs`: if true, store PDFs locally
- `pdf_output_dir`: where PDFs are saved when `store_pdfs` is true
- `max_results`: max papers per keyword per run
- `use_deepseek`: if true, use DeepSeek for summaries (requires API key)
- `deepseek_base_url`: API base URL
- `deepseek_model`: model name (e.g. `deepseek-chat`)
- `deepseek_max_tokens`: summary length control
- `deepseek_temperature`: set to null to use model default
- `use_published_date`: if true, filter by published date instead of updated date
- `date_tz_offset_hours`: timezone offset for date filtering (this repo currently uses `8` for Beijing time)
- `include_ids`: list of arXiv IDs to always include (bypasses date filter)
- `summary_language`: summary language code (e.g., `en`, `zh`)
- `summary_languages`: list of languages to generate (e.g., `["zh","en"]`)

In `fetch_mode: rss_daily`, "daily" means papers that newly appear on arXiv feeds that day, regardless of original submission date.

The four tracked categories are configured under `keywords` as:
- `cond-mat`
- `hep-th`
- `math-ph`
- `nlin`

## DeepSeek API key

Set an environment variable before running:

```powershell
$env:DEEPSEEK_API_KEY = "YOUR_KEY"
```
