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

## Timezone-aware date filtering

If arXiv dates look off by one day, set the offset in hours from UTC:

```powershell
C:/Python313/python.exe D:/git_website/arxiv_integrability/daily_arxiv.py --date 2026-03-13 --days_back 1 --tz_offset 8
```

Or filter by published date instead of updated date:

```powershell
C:/Python313/python.exe D:/git_website/arxiv_integrability/daily_arxiv.py --date 2026-03-13 --days_back 1 --use_published_date
```

## Schedule daily (Windows Task Scheduler)

```powershell
D:/git_website/arxiv_integrability/scripts/register_daily_task.ps1 -Time 12:30 -TaskName ArxivWeekdayUpdate
```

This creates a weekday (Mon-Fri) task that runs the same script at 12:30 Beijing time. To change the time, delete the task in Task Scheduler and rerun the command with a new time.

## GitHub Actions (daily)

The workflow is already configured in `.github/workflows/int-arxiv-daily.yml` and runs weekdays at 12:30 Beijing time plus on manual trigger.

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
- `date_tz_offset_hours`: timezone offset for date filtering
- `include_ids`: list of arXiv IDs to always include (bypasses date filter)
- `summary_language`: summary language code (e.g., `en`, `zh`)
- `summary_languages`: list of languages to generate (e.g., `["zh","en"]`)

## DeepSeek API key

Set an environment variable before running:

```powershell
$env:DEEPSEEK_API_KEY = "YOUR_KEY"
```
