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
from .contracts import VisualPlan
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
        settings.max_image_download_bytes, settings.max_video_download_bytes
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
        return render_template("index.html", workspaces=service.list_workspaces())

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
        upload = request.files.get("visual_plan")
        if upload is None or not upload.filename:
            flash("Choose a Visual Plan JSON file.", "error")
            return redirect(url_for("index"))
        try:
            plan = VisualPlan.model_validate_json(upload.read().decode("utf-8"))
            result = service.import_plan(plan)
        except (UnicodeDecodeError, ValidationError, json.JSONDecodeError) as exc:
            flash(f"Visual Plan validation failed: {_concise(exc)}", "error")
            return redirect(url_for("index"))
        flash("Visual Plan opened." if result["idempotent"] else "Visual Plan imported.", "success")
        return redirect(url_for("workspace", workspace_id=result["workspace_id"]))

    @app.get("/stories/<workspace_id>")
    def workspace(workspace_id: str) -> str:
        return render_template(
            "workspace.html",
            workspace=service.get_workspace(workspace_id),
            focused_beat=request.args.get("focus"),
            open_panel=request.args.get("panel"),
        )

    @app.post("/stories/<workspace_id>/beats/<beat_id>/select/<int:asset_id>")
    def select_asset(workspace_id: str, beat_id: str, asset_id: int):
        service.select_asset(workspace_id, beat_id, asset_id)
        flash("Asset selected for this beat.", "success")
        return _beat_redirect(service, workspace_id, beat_id, panel="local")

    @app.post("/stories/<workspace_id>/beats/<beat_id>/clear")
    def clear_selection(workspace_id: str, beat_id: str):
        service.clear_selection(workspace_id, beat_id)
        flash("Beat selection cleared.", "success")
        return _beat_redirect(service, workspace_id, beat_id)

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
) -> str:
    anchor = service.beat_anchor(workspace_id, beat_id)
    return url_for(
        "workspace",
        workspace_id=workspace_id,
        focus=anchor,
        panel=panel,
        _anchor=anchor,
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
    output("YT-Visuals Producer")
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
