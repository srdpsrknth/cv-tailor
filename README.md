# CV-Tailor

A tool that generates tailored CVs (LaTeX→PDF) and cover letters (DOCX) for job applications using Google Gemini AI.

## 🎯 Features

- **AI-Powered Tailoring**: Uses Google Gemini to intelligently adapt your CV and cover letter to job descriptions
- **ATS-Compliant**: Generated CVs are optimized for Applicant Tracking Systems
- **Professional Templates**: LaTeX-based CV compilation and Word document cover letters
- **Cost Tracking**: Real-time token usage and cost estimation
- **Preview & Download**: Streamlit UI for previewing and downloading outputs
- **No Fabrication**: AI strictly rewords existing experiences without inventing facts

## 🚀 Quick Start

### Prerequisites

1. **Python 3.10+** installed
2. **Tectonic** LaTeX compiler installed ([Download](https://tectonic-typesetting.github.io/))
3. **Google Gemini API Key** from [AI Studio](https://aistudio.google.com/app/apikey)

### Installation

1. **Clone the repository**
   ```bash
   cd d:\coding\cv-tailor
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   copy .env.example .env
   ```
   Edit `.env` and add your `GEMINI_API_KEY`

5. **Verify base profile**
   Check `storage/profile/profile.yaml` contains your CV content

### Running the Application

1. **Start Backend** (Terminal 1)
   ```bash
   venv\Scripts\activate
   cd backend
   uvicorn main:app --reload --port 8000
   ```

2. **Start UI** (Terminal 2)
   ```bash
   venv\Scripts\activate
   cd ui
   streamlit run app.py
   ```

3. **Open browser**: http://localhost:8501

## 📁 Project Structure

```
cv-tailor/
├── backend/
│   ├── main.py                 # FastAPI app
│   ├── models/                 # Pydantic models
│   ├── services/               # Business logic
│   │   ├── gemini_service.py   # Gemini API integration
│   │   ├── tailor_service.py   # CV/CL tailoring logic
│   │   └── profile_loader.py   # YAML loading
│   ├── renderers/              # Document generation
│   │   ├── latex_renderer.py   # LaTeX → PDF
│   │   └── docx_renderer.py    # DOCX generation
│   └── prompts/                # Gemini prompts
│       ├── tailor_cv_prompt.md
│       └── tailor_cl_prompt.md
├── ui/
│   └── app.py                  # Streamlit UI
├── templates/
│   ├── cv/                     # LaTeX templates
│   │   ├── main.tex.jinja2
│   │   └── altacv.cls
│   └── cover_letter/           # DOCX templates
│       └── cover_letter.docx
├── storage/
│   └── profile/
│       └── profile.yaml        # Base CV content
├── outputs/                    # Generated files
├── .env                        # Environment variables (not in git)
└── requirements.txt
```

## 🔧 Configuration

### Gemini Model Selection

In `.env`, choose your model:
- `gemini-1.5-flash` (recommended): Fast, cheap, good quality
- `gemini-1.5-pro`: Higher quality, more expensive
- `gemini-2.0-flash`: Latest, best performance/cost ratio

### Cost Estimates (Gemini 1.5 Flash - Free Tier)

- **Free Tier Limits**: 15 requests/minute, 1.5M tokens/day
- **Per CV**: ~2,000-3,000 tokens (~$0.0015)
- **Per Cover Letter**: ~1,000-1,500 tokens (~$0.0008)
- **Total per application**: ~$0.002 (within free tier)

## 📝 Usage

1. **Input**: Paste job description in text area
2. **Generate**: Click "Generate Tailored CV & Cover Letter"
3. **Preview**: View PDF preview and cover letter text
4. **Download**: Download both files
5. **Check Costs**: See token usage and estimated costs

## 🛠️ Development

### Adding New Features

Use GitHub Copilot with the instructions in `.github/copilot-instructions.md`

### Testing

```bash
pytest
```

### Validation

Validate profile YAML:
```bash
python backend/validate_profile.py
```

## 📖 How It Works

1. **Load Base Profile**: Reads your CV from `profile.yaml`
2. **Analyze Job Description**: Gemini extracts key requirements
3. **Tailor Content**:
   - Reorder/reword achievements to match job
   - Adjust skills section relevance
   - Keep experiences in reverse chronological order
   - No fabrication of facts
4. **Render Documents**:
   - LaTeX template → Tectonic → PDF
   - DOCX template → python-docx → Word document
5. **Return Outputs**: Preview and download

## ⚙️ Customization

### Editing Base Profile

Edit `storage/profile/profile.yaml` with your experiences, skills, education, etc.

### Customizing Templates

- **CV**: Modify `templates/cv/main.tex.jinja2`
- **Cover Letter**: Edit `templates/cover_letter/cover_letter.docx`

### Adjusting Prompts

Fine-tune AI behavior in `backend/prompts/`

## 🔒 Security

- ✅ API key stored in backend `.env` only
- ✅ Never exposed to frontend/Streamlit
- ✅ `.gitignore` prevents committing secrets

## 📄 License

MIT License - see LICENSE file

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Use GitHub Copilot with project instructions
4. Submit pull request

---

**Note**: This tool is for personal use. Generated CVs should be reviewed before submission.
