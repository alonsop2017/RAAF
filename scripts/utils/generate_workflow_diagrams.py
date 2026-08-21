#!/usr/bin/env python3
"""
Regenerate the RAAF "How It Works" workflow diagrams.

Renders the three per-workflow PNGs (PCR-Integrated / Manual Upload /
Repository Search) plus the combined poster, and writes them into both
docs/ and web/static/images/ (the help.html page serves from the latter).

Run this after editing WORKFLOW_A_STEPS / WORKFLOW_B_STEPS / WORKFLOW_C_STEPS
below to keep the diagrams in sync with web/templates/help.html's step lists.

Requirements: a local Chrome/Chromium install (used headless for HTML->PNG
rendering) and Pillow + numpy (`pip install pillow numpy`) for the
content-bounds auto-crop.

Usage: python3 scripts/utils/generate_workflow_diagrams.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).parent.parent.parent
OUT_DIRS = [REPO_ROOT / "docs", REPO_ROOT / "web" / "static" / "images"]

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]

PAGE_BG = "#f4f7fb"
PAGE_BG_RGB = (244, 247, 251)

THEMES = {
    "A": {"header": "#186faf", "box_bg": "#dcf0ff", "box_border": "#186faf", "text": "#1a2b3c"},
    "B": {"header": "#2e7d32", "box_bg": "#e8f5e9", "box_border": "#2e7d32", "text": "#1a2b3c"},
    "C": {"header": "#5e35b1", "box_bg": "#ede7f6", "box_border": "#5e35b1", "text": "#1a2b3c"},
}
AI_STEP = {"bg": "#e0f2f1", "border": "#00796b"}
ARCHIVE_STEP = {"bg": "#eceff1", "border": "#546e7a"}
DASHED = {"border": "#4db6ac", "bg": "#daf0ee", "label": "#00695c"}
DECISION = {"bg": "#fff3e0", "border": "#e65100", "text": "#e65100"}

# All color-agnostic structure lives here — safe to include once regardless of
# how many themed columns share a page (no per-column class collisions).
SHARED_CSS = f"""
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; background: {PAGE_BG}; }}
.col {{ padding: 32px 26px 26px; }}
.header-bar {{ color: white; border-radius: 8px; padding: 16px 10px;
  text-align: center; font-size: 21px; font-weight: 700; letter-spacing: .3px; margin-bottom: 22px; }}
.header-bar .badge {{ background: rgba(255,255,255,.22); border-radius: 5px; font-size: 13px;
  font-weight: 700; padding: 3px 9px; margin-left: 10px; vertical-align: middle; }}
.step {{ width: 620px; margin: 0 auto; border-radius: 10px; padding: 14px 22px; text-align: center; }}
.step .title {{ font-size: 19px; font-weight: 600; }}
.step .sub {{ font-size: 13px; font-style: italic; color: #5b6b7a; margin-top: 4px; }}
.arrow {{ text-align: center; font-size: 20px; line-height: 1; margin: 2px 0; }}
.dashed-wrap {{ border: 2px dashed {DASHED["border"]}; background: {DASHED["bg"]};
  border-radius: 10px; padding: 10px; margin: 8px 0; }}
.dashed-label {{ text-align: center; font-size: 13px; font-weight: 700; font-style: italic;
  color: {DASHED["label"]}; margin-top: 8px; }}
.panel {{ border-radius: 10px; background: white; padding: 18px 24px; margin-top: 30px; }}
.panel h4 {{ text-align: center; font-size: 19px; margin: 0 0 14px; }}
.panel-row {{ display: flex; justify-content: space-between; padding: 9px 4px;
  font-size: 15px; color: #37474f; border-bottom: 1px solid #eef1f4; }}
.panel-row:last-child {{ border-bottom: none; }}
.footer-rule {{ border: none; border-top: 1px solid #d7dee6; margin: 30px 0 0; }}
"""


def step_html(title, sub, bg, border, text="#1a2b3c"):
    return (f'<div class="step" style="background:{bg};border:2px solid {border};">'
            f'<div class="title" style="color:{text}">{title}</div>'
            f'<div class="sub">{sub}</div></div>')


def arrow(color):
    return f'<div class="arrow" style="color:{color}">&#9660;</div>'


# ── Step content — keep in sync with web/templates/help.html ────────────────
# "__AI__" / "__ARCHIVE__" / "__DECISION__" are rendered specially (see render_steps).

WORKFLOW_A_STEPS = [
    ("Create Position in PCR", "Enter job title, set Job Code = INDML"),
    ("PCR Posts Job to Indeed", "Automatic via PCR job board integration"),
    ("Candidates Apply on Indeed", "Applications auto-flow into PCR"),
    ("RAAF Auto-Syncs Every 5 Min", "Downloads resumes &amp; assesses new applicants automatically"),
    ("__AI__", None),
    ("Review &amp; Refine Scores", "Edit scores, add notes &mdash; Reassess anytime"),
    ("Generate Client Report", "Ranked DOCX &middot; top profiles &middot; gaps"),
    ("Push Scores &rarr; PCR", "Sync RAAF scores to candidate records"),
    ("Update PCR Pipeline Status", "Interview / On Hold / Not Selected"),
    ("Send Interview Invitations", "AI-drafted, personalized per candidate"),
    ("Deliver Report to Client", "Email or client portal"),
    ("__ARCHIVE__", "Position filled or cancelled"),
]

WORKFLOW_B_STEPS = [
    ("Receive JD from Client", "PDF or DOCX via email"),
    ("Initialise Client &amp; Requisition", "Create client record + new req in RAAF"),
    ("Build Assessment Framework", "Upload JD &rarr; AI generates scoring model"),
    ("Auto-Ingest or Upload Resumes", "Emailed resumes matched every 6 hrs &mdash; or drag-and-drop"),
    ("Extract Text &amp; Create Batch", "Auto-normalize filenames, batch folder"),
    ("__AI__", None),
    ("Review &amp; Refine Scores", "Edit scores, add notes &mdash; Reassess anytime"),
    ("Generate Client Report", "Ranked DOCX &middot; top profiles &middot; gaps"),
    ("Send Interview Invitations", "AI-drafted, personalized per candidate"),
    ("Deliver Report to Client", "Email or client portal"),
    ("__ARCHIVE__", "Position filled or cancelled"),
]

WORKFLOW_C_STEPS = [
    ("New Position Opens", "Same or new client"),
    ("Search Candidate Repository", "Top nav Search, or quick modal on Requisitions list"),
    ("__DECISION__", None),
    ("AI Matches Candidates", "Ranked by fit to new JD"),
    ("Review Past Assessments", "Scores, strengths, concerns, evidence"),
    ("Reach Out Directly", "Warm candidate &mdash; shorter time-to-hire"),
    ("Add to New Requisition", "Upload resume or re-use extracted text"),
    ("Re-Assess if Needed", "Fresh score against new role framework"),
    ("Continue via Workflow A or B", "Full pipeline from assessment onward"),
]


def render_steps(steps, theme_key):
    t = THEMES[theme_key]
    out = []
    for i, (title, sub) in enumerate(steps):
        if i > 0:
            out.append(arrow(t["header"]))
        if title == "__AI__":
            out.append('<div class="dashed-wrap">')
            out.append(step_html("AI Assessment", "6 weighted categories &middot; evidence-based",
                                  AI_STEP["bg"], AI_STEP["border"]))
            out.append('<div class="dashed-label">&mdash; Shared AI Assessment Engine &mdash;</div>')
            out.append('</div>')
        elif title == "__ARCHIVE__":
            out.append(step_html("Archive Requisition", sub, ARCHIVE_STEP["bg"], ARCHIVE_STEP["border"]))
        elif title == "__DECISION__":
            out.append(f'''
            <div style="display:flex;justify-content:center;margin:6px 0 2px;">
              <div style="width:230px;height:230px;transform:rotate(45deg);
                   background:{DECISION["bg"]};border:2px solid {DECISION["border"]};
                   border-radius:14px;display:flex;align-items:center;justify-content:center;">
                <div style="transform:rotate(-45deg);text-align:center;color:{DECISION["text"]};
                     font-size:14px;font-weight:700;width:150px;">
                  Search by JD upload<br>or keyword?
                </div>
              </div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:700;
                 color:{DECISION["text"]};padding:0 40px;margin-bottom:6px;">
              <span>&larr; JD upload</span><span>Keyword &rarr;</span>
            </div>''')
        else:
            out.append(step_html(title, sub, t["box_bg"], t["box_border"]))
    return "\n".join(out)


SCORING_ROWS = [
    ("Core Experience &amp; Qualifications", "25%"),
    ("Technical &amp; Analytical Skills", "20%"),
    ("Communication &amp; Relationships", "20%"),
    ("Strategic &amp; Business Acumen", "15%"),
    ("Job Stability", "10%"),
    ("Cultural Fit &amp; Soft Skills", "10%"),
]

TIER_ROWS = [
    ("STRONG RECOMMEND", "85%+", "#2e7d32"),
    ("RECOMMEND", "70&ndash;84%", "#186faf"),
    ("CONDITIONAL", "55&ndash;69%", "#e65100"),
    ("DO NOT RECOMMEND", "&lt;55%", "#c62828"),
]

LEGEND_ROWS = [
    (THEMES["A"]["box_bg"], THEMES["A"]["box_border"], "PCR-Integrated step"),
    (THEMES["B"]["box_bg"], THEMES["B"]["box_border"], "Manual workflow step"),
    (THEMES["C"]["box_bg"], THEMES["C"]["box_border"], "Repository search step"),
    (AI_STEP["bg"], AI_STEP["border"], "Shared AI Assessment step"),
    (ARCHIVE_STEP["bg"], ARCHIVE_STEP["border"], "Admin / archive step"),
    (DECISION["bg"], DECISION["border"], "Decision point"),
]


def panel_scoring(header_color):
    rows = "".join(
        f'<div class="panel-row"><span>{c}</span><b style="color:{header_color}">{p}</b></div>'
        for c, p in SCORING_ROWS
    )
    return (f'<div class="panel" style="border:2px solid {header_color};">'
            f'<h4 style="color:{header_color}">AI Scoring Framework</h4>{rows}</div>')


def panel_tiers(header_color):
    rows = "".join(
        f'<div class="panel-row" style="background:{c}11;border-radius:6px;margin-bottom:4px;border-bottom:none;">'
        f'<span style="color:{c};font-weight:700;">{name}</span><b style="color:{c}">{score}</b></div>'
        for name, score, c in TIER_ROWS
    )
    return (f'<div class="panel" style="border:2px solid {header_color};">'
            f'<h4 style="color:{header_color}">Recommendation Tiers</h4>{rows}</div>')


def panel_legend(header_color):
    rows = "".join(
        f'<div class="panel-row" style="border-bottom:none;"><span style="display:flex;align-items:center;">'
        f'<span style="display:inline-block;width:16px;height:16px;border-radius:4px;background:{bg};'
        f'border:2px solid {border};margin-right:10px;"></span>{label}</span></div>'
        for bg, border, label in LEGEND_ROWS
    )
    return (f'<div class="panel" style="border:2px solid {header_color};">'
            f'<h4 style="color:{header_color}">Legend</h4>{rows}</div>')


def column_body(key, title_html, steps, panel_html, width, include_rule=True):
    t = THEMES[key]
    rule = '<hr class="footer-rule">' if include_rule else ""
    return f'''
    <div class="col" style="width:{width}px;">
      <div class="header-bar" style="background:{t["header"]}">{title_html}</div>
      {render_steps(steps, key)}
      {panel_html}
      {rule}
    </div>'''


def build_column(key, title_html, steps, panel_html, width=1320):
    body = column_body(key, title_html, steps, panel_html, width)
    return f"<html><head><style>{SHARED_CSS}</style></head><body>{body}</body></html>", width


def build_combined(col_defs, col_width=1320):
    """col_defs: list of (key, title_html, steps, panel_html)"""
    cols_html = "".join(
        column_body(key, title_html, steps, panel_html, col_width, include_rule=False)
        for key, title_html, steps, panel_html in col_defs
    )
    extra_css = """
    .page-title { text-align: center; padding: 34px 0 10px; }
    .page-title h1 { color: #186faf; font-size: 34px; margin: 0; }
    .page-title p { color: #5b6b7a; font-size: 16px; font-style: italic; margin: 6px 0 0; }
    .title-rule { border: none; border-top: 3px solid #186faf; margin: 18px 60px 0; }
    .cols { display: flex; gap: 30px; padding: 0 40px 20px; align-items: flex-start; }
    .footer { text-align: center; color: #8a97a6; font-size: 14px; font-style: italic;
      padding: 20px 0 34px; border-top: 1px solid #d7dee6; margin: 10px 60px 0; }
    """
    from datetime import datetime
    month_year = datetime.now().strftime("%B %Y")
    body = f'''
    <div class="page-title">
      <h1>RAAF &mdash; Supported Workflows</h1>
      <p>Resume Assessment Automation Framework &middot; Archtekt Consulting Inc.</p>
    </div>
    <hr class="title-rule">
    <div class="cols">{cols_html}</div>
    <div class="footer">RAAF Workflow Diagram &middot; Archtekt Consulting Inc. &middot; Updated {month_year}</div>
    '''
    total_width = col_width * len(col_defs) + 30 * (len(col_defs) - 1) + 80
    return f"<html><head><style>{SHARED_CSS}{extra_css}</style></head><body>{body}</body></html>", total_width


def find_chrome():
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    sys.exit("No Chrome/Chromium install found. Install one or edit CHROME_CANDIDATES.")


def render_and_crop(chrome, html, width, out_stem, work_dir, render_height=3300, pad=40):
    """Render html at (width, render_height), then auto-crop to content bounds."""
    html_path = work_dir / f"{out_stem}.html"
    raw_path = work_dir / f"{out_stem}_raw.png"
    html_path.write_text(html)
    subprocess.run([
        chrome, "--headless=new", "--disable-gpu",
        f"--screenshot={raw_path}",
        f"--window-size={width},{render_height}",
        "--force-device-scale-factor=1",
        f"file://{html_path}"
    ], check=True, capture_output=True)

    im = Image.open(raw_path).convert("RGB")
    arr = np.array(im)
    nonbg = np.any(np.abs(arr.astype(int) - np.array(PAGE_BG_RGB)) > 3, axis=2)
    rows = np.where(nonbg.any(axis=1))[0]
    content_end = int(rows.max()) + pad if len(rows) else render_height
    cropped = im.crop((0, 0, width, min(content_end, render_height)))

    html_path.unlink()
    raw_path.unlink()
    return cropped


def main():
    chrome = find_chrome()
    col_defs = [
        ("A", 'WORKFLOW A &middot; PCR-Integrated <span class="badge">Recommended</span>',
         WORKFLOW_A_STEPS, panel_scoring(THEMES["A"]["header"])),
        ("B", "WORKFLOW B &middot; Manual / Direct Upload",
         WORKFLOW_B_STEPS, panel_tiers(THEMES["B"]["header"])),
        ("C", "WORKFLOW C &middot; Candidate Repository Search",
         WORKFLOW_C_STEPS, panel_legend(THEMES["C"]["header"])),
    ]
    filenames = {
        "A": "RAAF_Workflow_A_PCR_Integrated.png",
        "B": "RAAF_Workflow_B_Manual_Upload.png",
        "C": "RAAF_Workflow_C_Repository_Search.png",
    }

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        for key, title_html, steps, panel_html in col_defs:
            html, w = build_column(key, title_html, steps, panel_html)
            img = render_and_crop(chrome, html, w, f"col_{key}", work_dir)
            for out_dir in OUT_DIRS:
                img.save(out_dir / filenames[key])
            print(f"Wrote {filenames[key]} ({img.size[0]}x{img.size[1]})")

        html_combined, w_combined = build_combined(col_defs)
        img_combined = render_and_crop(chrome, html_combined, w_combined, "combined", work_dir)
        img_combined.save(REPO_ROOT / "web" / "static" / "images" / "workflow_diagram.png")
        img_combined.save(REPO_ROOT / "docs" / "RAAF_Workflow_Diagram.png")
        print(f"Wrote workflow_diagram.png / RAAF_Workflow_Diagram.png "
              f"({img_combined.size[0]}x{img_combined.size[1]})")


if __name__ == "__main__":
    main()
