# US_VS_CHINA_AI_2025_SPEC.md

## 1. Project Context & Objective

* **Project Name:** US vs CHINA AI Dashboard
* **Domain:** usvschina.ai
* **Date:** December 30, 2025 (Final Audit Edition)
* **Goal:** Create a "Viral" interactive HTML/CSS dashboard ranking the Top 10 AI models globally. The core narrative is the competition between **Team USA** (Frontier Intelligence) and **Team China** (Economic Efficiency).

## 2. Technical Stack

* **Architecture:** Static HTML5 frontend with decoupled JSON data source (`models.json`).
* **Frameworks:** Tailwind CSS (via CDN), Lucide-React (Icons), Vanilla JavaScript.
* **Design Aesthetic:**
  * **Theme:** "Cyber-Athletic" Dark Mode (`bg-slate-950`).
  * **Accents:** Electric Blue (`#3b82f6`) for USA, Crimson Red (`#ef4444`) for China.
  * **Typography:** Monospace numbers for data, bold sans-serif for headers.

## 3. Scoring Methodology

The **Unified Power Score** (Max 200) uses **Intelligence-Gated Value** — where intelligence is the foundation and value acts as a multiplier.

### Formula

$$\text{Unified} = I \times \left(1 + \frac{V}{100}\right)$$

*A model with zero intelligence scores zero—no matter how cheap. Value without intelligence is meaningless.*

### A. Intelligence Index ($I$) — Max 100

Unweighted average (Max 100) of 11 frontier benchmarks:

1. **[AIME 2025](https://llm-stats.com/benchmarks/aime-2025):** Math Olympiad (No-tool).
2. **[HMMT 2025](https://llm-stats.com/benchmarks/hmmt):** Harvard-MIT Mathematics Tournament.
3. **[GPQA Diamond](https://llm-stats.com/benchmarks/gpqa):** PhD-level science reasoning.
4. **[ARC-AGI](https://arcprize.org/):** Abstraction and Reasoning Corpus.
5. **[BrowseComp](https://llm-stats.com/benchmarks/browsecomp):** Web agent capabilities.
6. **[ARC-AGI v2](https://arcprize.org/):** Advanced general intelligence reasoning.
7. **[HLE (Humanity's Last Exam)](https://llm-stats.com/benchmarks/hle):** Multidisciplinary reasoning.
8. **[MMLU-Pro](https://llm-stats.com/benchmarks/mmlu-pro):** Robust multi-task understanding.
9. **[LiveCodeBench](https://llm-stats.com/benchmarks/livecodebench):** Live coding challenges.
10. **[SWE-Bench Verified](https://llm-stats.com/benchmarks/swe-bench-verified):** Real-world software engineering.
11. **[CodeForces](https://llm-stats.com/benchmarks/codeforces):** Competitive programming.

### B. Value Index ($V$) — Max 100

Log-normalized efficiency score based on **Blended Cost per 1M tokens ($C$)**.

* **Formula:** $V = 100 \times (1 - \frac{\log(C_{model} / 0.25)}{\log(60.00 / 0.25)})$
* *Floor: $0.25 (DeepSeek-V3.2) | Ceiling: $60.00 (Legacy Models)*

### C. National Score Calculation

The National Score for each team (USA vs China) is calculated as the **sum of the Unified Power Scores** for all models belonging to that nation that appear in the **Global Top 10**.

*   **Eligibility:** Only models ranked in the top 10 globally contribute to the national total.
*   **Aggregation:** Sum of Unified Scores of eligible models.
*   **Purpose:** This rewards both peak performance (having the #1 model) and depth of dominance (having multiple models in the top tier).

## 4. Audited Data Table (Dec 30, 2025)

| Rank | Model Name | Origin | Unified Score | IQ Index | Value Index | Source Link |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **1** | **DeepSeek-V3.2** | 🇨🇳 | **184.8** | 92.4 | 100.0 | [DeepSeek](https://llm-stats.com/models/deepseek-reasoner) |
| **2** | **DeepSeek-V3.2-Speciale** | 🇨🇳 | **176.1** | 90.1 | 95.5 | [DeepSeek](https://llm-stats.com/models/deepseek-v3.2-speciale) |
| **3** | **Gemini 3 Pro** | 🇺🇸 | **171.7** | 96.2 | 78.5 | [Google](https://llm-stats.com/models/gemini-3-pro-preview) |
| **4** | **Gemini 3 Flash** | 🇺🇸 | **170.0** | 88.5 | 92.0 | [Google](https://llm-stats.com/models/gemini-3-flash) |
| **5** | **DeepSeek-V3.2-Exp** | 🇨🇳 | **168.1** | 88.0 | 91.0 | [DeepSeek](https://llm-stats.com/models/deepseek-v3.2-exp) |
| **6** | **Qwen 3 Max** | 🇨🇳 | **165.2** | 89.1 | 85.3 | [Alibaba](https://dev.to/czmilo/qwen3-max-2025) |
| **7** | **Grok Code Fast 1** | 🇺🇸 | **161.7** | 86.0 | 88.0 | [xAI](https://llm-stats.com/models/grok-code-fast-1) |
| **8** | **GPT-5 mini** | 🇺🇸 | **159.1** | 82.0 | 94.0 | [OpenAI](https://llm-stats.com/models/gpt-5-mini-2025-08-07) |
| **9** | **Qwen3-235B-Thinking** | 🇨🇳 | **161.0** | 87.5 | 84.0 | [Alibaba](https://llm-stats.com/models/qwen3-235b-a22b-thinking-2507) |
| **10** | **GPT-5.1** | 🇺🇸 | **153.5** | 93.0 | 65.0 | [OpenAI](https://llm-stats.com/models/gpt-5.1-2025-11-13) |

