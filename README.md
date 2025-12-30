# US vs CHINA AI Dashboard

## Overview
The **US vs CHINA AI Dashboard** (hosted at `usvschina.ai`) is a "Viral" interactive HTML/CSS leaderboard that ranks the Top 10 AI models globally. The core narrative highlights the competition between **Team USA** (Frontier Intelligence) and **Team China** (Economic Efficiency), visualizing the landscape of AI dominance in late 2025.

## Features
- **Unified Power Score**: Ranks models based on a balance of Intelligence (IQ Index) and Value (Cost Efficiency).
- **National Scoreboard**: Real-time aggregation of top scores for Team USA vs. Team China.
- **Interactive UI**: 
  - Sortable columns (Rank, IQ, Value, Unified Score).
  - "Cyber-Athletic" Dark Mode design with neon accents.
  - Responsive layout for desktop and mobile.
- **Dynamic Data**: Model data is decoupled into `models.json` for easy updates without modifying the code.

## Setup & Usage
Because this project uses the `fetch()` API to load external JSON data, **it will not work if you simply double-click `index.html`** due to browser security restrictions (CORS) on local files. You must run it through a local web server.

### Option 1: Python (Recommended)
If you have Python installed (macOS/Linux usually do):
1. Open your terminal in the project folder.
2. Run:
   ```bash
   python3 -m http.server
   ```
3. Open your browser to `http://localhost:8000`.

### Option 2: VS Code Live Server
1. Install the **Live Server** extension in VS Code.
2. Right-click `index.html` in the file explorer.
3. Select **"Open with Live Server"**.

### Option 3: Node.js
If you have Node.js installed:
```bash
npx http-server .
```

## File Structure
- **`index.html`**: The main application file containing the UI structure, Tailwind styling, and JavaScript logic.
- **`models.json`**: The data source containing the array of AI models, their scores, and metadata.
- **`specifications.md`**: The detailed project requirements, scoring methodology, and design goals.

## Tech Stack
- **Core**: HTML5, Vanilla JavaScript
- **Styling**: [Tailwind CSS](https://tailwindcss.com/) (via CDN)
- **Icons**: [Lucide React](https://lucide.dev/) (via CDN)
- **Fonts**: Inter (via Google Fonts/System UI)

## Scoring Methodology
The **Unified Power Score** (Max 200) is calculated based on:

1.  **Intelligence Index ($I$)**: Unweighted average of 11 frontier benchmarks (AIME 2025, HMMT 2025, GPQA Diamond, ARC-AGI, BrowseComp, ARC-AGI v2, HLE, MMLU-Pro, LiveCodeBench, SWE-Bench Verified, CodeForces).
2.  **Value Index ($V$)**: Log-normalized efficiency score based on blended cost per 1M tokens.

### National Scoring Rule
The National Score for Team USA and Team China is the **sum of the Unified Power Scores** for all models belonging to that nation that appear in the **Global Top 10**. This ensures the scoreboard reflects only the most competitive models in the world.

## Historical Archives
The project includes a `history.html` page that tracks the balance of power over time. It features:
- **Snapshots**: Historical leaderboards from previous dates.
- **Interactive Filtering**: View Top 10 Global, USA, or China models for any specific date.
- **Trend Analysis**: See how the "National Score" has evolved.

1.  **Intelligence Index ($I$)**: Unweighted average of 7 frontier benchmarks:
    *   AIME 2025 (Math Olympiad)
    *   HMMT 2025 (Harvard-MIT Math Tournament)
    *   GPQA Diamond (PhD-level Science)
    *   ARC-AGI (Abstraction & Reasoning)
    *   BrowseComp (Web Agent Capabilities)
    *   ARC-AGI v2 (Advanced Reasoning)
    *   HLE (Humanity's Last Exam)

2.  **Value Index ($V$)**: Log-normalized efficiency score based on blended cost per 1M tokens.

*Data Audited: December 30, 2025*
