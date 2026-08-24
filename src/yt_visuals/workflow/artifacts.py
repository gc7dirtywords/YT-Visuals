from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def write_json(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(data, encoding="utf-8")
    return file_sha256(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_video_frames(
    source: Path,
    destination_dir: Path,
    *,
    duration_ms: int,
    root: Path,
) -> list[dict[str, Any]]:
    if duration_ms <= 0:
        raise RuntimeError("video duration is unavailable")
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("ffmpeg was not found on PATH")
    destination_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for index, fraction in enumerate((0.10, 0.50, 0.90), start=1):
        timestamp_ms = min(duration_ms - 1, max(0, round(duration_ms * fraction)))
        output = destination_dir / f"frame-{index}-{timestamp_ms}ms.jpg"
        completed = subprocess.run(
            [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp_ms / 1000:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            raise RuntimeError(
                f"representative frame extraction failed at {timestamp_ms}ms: "
                f"{completed.stderr.strip()[:300]}"
            )
        frame_hash = file_sha256(output)
        if frame_hash in seen_hashes:
            output.unlink(missing_ok=True)
            continue
        seen_hashes.add(frame_hash)
        frames.append(
            {
                "relative_path": output.relative_to(root).as_posix(),
                "timestamp_ms": timestamp_ms,
            }
        )
    if not frames:
        raise RuntimeError("representative video frames were all unusable")
    return frames


def render_storyboard(report: dict[str, Any], destination: Path, *, root: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(destination), pagesize=letter, invariant=1, pageCompression=0)
    width, height = letter
    summary = report["summary"]

    pdf.setTitle(f"YT-Visuals Storyboard - {report['story']['title']}")
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(54, height - 72, "YT-Visuals Candidate Storyboard")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(54, height - 112, report["story"]["title"][:70])
    pdf.setFont("Helvetica", 10)
    lines = [
        f"Story ID: {report['story']['story_id']}",
        f"Request revision: {report['request_revision']}",
        f"Package iteration: {report['iteration']}",
        f"Package ID: {report['package_id']}",
        "Review threshold: 90 alignment",
        f"Review required: {summary['review_required']}",
        f"Accepted / locked: {summary['locked_accepted']}",
        f"Blocked - no candidate: {summary['blocked_no_candidate']}",
        f"Blocked - missing locked asset: {summary['blocked_missing']}",
    ]
    y = height - 150
    for line in lines:
        pdf.drawString(54, y, line)
        y -= 17
    pdf.setFillColor(colors.HexColor("#334155"))
    _wrapped_text(
        pdf,
        "Legend: IMAGE / VIDEO identifies media type. LICENSE: UNKNOWN requires later resolution. "
        "STATIC VIDEO LIMITATION: motion and camera movement are not fully reviewable.",
        54,
        y - 22,
        500,
        12,
    )
    pdf.setFillColor(colors.black)
    pdf.showPage()
    pages = 1

    for beat in report["beats"]:
        pages += 1
        _render_beat_page(pdf, beat, root=root, page_width=width, page_height=height)
        pdf.showPage()
    pdf.save()
    return pages


def _render_beat_page(
    pdf: canvas.Canvas,
    beat: dict[str, Any],
    *,
    root: Path,
    page_width: float,
    page_height: float,
) -> None:
    snapshot = beat["request_snapshot"]
    state = beat["state"]
    banner = {
        "review_required": ("REVIEW REQUIRED", colors.HexColor("#1d4ed8")),
        "locked_accepted": ("ACCEPTED / LOCKED", colors.HexColor("#15803d")),
        "blocked_no_candidate": ("NO LOCAL CANDIDATE - GUIDANCE REQUESTED", colors.HexColor("#b45309")),
        "blocked_missing": ("LOCKED ASSET MISSING", colors.HexColor("#b91c1c")),
    }[state]
    pdf.setFillColor(banner[1])
    pdf.rect(0, page_height - 48, page_width, 48, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(42, page_height - 30, banner[0])
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(42, page_height - 70, f"Beat {beat['sequence']}: {beat['beat_id']}")
    timing = snapshot.get("timing")
    if timing:
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(
            page_width - 42,
            page_height - 70,
            f"{timing['start_ms'] / 1000:.1f}s - {timing['end_ms'] / 1000:.1f}s ({timing['precision']})",
        )
    y = page_height - 92
    y = _labeled_wrapped(pdf, "Narration", snapshot["narration_context"], 42, y, 528)
    y = _labeled_wrapped(pdf, "Requested visual", snapshot["desired_visual"]["summary"], 42, y - 4, 528)
    y = _labeled_wrapped(pdf, "Must have", "; ".join(snapshot["must_have"]) or "None specified", 42, y - 4, 528)
    y = _labeled_wrapped(pdf, "Avoid", "; ".join(snapshot["avoid"]) or "None specified", 42, y - 4, 528)
    if state == "blocked_no_candidate":
        search_context = "; ".join(
            directive["query"] for directive in snapshot["search_directives"]
        )
        y = _labeled_wrapped(pdf, "Search context", search_context, 42, y - 4, 528)

    candidates = beat["candidates"]
    if candidates:
        candidate = candidates[0]
        visuals = candidate["storyboard_visuals"]
        paths = [item["relative_path"] for item in visuals["video_frames"]]
        if not paths:
            paths = [visuals["poster_frame_path"]]
        image_top = min(y - 12, 490)
        image_bottom = 155
        if len(paths) == 1:
            _draw_aspect_fit(pdf, root / paths[0], 42, image_bottom, 528, image_top - image_bottom)
        else:
            cell_width = (528 - 12) / len(paths)
            for index, path in enumerate(paths):
                x = 42 + index * (cell_width + 6)
                _draw_aspect_fit(pdf, root / path, x, image_bottom + 18, cell_width, image_top - image_bottom - 18)
                timestamp = visuals["video_frames"][index]["timestamp_ms"]
                pdf.setFont("Helvetica", 8)
                pdf.drawCentredString(x + cell_width / 2, image_bottom + 5, f"{timestamp / 1000:.2f}s")
        pdf.setFont("Helvetica-Bold", 9)
        duration = candidate["technical"]["duration_ms"]
        media = candidate["media_type"].upper()
        media_line = media + (f" | Duration {duration / 1000:.2f}s" if duration is not None else "")
        pdf.drawString(42, 132, media_line)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(42, 116, f"Candidate {candidate['candidate_id']} | Asset {candidate['asset_id']}")
        provenance = candidate["provenance"]
        source = provenance["provider"] or provenance["origin"]
        creator = provenance["creator_name"] or "creator unknown"
        pdf.drawString(42, 101, f"{candidate['catalog_status']} | {source} | {creator}")
        usage = candidate["usage"]
        pdf.drawString(42, 86, f"Prior uses: {usage['usage_count']}")
        if candidate["license"]["status"] == "unknown":
            pdf.setFillColor(colors.HexColor("#b45309"))
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawRightString(page_width - 42, 86, "LICENSE: UNKNOWN")
            pdf.setFillColor(colors.black)
        if beat.get("lock"):
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawRightString(
                page_width - 42,
                116,
                f"Accepted alignment: {beat['lock']['alignment_score']}",
            )
    else:
        reason = beat.get("blocked_reason") or {}
        pdf.setFillColor(colors.HexColor("#f8fafc"))
        pdf.rect(42, 260, 528, 180, fill=1, stroke=1)
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawCentredString(page_width / 2, 390, reason.get("code", "blocked").replace("_", " ").upper())
        pdf.setFont("Helvetica", 10)
        _wrapped_text(pdf, reason.get("explanation", ""), 70, 355, 472, 14)


def _draw_aspect_fit(
    pdf: canvas.Canvas, path: Path, x: float, y: float, width: float, height: float
) -> None:
    with Image.open(path) as image:
        image_width, image_height = image.size
    scale = min(width / image_width, height / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    draw_x = x + (width - draw_width) / 2
    draw_y = y + (height - draw_height) / 2
    pdf.drawImage(
        ImageReader(str(path)), draw_x, draw_y, draw_width, draw_height,
        preserveAspectRatio=True, anchor="c", mask="auto",
    )


def _labeled_wrapped(
    pdf: canvas.Canvas, label: str, value: str, x: float, y: float, width: float
) -> float:
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(x, y, f"{label}:")
    pdf.setFont("Helvetica", 8)
    return _wrapped_text(pdf, value, x + 80, y, width - 80, 10)


def _wrapped_text(
    pdf: canvas.Canvas, value: str, x: float, y: float, width: float, leading: float
) -> float:
    words = value.split()
    line = ""
    current_y = y
    for word in words:
        candidate = f"{line} {word}".strip()
        if pdf.stringWidth(candidate, "Helvetica", 8) <= width:
            line = candidate
            continue
        pdf.drawString(x, current_y, line)
        current_y -= leading
        line = word
    if line:
        pdf.drawString(x, current_y, line)
        current_y -= leading
    return current_y
