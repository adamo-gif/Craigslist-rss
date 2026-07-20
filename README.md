# Craigslist → RSS notifier (100% free)

Craigslist discontinued its own RSS output years ago, so this repo scrapes
your saved search(es), builds a real RSS 2.0 feed, and republishes it every
30 minutes using free infrastructure only:

- **GitHub Actions** — free scheduler that runs the Python script (no server to maintain)
- **GitHub Pages** — free static hosting for the resulting feed.xml files
- **Your RSS reader app** — polls the feed and notifies you of new items (Feedly, Inoreader free tier, NetNewsWire, Reeder, etc.)

## Setup (10 minutes, one time)

1. **Create a GitHub account** if you don't have one (free): https://github.com/join

2. **Create a new repository**
   - Click "New repository", make it public (required for free GitHub Pages), name it anything, e.g. `craigslist-rss`.

3. **Upload these files** to the repo (drag-and-drop on github.com works, or use `git push` if you're comfortable with git):
   - `generate_feed.py`
   - `config.json`
   - `.github/workflows/update-feed.yml`

4. **Edit `config.json`** with your own search(es). To get the URL for a search:
   - Go to craigslist.org, run your search, set any filters (price, category, keywords) exactly as you want them.
   - Copy the URL from your browser's address bar — paste it into `config.json` as the `url` field.
   - You can list as many searches as you want in the `feeds` array, each with its own `name`.

5. **Turn on GitHub Pages**
   - In your repo: Settings → Pages → under "Build and deployment", set Source to "Deploy from a branch", Branch to `main` (or `master`), folder to `/docs`. Save.
   - GitHub will give you a URL like `https://yourusername.github.io/craigslist-rss/`.

6. **Run the workflow once manually**
   - Go to the "Actions" tab → "Update Craigslist RSS feeds" → "Run workflow".
   - This generates the first `docs/*.xml` files and commits them.

7. **Subscribe in your RSS reader**
   - Your feed will be at `https://yourusername.github.io/craigslist-rss/<slug>.xml`
   - The exact filename is listed at `https://yourusername.github.io/craigslist-rss/` (the index page).
   - Paste that feed URL into any RSS reader app and turn on push notifications for it (most reader apps, e.g. Feedly, support this on their free tier).

From then on, GitHub Actions re-runs the scraper every 30 minutes automatically, and your reader app notifies you whenever a new matching listing shows up.

## Notes & tuning

- **Change the check frequency**: edit the `cron` line in `.github/workflows/update-feed.yml`. Don't go much tighter than every 15 minutes — be considerate of Craigslist's servers, and there's no benefit since listings don't update that fast.
- **How "new" is detected**: the script keeps a small state file per search (`docs/state/<slug>.json`) recording when it first saw each listing. This is what makes your RSS reader correctly show only genuinely new listings, not the same ones every run.
- **Old listings drop off**: after `max_age_days` (default 14, set in `config.json`), a listing is removed from the feed and state file automatically.
- **Multiple searches** show up as separate feed files (e.g. `road-bikes-under-500.xml`) — subscribe to each one separately, or run several search URLs if you're tracking different categories (apartments, gigs, free stuff, etc.).
- **If Craigslist changes their page layout**: the script tries a structured JSON-LD block first and falls back to a CSS-selector scrape. If both ever break, that means CL changed something on their end — check for an updated selector and adjust `generate_feed.py` accordingly.
