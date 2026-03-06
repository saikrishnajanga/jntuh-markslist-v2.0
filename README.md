# 🎓 JNTU Topper Analyzer V2.0

A powerful web-based tool to analyze JNTUH student exam results from Excel files. Upload your markslist and instantly get rankings, subject-wise pass percentages, failed student reports, and interactive charts.

## ✨ Features

- **📋 Main Results Table** — Subject-wise marks, total marks, overall %, and SGPA for every student
- **🏆 Rank Lists** — Students ranked by Total Marks and SGPA
- **✅ Subject Pass %** — Pass/fail count and percentage for each subject
- **❌ Failed Students** — List of students with their failed subjects
- **📊 Interactive Charts** — Doughnut charts per subject + overall pass/fail bar chart
- **🌙 Dark/Light Mode** — Toggle between morning and night themes
- **⬇ Excel Download** — Export processed results as `.xlsx`

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
