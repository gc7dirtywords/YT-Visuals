from __future__ import annotations

import json
import ipaddress
import secrets
import socket
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Callable

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from pydantic import ValidationError
from sqlalchemy import Engine
from werkzeug.serving import make_server

from ..config import Settings
from ..credentials import CredentialStore, CredentialStoreError
from ..database import initialize_database
from ..providers.errors import ProviderAuthenticationError, ProviderError
from ..providers.pexels import PexelsProvider
from .contracts import EditPlan, VisualPlan
from .service import ProducerWorkflowError, ProducerWorkflowService


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    service: ProducerWorkflowService | None = None,
    credential_store: CredentialStore | None = None,
    pexels_tester: Callable[[str], None] | None = None,
    path_opener: Callable[[str], Any] | None = None,
) -> Flask:
    settings = settings or Settings.load()
    owned_engine = engine is None
    engine = engine or initialize_database(settings)
    service = service or ProducerWorkflowService(settings, engine)
    credential_store = credential_store or CredentialStore()
    pexels_tester = pexels_tester or test_pexels_connection
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.config["MAX_CONTENT_LENGTH"] = max(
        settings.max_image_download_bytes,
        settings.max_video_download_bytes,
        settings.max_audio_download_bytes,
    )
    app.extensions["yt_visuals_engine"] = engine
    app.extensions["yt_visuals_engine_owned"] = owned_engine
    app.extensions["producer_service"] = service
    app.extensions["credential_store"] = credential_store

    @app.context_processor
    def integration_context() -> dict[str, Any]:
        return {"pexels_status": credential_store.pexels_status()}

    @app.get("/")
    def index() -> str:
        show_finished = request.args.get("show_finished") == "1"
        return render_template(
            "index.html",
            buckets=service.workspace_buckets(show_finished=show_finished),
            releases=service.list_releases(show_released=show_finished),
            show_finished=show_finished,
            show_import=request.args.get("import_plan") == "1",
        )

    @app.get("/releases/<release_id>")
    def release_detail(release_id: str) -> str:
        return render_template(
            "release.html",
            release=service.get_release(release_id),
            thumbnail_candidates=service.list_thumbnail_candidates(),
        )

    @app.post("/releases")
    def create_release():
        release = service.create_release(request.form.get("name", ""))
        flash("Video release created.", "success")
        return redirect(url_for("release_detail", release_id=release["id"]))

    @app.post("/releases/<release_id>/rename")
    def rename_release(release_id: str):
        service.rename_release(release_id, request.form.get("name", "")); flash("Video release renamed.", "success")
        return redirect(url_for("release_detail", release_id=release_id))

    @app.post("/releases/<release_id>/metadata")
    def update_release_metadata(release_id: str):
        service.update_release_metadata(
            release_id,
            status=request.form.get("status", ""),
            release_date=request.form.get("release_date") or None,
        )
        flash("Video release details updated.", "success")
        return redirect(url_for("release_detail", release_id=release_id))

    @app.post("/releases/<release_id>/delete")
    def delete_release(release_id: str):
        service.delete_release(release_id); flash("Empty video release deleted.", "success")
        return redirect(url_for("index"))

    @app.post("/releases/<release_id>/presentation")
    def revise_release_presentation(release_id: str):
        raw_thumbnail = request.form.get("thumbnail_asset_id", "").strip()
        try:
            thumbnail_asset_id = int(raw_thumbnail) if raw_thumbnail else None
        except ValueError as exc:
            raise ProducerWorkflowError("thumbnail asset ID must be a number") from exc
        service.create_release_presentation(
            release_id,
            public_title=request.form.get("public_title", ""),
            description=request.form.get("description"),
            thumbnail_asset_id=thumbnail_asset_id,
            change_note=request.form.get("change_note"),
        )
        flash("Public presentation revision saved.", "success")
        return redirect(url_for("release_detail", release_id=release_id))

    @app.post("/releases/<release_id>/presentation/title")
    def revise_release_title(release_id: str):
        service.revise_release_presentation(
            release_id,
            public_title=request.form.get("public_title", ""),
            change_note=request.form.get("change_note"),
        )
        flash("Public title revision saved.", "success")
        return redirect(url_for("release_detail", release_id=release_id))

    @app.post("/releases/<release_id>/presentation/description")
    def revise_release_description(release_id: str):
        service.revise_release_presentation(
            release_id,
            description=request.form.get("description", ""),
            change_note=request.form.get("change_note"),
        )
        flash("Description revision saved.", "success")
        return redirect(url_for("release_detail", release_id=release_id))

    @app.post("/releases/<release_id>/presentation/thumbnail")
    def revise_release_thumbnail(release_id: str):
        raw_thumbnail = request.form.get("thumbnail_asset_id", "").strip()
        try:
            thumbnail_asset_id = int(raw_thumbnail) if raw_thumbnail else None
        except ValueError as exc:
            raise ProducerWorkflowError("thumbnail asset ID must be a number") from exc
        service.revise_release_presentation(
            release_id,
            thumbnail_asset_id=thumbnail_asset_id,
            change_note=request.form.get("change_note"),
        )
        flash("Thumbnail revision saved.", "success")
        return redirect(url_for("release_detail", release_id=release_id))

    @app.post("/releases/<release_id>/presentation/thumbnail/upload")
    def upload_release_thumbnail(release_id: str):
        upload = request.files.get("thumbnail_file")
        if upload is None or not upload.filename:
            raise ProducerWorkflowError("choose an image file to upload as the thumbnail")
        upload_dir = settings.root / "Temp" / "producer-uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.filename).suffix.lower()
        temporary_path = upload_dir / f"{uuid.uuid4()}{suffix}"
        try:
            upload.save(temporary_path)
            outcome = service.import_release_thumbnail_upload(
                release_id, temporary_path, Path(upload.filename).name
            )
        finally:
            temporary_path.unlink(missing_ok=True)
        flash(
            f"Thumbnail uploaded, cataloged, and selected (asset {outcome['asset_id']}).",
            "success",
        )
        return redirect(url_for("release_detail", release_id=release_id))

    @app.get("/settings/integrations")
    def integrations() -> str:
        return render_template(
            "integrations.html", pexels=credential_store.pexels_status()
        )

    @app.post("/settings/integrations/pexels/save")
    def save_pexels():
        credential_store.save_pexels_api_key(request.form.get("api_key", ""))
        flash(
            "Pexels API key saved. Test the connection when you are ready.",
            "success",
        )
        return redirect(url_for("integrations"))

    @app.post("/settings/integrations/pexels/test")
    def test_pexels():
        supplied = request.form.get("api_key", "").strip()
        secret = supplied or credential_store.resolve_pexels_api_key()
        if not secret:
            flash("Add a Pexels API key before testing the connection.", "error")
            return redirect(url_for("integrations"))
        try:
            pexels_tester(secret)
        except ProviderAuthenticationError:
            flash("Pexels rejected the API key. Check the key and try again.", "error")
        except ProviderError as exc:
            flash(f"Pexels could not be reached: {_concise(exc)}", "error")
        else:
            flash("Pexels connection succeeded.", "success")
        return redirect(url_for("integrations"))

    @app.post("/settings/integrations/pexels/remove")
    def remove_pexels():
        removed = credential_store.remove_pexels_api_key()
        status = credential_store.pexels_status()
        if status.source == "environment":
            flash(
                "Stored Pexels key removed. Pexels remains configured through the environment override.",
                "success",
            )
        elif removed:
            flash("Stored Pexels API key removed.", "success")
        else:
            flash("No stored Pexels API key was present.", "success")
        return redirect(url_for("integrations"))

    @app.post("/plans")
    def import_plan():
        pasted = request.form.get("visual_plan_json", "").strip()
        upload = request.files.get("visual_plan")
        if pasted:
            document = pasted
        elif upload is not None and upload.filename:
            try:
                document = upload.read().decode("utf-8")
            except UnicodeDecodeError as exc:
                flash(f"Visual Plan validation failed: {_concise(exc)}", "error")
                return redirect(url_for("index", import_plan="1"))
        else:
            flash("Choose a Visual Plan JSON file or paste Visual Plan JSON.", "error")
            return redirect(url_for("index", import_plan="1"))
        try:
            plan = VisualPlan.model_validate_json(document)
            result = service.import_plan(plan)
        except (ValidationError, json.JSONDecodeError) as exc:
            flash(f"Visual Plan validation failed: {_concise(exc)}", "error")
            return redirect(url_for("index", import_plan="1"))
        flash("Visual Plan opened." if result["idempotent"] else "Visual Plan imported.", "success")
        return redirect(url_for("workspace", workspace_id=result["workspace_id"]))

    @app.get("/stories/<workspace_id>")
    def workspace(workspace_id: str) -> str:
        return render_template(
            "workspace.html",
            workspace=service.get_workspace(
                workspace_id,
                local_query=request.args.get("local_query", ""),
                local_beat_id=request.args.get("local_beat"),
                sfx_query=request.args.get("sfx_query", ""),
                sfx_beat_id=request.args.get("sfx_beat"),
            ),
            focused_beat=request.args.get("focus"),
            open_panel=request.args.get("panel"),
            releases=service.list_releases(show_released=False),
        )

    @app.post("/stories/<workspace_id>/edit-plan")
    def import_edit_plan(workspace_id: str):
        pasted = request.form.get("edit_plan_json", "").strip()
        upload = request.files.get("edit_plan")
        if pasted:
            document = pasted
        elif upload is not None and upload.filename:
            try:
                document = upload.read().decode("utf-8")
            except UnicodeDecodeError as exc:
                flash(f"Edit Plan validation failed: {_concise(exc)}", "error")
                return redirect(url_for("workspace", workspace_id=workspace_id))
        else:
            flash("Choose an Edit Plan JSON file or paste Edit Plan JSON.", "error")
            return redirect(url_for("workspace", workspace_id=workspace_id))
        try:
            plan = EditPlan.model_validate_json(document)
            result = service.import_edit_plan(workspace_id, plan)
        except (ValidationError, json.JSONDecodeError) as exc:
            flash(f"Edit Plan validation failed: {_concise(exc)}", "error")
            return redirect(url_for("workspace", workspace_id=workspace_id))
        flash(f"Edit Plan imported for {result['beats']} beats.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/beats/<beat_id>/edit-guidance")
    def update_edit_guidance(workspace_id: str, beat_id: str):
        service.update_edit_guidance_choice(
            workspace_id,
            beat_id,
            motion_type=request.form.get("motion_type", ""),
            motion_target=request.form.get("motion_target") or None,
            transition_type=request.form.get("transition_type") or None,
        )
        flash("Producer edit guidance updated.", "success")
        return _beat_redirect(service, workspace_id, beat_id)

    @app.post("/stories/<workspace_id>/beats/<beat_id>/edit-guidance/reset")
    def reset_edit_guidance(workspace_id: str, beat_id: str):
        service.reset_edit_guidance_choice(workspace_id, beat_id)
        flash("Producer edit guidance reset to the Project recommendation.", "success")
        return _beat_redirect(service, workspace_id, beat_id)

    @app.post("/stories/<workspace_id>/beats/<beat_id>/select/<int:asset_id>")
    def select_asset(workspace_id: str, beat_id: str, asset_id: int):
        service.select_asset(
            workspace_id,
            beat_id,
            asset_id,
            override_media_preference=request.form.get("override_media_preference") == "1",
        )
        flash("Asset selected for this beat.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="local")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/clear")
    def clear_selection(workspace_id: str, beat_id: str):
        service.clear_selection(workspace_id, beat_id)
        flash("Beat selection cleared.", "success")
        return _beat_redirect(service, workspace_id, beat_id)

    @app.post("/stories/<workspace_id>/beats/<beat_id>/sfx/select/<int:asset_id>")
    def select_sfx(workspace_id: str, beat_id: str, asset_id: int):
        service.select_sfx(workspace_id, beat_id, asset_id)
        flash("SFX selected for this beat.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="sfx")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/sfx/clear")
    def clear_sfx(workspace_id: str, beat_id: str):
        service.clear_sfx_selection(workspace_id, beat_id)
        flash("SFX selection removed.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="sfx")

    @app.post("/stories/<workspace_id>/organization/status")
    def update_workspace_status(workspace_id: str):
        service.update_workspace_status(workspace_id, request.form.get("status", "")); flash("Workspace status updated.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/organization/title")
    def rename_workspace_title(workspace_id: str):
        service.rename_workspace_title(workspace_id, request.form.get("title", ""))
        flash("Story display title updated.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/organization/release")
    def assign_workspace_release(workspace_id: str):
        service.assign_workspace_release(workspace_id, request.form.get("release_id") or None); flash("Workspace release assignment updated.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/beats/<beat_id>/requirements")
    def update_beat_requirements(workspace_id: str, beat_id: str):
        service.update_beat_requirements(
            workspace_id,
            beat_id,
            media_preference=request.form.get("media_preference", ""),
            source_requirement=request.form.get("source_requirement", ""),
        )
        flash("Beat sourcing requirements updated.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="local")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/search")
    def search_existing_media(workspace_id: str, beat_id: str):
        query = request.form.get("local_query", "").strip()
        if not query:
            flash("Enter a catalog search term.", "error")
            return _beat_redirect(service, workspace_id, beat_id, panel="local")
        if not service.search_existing_media(query):
            flash("No existing catalog media matched that search.", "error")
        return redirect(
            _beat_location(
                service,
                workspace_id,
                beat_id,
                panel="local",
                local_query=query,
                local_beat=beat_id,
                source="local",
            )
        )

    @app.post("/stories/<workspace_id>/beats/<beat_id>/sfx/search")
    def search_sfx_media(workspace_id: str, beat_id: str):
        query = request.form.get("sfx_query", "").strip()
        if not query:
            flash("Enter an SFX catalog search term.", "error")
            return _beat_redirect(service, workspace_id, beat_id, panel="sfx")
        if not service.search_sfx_media(query):
            flash("No existing SFX matched that search.", "error")
        return redirect(_beat_location(
            service, workspace_id, beat_id, panel="sfx",
            sfx_query=query, sfx_beat=beat_id, source="sfx",
        ))

    @app.post("/stories/<workspace_id>/organization/order/<direction>")
    def move_workspace_release(workspace_id: str, direction: str):
        service.move_workspace_release_position(workspace_id, -1 if direction == "up" else 1); flash("Release story order updated.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/delete")
    def delete_workspace(workspace_id: str):
        workspace = service.get_workspace(workspace_id, include_candidates=False)
        if request.form.get("confirm") != workspace["story_id"]:
            raise ProducerWorkflowError("type the story ID to confirm workspace deletion")
        deleted = service.delete_workspace(workspace_id)
        flash(f"Workspace {deleted} and its project files were deleted. Master Library assets were kept.", "success")
        return redirect(url_for("index"))

    @app.post("/stories/<workspace_id>/beats/<beat_id>/hide/<int:asset_id>")
    def hide_asset(workspace_id: str, beat_id: str, asset_id: int):
        service.hide_asset(workspace_id, beat_id, asset_id)
        flash("Asset hidden for this beat only.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="local")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/restore/<int:asset_id>")
    def restore_asset(workspace_id: str, beat_id: str, asset_id: int):
        service.restore_asset(workspace_id, beat_id, asset_id)
        flash("Hidden asset restored for this beat.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="local")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/pexels")
    def import_pexels(workspace_id: str, beat_id: str):
        service.import_pexels_page(workspace_id, beat_id, request.form.get("source_url", ""))
        flash("Pexels media acquired and selected.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="pexels")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/external")
    def import_external(workspace_id: str, beat_id: str):
        try:
            service.import_external_media(
                workspace_id,
                beat_id,
                request.form.get("direct_media_url", ""),
                source_page_url=request.form.get("source_page_url"),
                creator_attribution=request.form.get("creator_attribution"),
                license_name=request.form.get("license_name"),
                license_url=request.form.get("license_url"),
            )
        except (ProducerWorkflowError, ProviderError):
            raise
        except Exception as exc:
            raise ProducerWorkflowError(
                "External import could not be completed. Check the supplied media URL and try again."
            ) from exc
        flash("External media validated, cataloged, and selected.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="external")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/upload")
    def upload_media(workspace_id: str, beat_id: str):
        upload = request.files.get("media_file")
        if upload is None or not upload.filename:
            raise ProducerWorkflowError("choose an image or video file to upload")
        upload_dir = settings.root / "Temp" / "producer-uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.filename).suffix.lower()
        temporary_path = upload_dir / f"{uuid.uuid4()}{suffix}"
        try:
            upload.save(temporary_path)
            service.import_upload(
                workspace_id, beat_id, temporary_path, Path(upload.filename).name
            )
        finally:
            temporary_path.unlink(missing_ok=True)
        flash("Uploaded media validated, cataloged, and selected.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="local")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/sfx/upload")
    def upload_sfx(workspace_id: str, beat_id: str):
        upload = request.files.get("sfx_file")
        if upload is None or not upload.filename:
            raise ProducerWorkflowError("choose a WAV, MP3, or FLAC file to upload")
        upload_dir = settings.root / "Temp" / "producer-uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.filename).suffix.lower()
        temporary_path = upload_dir / f"{uuid.uuid4()}{suffix}"
        try:
            upload.save(temporary_path)
            service.import_upload(
                workspace_id, beat_id, temporary_path, Path(upload.filename).name,
                media_role="sfx", sfx_kind=request.form.get("sfx_kind"),
            )
        finally:
            temporary_path.unlink(missing_ok=True)
        flash("SFX validated, cataloged, and selected.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="sfx")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/sfx/import")
    def import_external_sfx(workspace_id: str, beat_id: str):
        service.import_external_media(
            workspace_id, beat_id, request.form.get("direct_media_url", ""),
            source_page_url=request.form.get("source_page_url"),
            creator_attribution=request.form.get("creator_attribution"),
            license_name=request.form.get("license_name"),
            license_url=request.form.get("license_url"),
            media_role="sfx", sfx_kind=request.form.get("sfx_kind"),
            source_name=request.form.get("source_name"),
        )
        flash("External SFX validated, cataloged, and selected.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="sfx")

    @app.post("/stories/<workspace_id>/edit/rebuild")
    def rebuild_edit(workspace_id: str):
        result = service.build_edit_folder(workspace_id)
        flash(f"Edit folder rebuilt with {len(result['entries'])} selected assets.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/edit/open")
    def open_edit(workspace_id: str):
        service.open_edit_folder(workspace_id)
        flash("Edit folder opened.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/storyboard")
    def generate_storyboard(workspace_id: str):
        result = service.generate_storyboard(workspace_id)
        flash(f"Storyboard generated ({result['pages']} pages).", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/storyboard/open")
    def open_storyboard(workspace_id: str):
        service.open_storyboard(workspace_id, opener=path_opener)
        flash("Storyboard opened.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.post("/stories/<workspace_id>/storyboard/folder")
    def open_storyboard_folder(workspace_id: str):
        service.open_storyboard_folder(workspace_id, opener=path_opener)
        flash("Storyboard folder opened.", "success")
        return redirect(url_for("workspace", workspace_id=workspace_id))

    @app.get("/stories/<workspace_id>/storyboard/view")
    def view_storyboard(workspace_id: str):
        return send_file(
            service.storyboard_path(workspace_id),
            mimetype="application/pdf",
            as_attachment=False,
            conditional=True,
        )

    @app.get("/media/<int:asset_id>")
    def media(asset_id: int):
        return send_file(service.asset_path(asset_id), conditional=True)

    @app.errorhandler(ProducerWorkflowError)
    def producer_error(error: ProducerWorkflowError):
        flash(str(error), "error")
        target = _error_target(service)
        return redirect(target)

    @app.errorhandler(ProviderError)
    def provider_error(error: ProviderError):
        flash(str(error), "error")
        target = _error_target(service)
        return redirect(target)

    @app.errorhandler(CredentialStoreError)
    def credential_error(error: CredentialStoreError):
        flash(str(error), "error")
        return redirect(url_for("integrations"))

    return app


def _beat_redirect(
    service: ProducerWorkflowService,
    workspace_id: str,
    beat_id: str,
    *,
    panel: str | None = None,
):
    return redirect(_beat_location(service, workspace_id, beat_id, panel=panel))


def _beat_location(
    service: ProducerWorkflowService,
    workspace_id: str,
    beat_id: str,
    *,
    panel: str | None = None,
    **query: str,
) -> str:
    anchor = service.beat_anchor(workspace_id, beat_id)
    return url_for(
        "workspace",
        workspace_id=workspace_id,
        focus=anchor,
        panel=panel,
        _anchor=anchor,
        **query,
    )


def _error_target(service: ProducerWorkflowService) -> str:
    values = request.view_args or {}
    workspace_id = values.get("workspace_id")
    beat_id = values.get("beat_id")
    if isinstance(workspace_id, str) and isinstance(beat_id, str):
        try:
            panels = {
                "import_pexels": "pexels",
                "import_external": "external",
                "upload_media": "local",
                "select_asset": "local",
                "hide_asset": "local",
                "restore_asset": "local",
                "search_existing_media": "local",
                "select_sfx": "sfx",
                "clear_sfx": "sfx",
                "search_sfx_media": "sfx",
                "upload_sfx": "sfx",
                "import_external_sfx": "sfx",
            }
            return _beat_location(
                service,
                workspace_id,
                beat_id,
                panel=panels.get(request.endpoint or ""),
            )
        except ProducerWorkflowError:
            pass
    return request.referrer or url_for("index")


def run_web_app(
    settings: Settings,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    app_factory: Callable[[Settings], Any] = create_app,
    server_factory: Callable[..., Any] = make_server,
    browser_opener: Callable[[str], Any] = webbrowser.open,
    output: Callable[[str], Any] = print,
    lan_ip_resolver: Callable[[], str | None] | None = None,
) -> None:
    app = app_factory(settings)
    server = server_factory(host, port, app, threaded=True)
    actual_port = int(getattr(server, "server_port", port))
    display_host = "127.0.0.1" if _is_wildcard(host) else host
    local_url = f"http://{display_host}:{actual_port}"
    output("YT-ChannelOps")
    output(f"Serving at {local_url}")
    if not _is_loopback(host):
        output("WARNING: The producer UI may be reachable by other devices on your local network.")
        output(f"Local machine: http://127.0.0.1:{actual_port}")
        resolver = lan_ip_resolver or _likely_lan_ip
        lan_ip = resolver()
        if lan_ip:
            output(f"LAN: http://{lan_ip}:{actual_port}")
    if open_browser:
        output("Opening browser...")
        try:
            opened = browser_opener(local_url)
            if opened is False:
                output(f"Browser did not open automatically. Open {local_url}")
        except Exception:
            output(f"Browser did not open automatically. Open {local_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def test_pexels_connection(api_key: str) -> None:
    provider = PexelsProvider(api_key)
    try:
        provider.search_photos("test", page=1, per_page=1)
    finally:
        provider.close()


def _is_wildcard(host: str) -> bool:
    return host.strip() in {"0.0.0.0", "::", "[::]"}


def _is_loopback(host: str) -> bool:
    normalized = host.strip().casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized.strip("[]")).is_loopback
    except ValueError:
        return False


def _likely_lan_ip() -> str | None:
    try:
        candidate = socket.gethostbyname(socket.gethostname())
        address = ipaddress.ip_address(candidate)
        return candidate if not address.is_loopback and not address.is_unspecified else None
    except (OSError, ValueError):
        return None


def _concise(error: Exception) -> str:
    return " ".join(str(error).split())[:500]
