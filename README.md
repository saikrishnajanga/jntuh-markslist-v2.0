# 🎓 JNTU Topper Analyzer V2.0

A powerful web-based tool to analyze JNTUH student exam results from Excel files. Upload your markslist and instantly get rankings, subject-wise pass percentages, failed student reports, and interactive charts.

## ✨ Features

- **🎨 Modernized SaaS Design System** — Coordinated color palettes, typography, glassmorphism, and responsive layouts
- **🚀 Interactive Drag & Drop Upload** — Visual dropzone with file size/format checks and live sample preview (`/demo`)
- **📋 Enhanced Data Tables** — Multi-row sticky headers, monospace roll numbers, and grade badges
- **🔍 Instant Search & Quick Filters** — Live real-time search with clear buttons, match counters, and passed/backlogs filtering
- **🏆 Rank Lists with Medals** — Students ranked by Total Marks and SGPA featuring Gold 🥇, Silver 🥈, and Bronze 🥉 honors
- **✅ Subject Pass % & Progress Bars** — Pass/fail counts with visual colored progress indicators
- **❌ Backlogs & Failed Students** — Tagged failed subjects and backlog count pill badges
- **📊 Interactive Visualizations** — Subject doughnuts, pass vs fail bar charts, SGPA histograms, and top performer charts
- **🌙 Dynamic Light / Dark Mode** — Morning & Night themes with automatic Chart.js contrast synchronization
- **📄 PDF & Multi-Sheet Excel Export** — Client-side landscape PDF export (`html2pdf.js`) and multi-sheet detailed `.xlsx` reports

## 🛠 Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python, Flask |
| Data Processing | Pandas, OpenPyXL |
| Frontend | HTML, CSS, Bootstrap 5 |
| Charts | Chart.js |
| Compression | Flask-Compress (gzip/brotli) |
| Deployment | Render, Gunicorn |

## 🚀 Getting Started

### Prerequisites
- Python 3.8+

### Installation

```bash
# Clone the repository
git clone https://github.com/saikrishnajanga/jntuh-markslist-v2.0.git
cd jntuh-markslist-v2.0

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

### Usage

1. Click **Upload** and select your JNTUH markslist Excel file
2. Navigate between tabs: Main List, Rankwise, Subject Pass %, Failed Students, Charts
3. Click **Download Excel** to export processed results
4. Toggle 🌙/☀️ for dark/light mode

## 📁 Project Structure

```
├── app.py              # Flask backend + data processing
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Frontend UI with charts & themes
└── uploads/            # Temporary file storage
```

## 🌐 Deployment

Deployed on **Render** with Gunicorn. Auto-deploys on push to `main`.

## 📄 License

This project is open source and available for educational purposes.

---

**Made with ❤️ by [Sai Krishna Janga](https://github.com/saikrishnajanga)**
