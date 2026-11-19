# Phase 5 — News Intelligence

The monitor ingests free official RSS/Atom feeds as source-attributed market context only. It never creates BUY/SELL, directional sentiment, vetoes, or orders. Decision authority is CONTEXT_ONLY and trade authority is NONE.

Initial feeds:
- ECB press releases and speeches: https://www.ecb.europa.eu/rss/press.html
- Federal Reserve press releases: https://www.federalreserve.gov/feeds/press_all.xml
- BLS latest releases: https://www.bls.gov/feed/bls_latest.rss
- Eurostat news releases: https://ec.europa.eu/eurostat/cache/RSS/rss_estat_news.xml

Each immutable NewsItem retains source identity, authority tier, title, HTTPS article URL, publication and retrieval times, summary, currency tags and topics. RSS 2.0 and Atom are supported. Naive publication times and links outside the configured source host are rejected. Fetches use HTTPS, an 8-second timeout, a 2 MB bound and same-host redirect checks. Feed parsing rejects DTD/entity declarations. Article pages are not crawled.

Articles are stored in independent data/news/news.sqlite. Stable IDs deduplicate; semantic changes append revisions while retrieval-time-only changes do not. Source state records attempts, success, count and errors. Failures preserve accepted items and expose degraded status.

Refresh runs in a daemon thread outside MT5 polling. News is not passed to the legacy decision evaluator. Unit tests use synthetic fixtures and injected fetchers; live feed compatibility and MT5 runtime acceptance remain separate.
