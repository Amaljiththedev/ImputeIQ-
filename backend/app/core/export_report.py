"""
export_report.py

Generates a beautiful PDF report documenting the synthetic missingness
injected into the dataset, the statistical diagnosis results, and visualizations.
"""

from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
from fpdf import FPDF

# ---------------------------------------------------------------------------
# Configuration & Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
MANIFEST_PATH = SYNTHETIC_DIR / "manifest.json"
DIAGNOSIS_PATH = SYNTHETIC_DIR / "diagnosis_report.json"
OUTPUT_PDF_PATH = DATA_DIR / "missingness_report.pdf"
TEMP_IMAGE_PATH = SYNTHETIC_DIR / "temp_accuracy_plot.png"


# ---------------------------------------------------------------------------
# PDF Generator Class
# ---------------------------------------------------------------------------

class MissingnessPDF(FPDF):
    def header(self):
        # Premium Slate Blue banner header
        self.set_fill_color(38, 76, 114)
        self.rect(0, 0, 210, 15, 'F')
        self.set_y(2)
        self.set_text_color(255, 255, 255)
        self.set_font('helvetica', 'B', 10)
        self.cell(0, 10, '  MISSING DATA PIPELINE  |  RESEARCH & METHODOLOGY REPORT', align='L')
        self.set_text_color(0, 0, 0)
        self.set_y(20)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')


# ---------------------------------------------------------------------------
# Visualization Generator
# ---------------------------------------------------------------------------

def generate_visualizations(report_data: dict) -> Path | None:
    """Generates a bar plot showing accuracy by mechanism and returns path."""
    try:
        mechs = []
        accuracies = []
        
        for mech, data in report_data["accuracy_by_mechanism"].items():
            mechs.append(mech)
            accuracies.append(data["pct"])

        # Styled plot matching slate theme
        plt.figure(figsize=(6, 3))
        bars = plt.bar(mechs, accuracies, color=["#4A7C59", "#264C72", "#C05621"], width=0.5, edgecolor="#2d3748", linewidth=0.8)
        
        plt.title("Diagnosis Accuracy by Missingness Mechanism", fontsize=11, fontweight="bold", pad=12, color="#2d3748")
        plt.xlabel("Mechanism", fontsize=9, fontweight="bold", color="#4a5568")
        plt.ylabel("Accuracy (%)", fontsize=9, fontweight="bold", color="#4a5568")
        plt.ylim(0, 110)
        plt.grid(axis='y', linestyle='--', alpha=0.5)

        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2.0, yval + 3, f"{yval:.1f}%", ha='center', va='bottom', fontsize=8, fontweight="bold")

        plt.tight_layout()
        plt.savefig(TEMP_IMAGE_PATH, dpi=300)
        plt.close()
        return TEMP_IMAGE_PATH
    except Exception as e:
        print(f"Failed to generate plot: {e}")
        return None


# ---------------------------------------------------------------------------
# Main PDF Orchestrator
# ---------------------------------------------------------------------------

def main() -> None:
    if not MANIFEST_PATH.exists() or not DIAGNOSIS_PATH.exists():
        print("Error: Missing manifest.json or diagnosis_report.json. Make sure to run both scripts first.")
        return

    # Load configurations and reports
    manifest = json.loads(MANIFEST_PATH.read_text())
    diagnosis = json.loads(DIAGNOSIS_PATH.read_text())

    # Generate the accuracy plot image
    plot_img = generate_visualizations(diagnosis)

    # Initialize FPDF
    pdf = MissingnessPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Title & Metadata
    pdf.set_font('helvetica', 'B', 22)
    pdf.set_text_color(38, 76, 114)
    pdf.cell(0, 15, 'Missingness Injection & Diagnosis', ln=True)
    pdf.set_font('helvetica', '', 10)
    pdf.set_text_color(102, 102, 102)
    pdf.cell(0, 5, f"Source dataset: {Path(manifest['source_file']).name}  |  Shape: {manifest['source_shape']}", ln=True)
    pdf.cell(0, 5, f"Random seed: {manifest['random_seed']}  |  Significance level (alpha): {diagnosis['alpha']}", ln=True)
    pdf.ln(8)

    # Section 1: Executive Summary
    pdf.set_font('helvetica', 'B', 14)
    pdf.set_text_color(38, 76, 114)
    pdf.cell(0, 10, '1. Executive Summary', ln=True)
    pdf.set_font('helvetica', '', 10)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 5.5, (
        "This report outlines the injection of synthetic missingness into the ground-truth "
        "dataset and documents the statistical validation results. Missingness was injected using "
        "three primary mechanisms: Missing Completely At Random (MCAR), Missing At Random (MAR), "
        "and Missing Not At Random (MNAR) across three rates: 10%, 20%, and 30%.\n\n"
        "A three-part diagnosis pipeline was deployed to evaluate the datasets: Little's MCAR test, "
        "chi-square / Welch's t-test association checks (for MAR detection), and MNAR flagging by elimination. "
        f"The diagnostic pipeline correctly classified {diagnosis['n_correct']} out of {diagnosis['n_total']} datasets, "
        f"yielding an overall accuracy of {diagnosis['accuracy_pct']}%."
    ))
    pdf.ln(6)

    # Section 2: Datasets Generated (Table)
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 10, '2. Synthetic Datasets & Injection Manifest', ln=True)
    pdf.ln(2)

    # Table Header
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_fill_color(240, 244, 248)
    pdf.cell(50, 7, ' Output File', border=1, fill=True)
    pdf.cell(20, 7, ' Mechanism', border=1, fill=True, align='C')
    pdf.cell(30, 7, ' Target Column', border=1, fill=True, align='C')
    pdf.cell(30, 7, ' Driver Column', border=1, fill=True, align='C')
    pdf.cell(25, 7, ' Req. Rate', border=1, fill=True, align='C')
    pdf.cell(35, 7, ' Actual Missing (%)', border=1, fill=True, align='C')
    pdf.ln()

    # Table Body
    pdf.set_font('helvetica', '', 8.5)
    for entry in manifest["generated_files"]:
        pdf.cell(50, 6, f" {entry['output_file']}", border=1)
        pdf.cell(20, 6, f" {entry['mechanism']}", border=1, align='C')
        pdf.cell(30, 6, f" {entry['target_column']}", border=1, align='C')
        driver_str = entry['driver_column'] if entry['driver_column'] else "None"
        pdf.cell(30, 6, f" {driver_str}", border=1, align='C')
        pdf.cell(25, 6, f" {int(entry['requested_rate'] * 100)}%", border=1, align='C')
        pdf.cell(35, 6, f" {entry['actual_missing_count']} ({entry['actual_missing_pct']}%)", border=1, align='C')
        pdf.ln()

    pdf.ln(10)

    # Start page 2
    pdf.add_page()

    # Section 3: Diagnostic Results
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 10, '3. Diagnostic Pipeline & Statistical Validation', ln=True)
    pdf.ln(2)

    # Table Header
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_fill_color(240, 244, 248)
    pdf.cell(50, 7, ' Dataset', border=1, fill=True)
    pdf.cell(25, 7, ' Actual Mech.', border=1, fill=True, align='C')
    pdf.cell(25, 7, ' Diagnosed Mech.', border=1, fill=True, align='C')
    pdf.cell(25, 7, " Little's p-value", border=1, fill=True, align='C')
    pdf.cell(40, 7, ' Significant Drivers', border=1, fill=True)
    pdf.cell(25, 7, ' Status', border=1, fill=True, align='C')
    pdf.ln()

    # Table Body
    pdf.set_font('helvetica', '', 8.5)
    for r in diagnosis["results"]:
        pdf.cell(50, 6, f" {r['file']}", border=1)
        pdf.cell(25, 6, f" {r['actual_mechanism']}", border=1, align='C')
        pdf.cell(25, 6, f" {r['diagnosed_mechanism']}", border=1, align='C')
        littles_p_str = f" {r['littles_p_value']:.4f}" if r.get('littles_p_value') is not None else " N/A"
        pdf.cell(25, 6, littles_p_str, border=1, align='C')
        drivers_str = ", ".join(r['significant_drivers']) if r['significant_drivers'] else "None"
        pdf.cell(40, 6, f" {drivers_str}", border=1)
        
        status_text = "CORRECT" if r["correct"] else "INCORRECT"
        if r["correct"]:
            pdf.set_text_color(38, 115, 38)
        else:
            pdf.set_text_color(191, 38, 38)
        pdf.cell(25, 6, f" {status_text}", border=1, align='C')
        pdf.set_text_color(0, 0, 0)
        pdf.ln()

    pdf.ln(8)

    # Embed plot if it exists
    if plot_img and plot_img.exists():
        pdf.image(str(plot_img), x=35, y=pdf.get_y(), w=140)
        pdf.ln(70) # space for image

    # Section 4: Analytical Discussion
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(38, 76, 114)
    pdf.cell(0, 8, '4. Methodology Findings & Limitations Discussion', ln=True)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 5, (
        "1. Little's MCAR Test Limitation:\n"
        "Little's statistical test works solely on numeric variables. When missingness is driven by a categorical "
        "variable (such as 'smoking_status' in our MAR glucose datasets), Little's test yields a high p-value "
        "and falsely suggests the data is MCAR. Our association checks correctly override this and detect MAR.\n\n"
        "2. The MNAR Detection Caveat:\n"
        "By definition, MNAR indicates that missingness depends on the unobserved values themselves. "
        "It is mathematically impossible to positively prove MNAR using only observed data. "
        "Consequently, our pipeline diagnoses MNAR by elimination (e.g. when Little's test rejects MCAR, but no "
        "observed driver is identified). This explains the 0.0% direct diagnosis accuracy for MNAR: since MNAR "
        "has no observed drivers and Little's test fails to reject MCAR (retaining H0 due to small sample/distribution "
        "overlaps), the pipeline labels them as MCAR. This limitation is a valuable dissertation finding."
    ))

    # Save PDF
    pdf.output(str(OUTPUT_PDF_PATH))
    print(f"\nPDF Report generated successfully at: {OUTPUT_PDF_PATH.resolve()}")

    # Cleanup temp image
    if plot_img and plot_img.exists():
        plot_img.unlink()


if __name__ == "__main__":
    main()
