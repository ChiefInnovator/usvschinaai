# **US vs CHINA AI Dashboard**
*Track the AI race in real-time between the US 🇺🇸 and China 🇨🇳*

## ✨ Features
- **Unified Score (0–1000)**: A comprehensive metric that evaluates AI models based on both capability and value.
- **National Scoreboard**: An engaging scoreboard format to compare the AI prowess of Team USA 🇺🇸 and Team China 🇨🇳.
- **Auto-Sorted Rankings**: Instantly see AI models ranked by their Unified Scores with a simple descending order display.
- **Historical Archives**: Access expandable historical data to explore how the AI competition has evolved over time.
- **Informative About Page**: Gain insights into the scoring methodology and benchmarks used for evaluation.
- **Automated Daily Updates**: Receive fresh data daily at 00:00 UTC, ensuring you have the latest information.

## 🚀 Getting Started
Experience the AI leaderboard live by visiting our deployed application: [US vs CHINA AI Dashboard](https://usvschina.ai).
For detailed information, check our GitHub Pages site: [GitHub Pages](https://chiefinnovator.github.io/usvschinaai/).

### Getting Started Locally
To run the project locally, you will need a local web server. Here are some easy methods to set it up:

#### Python (Recommended)
```bash
python3 -m http.server
```
Then, navigate to `http://localhost:8000` in your web browser.

#### VS Code Live Server
1. Install the **Live Server** extension.
2. Right-click `index.html` and select **Open with Live Server**.

#### Node.js
```bash
npx http-server .
```

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
- **Web Interface**: The main application interface is served through `index.html`, providing a straightforward user experience.

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
- [Microsoft MVP](https://mvp.microsoft.com/en-US/MVP/profile/10ce0bc0-7536-43f6-b28c-e9601a4a0d0d): Rich has been a Microsoft Most Valued Professional for several years in AI, Azure, Dev, DevOps, and more.
- [Inventing Fire with AI](https://inventingfirewith.ai): The website for Inventing Fire with AI podcast.
- [MILL5](https://www.mill5.com): An AI innovation company.

---

<sub>Powered by [Inventing Fire with AI](https://inventingfirewith.ai)</sub>


---

<sub>Powered by [RepoBeacon](https://repobeacon.com)</sub>
