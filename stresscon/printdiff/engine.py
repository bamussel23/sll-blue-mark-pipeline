"""
PrintDiff Engine v2.0 — SideLineLabs LLC
Blueprint revision detection using anaglyph pixel-diff.

Designed as the processing backend for the PrintDiff Power App.
Can run as: CLI tool, Azure Function, or local HTTP service.

Replaces: Bluebeam Revu ($5,200/yr for 30 users)
Cost: $0
"""

from __future__ import annotations

import json
import os
import sys
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image, ImageChops, ImageOps, ImageFilter
import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PageDiff:
    """Result of comparing a single page between two PDF versions."""
    page_number: int
    change_percent: float          # 0.0–100.0
    pixels_changed: int
    pixels_total: int
    has_changes: bool
    diff_image_path: Optional[str] = None
    old_image_path: Optional[str] = None
    new_image_path: Optional[str] = None
    heatmap_path: Optional[str] = None
    severity: str = "none"         # none | minor | moderate | major


@dataclass
class DiffReport:
    """Full comparison report between two PDF versions."""
    old_pdf: str
    new_pdf: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    old_hash: str = ""
    new_hash: str = ""
    old_page_count: int = 0
    new_page_count: int = 0
    pages: list[PageDiff] = field(default_factory=list)
    total_change_percent: float = 0.0
    pages_with_changes: int = 0
    most_changed_page: int = 0
    severity: str = "none"         # none | minor | moderate | major
    added_pages: list[int] = field(default_factory=list)
    removed_pages: list[int] = field(default_factory=list)
    dpi: int = 150
    threshold: int = 30
    output_dir: str = ""

    def to_json(self, path: Optional[str] = None) -> str:
        """Serialize report to JSON."""
        data = asdict(self)
        json_str = json.dumps(data, indent=2)
        if path:
            Path(path).write_text(json_str)
        return json_str


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def file_hash(path: str) -> str:
    """SHA-256 hash of a file for integrity tracking."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def render_page(pdf_path: str, page_num: int, dpi: int = 150) -> Optional[Image.Image]:
    """Render a single PDF page to a PIL Image."""
    try:
        doc = fitz.open(pdf_path)
        if page_num >= len(doc):
            return None
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return img
    except Exception as e:
        print(f"  ✗ Error rendering {pdf_path} page {page_num}: {e}")
        return None


def create_anaglyph(img_old: Image.Image, img_new: Image.Image) -> Image.Image:
    """
    Create anaglyph overlay — the core PrintDiff visualization.

    Old version → Red channel
    New version → Cyan channel (Blue + Green)

    Result reads as:
    - Black/Grey = unchanged (lines overlap)
    - Bright Red = deleted (only in old)
    - Bright Cyan = added (only in new)
    """
    gray_old = ImageOps.grayscale(img_old)
    gray_new = ImageOps.grayscale(img_new)

    colored_old = ImageOps.colorize(gray_old, black="red", white="white")
    colored_new = ImageOps.colorize(gray_new, black="cyan", white="white")

    return ImageChops.multiply(colored_old, colored_new)


def create_heatmap(img_old: Image.Image, img_new: Image.Image, threshold: int = 30) -> Image.Image:
    """
    Create a change heatmap highlighting regions with differences.

    Areas with changes glow yellow/orange on a dark background.
    Useful for quickly spotting moved bolt holes, changed dimensions, etc.
    """
    gray_old = ImageOps.grayscale(img_old)
    gray_new = ImageOps.grayscale(img_new)

    arr_old = np.array(gray_old, dtype=np.float32)
    arr_new = np.array(gray_new, dtype=np.float32)

    diff = np.abs(arr_old - arr_new)

    # Apply threshold — ignore minor rendering artifacts
    diff[diff < threshold] = 0
    diff = np.clip(diff * 3, 0, 255).astype(np.uint8)

    # Blur for region-level visibility
    heatmap_gray = Image.fromarray(diff)
    heatmap_gray = heatmap_gray.filter(ImageFilter.GaussianBlur(radius=5))

    # Colorize: black → transparent-ish, white → hot orange
    heatmap = ImageOps.colorize(heatmap_gray, black="#1a1a2e", white="#f5c518")

    return heatmap


def calculate_change_metrics(
    img_old: Image.Image,
    img_new: Image.Image,
    threshold: int = 30,
) -> tuple[float, int, int]:
    """
    Calculate percentage of pixels that changed between versions.

    Returns: (change_percent, pixels_changed, pixels_total)
    """
    gray_old = np.array(ImageOps.grayscale(img_old), dtype=np.float32)
    gray_new = np.array(ImageOps.grayscale(img_new), dtype=np.float32)

    diff = np.abs(gray_old - gray_new)
    changed = int(np.sum(diff > threshold))
    total = int(gray_old.size)
    percent = round((changed / total) * 100, 2) if total > 0 else 0.0

    return percent, changed, total


def classify_severity(change_percent: float) -> str:
    """Classify change severity for QA prioritization."""
    if change_percent == 0:
        return "none"
    elif change_percent < 1.0:
        return "minor"
    elif change_percent < 5.0:
        return "moderate"
    else:
        return "major"


# ---------------------------------------------------------------------------
# Main comparison function
# ---------------------------------------------------------------------------

def compare_blueprints(
    old_pdf: str,
    new_pdf: str,
    output_dir: str = "diff_reports",
    dpi: int = 150,
    threshold: int = 30,
    generate_heatmaps: bool = True,
    save_originals: bool = True,
) -> DiffReport:
    """
    Compare two blueprint PDFs and generate a full diff report.

    Args:
        old_pdf: Path to the previous version PDF.
        new_pdf: Path to the new version PDF.
        output_dir: Directory for output images and report.
        dpi: Render resolution (150 = fast, 300 = print quality).
        threshold: Pixel difference threshold (0–255). Higher = ignore minor differences.
        generate_heatmaps: Also generate change heatmap images.
        save_originals: Save rendered originals alongside diffs.

    Returns:
        DiffReport with per-page metrics and paths to generated images.
    """
    os.makedirs(output_dir, exist_ok=True)

    report = DiffReport(
        old_pdf=os.path.basename(old_pdf),
        new_pdf=os.path.basename(new_pdf),
        old_hash=file_hash(old_pdf),
        new_hash=file_hash(new_pdf),
        dpi=dpi,
        threshold=threshold,
        output_dir=output_dir,
    )

    doc_old = fitz.open(old_pdf)
    doc_new = fitz.open(new_pdf)
    report.old_page_count = len(doc_old)
    report.new_page_count = len(doc_new)
    doc_old.close()
    doc_new.close()

    common_pages = min(report.old_page_count, report.new_page_count)

    # Flag added/removed pages
    if report.new_page_count > report.old_page_count:
        report.added_pages = list(range(report.old_page_count + 1, report.new_page_count + 1))
    elif report.old_page_count > report.new_page_count:
        report.removed_pages = list(range(report.new_page_count + 1, report.old_page_count + 1))

    print(f"┌─ PrintDiff v2.0 — SideLineLabs")
    print(f"│  Old: {report.old_pdf} ({report.old_page_count} pages)")
    print(f"│  New: {report.new_pdf} ({report.new_page_count} pages)")
    print(f"│  DPI: {dpi}  Threshold: {threshold}")
    print(f"│  Comparing {common_pages} common pages...")
    print(f"├──────────────────────────────────")

    total_changed = 0
    total_pixels = 0
    max_change = 0.0
    max_change_page = 0

    for i in range(common_pages):
        page_num = i + 1
        img_old = render_page(old_pdf, i, dpi)
        img_new = render_page(new_pdf, i, dpi)

        if img_old is None or img_new is None:
            print(f"│  Page {page_num}: ✗ render failed")
            continue

        # Normalize sizes if sheets differ slightly
        if img_old.size != img_new.size:
            img_new = img_new.resize(img_old.size, Image.LANCZOS)

        # Calculate metrics
        pct, changed, total = calculate_change_metrics(img_old, img_new, threshold)
        severity = classify_severity(pct)
        total_changed += changed
        total_pixels += total

        if pct > max_change:
            max_change = pct
            max_change_page = page_num

        page_diff = PageDiff(
            page_number=page_num,
            change_percent=pct,
            pixels_changed=changed,
            pixels_total=total,
            has_changes=pct > 0,
            severity=severity,
        )

        # Generate anaglyph diff image
        diff_img = create_anaglyph(img_old, img_new)
        diff_path = os.path.join(output_dir, f"diff_page_{page_num}.png")
        diff_img.save(diff_path, optimize=True)
        page_diff.diff_image_path = diff_path

        # Generate heatmap
        if generate_heatmaps and pct > 0:
            heatmap = create_heatmap(img_old, img_new, threshold)
            heat_path = os.path.join(output_dir, f"heat_page_{page_num}.png")
            heatmap.save(heat_path, optimize=True)
            page_diff.heatmap_path = heat_path

        # Save originals for side-by-side
        if save_originals:
            old_path = os.path.join(output_dir, f"old_page_{page_num}.png")
            new_path = os.path.join(output_dir, f"new_page_{page_num}.png")
            img_old.save(old_path, optimize=True)
            img_new.save(new_path, optimize=True)
            page_diff.old_image_path = old_path
            page_diff.new_image_path = new_path

        # Status indicator
        icon = "●" if severity == "major" else "◑" if severity == "moderate" else "○" if severity == "minor" else "·"
        print(f"│  Page {page_num:>3}: {icon} {pct:>6.2f}% changed  [{severity}]")

        report.pages.append(page_diff)

    # Summary
    report.total_change_percent = round((total_changed / total_pixels) * 100, 2) if total_pixels > 0 else 0.0
    report.pages_with_changes = sum(1 for p in report.pages if p.has_changes)
    report.most_changed_page = max_change_page
    report.severity = classify_severity(report.total_change_percent)

    print(f"├──────────────────────────────────")
    print(f"│  Total change: {report.total_change_percent}%")
    print(f"│  Pages with changes: {report.pages_with_changes}/{common_pages}")
    if max_change_page:
        print(f"│  Most changed: Page {max_change_page} ({max_change:.2f}%)")
    if report.added_pages:
        print(f"│  Added pages: {report.added_pages}")
    if report.removed_pages:
        print(f"│  Removed pages: {report.removed_pages}")
    print(f"└──────────────────────────────────")

    # Save JSON report
    report_path = os.path.join(output_dir, "report.json")
    report.to_json(report_path)
    print(f"\n  Report saved: {report_path}")

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI interface for PrintDiff."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="printdiff",
        description="PrintDiff — Blueprint revision detection by SideLineLabs",
    )
    parser.add_argument("old_pdf", help="Path to previous version PDF")
    parser.add_argument("new_pdf", help="Path to new version PDF")
    parser.add_argument("-o", "--output", default="diff_reports", help="Output directory (default: diff_reports)")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI (default: 150, use 300 for print)")
    parser.add_argument("--threshold", type=int, default=30, help="Change threshold 0-255 (default: 30)")
    parser.add_argument("--no-heatmaps", action="store_true", help="Skip heatmap generation")
    parser.add_argument("--no-originals", action="store_true", help="Skip saving original renders")
    parser.add_argument("--json", action="store_true", help="Output report as JSON to stdout")

    args = parser.parse_args()

    if not os.path.exists(args.old_pdf):
        print(f"Error: {args.old_pdf} not found")
        sys.exit(1)
    if not os.path.exists(args.new_pdf):
        print(f"Error: {args.new_pdf} not found")
        sys.exit(1)

    report = compare_blueprints(
        old_pdf=args.old_pdf,
        new_pdf=args.new_pdf,
        output_dir=args.output,
        dpi=args.dpi,
        threshold=args.threshold,
        generate_heatmaps=not args.no_heatmaps,
        save_originals=not args.no_originals,
    )

    if args.json:
        print(report.to_json())


if __name__ == "__main__":
    main()
