"""Generate QR code labels for Stresscon machinery.

Outputs:
  - Individual PNG images per asset in data/qr_labels/
  - A printable PDF sheet with all labels at data/qr_labels/all_labels.pdf
"""

import os
import sys
from pathlib import Path

import qrcode
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from PIL import Image

ASSETS = {
    "CRN-01": "Overhead Crane #1",
    "CRN-02": "Overhead Crane #2",
    "CRN-03": "Gantry Crane",
    "CRN-04": "Jib Crane East",
    "CRN-05": "Jib Crane West",
    "MIX-01": "Batch Mixer Primary",
    "MIX-02": "Batch Mixer Secondary",
    "MIX-03": "Color Mixer",
    "FORM-01": "Double Tee Form A",
    "FORM-02": "Double Tee Form B",
    "FORM-03": "Wall Form #1",
    "FORM-04": "Beam Form #1",
    "BATCH-01": "Batch Plant Main",
    "BATCH-02": "Batch Plant Auxiliary",
}

# Layout: 3 columns x 5 rows per page
COLS = 3
ROWS = 5
LABEL_WIDTH = 2.5 * inch
LABEL_HEIGHT = 2.0 * inch
MARGIN_X = 0.5 * inch
MARGIN_Y = 0.5 * inch
QR_SIZE = 1.3 * inch


def generate_pngs(output_dir: Path) -> dict[str, Path]:
    """Generate individual QR code PNG files for each asset."""
    paths = {}
    for asset_id, name in ASSETS.items():
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(asset_id)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        png_path = output_dir / f"{asset_id}.png"
        img.save(str(png_path))
        paths[asset_id] = png_path
    return paths


def generate_pdf(output_dir: Path, png_paths: dict[str, Path]):
    """Generate a printable PDF sheet with all QR labels."""
    pdf_path = output_dir / "all_labels.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=LETTER)
    page_w, page_h = LETTER

    items = list(ASSETS.items())
    per_page = COLS * ROWS
    total_pages = (len(items) + per_page - 1) // per_page

    for page in range(total_pages):
        if page > 0:
            c.showPage()

        start = page * per_page
        page_items = items[start:start + per_page]

        for idx, (asset_id, name) in enumerate(page_items):
            col = idx % COLS
            row = idx // COLS

            x = MARGIN_X + col * LABEL_WIDTH
            y = page_h - MARGIN_Y - (row + 1) * LABEL_HEIGHT

            # Draw label border
            c.setStrokeColorRGB(0.7, 0.7, 0.7)
            c.setLineWidth(0.5)
            c.rect(x, y, LABEL_WIDTH, LABEL_HEIGHT)

            # Draw QR code image
            qr_x = x + (LABEL_WIDTH - QR_SIZE) / 2
            qr_y = y + 0.4 * inch
            png_path = png_paths[asset_id]
            c.drawImage(str(png_path), qr_x, qr_y, QR_SIZE, QR_SIZE)

            # Asset ID (bold, larger)
            c.setFont("Helvetica-Bold", 11)
            text_x = x + LABEL_WIDTH / 2
            c.drawCentredString(text_x, y + 0.22 * inch, asset_id)

            # Equipment name (smaller)
            c.setFont("Helvetica", 8)
            c.drawCentredString(text_x, y + 0.08 * inch, name)

    c.save()
    return pdf_path


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    output_dir = project_root / "data" / "qr_labels"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating QR codes for {len(ASSETS)} assets...")
    png_paths = generate_pngs(output_dir)
    for asset_id, path in png_paths.items():
        print(f"  {asset_id}: {path.name}")

    print(f"\nGenerating printable PDF...")
    pdf_path = generate_pdf(output_dir, png_paths)
    print(f"  {pdf_path.name}")

    print(f"\nAll files saved to: {output_dir}")


if __name__ == "__main__":
    main()
