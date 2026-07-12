from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


def safe_file_part(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch not in '<>:"/\\|?*')
    return " ".join(cleaned.split()).strip()


def _set_fit_open_action(c: canvas.Canvas) -> None:
    destination = c.bookmarkPage("fit-page", fit="Fit")
    c._doc.Catalog.OpenAction = destination


def _draw_full_bleed_page(
    c: canvas.Canvas,
    image_path: Path,
    overlay_image_path: Path | None = None,
    overlay_position: str = "top-right",
    overlay_width: float = 250,
) -> None:
    page_width, page_height = landscape(letter)
    with Image.open(image_path) as image:
        width, height = image.size
    scale = max(page_width / width, page_height / height)
    draw_width = width * scale
    draw_height = height * scale
    x = (page_width - draw_width) / 2
    y = (page_height - draw_height) / 2

    c.drawImage(str(image_path), x, y, width=draw_width, height=draw_height)
    if overlay_image_path and overlay_image_path.exists():
        with Image.open(overlay_image_path) as overlay:
            overlay_pixel_width, overlay_pixel_height = overlay.size
        overlay_height = overlay_width * (overlay_pixel_height / overlay_pixel_width)
        margin = 18
        overlay_x = page_width - overlay_width - margin
        if overlay_position == "bottom-right":
            overlay_y = margin + 18
        else:
            overlay_y = page_height - overlay_height - margin
        c.drawImage(
            str(overlay_image_path),
            overlay_x,
            overlay_y,
            width=overlay_width,
            height=overlay_height,
            preserveAspectRatio=True,
            mask="auto",
        )


def image_to_full_bleed_pdf(
    image_path: Path,
    pdf_path: Path,
    overlay_image_path: Path | None = None,
    overlay_position: str = "top-right",
    overlay_width: float = 250,
) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(pdf_path), pagesize=landscape(letter))
    _set_fit_open_action(c)
    _draw_full_bleed_page(c, image_path, overlay_image_path, overlay_position, overlay_width)
    c.showPage()
    c.save()


def images_to_full_bleed_pdf(
    image_pages: Sequence[tuple[Path, Path | None]],
    pdf_path: Path,
) -> None:
    if not image_pages:
        raise ValueError("At least one image page is required")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(pdf_path), pagesize=landscape(letter))
    _set_fit_open_action(c)
    for image_path, overlay_image_path in image_pages:
        _draw_full_bleed_page(c, image_path, overlay_image_path)
        c.showPage()
    c.save()


def image_to_fit_pdf(image_path: Path, pdf_path: Path) -> None:
    page_width, page_height = landscape(letter)
    with Image.open(image_path) as image:
        width, height = image.size
    scale = min(page_width / width, page_height / height)
    draw_width = width * scale
    draw_height = height * scale
    x = (page_width - draw_width) / 2
    y = (page_height - draw_height) / 2

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(pdf_path), pagesize=landscape(letter))
    _set_fit_open_action(c)
    c.drawImage(str(image_path), x, y, width=draw_width, height=draw_height)
    c.showPage()
    c.save()
