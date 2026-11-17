"""The editorial workspace visual system; no user content is interpolated here."""

CSS = """
<style>
:root { --cv-ink:#202e32; --cv-teal:#17685d; --cv-line:#d9dfda; }
.stApp { background:#f7f6f2; color:var(--cv-ink); }
[data-testid="stSidebar"] { background:#efefea; border-right:1px solid var(--cv-line); }
.block-container { padding-top:4.5rem; padding-bottom:3rem; max-width:1440px; }
h1 { font-family:Georgia,serif !important; letter-spacing:-.04em; font-weight:500 !important; }
h2,h3 { letter-spacing:-.025em; }
[data-testid="stMetricValue"] { font-size:1.25rem; }
[data-testid="stMetricLabel"] { font-size:.8rem; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:8px; }
button[kind="primary"] { background:var(--cv-teal); border-color:var(--cv-teal); }
button[kind="primary"]:hover { background:#105449; border-color:#105449; }
button:focus-visible,a:focus-visible { outline:3px solid #b6801d !important; outline-offset:3px; }
.stTabs [aria-selected="true"] { color:var(--cv-teal); }
.stTabs [data-baseweb="tab-highlight"] { background-color:var(--cv-teal); }
[data-testid="stAppDeployButton"] { display:none; }
.cv-before,.cv-after { padding:18px; border:1px solid var(--cv-line); border-radius:6px; white-space:pre-wrap; overflow-wrap:anywhere; }
.cv-before { background:#f3f0e9; }.cv-after { background:#eaf3ed; }
.cv-before del { background:#eedbd3; }.cv-after ins { background:#c8e5d5; text-decoration:none; }
@media(max-width:700px) { .block-container { padding:4.5rem 1rem 2rem; } h1 { font-size:2rem !important; } }
</style>
"""
