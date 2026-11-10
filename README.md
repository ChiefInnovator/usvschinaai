# **US vs CHINA AI Dashboard**
*Compare US and Chinese AI models using daily snapshots and inspectable evidence.*

## ✨ Features
- **Unified Score (0–1000)**: A comprehensive metric that evaluates AI models based on both capability and value.
- **Seventeen-Benchmark Scoring**: Seventeen configured Avg IQ benchmark allocations, with no participation filters or multipliers, a fixed 100% denominator, and missing results contributing zero. Avg Value uses the same rebuilt Avg IQ and retained model prices.
- **Smart Normalization**: Percentage benchmarks (GPQA, MMMU-Pro, etc.) use their raw 0–100 score directly. Non-percentage benchmarks with a known range (CodeArena helper range 1000–2800) use that range. Only unknown-scale benchmarks fall back to cohort min–max.
- **National Scoreboard**: An engaging scoreboard format to compare the AI prowess of Team USA 🇺🇸 and Team China 🇨🇳.
- **Auto-Sorted Rankings**: Instantly see AI models ranked by their Unified Scores with a simple descending order display.
- **Historical Archives**: Access expandable historical data to explore how the AI competition has evolved over time.
- **Informative About Page**: Gain insights into the scoring methodology and benchmarks used for evaluation.
- **Automated Daily Updates**: Receive a daily scrape scheduled at 03:17 UTC, with a visible warning when the latest snapshot is delayed.

## 🧮 Scoring Methodology (at a glance)

```text
Avg IQ inputs: seventeen components in data/core_benchmarks.json, totaling 100%
Only these seventeen benchmark columns remain in current and historical data
AvgIQ = sum(normalized scores × configured weights) / 1.00
Missing results contribute zero; denominator always includes all 18
Models are selected by Unified Score only, with no benchmark-count minimum
Value = AvgIQ ÷ (Input $/M + Output $/M)
Unified = 10 × (0.9 × norm(AvgIQ) + 0.1 × norm(Value))
```

Rebuild all retained historical cohorts with `.venv/bin/python scripts/rescore_history.py --rebuild --write --refresh-images`.
This removes old benchmark scores and scoring inputs, repopulates the seventeen components from dated evidence, and recalculates every score.

Benchmark weights are editor-selected and recorded in `data/core_benchmarks.json`.
Their adjustment history, including ranking-targeted changes, is documented in
`docs/two_pass_scoring.md`. The rankings measure this configured scoring system,
not an independent or neutral national capability standard.

Full rationale and design decisions: [docs/two_pass_scoring.md](docs/two_pass_scoring.md).

## 🚀 Getting Started
Experience the AI leaderboard live by visiting our deployed application: [US vs CHINA AI Dashboard](https://usvschina.ai).
For detailed information, check our GitHub Pages site: [GitHub Pages](https://chiefinnovator.github.io/usvschinaai/).

### Getting Started Locally

Install Python dependencies and the pinned frontend build packages, then build the
public artifact:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements.txt
npm ci --ignore-scripts
npm run build
python3 -m http.server 8000 --directory dist
```

Open `http://localhost:8000`. `npm run build:assets` builds only local CSS/vendor
assets when developing against the source HTML. The complete build verifies the
publication manifest and copies an explicit public-file allowlist into `dist/`.

### Every scoring change requires a full historical rescore

Changes to benchmark selection, weights, normalization, missing-result rules,
Value or evidence selection require replaying **every retained snapshot**.
Historical timestamps, model membership and historical price profiles stay
intact. Archive scores always reflect the current algorithm.

```sh
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/prepare_publication.py --write
.venv/bin/python scripts/prepare_publication.py
npm run build
```

Preparation runs in an isolated staging directory, regenerates scores, summary,
images and deterministic social captions, and installs a validated generation.
Verification independently replays all history and rejects stale outputs; it does
not run research or post social content. Include regenerated outputs in the same
change as the algorithm. See [publication and storage](docs/model_storage.md).

## 🔍 Explore the Pages
| Page          | Description                          |
|---------------|--------------------------------------|
| `index.html`  | Main leaderboard with current rankings |
| `history.html`| Historical snapshots over time       |
| `about.html`  | Detailed scoring methodology and assumptions |

## 🏗️ Architecture
The project is built primarily using HTML, CSS, and JavaScript for the front-end interface, while Python scripts are used for data scraping and processing. Key components include:

- **Data Scraping**: Scripts in the `scripts/` directory (`scrape_models.py` and `scrape_news.py`) gather real-time data on AI models and relevant news.
- **Data Storage**: Model data is stored in `models.json` and news data in `news.json` for easy access and manipulation.
- **Web Interface**: Static pages load `data/site_summary.json` first; raw history and benchmark evidence load on request.
- **Publication**: `data/publication.json` binds a complete data/image generation. The deployment workflow tests and deploys the same allowlisted artifact.

## 🤝 Contributing
We welcome contributions! If you'd like to help improve the project, please fork the repository and submit a pull request.

## 📜 License
This project is licensed under the [Unlicense](https://unlicense.org). Feel free to use, modify, and distribute it as you wish!

---

### Contact
For inquiries, you can reach out to the creator:
- **Richard Crane**: [rich@mill5.com](mailto:rich@mill5.com)
- **Website**: [Inventing Fire with AI](https://inventingfirewith.ai)

### Related Links
- [MILL5](https://www.mill5.com): An AI innovation company.
- [Microsoft MVP](https://mvp.microsoft.com/en-US/MVP/profile/10ce0bc0-7536-43f6-b28c-e9601a4a0d0d): Rich has been a Microsoft Most Valued Professional for several years in AI, Azure, Dev, DevOps, and more.
- [Inventing Fire with AI](https://inventingfirewith.ai): The website for Inventing Fire with AI podcast.

---

<sub>Powered by [Inventing Fire with AI](https://inventingfirewith.ai)</sub>


---

<sub>Powered by [RepoBeacon](https://repobeacon.com)</sub>

Shared model records, dated roster references, and full-history recalculation are documented in [Model storage](docs/model_storage.md).

Run all checks and review the application contracts in [Testing and preconditions](docs/testing.md).
