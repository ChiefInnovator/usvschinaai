# Technical Specification: AI-First Web Optimization (SEO/AEO/GEO)

## 1. Overview

This specification outlines the SEO, GEO (Generative Engine Optimization), and AEO (Answer Engine Optimization) implementation for **US vs CHINA AI** (usvschina.ai). The goal is to maximize visibility in both traditional search engines and AI-driven search environments (ChatGPT, Perplexity, Claude, Google AI Overviews).

---

## 2. Global AI Directive — `llms.txt`

**Status:** ✅ Implemented

A markdown file at `/llms.txt` provides a high-signal knowledge map for LLM crawlers.

### Content Structure

See the live `/llms.txt` for the canonical content. Summary of what it contains:

- **Header** — site name, focus, URL, last-updated date.
- **What This Site Is** — short list of what the leaderboard tracks (Unified Score, national scoreboard, benchmarks, history).
- **Scoring Methodology** — current formula `Unified = 10 × (0.9 × norm(AvgIQ) + 0.1 × norm(Value))`, the two-pass AvgIQ description (Pass 1 picks Initial Top 10, Pass 2 flat-averages the qualified set), and the normalization precedence (known range → percentage auto-detect → cohort fallback).
- **Benchmarks Included** — common categories (math/reasoning, general intelligence, coding/engineering, agentic/web). Explicitly notes that benchmarks reported by fewer than 4 cohort models are dropped.
- **Key Resources** — `/index.html`, `/history.html`, `/about.html`, `/models.json`.
- **FAQ** — how models are ranked, why two-pass, update cadence.
- **Citation + Disclaimer.**

---

## 3. Structured Data — JSON-LD Entity Mapping

**Status:** ✅ Implemented

### WebSite Schema (index.html)

```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "US vs CHINA AI",
  "url": "https://usvschina.ai/",
  "description": "Compare the world's best AI models ranked by intelligence and cost efficiency.",
  "publisher": {
    "@type": "Organization",
    "name": "US vs CHINA AI"
  }
}
```

### FAQPage Schema (index.html)

Generated dynamically in JavaScript from the current top model and national totals so it's never stale. Questions (as of 2026-04-12):

1. **"What is the best AI model right now?"** — answered from the live top-1 model with its current Unified score, AvgIQ, and Value.
2. **"Is the US or China winning the AI race?"** — answered from the live national Top-10 Unified totals.
3. **"How are AI models ranked on this leaderboard?"** — answered with the current two-pass scoring description, including the 0.9/0.1 capability-vs-value split and the qualified-set rule.

See [index.html:700-735](../index.html#L700-L735) for the generator.

### ItemList Schema (index.html)

Generated dynamically from the live top 10 so it always reflects the current snapshot. The `name` is built from the audit date (e.g. "Top 10 AI Models April 2026"), and each `ListItem` carries the model name, origin, and Unified score.

### Dataset Schema (index.html)

```json
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "US vs China AI Model Rankings",
  "description": "Two-pass scoring over 29+ frontier benchmarks, refreshed per scrape.",
  "url": "https://usvschina.ai/",
  "license": "https://creativecommons.org/licenses/by/4.0/",
  "isAccessibleForFree": true,
  "distribution": {
    "@type": "DataDownload",
    "encodingFormat": "application/json",
    "contentUrl": "https://usvschina.ai/models.json"
  },
  "temporalCoverage": "<built dynamically from latest audit date>",
  "spatialCoverage": ["United States", "China"]
}
```

### SpeakableSpecification Schema (index.html)

```json
{
  "@context": "https://schema.org",
  "@type": "SpeakableSpecification",
  "cssSelector": ["#page-title", "#page-subtitle", ".glass h3"]
}
```

### AboutPage Schema (about.html)

```json
{
  "@context": "https://schema.org",
  "@type": "AboutPage",
  "name": "About US vs CHINA AI",
  "description": "Methodology and scoring explanation for the AI leaderboard",
  "url": "https://usvschina.ai/about.html"
}
```

### CollectionPage Schema (history.html)

```json
{
  "@context": "https://schema.org",
  "@type": "CollectionPage",
  "name": "US vs CHINA AI Historical Archives",
  "description": "Historical snapshots of AI model rankings",
  "url": "https://usvschina.ai/history.html"
}
```

---

## 4. Meta Tags Implementation

**Status:** ✅ Implemented

### Standard SEO Meta Tags

- `<meta name="description">` — unique per page; the index.html copy auto-updates the trailing month on each scraper run.
- `<meta name="keywords">` — relevant AI/model terms.
- `<meta name="author">` — "US vs CHINA AI".
- `<meta name="robots">` — `index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1`.
- `<link rel="canonical">` — absolute URL per page.

### Open Graph Tags

- `og:type` — website/article
- `og:url` — canonical URL
- `og:title` — page title
- `og:description` — page description
- `og:image` — og-image.png
- `og:site_name` — "US vs CHINA AI"
- `og:locale` — "en_US"

### Twitter Card Tags

- `twitter:card` — summary_large_image
- `twitter:url` — canonical URL
- `twitter:title` — page title
- `twitter:description` — page description
- `twitter:image` — og-image.png

### Additional Meta

- `theme-color` — `#020617` (site background)
- `<link rel="alternate" href="/llms.txt">` — LLM knowledge map reference

---

## 5. robots.txt Configuration

**Status:** ✅ Implemented

```text
User-agent: *
Allow: /

Sitemap: https://usvschina.ai/sitemap.xml

# LLM-specific knowledge map reference
# See: https://usvschina.ai/llms.txt

# AI Crawler Permissions
User-agent: GPTBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: Claude-Web
Allow: /

User-agent: Anthropic-AI
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /
```

---

## 6. Sitemap Configuration

**Status:** ✅ Implemented

**File:** `/sitemap.xml`

Includes:

- `/` and `/index.html` (priority 1.0, daily) — `lastmod` auto-bumped on every scraper run.
- `/history.html` (priority 0.8, daily) — `lastmod` auto-bumped on every scraper run.
- `/llms.txt` (priority 0.6, daily) — `lastmod` auto-bumped on every scraper run.
- `/models.json` (priority 0.5, daily) — `lastmod` auto-bumped on every scraper run.
- `/about.html` (priority 0.7, monthly) — static page, lastmod only changes on edits.
- `/privacy.html`, `/terms.html`, `/humans.txt` — static, yearly cadence.

---

## 7. Content Optimization for AI Retrieval

### Implemented Strategies

1. **Direct Answer Format** — FAQPage schema with concise answers.
2. **Structured Data** — multiple schema types for entity recognition.
3. **llms.txt** — dedicated AI crawler knowledge map.
4. **Clean HTML Structure** — semantic headings (h1, h2, h3).
5. **Data Accessibility** — JSON endpoint for raw data.

### Key Query Targets

| Query | Optimized Answer Location |
| --- | --- |
| "Best AI model 2026" | FAQPage schema, llms.txt |
| "US vs China AI race" | FAQPage schema, llms.txt |
| "AI model rankings" | ItemList schema, llms.txt |
| "How to compare AI models" | AboutPage, llms.txt methodology |
| "Gemini vs Claude Opus vs GPT-5" | ItemList with live Unified scores |
| "Best coding AI model" | (future) coding-unified-score spec in docs/coding_unified_score.md |

---

## 8. Social Sharing Implementation

**Status:** ✅ Implemented

Share buttons in header with:

- X (formerly Twitter)
- Facebook
- LinkedIn
- Copy Link
- Email

Each uses appropriate share URLs with pre-populated content.

---

## 9. Future Enhancements

### Recommended

1. **Create og-image.png** — custom Open Graph image (1200x630px).
2. **Create PNG favicons** — favicon-16x16.png, favicon-32x32.png, favicon-192x192.png, favicon-512x512.png.
3. **Create apple-touch-icon.png** — 180x180px iOS icon.
4. **Add hreflang tags** — if multi-language support is added.

### Optional

1. **RSS/Atom feed** — for ranking updates.
2. **API documentation page** — for models.json consumers.
3. **Changelog page** — track methodology updates.

---

## 10. Verification Checklist

- [x] llms.txt created and populated
- [x] robots.txt references llms.txt
- [x] sitemap.xml includes all pages
- [x] JSON-LD schemas on all pages
- [x] Meta tags complete on all pages
- [x] Open Graph tags on all pages
- [x] Twitter Card tags on all pages
- [x] Canonical URLs set
- [x] AI crawler permissions in robots.txt
- [x] Share buttons functional
- [x] favicon.svg created (SVG favicon)
- [x] site.webmanifest created (PWA manifest)
- [x] humans.txt created
- [x] security.txt created (.well-known/security.txt)
- [x] Favicon link tags added to all pages
- [x] sitemap.xml `lastmod` auto-updates on every scraper run
- [x] sitemap.xml `changefreq` set to daily for content that changes daily
- [x] index.html meta description auto-updates the month on every scraper run
- [ ] og-image.png created (1200x630px)
- [ ] PNG favicon variants created
- [ ] apple-touch-icon.png created (180x180px)
