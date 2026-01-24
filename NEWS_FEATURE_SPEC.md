# News Marquee Feature Specification
**US vs China AI Dashboard Enhancement**

## 1. Overview

### 1.1 Goal
Add a dynamic news marquee at the top of the website that displays the latest AI-related news about US and China, allowing users to click through to read full articles.

### 1.2 Success Metrics
- Display fresh, relevant AI news (updated at least daily)
- High click-through rate (users engaging with news)
- Fast load time (<500ms for marquee)
- Mobile-responsive design

---

## 2. User Experience

### 2.1 Visual Design

**Position**: Fixed banner at the top of the page, above the scoreboard

**Layout**:
```
┌─────────────────────────────────────────────────────────────┐
│ 🔥 LATEST NEWS: [Headline 1] • [Headline 2] • [Headline 3] │
│                 ←─────────────────────────────────→          │
└─────────────────────────────────────────────────────────────┘
```

**Style Consistency**:
- Match existing neon/glass-morphism design
- Use Tailwind CSS classes
- Lucide icons for news indicator
- Smooth auto-scroll animation

### 2.2 User Interactions

1. **Auto-scroll**: Headlines scroll horizontally (right to left)
2. **Hover**: Pause scrolling on hover
3. **Click**: Open article in new tab
4. **Close**: Optional dismiss button (saves to localStorage)
5. **Mobile**: Swipe to navigate between headlines

### 2.3 Content Display

**Headline Format**:
```
[Country Flag] [Organization] released [Model Name] achieving [Score]% on [Benchmark]
🇺🇸 OpenAI released GPT-5.2 achieving 92.4% on GPQA • 🇨🇳 DeepSeek launches V3.2...
```

**Each Item Shows**:
- Country flag (🇺🇸 or 🇨🇳)
- Headline (max 100 characters)
- Source (e.g., "TechCrunch")
- Time ago (e.g., "2h ago")
- Click indicator icon

---

## 3. Technical Architecture

### 3.1 Data Pipeline

```
News Sources → News API/RSS → Python Scraper → news.json → Frontend Display
     ↓              ↓              ↓               ↓              ↓
  Various      Aggregation    Daily Cron     Static File    Client JS
   APIs          Service       00:00 UTC      (CDN)         (Fetch)
```

### 3.2 News Sources

**Primary Sources** (Free Tier):
1. **NewsAPI.org** (Free: 100 requests/day)
   - Endpoint: `https://newsapi.org/v2/everything`
   - Query: `"artificial intelligence" AND ("China" OR "United States")`

2. **RSS Feeds**:
   - Google News RSS: AI + China/US
   - TechCrunch AI RSS
   - MIT Tech Review RSS
   - The Verge AI RSS

3. **Custom Scrapers** (Optional):
   - Twitter/X API (for researcher announcements)
   - ArXiv papers (for model releases)
   - Company blogs (OpenAI, Anthropic, DeepSeek, etc.)

### 3.3 File Structure

```
aiolympics/
├── news.json              # Latest news data
├── scripts/
│   └── scrape_news.py     # News aggregation script
├── .github/workflows/
│   └── daily-news.yml     # GitHub Action for news updates
└── index.html             # Updated with news marquee
```

### 3.4 Data Schema

**news.json**:
```json
{
  "lastUpdated": "2026-01-24T12:00:00Z",
  "items": [
    {
      "id": "unique-hash-123",
      "headline": "OpenAI releases GPT-5.2 achieving 92.4% on GPQA",
      "url": "https://techcrunch.com/...",
      "source": "TechCrunch",
      "country": "US",
      "category": "model-release",
      "publishedAt": "2026-01-24T10:30:00Z",
      "tags": ["OpenAI", "GPT-5.2", "GPQA"],
      "imageUrl": "https://...",
      "relevanceScore": 0.95
    }
  ]
}
```

**Fields**:
- `id`: SHA256 hash of URL + publishedAt (deduplication)
- `headline`: Cleaned, formatted headline (max 100 chars)
- `url`: Original article URL
- `source`: Publisher name
- `country`: "US", "CN", or "Both"
- `category`: "model-release", "policy", "research", "funding", "regulation"
- `publishedAt`: ISO 8601 timestamp
- `tags`: Extracted entities (companies, models, benchmarks)
- `relevanceScore`: 0-1 score for ranking (ML-based or keyword matching)

---

## 4. Implementation Plan

### Phase 1: MVP (Week 1)
**Goal**: Basic news marquee with manual updates

- [ ] Design HTML/CSS marquee component
- [ ] Create static `news.json` with 10 sample articles
- [ ] Implement JavaScript auto-scroll
- [ ] Add click-through functionality
- [ ] Test responsive design

**Deliverable**: Working marquee with static data

### Phase 2: Automation (Week 2)
**Goal**: Automated daily news updates

- [ ] Create `scripts/scrape_news.py`
- [ ] Integrate NewsAPI.org (free tier)
- [ ] Add RSS feed parsing
- [ ] Implement deduplication logic
- [ ] Create `.github/workflows/daily-news.yml`
- [ ] Test daily automation

**Deliverable**: Automated news updates via GitHub Actions

### Phase 3: Enhancement (Week 3-4)
**Goal**: Improve relevance and user experience

- [ ] Add keyword filtering (model names, benchmarks)
- [ ] Implement relevance scoring algorithm
- [ ] Add category filtering UI
- [ ] Improve headline extraction
- [ ] Add "Load More" / "Archive" page
- [ ] Analytics tracking (click-through rates)

**Deliverable**: Intelligent news curation

### Phase 4: Advanced (Future)
**Goal**: Real-time updates and AI summarization

- [ ] Add Twitter/X integration for researcher announcements
- [ ] Use LLM to summarize articles
- [ ] Real-time updates via WebSocket (optional)
- [ ] User preferences (filter by source, category)
- [ ] Email digest (weekly roundup)

---

## 5. Python Scraper Design

### 5.1 Core Script: `scripts/scrape_news.py`

```python
#!/usr/bin/env python3
"""
Scrape AI news about US vs China from various sources.
Runs daily via GitHub Actions.
"""
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict

# News sources
def fetch_newsapi(api_key: str, days_back: int = 2) -> List[Dict]:
    """Fetch from NewsAPI.org"""
    pass

def fetch_rss_feeds(feeds: List[str]) -> List[Dict]:
    """Fetch from RSS feeds"""
    pass

def fetch_arxiv(query: str) -> List[Dict]:
    """Fetch recent papers from arXiv"""
    pass

# Processing
def extract_entities(text: str) -> List[str]:
    """Extract company names, model names, benchmarks"""
    pass

def calculate_relevance(item: Dict) -> float:
    """Score 0-1 based on keywords, source, recency"""
    pass

def deduplicate(items: List[Dict]) -> List[Dict]:
    """Remove duplicates based on URL/title similarity"""
    pass

def clean_headline(headline: str, max_length: int = 100) -> str:
    """Clean and truncate headline"""
    pass

# Main
def main():
    # Fetch from all sources
    # Combine and deduplicate
    # Score and rank
    # Take top 20
    # Write to news.json
    pass
```

### 5.2 GitHub Action: `.github/workflows/daily-news.yml`

```yaml
name: Daily AI News Scrape

on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:  # Manual trigger

permissions:
  contents: write

jobs:
  scrape:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install requests feedparser python-dateutil

      - name: Run news scraper
        env:
          NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}
        run: |
          python scripts/scrape_news.py

      - name: Commit and push changes
        run: |
          git config --local user.email "actions@github.com"
          git config --local user.name "GitHub Actions"
          git add news.json
          git diff --quiet && git diff --staged --quiet || \
          git commit -m "Update news - $(date -u +'%Y-%m-%dT%H:%M:%S UTC')"
          git push
```

---

## 6. Frontend Implementation

### 6.1 HTML Structure

```html
<!-- News Marquee (add at top of <body>) -->
<div id="newsMarquee" class="fixed top-0 left-0 right-0 z-50 bg-gradient-to-r from-blue-900/90 to-red-900/90 backdrop-blur-sm border-b border-white/10">
  <div class="relative overflow-hidden h-12">
    <div id="newsTrack" class="flex items-center h-full whitespace-nowrap animate-scroll">
      <!-- News items will be injected here -->
    </div>
  </div>
  <button id="dismissNews" class="absolute right-2 top-2 text-white/60 hover:text-white">
    <svg><!-- Close icon --></svg>
  </button>
</div>
```

### 6.2 JavaScript Logic

```javascript
// Fetch and display news
async function loadNews() {
  const response = await fetch('news.json');
  const data = await response.json();

  const newsTrack = document.getElementById('newsTrack');
  newsTrack.innerHTML = data.items.map(item => `
    <a href="${item.url}" target="_blank" class="news-item inline-flex items-center px-6">
      <span class="text-2xl mr-2">${item.country === 'US' ? '🇺🇸' : '🇨🇳'}</span>
      <span class="text-white font-medium">${item.headline}</span>
      <span class="text-white/50 ml-2 text-sm">(${item.source})</span>
      <span class="mx-4 text-white/30">•</span>
    </a>
  `).join('');

  // Duplicate for seamless loop
  newsTrack.innerHTML += newsTrack.innerHTML;
}

// Auto-scroll animation
function startScroll() {
  const track = document.getElementById('newsTrack');
  let position = 0;

  setInterval(() => {
    position -= 1;
    if (Math.abs(position) >= track.scrollWidth / 2) {
      position = 0;
    }
    track.style.transform = `translateX(${position}px)`;
  }, 30);
}

// Pause on hover
newsTrack.addEventListener('mouseenter', () => { /* pause */ });
newsTrack.addEventListener('mouseleave', () => { /* resume */ });
```

### 6.3 CSS Animations

```css
@keyframes scroll {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

.animate-scroll {
  animation: scroll 60s linear infinite;
}

.animate-scroll:hover {
  animation-play-state: paused;
}
```

---

## 7. Content Strategy

### 7.1 Filtering Criteria

**Include**:
- New model releases (GPT-5, Gemini 3, DeepSeek V3, etc.)
- Benchmark achievements
- Funding announcements (>$50M)
- Policy/regulation changes
- Research breakthroughs
- Company partnerships

**Exclude**:
- General tech news
- Unrelated AI applications
- Op-eds/opinions (unless from major figures)
- Duplicate announcements
- Old news (>7 days)

### 7.2 Keyword Weights

**High Priority (score +0.3)**:
- Model names: GPT, Gemini, Claude, DeepSeek, GLM, Qwen
- Benchmarks: GPQA, MMLU, SWE-bench, ARC-AGI
- Companies: OpenAI, Anthropic, Google, DeepSeek, Alibaba

**Medium Priority (score +0.2)**:
- Keywords: "artificial intelligence", "machine learning", "AI model"
- Actions: "released", "launched", "achieved", "breakthrough"

**Low Priority (score +0.1)**:
- General: "technology", "innovation", "research"

---

## 8. Performance & Scalability

### 8.1 Performance Targets

- **Initial Load**: <100ms (news.json is ~50KB)
- **Marquee Render**: <50ms
- **Smooth Animation**: 60 FPS
- **Click Response**: Instant

### 8.2 Optimization

1. **CDN**: Serve `news.json` from Azure CDN
2. **Compression**: Gzip news.json
3. **Caching**: Browser cache for 6 hours
4. **Lazy Load**: Only load images on hover
5. **Pagination**: Limit to 20 items in marquee

### 8.3 Scalability

- **News Storage**: Keep last 30 days (auto-prune old items)
- **Archive Page**: Separate `news-archive.json` for history
- **API Rate Limits**: Respect NewsAPI 100 req/day limit
- **Fallback**: If API fails, show cached news

---

## 9. Analytics & Monitoring

### 9.1 Track Metrics

```javascript
// Track clicks
newsItem.addEventListener('click', (e) => {
  gtag('event', 'news_click', {
    headline: item.headline,
    source: item.source,
    country: item.country,
    category: item.category
  });
});
```

**Key Metrics**:
- Click-through rate (CTR)
- Most clicked sources
- Most clicked categories
- Average time to click
- Mobile vs desktop engagement

### 9.2 Error Monitoring

- Failed news fetch
- Parsing errors
- API quota exceeded
- Stale data (>24h old)

---

## 10. Future Enhancements

### 10.1 v2.0 Features
- [ ] User accounts (save preferences)
- [ ] Email digest (weekly AI roundup)
- [ ] Filter by category/source
- [ ] "Breaking" badge for urgent news
- [ ] Dark/light mode toggle
- [ ] Multilingual support (Chinese translations)

### 10.2 v3.0 Features
- [ ] AI-powered summarization (using Claude/GPT)
- [ ] Sentiment analysis (bullish/bearish for US/CN)
- [ ] Trend detection (rising topics)
- [ ] Integration with main dashboard (link news to models)
- [ ] Community submissions (verified users can submit)

---

## 11. Testing Plan

### 11.1 Unit Tests
- [ ] Test news fetching from each source
- [ ] Test deduplication logic
- [ ] Test relevance scoring
- [ ] Test headline cleaning

### 11.2 Integration Tests
- [ ] Test GitHub Action workflow
- [ ] Test news.json update
- [ ] Test frontend loading

### 11.3 UI Tests
- [ ] Test marquee scrolling
- [ ] Test click-through
- [ ] Test responsive design (mobile/tablet/desktop)
- [ ] Test accessibility (screen readers)

### 11.4 Performance Tests
- [ ] Load test (1000 concurrent users)
- [ ] Animation smoothness test (60 FPS)
- [ ] Network throttling test (3G connection)

---

## 12. Dependencies

### 12.1 Python Packages
```txt
requests==2.31.0
feedparser==6.0.10
python-dateutil==2.8.2
beautifulsoup4==4.12.0  # Optional: for web scraping
```

### 12.2 External APIs
- NewsAPI.org (free tier: 100 req/day)
- Optional: Twitter/X API v2 (free tier)
- Optional: OpenAI API (for summarization)

### 12.3 GitHub Secrets
```
NEWSAPI_KEY=your_newsapi_key_here
```

---

## 13. Launch Checklist

### Pre-Launch
- [ ] Test on all major browsers (Chrome, Firefox, Safari, Edge)
- [ ] Test on mobile devices (iOS, Android)
- [ ] Verify accessibility (WCAG 2.1 AA)
- [ ] Set up analytics tracking
- [ ] Configure error monitoring

### Launch Day
- [ ] Deploy news marquee HTML/CSS/JS
- [ ] Run initial news scrape
- [ ] Verify GitHub Action runs successfully
- [ ] Monitor for errors
- [ ] Announce feature on social media

### Post-Launch
- [ ] Monitor CTR for first week
- [ ] Gather user feedback
- [ ] Fix any bugs
- [ ] Optimize based on analytics
- [ ] Plan v2.0 features

---

## 14. Budget Estimate

### Free Tier (MVP)
- NewsAPI.org: Free (100 req/day)
- RSS Feeds: Free
- GitHub Actions: Free (2000 min/month)
- Azure CDN: Included in current hosting
- **Total: $0/month**

### Paid Tier (Enhanced)
- NewsAPI.org Pro: $449/month (100K req/day)
- OpenAI API: ~$10/month (summarization)
- Monitoring: Free (Google Analytics)
- **Total: ~$460/month** (only if scaling significantly)

**Recommendation**: Start with free tier, upgrade if CTR is high (>5%)

---

## 15. Risks & Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| API rate limit exceeded | High | Medium | Cache aggressively, use multiple sources |
| Irrelevant news shown | Medium | High | Improve filtering, manual curation |
| Marquee distracts from main content | Medium | Low | Add dismiss button, subtle design |
| News scraper fails | High | Low | Fallback to cached data, error alerts |
| CORS issues with news.json | High | Low | Serve from same domain, proper headers |

---

## Contact & Ownership

**Owner**: Rich Crane (ChiefInnovator)
**Repository**: https://github.com/ChiefInnovator/usvschinaai
**Website**: https://usvschina.ai
**Last Updated**: 2026-01-24
