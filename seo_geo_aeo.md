# Technical Specification: AI-First Web Optimization (SEO/AEO/GEO)

## 1. Overview

This specification outlines the SEO, GEO (Generative Engine Optimization), and AEO (Answer Engine Optimization) implementation for **US vs CHINA AI** (usvschina.ai). The goal is to maximize visibility in both traditional search engines and AI-driven search environments (ChatGPT, Perplexity, Claude, Google AI Overviews).

---

## 2. Global AI Directive: `llms.txt`

**Status:** ✅ Implemented

A markdown file at `/llms.txt` provides a high-signal knowledge map for LLM crawlers.

### Content Structure:

```markdown
# US vs CHINA AI - AI Knowledge Map

> Primary Focus: Tracking the AI race between the United States and China through comprehensive model rankings and benchmarks.
> Website: https://usvschina.ai/
> Updated: December 2025

## Core Entities

- **Website:** US vs CHINA AI (usvschina.ai)
- **Type:** AI Model Leaderboard & Comparison Tool
- **Focus:** US-China AI Competition Analysis
- **Data Source:** Aggregated benchmark results from public sources

## Key Resources

- /index.html: Main leaderboard with current rankings and national scores
- /history.html: Historical archives of past rankings
- /about.html: Detailed methodology explanation
- /models.json: Raw data in JSON format

## Scoring Methodology

- Unified Power Score (Max 200): IQ × (1 + Value / 100)
- Intelligence Index: Average of 11 benchmark scores
- Value Index: Log-normalized cost efficiency score

## Current Rankings

[Top 10 models with scores and origins]

## Frequently Asked Questions

[Common queries with direct answers]
```

---

## 3. Structured Data: JSON-LD Entity Mapping

**Status:** ✅ Implemented

### WebSite Schema (index.html):

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

### FAQPage Schema (index.html):

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What is the best AI model in 2025?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "DeepSeek-V3.2 from China leads with a Unified Power Score of 184.8..."
      }
    },
    {
      "@type": "Question",
      "name": "Is the US or China winning the AI race?",
      "acceptedAnswer": {...}
    },
    {
      "@type": "Question",
      "name": "How are AI models ranked on this leaderboard?",
      "acceptedAnswer": {...}
    }
  ]
}
```

### ItemList Schema (index.html):

```json
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "name": "Top 10 AI Models December 2025",
  "description": "Global ranking of frontier AI models by Unified Power Score",
  "numberOfItems": 10,
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "DeepSeek-V3.2", "description": "Score: 184.8 | Origin: China"},
    ...
  ]
}
```

### Dataset Schema (index.html):

```json
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "US vs China AI Model Rankings",
  "description": "Comprehensive dataset ranking frontier AI models...",
  "url": "https://usvschina.ai/",
  "license": "https://creativecommons.org/licenses/by/4.0/",
  "isAccessibleForFree": true,
  "distribution": {
    "@type": "DataDownload",
    "encodingFormat": "application/json",
    "contentUrl": "https://usvschina.ai/models.json"
  },
  "temporalCoverage": "2025-12",
  "spatialCoverage": ["United States", "China"]
}
```

### SpeakableSpecification Schema (index.html):

```json
{
  "@context": "https://schema.org",
  "@type": "SpeakableSpecification",
  "cssSelector": ["#page-title", "#page-subtitle", ".glass h3"]
}
```

### AboutPage Schema (about.html):

```json
{
  "@context": "https://schema.org",
  "@type": "AboutPage",
  "name": "About US vs CHINA AI",
  "description": "Methodology and scoring explanation for the AI leaderboard",
  "url": "https://usvschina.ai/about.html"
}
```

### CollectionPage Schema (history.html):

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

### Standard SEO Meta Tags:

- `<meta name="description">` - Unique per page
- `<meta name="keywords">` - Relevant AI/model terms
- `<meta name="author">` - "US vs CHINA AI"
- `<meta name="robots">` - "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
- `<link rel="canonical">` - Absolute URL per page

### Open Graph Tags:

- `og:type` - website/article
- `og:url` - Canonical URL
- `og:title` - Page title
- `og:description` - Page description
- `og:image` - og-image.png
- `og:site_name` - "US vs CHINA AI"
- `og:locale` - "en_US"

### Twitter Card Tags:

- `twitter:card` - summary_large_image
- `twitter:url` - Canonical URL
- `twitter:title` - Page title
- `twitter:description` - Page description
- `twitter:image` - og-image.png

### Additional Meta:

- `theme-color` - "#020617" (site background)
- `<link rel="alternate" href="/llms.txt">` - LLM knowledge map reference

---

## 5. robots.txt Configuration

**Status:** ✅ Implemented

```
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
- `/` and `/index.html` (priority 1.0, weekly)
- `/history.html` (priority 0.8, weekly)
- `/about.html` (priority 0.7, monthly)
- `/llms.txt` (priority 0.6, weekly)
- `/models.json` (priority 0.5, weekly)

---

## 7. Content Optimization for AI Retrieval

### Implemented Strategies:

1. **Direct Answer Format** - FAQPage schema with concise answers
2. **Structured Data** - Multiple schema types for entity recognition
3. **llms.txt** - Dedicated AI crawler knowledge map
4. **Clean HTML Structure** - Semantic headings (h1, h2, h3)
5. **Data Accessibility** - JSON endpoint for raw data

### Key Query Targets:

| Query | Optimized Answer Location |
|-------|--------------------------|
| "Best AI model 2025" | FAQPage schema, llms.txt |
| "US vs China AI race" | FAQPage schema, llms.txt |
| "AI model rankings" | ItemList schema, llms.txt |
| "How to compare AI models" | AboutPage, llms.txt methodology |
| "DeepSeek vs GPT" | ItemList with scores |

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

### Recommended:

1. **Create og-image.png** - Custom Open Graph image (1200x630px)
2. **Create PNG favicons** - favicon-16x16.png, favicon-32x32.png, favicon-192x192.png, favicon-512x512.png
3. **Create apple-touch-icon.png** - 180x180px iOS icon
4. **Add hreflang tags** - If multi-language support added

### Optional:

1. **RSS/Atom feed** - For ranking updates
2. **API documentation page** - For models.json consumers
3. **Changelog page** - Track methodology updates

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
- [ ] og-image.png created (1200x630px)
- [ ] PNG favicon variants created
- [ ] apple-touch-icon.png created (180x180px)
