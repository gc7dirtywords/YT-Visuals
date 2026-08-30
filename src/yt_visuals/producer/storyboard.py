from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..workflow.artifacts import extract_video_frames


def render_producer_storyboard(
    workspace: dict[str, Any], destination: Path, *, root: Path
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(destination), pagesize=letter, invariant=1, pageCompression=0)
    page_width, page_height = letter
    pdf.setTitle(f"YT-Visuals Producer Storyboard - {workspace['title']}")
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(54, page_height - 76, "Producer Storyboard")
    pdf.setFont("Helvetica-Bold", 17)
    _wrapped(pdf, workspace["title"], 54, page_height - 116, 500, 19, font="Helvetica-Bold", size=17)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(54, page_height - 164, f"Story ID: {workspace['story_id']}")
    pdf.drawString(
        54,
        page_height - 184,
        f"Selected media: {workspace['selected']} of {workspace['total']} beats",
    )
    pdf.setFillColor(colors.HexColor("#475569"))
    _wrapped(
        pdf,
        "Producer selections for final human / ChatGPT sanity review. "
        "No alignment score or automated acceptance is implied.",
        54,
        page_height - 224,
        500,
        14,
    )
    pdf.setFillColor(colors.black)
    pdf.showPage()
    pages = 1
    temp_root = root / "Temp" / f"producer-storyboard-{uuid.uuid4()}"
    try:
        for beat in workspace["beats"]:
            pages += 1
            _render_beat(pdf, beat, root=root, temp_root=temp_root)
            pdf.showPage()
        pdf.save()
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return pages


def _render_beat(
    pdf: canvas.Canvas,
    beat: dict[str, Any],
    *,
    root: Path,
    temp_root: Path,
) -> None:
    width, height = letter
    selected = beat["selected"]
    pdf.setFillColor(colors.HexColor("#1e293b") if selected else colors.HexColor("#9a3412"))
    pdf.rect(0, height - 48, width, 48, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 15)
    state = "MEDIA SELECTED" if selected else "NO MEDIA SELECTED"
    pdf.drawString(42, height - 30, f"Beat {beat['sequence']}: {beat['beat_id']} — {state}")
    pdf.setFillColor(colors.black)
    spec = beat["specification"]
    y = height - 72
    y = _labeled(pdf, "Narration", spec["narration_context"], 42, y, 528)
    y = _labeled(pdf, "Desired visual", spec["desired_visual"], 42, y - 4, 528)
    y = _labeled(pdf, "Must have", "; ".join(spec["must_have"]) or "None", 42, y - 4, 528)
    y = _labeled(pdf, "Avoid", "; ".join(spec["avoid"]) or "None", 42, y - 4, 528)
    y = _labeled(
        pdf,
        "Requirement",
        f"{spec['media_preference']} / {spec['source_requirement']}",
        42,
        y - 4,
        528,
    )
    opportunities = spec.get("production_opportunities", [])
    if opportunities:
        text = " | ".join(
            f"{item['trigger']}: "
            + "; ".join(
                value
                for value in (item.get("sfx_suggestion"), item.get("edit_suggestion"))
                if value
            )
            for item in opportunities
        )
        y = _labeled(pdf, "Optional production", text, 42, y - 4, 528)
    recommendations = beat.get("sfx_recommendations", [])
    if recommendations:
        recommendation = recommendations[0]
        detail = recommendation.get("desired_sound", "")
        if recommendation.get("purpose"):
            detail += f" — {recommendation['purpose']}"
        y = _labeled(pdf, "SFX recommendation", detail, 42, y - 4, 528)
    selected_sfx = beat.get("selected_sfx")
    if selected_sfx:
        license_record = selected_sfx["license"]
        detail = (
            f"{selected_sfx.get('title') or ('Asset ' + str(selected_sfx['asset_id']))}"
            f" | {selected_sfx.get('sfx_kind') or 'unclassified'}"
            f" | License: {license_record['name'] or 'UNKNOWN'}"
        )
        y = _labeled(pdf, "Selected SFX", detail, 42, y - 4, 528)

    if selected:
        paths: list[Path]
        source_path = root / selected["current_location"]
        if selected["media_type"] == "video" and selected["duration_ms"]:
            frames = extract_video_frames(
                source_path,
                temp_root / beat["beat_id"],
                duration_ms=selected["duration_ms"],
                root=root,
            )
            paths = [root / item["relative_path"] for item in frames]
        elif selected["media_type"] == "video":
            paths = []
        else:
            paths = [source_path]
        image_top = min(y - 12, 475)
        image_bottom = 155
        if not paths:
            pdf.setFillColor(colors.HexColor("#e2e8f0"))
            pdf.rect(42, image_bottom, 528, image_top - image_bottom, fill=1, stroke=1)
            pdf.setFillColor(colors.HexColor("#334155"))
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawCentredString(
                width / 2,
                (image_top + image_bottom) / 2,
                "VIDEO PREVIEW UNAVAILABLE",
            )
            pdf.setFillColor(colors.black)
        elif len(paths) == 1:
            _draw_fit(pdf, paths[0], 42, image_bottom, 528, image_top - image_bottom)
        else:
            cell = (528 - 12) / len(paths)
            for index, path in enumerate(paths):
                _draw_fit(pdf, path, 42 + index * (cell + 6), image_bottom, cell, image_top - image_bottom)
        source = selected["source"]
        license_record = selected["license"]
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(42, 130, f"{selected['media_type'].upper()} | Asset {selected['asset_id']}")
        pdf.setFont("Helvetica", 8)
        pdf.drawString(
            42,
            114,
            f"Source: {source['provider'] or source['origin']} | Creator: {source['creator_name'] or 'unknown'}",
        )
        pdf.drawString(
            42,
            98,
            f"License: {license_record['name'] or 'UNKNOWN'}",
        )
    else:
        pdf.setFillColor(colors.HexColor("#fff7ed"))
        pdf.rect(42, 235, 528, 210, fill=1, stroke=1)
        pdf.setFillColor(colors.HexColor("#9a3412"))
        pdf.setFont("Helvetica-Bold", 20)
        pdf.drawCentredString(width / 2, 350, "NO MEDIA SELECTED")
        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(width / 2, 325, "Producer selection is still required for this beat.")
        pdf.setFillColor(colors.black)


def _draw_fit(
    pdf: canvas.Canvas, path: Path, x: float, y: float, width: float, height: float
) -> None:
    with Image.open(path) as image:
        image_width, image_height = image.size
    scale = min(width / image_width, height / image_height)
    draw_width, draw_height = image_width * scale, image_height * scale
    pdf.drawImage(
        ImageReader(str(path)),
        x + (width - draw_width) / 2,
        y + (height - draw_height) / 2,
        draw_width,
        draw_height,
        preserveAspectRatio=True,
        mask="auto",
    )


def _labeled(
    pdf: canvas.Canvas, label: str, value: str, x: float, y: float, width: float
) -> float:
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(x, y, f"{label}:")
    return _wrapped(pdf, value, x + 92, y, width - 92, 10)


def _wrapped(
    pdf: canvas.Canvas,
    value: str,
    x: float,
    y: float,
    width: float,
    leading: float,
    *,
    font: str = "Helvetica",
    size: int = 8,
) -> float:
    pdf.setFont(font, size)
    words = value.split()
    line = ""
    current_y = y
    for word in words:
        candidate = f"{line} {word}".strip()
        if pdf.stringWidth(candidate, font, size) <= width:
            line = candidate
            continue
        pdf.drawString(x, current_y, line)
        current_y -= leading
        line = word
    if line:
        pdf.drawString(x, current_y, line)
    return current_y - leading
