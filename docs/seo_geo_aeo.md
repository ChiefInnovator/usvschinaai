# Search and AI discovery

Verified against the repository and production on November 7, 2026.

## Sitemap and crawl access

`sitemap.xml` lists the five canonical indexable pages: `/`, `/history.html`,
`/about.html`, `/privacy.html`, and `/terms.html`. The homepage alias
`/index.html` is excluded because its canonical URL is `/`. The error page,
assets, raw JSON, and support text files are not search landing pages.
Machine-readable resources remain discoverable through `llms.txt` and Dataset markup.

Homepage and archive modification dates follow the snapshot date. Static-page
dates reflect their latest committed page changes (November 2, 2026 at this audit),
and must be updated when those pages change. Daily refreshes preserve those dates
and never move an existing date backward. Optional priority/changefreq hints have
been removed; Google and Bing ignore them.

`robots.txt` advertises the sitemap and allows search and AI crawlers, including
OAI-SearchBot. The existing training-crawler policy is unchanged.

## Answer and generative engine discovery

`llms.txt` describes the current seventeen-benchmark algorithm, missing-result
handling, national Top 10 totals, evidence, publication timestamps, and protected
release cadence. It links to canonical pages and the publication manifest, site
summary, current/history data, model catalog, and scoring revision. Benchmark names
appear without weight percentages. The scraper and daily workflow refresh its date
and benchmark list, and the workflow commits the file with each data publication.

The homepage already publishes WebSite, FAQPage, ItemList, and Dataset JSON-LD;
ranking-dependent markup comes from the same loaded publication as the visible
leaderboard. About, archive, privacy, and terms pages have canonical URLs and
page-specific metadata. This change preserves those schemas and page content.

`llms.txt` is a convenience for consumers that read it, not a required standard
or a guarantee of indexing or citation. No search-engine submissions or verified
Search Console/Bing Webmaster account checks are claimed by this audit.

## Validation

`tests/test_search_discovery.py` checks sitemap/canonical agreement, uniqueness,
indexability, sitemap discovery, resource targets, all configured benchmark names,
current methodology, date refresh behavior, and AI-map refresh idempotence.
Build and CI checks verify that crawler resources ship in the allowlisted site.

## Official references

- [Google: build and submit a sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap)
- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- [Bing: sitemaps in AI-powered search](https://blogs.bing.com/webmaster/2025/7/Keeping-Content-Discoverable-with-Sitemaps-in-AI-Powered-Search/)
- [OpenAI: crawler controls](https://developers.openai.com/api/docs/bots)
