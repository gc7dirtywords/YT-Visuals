from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session
import yt_visuals.producer.service as producer_service_module

from yt_visuals.acquisition import AcquisitionService, ProbeResult
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.library import LibraryScanner
from yt_visuals.library.inspection import inspect_media_file
from yt_visuals.models import (
    AssetLicense,
    MediaAsset,
    MediaDownload,
    MediaSource,
    MediaLocation,
    ProducerBeat,
    ProducerWorkspace,
    ProducerBeatHiddenAsset,
    ProductionEvent,
    ReleasePresentationRevision,
    StoryDocumentVersion,
)
from yt_visuals.producer.contracts import EditPlan, VisualPlan
from yt_visuals.producer.service import (
    ProducerWorkflowError,
    ProducerWorkflowService,
    WIKIMEDIA_USER_AGENT,
    parse_pexels_page_url,
    resolve_wikimedia_file_page,
)
from yt_visuals.providers.base import MediaSearchResult, ProviderInfo


def _plan(*, preference: str = "either") -> VisualPlan:
    return VisualPlan.model_validate(
        {
            "document_type": "visual_plan",
            "contract_version": 1,
            "story": {"story_id": "producer-story", "title": "Producer Story"},
            "beats": [
                {
                    "beat_id": "beat-001",
                    "sequence": 1,
                    "narration_context": "A fire burns in the dark room.",
                    "desired_visual": "Dark fireplace",
                    "search_queries": ["dark fireplace", "old hearth"],
                    "must_have": ["fireplace"],
                    "avoid": ["people"],
                    "media_preference": preference,
                    "source_requirement": "representative",
                    "production_opportunities": [],
                },
                {
                    "beat_id": "beat-002",
                    "sequence": 2,
                    "narration_context": "The room falls silent.",
                    "desired_visual": "Empty dark room",
                    "search_queries": ["empty dark room"],
                    "must_have": [],
                    "avoid": [],
                    "media_preference": "image",
                    "source_requirement": "exact",
                    "production_opportunities": [],
                },
            ],
        }
    )


def _sfx_plan() -> VisualPlan:
    value = _plan().model_dump(mode="json")
    value["story"] = {"story_id": "sfx-story", "title": "SFX Story"}
    value["beats"][0]["production_opportunities"] = [
        {
            "trigger": "The chest shifts away from the wall.",
            "sfx_recommendation": {
                "type": "sfx",
                "purpose": "Attention reset for the unexpected reveal",
                "sfx_kind": "one_shot",
                "desired_sound": "restrained low tonal accent",
                "search_queries": ["subtle dark hit"],
                "intensity": "subtle",
                "note": "Keep it restrained.",
            },
        }
    ]
    return VisualPlan.model_validate(value)


def _edit_plan() -> EditPlan:
    return EditPlan.model_validate(
        {
            "document_type": "edit_plan",
            "contract_version": 1,
            "story": {"story_id": "producer-story"},
            "beats": [
                {
                    "beat_id": "beat-001",
                    "sequence": 1,
                    "motion_recommendation": {
                        "type": "slow_zoom_in",
                        "purpose": "Draw attention toward the fireplace.",
                        "target": "fireplace",
                    },
                    "transition_out_recommendation": {
                        "type": "cross_dissolve",
                        "to_beat_id": "beat-002",
                        "purpose": "Ease into the empty room.",
                    },
                },
                {
                    "beat_id": "beat-002",
                    "sequence": 2,
                    "motion_recommendation": {
                        "type": "static",
                        "purpose": "Hold the empty composition.",
                        "target": None,
                    },
                    "transition_out_recommendation": None,
                },
            ],
        }
    )


def _image(path: Path, color: str = "navy", size: tuple[int, int] = (160, 90)) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="JPEG")
    return path.read_bytes()


def _jpeg_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (320, 180), "#2b2118").save(stream, format="JPEG")
    return stream.getvalue()


def _colored_jpeg_bytes(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (320, 180), color).save(stream, format="JPEG")
    return stream.getvalue()


def _docx(path: Path, text: str = "document") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f"<document>{text}</document>")
    return path.read_bytes()


def _setup(catalog_settings: Settings) -> tuple[object, ProducerWorkflowService, dict]:
    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)
    imported = service.import_plan(_plan())
    return engine, service, imported


def test_plan_import_local_candidates_selection_hide_restore_and_replace(
    catalog_settings: Settings,
) -> None:
    _image(catalog_settings.root / "Library/Images/dark-fireplace.jpg", "maroon")
    _image(catalog_settings.root / "Library/Images/old-hearth.jpg", "gray")
    engine, service, imported = _setup(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    workspace = service.get_workspace(imported["workspace_id"])
    beat = workspace["beats"][0]
    assert imported["idempotent"] is False
    assert service.import_plan(_plan())["idempotent"] is True
    assert len(beat["candidates"]) == 2

    first, second = beat["candidates"]
    service.select_asset(workspace["workspace_id"], beat["id"], first["asset_id"])
    selected = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert selected["beats"][0]["selected"]["asset_id"] == first["asset_id"]
    edit_visuals = catalog_settings.root / "Projects/producer-story/Edit/Visuals"
    assert len(list(edit_visuals.iterdir())) == 1

    service.hide_asset(workspace["workspace_id"], beat["id"], first["asset_id"])
    hidden = service.get_workspace(workspace["workspace_id"])["beats"][0]
    assert hidden["selected"] is None
    assert first["asset_id"] in hidden["hidden_asset_ids"]
    assert first["asset_id"] not in {item["asset_id"] for item in hidden["candidates"]}
    service.restore_asset(workspace["workspace_id"], beat["id"], first["asset_id"])
    service.select_asset(workspace["workspace_id"], beat["id"], second["asset_id"])
    replaced = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert replaced["beats"][0]["selected"]["asset_id"] == second["asset_id"]
    edit_file = next(edit_visuals.iterdir())
    assert edit_file.read_bytes() == (
        catalog_settings.root / replaced["beats"][0]["selected"]["current_location"]
    ).read_bytes()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProducerBeatHiddenAsset)) == 0
    engine.dispose()


def test_local_upload_validates_catalogs_and_sha_deduplicates(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    first_beat, second_beat = workspace["beats"]
    upload_one = catalog_settings.root / "Temp/first-upload.jpg"
    content = _image(upload_one, "purple")
    first = service.import_upload(
        workspace["workspace_id"], first_beat["id"], upload_one, "chosen fireplace.jpg"
    )
    upload_two = catalog_settings.root / "Temp/second-upload.jpg"
    upload_two.write_bytes(content)
    second = service.import_upload(
        workspace["workspace_id"], second_beat["id"], upload_two, "same bytes.jpg"
    )
    assert first["asset_id"] == second["asset_id"]
    assert second["deduplicated"] is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        asset = session.get(MediaAsset, first["asset_id"])
        assert asset is not None and asset.license is None
        assert {item.original_filename for item in asset.sources} == {
            "chosen fireplace.jpg",
            "same bytes.jpg",
        }
        assert all(item.provider_id is None for item in asset.sources)
    engine.dispose()


def test_sfx_recommendation_selection_reuse_and_edit_handoff(
    catalog_settings: Settings,
) -> None:
    path = catalog_settings.root / "Library/SFX/subtle-dark-hit.wav"
    path.write_bytes(b"shared synthetic sfx")
    engine = initialize_database(catalog_settings)

    def inspector(candidate):
        return inspect_media_file(
            candidate,
            video_probe=lambda path: ProbeResult(
                duration_ms=900, audio_codec="pcm_s16le", sample_rate=48_000,
                channels=1, container="wav", raw_metadata={"streams": []},
            ),
        )

    LibraryScanner(catalog_settings, engine, inspector=inspector).scan()
    with Session(engine) as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        asset.sfx_kind = "one_shot"
        session.commit()
        asset_id = asset.id

    service = ProducerWorkflowService(catalog_settings, engine)
    imported = service.import_plan(_sfx_plan())
    workspace = service.get_workspace(imported["workspace_id"])
    first, second = workspace["beats"]
    assert first["sfx_recommendations"][0]["purpose"].startswith("Attention reset")
    assert [item["asset_id"] for item in first["sfx_candidates"]] == [asset_id]
    assert second["sfx_recommendations"] == []

    service.select_sfx(workspace["workspace_id"], first["id"], asset_id)
    service.select_sfx(workspace["workspace_id"], second["id"], asset_id)
    selected = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert [beat["selected_sfx"]["asset_id"] for beat in selected["beats"]] == [
        asset_id, asset_id
    ]
    assert selected["beats"][1]["sfx_reuse"]["story"][0]["asset_id"] == asset_id
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1

    result = service.build_edit_folder(workspace["workspace_id"])
    sfx_entries = [row for row in result["entries"] if row["media_role"] == "sfx"]
    assert len(sfx_entries) == 2
    assert len(list((catalog_settings.root / "Projects/sfx-story/Edit/SFX").iterdir())) == 2
    with (catalog_settings.root / "Projects/sfx-story/Edit/manifest.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        assert [row["media_role"] for row in csv.DictReader(handle)] == ["sfx", "sfx"]
    assert path.read_bytes() == b"shared synthetic sfx"

    storyboard = service.generate_storyboard(workspace["workspace_id"])
    assert Path(storyboard["storyboard_path"]).is_file()
    service.clear_sfx_selection(workspace["workspace_id"], second["id"])
    assert service.get_workspace(workspace["workspace_id"], include_candidates=False)["beats"][1]["selected_sfx"] is None
    engine.dispose()


def test_external_sfx_import_validates_provenance_license_and_sha_deduplicates(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"Content-Type": "audio/wav"}, content=b"valid wave fixture")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service.acquisition_factory = lambda settings, supplied: AcquisitionService(
        settings, supplied, http_client=client,
        metadata_probe=lambda path: ProbeResult(
            duration_ms=1_500, audio_codec="pcm_s16le", sample_rate=48_000,
            channels=2, container="wav", raw_metadata={"streams": [{"codec_type": "audio"}]},
        ),
    )
    first = service.import_external_media(
        workspace["workspace_id"], workspace["beats"][0]["id"],
        "https://audio.example.test/subtle-hit.wav",
        source_page_url="https://audio.example.test/sounds/42",
        creator_attribution="Archive Artist", license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        media_role="sfx", sfx_kind="one_shot", source_name="Sound Archive",
    )
    second = service.import_external_media(
        workspace["workspace_id"], workspace["beats"][1]["id"],
        "https://audio.example.test/subtle-hit.wav",
        source_page_url="https://audio.example.test/sounds/42",
        creator_attribution="Archive Artist", license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        media_role="sfx", sfx_kind="one_shot", source_name="Sound Archive",
    )
    assert first["asset_id"] == second["asset_id"]
    assert requests == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        asset = session.get(MediaAsset, first["asset_id"])
        assert asset is not None and asset.media_type == "audio" and asset.sfx_kind == "one_shot"
        assert asset.license is not None and asset.license.license_name == "CC BY 4.0"
        assert asset.sources[0].source_url == "https://audio.example.test/sounds/42"
        assert asset.sources[0].creator_name == "Archive Artist"
        assert asset.sources[0].provider is not None
        assert asset.sources[0].provider.name == "Sound Archive"
    client.close()
    engine.dispose()


def test_pexels_page_parser_and_manual_import_reuse_hardened_acquisition(
    catalog_settings: Settings,
) -> None:
    assert parse_pexels_page_url(
        "https://www.pexels.com/photo/dark-fireplace-7001/"
    ) == ("image", "7001")
    assert parse_pexels_page_url("https://pexels.com/video/fire-8002/") == (
        "video",
        "8002",
    )
    with pytest.raises(ProducerWorkflowError, match="only HTTPS Pexels"):
        parse_pexels_page_url("http://www.pexels.com/photo/test-1/")
    with pytest.raises(ProducerWorkflowError, match="not a recognized"):
        parse_pexels_page_url("https://www.pexels.com/search/fireplace/")

    engine = initialize_database(catalog_settings)
    calls: list[str] = []
    result = MediaSearchResult(
        provider="pexels",
        provider_asset_id="7001",
        media_type="image",
        title="Dark fireplace",
        description=None,
        creator_name="Creator",
        creator_url="https://www.pexels.com/@creator",
        source_url="https://www.pexels.com/photo/dark-fireplace-7001/",
        download_url="https://images.pexels.com/photos/7001/fireplace.jpeg",
        preview_url=None,
        width=320,
        height=180,
        duration_ms=None,
        mime_type="image/jpeg",
        license_name="Pexels License",
        license_url="https://www.pexels.com/legal-pages/license/",
        attribution_required=False,
        attribution_text="Photo by Creator on Pexels",
        raw_metadata={"id": 7001},
        commercial_use_allowed=True,
        modifications_allowed=True,
    )

    class FakeProvider:
        info = ProviderInfo("pexels", "Pexels", None, None, None, None, False)
        def get_photo(self, asset_id: str) -> MediaSearchResult:
            calls.append(asset_id)
            return result
        def get_video(self, asset_id: str) -> MediaSearchResult:
            raise AssertionError("photo URL must not fetch video")
        def close(self) -> None:
            return None

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"Content-Type": "image/jpeg"}, content=_jpeg_bytes()
            )
        )
    )
    service = ProducerWorkflowService(
        catalog_settings,
        engine,
        provider_factory=lambda name, settings: FakeProvider(),
        acquisition_factory=lambda settings, supplied: AcquisitionService(
            settings, supplied, http_client=client
        ),
    )
    imported = service.import_plan(_plan())
    beat = service.get_workspace(imported["workspace_id"], include_candidates=False)["beats"][0]
    acquired = service.import_pexels_page(
        imported["workspace_id"], beat["id"], result.source_url
    )
    assert acquired["source_kind"] == "pexels_page"
    assert calls == ["7001"]
    selected = service.get_workspace(imported["workspace_id"], include_candidates=False)["beats"][0]["selected"]
    assert selected["source"]["provider"] == "pexels"
    assert selected["license"]["name"] == "Pexels License"
    client.close()
    engine.dispose()


def test_external_import_preserves_provenance_license_and_sha_deduplicates(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    requested: list[str] = []
    shared_bytes = _colored_jpeg_bytes("teal")

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        content = (
            _colored_jpeg_bytes("orange")
            if request.url.path.endswith("unknown.jpg")
            else shared_bytes
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg"},
            content=content,
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    service = ProducerWorkflowService(
        catalog_settings,
        engine,
        acquisition_factory=lambda settings, supplied: AcquisitionService(
            settings, supplied, http_client=client
        ),
    )
    imported = service.import_plan(_plan())
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    first_beat, second_beat = workspace["beats"]
    direct_one = "https://media.example.test/commons-one.jpg"
    direct_two = "https://archive.example.test/archive-copy.jpg"
    source_page = "https://commons.example.test/wiki/File:Fireplace.jpg"
    license_url = "https://creativecommons.org/licenses/by/4.0/"

    first = service.import_external_media(
        workspace["workspace_id"],
        first_beat["id"],
        direct_one,
        source_page_url=source_page,
        creator_attribution="Photograph by Example Creator",
        license_name="CC BY 4.0",
        license_url=license_url,
    )
    duplicate = service.import_external_media(
        workspace["workspace_id"], second_beat["id"], direct_two
    )

    assert first["asset_id"] == duplicate["asset_id"]
    assert duplicate["duplicate_reason"] == "sha256"
    assert requested == [direct_one, direct_two]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        asset = session.get(MediaAsset, first["asset_id"])
        assert asset is not None
        assert asset.license is not None
        assert asset.license.license_name == "CC BY 4.0"
        assert asset.license.license_url == license_url
        assert asset.license.attribution_text == "Photograph by Example Creator"
        assert asset.license.commercial_use_allowed is None
        assert asset.license.modifications_allowed is None
        sources = list(asset.sources)
        assert {item.source_url for item in sources} == {source_page, direct_two}
        assert "Photograph by Example Creator" in {
            item.creator_name for item in sources
        }
        downloads = list(session.scalars(select(MediaDownload)))
        assert {item.download_url for item in downloads} == {direct_one, direct_two}
        assert source_page not in {item.download_url for item in downloads}

    unknown = service.import_external_media(
        workspace["workspace_id"], second_beat["id"],
        "https://media.example.test/unknown.jpg",
    )
    selected = service.get_workspace(
        workspace["workspace_id"], include_candidates=False
    )["beats"][1]["selected"]
    assert selected["asset_id"] == unknown["asset_id"]
    assert selected["license"]["status"] == "unknown"
    with Session(engine) as session:
        unknown_asset = session.get(MediaAsset, unknown["asset_id"])
        assert unknown_asset is not None and unknown_asset.license is not None
        assert unknown_asset.license.license_name is None
        assert unknown_asset.license.commercial_use_allowed is None
        assert unknown_asset.license.modifications_allowed is None
    client.close()
    engine.dispose()


def test_external_import_rejects_html_and_unsupported_formats(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b"<html>not media</html>",
            )
        )
    )
    service = ProducerWorkflowService(
        catalog_settings,
        engine,
        acquisition_factory=lambda settings, supplied: AcquisitionService(
            settings, supplied, http_client=client
        ),
    )
    imported = service.import_plan(_plan())
    beat = service.get_workspace(imported["workspace_id"], include_candidates=False)[
        "beats"
    ][0]

    with pytest.raises(ProducerWorkflowError, match="did not resolve to a supported media"):
        service.import_external_media(
            imported["workspace_id"], beat["id"],
            "https://example.test/not-really-an-image.jpg",
        )
    with pytest.raises(ProducerWorkflowError, match="GIF and SVG"):
        service.import_external_media(
            imported["workspace_id"], beat["id"],
            "https://example.test/animation.gif",
        )
    with pytest.raises(ProducerWorkflowError, match="valid HTTPS"):
        service.import_external_media(
            imported["workspace_id"], beat["id"],
            "http://example.test/image.jpg",
        )
    client.close()

    redirect_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                302,
                headers={"Location": "https://unrelated.test/image.jpg"},
            )
            if request.url.host == "example.test"
            else httpx.Response(
                200, headers={"Content-Type": "image/jpeg"}, content=_jpeg_bytes()
            )
        )
    )
    service.acquisition_factory = lambda settings, supplied: AcquisitionService(
        settings, supplied, http_client=redirect_client
    )
    with pytest.raises(ProducerWorkflowError, match="host is not allowlisted"):
        service.import_external_media(
            imported["workspace_id"], beat["id"],
            "https://example.test/image.jpg",
        )
    redirect_client.close()
    engine.dispose()


def test_documented_external_dedupe_enriches_local_upload_and_exports_best_source(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    beat = workspace["beats"][0]
    upload = catalog_settings.root / "Temp/local-first.jpg"
    content = _image(upload, "midnightblue")
    local = service.import_upload(
        workspace["workspace_id"], beat["id"], upload, "local-first.jpg"
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"Content-Type": "image/jpeg"}, content=content
            )
        )
    )
    service.acquisition_factory = lambda settings, supplied: AcquisitionService(
        settings, supplied, http_client=client
    )
    direct_url = "https://upload.wikimedia.org/history/local-first.jpg"
    source_page = "https://commons.wikimedia.org/wiki/File:Local_first.jpg"
    documented = service.import_external_media(
        workspace["workspace_id"],
        beat["id"],
        direct_url,
        source_page_url=source_page,
        creator_attribution="Wikimedia contributor",
        license_name="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
    )
    repeated = service.import_external_media(
        workspace["workspace_id"],
        beat["id"],
        direct_url,
        source_page_url=source_page,
        creator_attribution="Wikimedia contributor",
        license_name="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
    )

    assert local["asset_id"] == documented["asset_id"] == repeated["asset_id"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        asset = session.get(MediaAsset, local["asset_id"])
        assert asset is not None and asset.license is not None
        assert asset.license.license_name == "CC BY-SA 4.0"
        assert asset.license.commercial_use_allowed is None
        assert asset.license.modifications_allowed is None
        assert len(asset.sources) == 2
        assert any(source.provider_id is None for source in asset.sources)
        assert sum(source.source_url == source_page for source in asset.sources) == 1

    selected = service.get_workspace(
        workspace["workspace_id"], include_candidates=False
    )["beats"][0]["selected"]
    assert selected["source"]["provider"] == "manual_external"
    assert selected["source"]["source_url"] == source_page
    assert selected["source"]["creator_name"] == "Wikimedia contributor"
    built = service.build_edit_folder(workspace["workspace_id"])
    with Path(built["edit_folder"]).joinpath("manifest.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        manifest = list(csv.DictReader(handle))
    assert manifest[0]["source_provider"] == "manual_external"
    assert manifest[0]["source_url"] == source_page
    storyboard = service.generate_storyboard(workspace["workspace_id"])
    pdf = Path(storyboard["storyboard_path"]).read_bytes()
    assert b"manual_external | Creator: Wikimedia contributor" in pdf
    assert b"License: CC BY-SA 4.0" in pdf
    client.close()
    engine.dispose()


def test_wikimedia_file_page_resolves_structured_metadata_and_imports(
    catalog_settings: Settings,
) -> None:
    file_page = "https://commons.wikimedia.org/wiki/File:Historical_house.jpg"
    direct_url = "https://upload.wikimedia.org/wikipedia/commons/a/a1/Historical_house.jpg"

    def api_response(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == WIKIMEDIA_USER_AGENT
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "imageinfo": [
                                {
                                    "url": direct_url,
                                    "descriptionurl": file_page,
                                    "extmetadata": {
                                        "Artist": {"value": "<b>Archive Author</b>"},
                                        "LicenseShortName": {"value": "CC0 1.0"},
                                        "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/zero/1.0/"},
                                    },
                                }
                            ]
                        }
                    ]
                }
            },
        )

    api_client = httpx.Client(
        transport=httpx.MockTransport(api_response),
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
    )
    resolved = resolve_wikimedia_file_page(file_page, http_client=api_client)
    assert resolved.direct_media_url == direct_url
    assert resolved.creator_attribution == "Archive Author"
    assert resolved.license_name == "CC0 1.0"

    engine = initialize_database(catalog_settings)
    media_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"Content-Type": "image/jpeg"}, content=_jpeg_bytes()
            )
        )
    )
    service = ProducerWorkflowService(
        catalog_settings,
        engine,
        acquisition_factory=lambda settings, supplied: AcquisitionService(
            settings, supplied, http_client=media_client
        ),
        wikimedia_resolver=lambda page: resolve_wikimedia_file_page(
            page, http_client=api_client
        ),
    )
    imported = service.import_plan(_plan())
    beat = service.get_workspace(imported["workspace_id"], include_candidates=False)["beats"][0]
    outcome = service.import_external_media(imported["workspace_id"], beat["id"], file_page)
    selected = service.get_workspace(imported["workspace_id"], include_candidates=False)["beats"][0]["selected"]
    assert outcome["source_page_url"] == file_page
    assert selected["source"]["source_url"] == file_page
    assert selected["source"]["creator_name"] == "Archive Author"
    assert selected["license"]["name"] == "CC0 1.0"
    direct_import = service.import_external_media(
        imported["workspace_id"],
        service.get_workspace(imported["workspace_id"], include_candidates=False)["beats"][1]["id"],
        direct_url,
        source_page_url=file_page,
    )
    assert direct_import["asset_id"] == outcome["asset_id"]

    with pytest.raises(ProducerWorkflowError, match="no original media"):
        resolve_wikimedia_file_page(
            "https://commons.wikimedia.org/wiki/File:Missing.jpg",
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"query": {"pages": [{}]}})
                )
            ),
        )
    api_client.close()
    media_client.close()
    engine.dispose()


def test_wikimedia_resolver_sends_descriptive_user_agent_and_tolerates_bad_metadata(
    monkeypatch,
) -> None:
    file_page = "https://commons.wikimedia.org/wiki/File:Optional_metadata.jpg"
    direct_url = "https://upload.wikimedia.org/wikipedia/commons/0/01/Optional_metadata.jpg"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == WIKIMEDIA_USER_AGENT
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "imageinfo": [
                                {
                                    "url": direct_url,
                                    "descriptionurl": file_page,
                                    "extmetadata": {
                                        "Artist": {"value": 17},
                                        "LicenseShortName": ["malformed"],
                                        "LicenseUrl": None,
                                    },
                                }
                            ]
                        }
                    ]
                }
            },
        )

    real_client = httpx.Client

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(producer_service_module.httpx, "Client", client_factory)
    resolved = resolve_wikimedia_file_page(file_page)
    assert resolved.direct_media_url == direct_url
    assert resolved.source_page_url == file_page
    assert resolved.creator_attribution is None
    assert resolved.license_name is None
    assert resolved.license_url is None


def test_workspace_organization_release_order_and_safe_delete(catalog_settings: Settings) -> None:
    engine, service, imported = _setup(catalog_settings)
    first = service.get_workspace(imported["workspace_id"], include_candidates=False)
    plan_data = _plan().model_dump(mode="json")
    plan_data["story"] = {"story_id": "producer-story-two", "title": "Second Story"}
    plan_data["beats"][0]["beat_id"] = "second-001"
    plan_data["beats"][1]["beat_id"] = "second-002"
    second_import = service.import_plan(VisualPlan.model_validate(plan_data))
    release = service.create_release("EP0001-Hauntings Behind Horror Movies")
    service.assign_workspace_release(first["workspace_id"], release["id"])
    service.assign_workspace_release(second_import["workspace_id"], release["id"])
    service.move_workspace_release_position(second_import["workspace_id"], -1)
    detail = service.get_release(release["id"])
    assert [item["title"] for item in detail["workspaces"]] == ["Second Story", "Producer Story"]
    assert detail["workspaces"][0]["status"] == "planned"
    with pytest.raises(ProducerWorkflowError, match="still contains"):
        service.delete_release(release["id"])
    service.assign_workspace_release(first["workspace_id"], None)
    assert service.get_workspace(first["workspace_id"], include_candidates=False)["release"] is None
    project = catalog_settings.root / "Projects" / first["story_id"]
    project.mkdir(parents=True, exist_ok=True)
    (project / "generated.txt").write_text("workspace only", encoding="utf-8")
    with pytest.raises(ProducerWorkflowError, match="assignment history"):
        service.delete_workspace(first["workspace_id"])
    assert project.exists()
    assert any(item["workspace_id"] == first["workspace_id"] for item in service.list_workspaces())
    assert service.get_release(release["id"])["name"] == release["name"]
    engine.dispose()


def test_delete_one_of_four_workspaces_preserves_other_beats_and_shared_media(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)

    def make_plan(story_id: str, title: str, beat_count: int) -> VisualPlan:
        data = _plan().model_dump(mode="json")
        data["story"] = {"story_id": story_id, "title": title}
        template = data["beats"][0]
        data["beats"] = [
            {**template, "beat_id": f"{story_id}-{sequence}", "sequence": sequence}
            for sequence in range(1, beat_count + 1)
        ]
        return VisualPlan.model_validate(data)

    plans = [
        make_plan("workspace-a", "Workspace A", 3),
        make_plan("workspace-b", "Workspace B", 4),
        make_plan("workspace-c", "Workspace C", 2),
        make_plan("workspace-test", "Test Workspace", 1),
    ]
    imported = [service.import_plan(plan) for plan in plans]
    test_workspace = service.get_workspace(imported[3]["workspace_id"], include_candidates=False)
    shared_file = catalog_settings.root / "Temp" / "shared-delete-safety.jpg"
    _image(shared_file, "darkred")
    shared = service.import_upload(
        test_workspace["workspace_id"], test_workspace["beats"][0]["id"], shared_file, shared_file.name
    )
    with Session(engine) as session:
        session.add(AssetLicense(asset_id=shared["asset_id"], license_name="Test License"))
        session.commit()
    first_workspace = service.get_workspace(imported[0]["workspace_id"], include_candidates=False)
    service.select_asset(first_workspace["workspace_id"], first_workspace["beats"][0]["id"], shared["asset_id"])
    project = catalog_settings.root / "Projects" / test_workspace["story_id"]
    project.mkdir(parents=True, exist_ok=True)
    (project / "generated.txt").write_text("test workspace only", encoding="utf-8")

    repeated = service.import_plan(plans[0])
    assert repeated["workspace_id"] == imported[0]["workspace_id"]
    assert repeated["idempotent"] is True
    assert service.get_workspace(repeated["workspace_id"], include_candidates=False)["total"] == 3
    service.delete_workspace(test_workspace["workspace_id"])

    assert not project.exists()
    assert [service.get_workspace(item["workspace_id"], include_candidates=False)["total"] for item in imported[:3]] == [3, 4, 2]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProducerWorkspace)) == 3
        assert session.scalar(select(func.count()).select_from(ProducerBeat)) == 9
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        assert session.scalar(select(func.count()).select_from(MediaSource)) == 1
        assert session.scalar(select(func.count()).select_from(AssetLicense)) == 1
    assert (catalog_settings.root / "Library" / "Images").exists()
    engine.dispose()


def test_workspace_delete_filesystem_failure_keeps_database_state(
    catalog_settings: Settings, monkeypatch
) -> None:
    engine, service, imported = _setup(catalog_settings)
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    project = catalog_settings.root / "Projects" / workspace["story_id"]
    project.mkdir(parents=True, exist_ok=True)

    def fail_delete(_path):
        raise OSError("locked")

    monkeypatch.setattr(producer_service_module.shutil, "rmtree", fail_delete)
    with pytest.raises(ProducerWorkflowError, match="workspace was kept"):
        service.delete_workspace(workspace["workspace_id"])
    assert service.get_workspace(workspace["workspace_id"], include_candidates=False)["total"] == 2
    assert project.exists()
    engine.dispose()


def test_release_metadata_sorting_title_rename_and_cross_story_reuse(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    first = service.get_workspace(imported["workspace_id"], include_candidates=False)
    plan_data = _plan().model_dump(mode="json")
    plan_data["story"] = {"story_id": "second-producer-story", "title": "Second Producer Story"}
    plan_data["beats"][0]["beat_id"] = "second-001"
    plan_data["beats"][1]["beat_id"] = "second-002"
    second_import = service.import_plan(VisualPlan.model_validate(plan_data))
    second = service.get_workspace(second_import["workspace_id"], include_candidates=False)

    release = service.create_release("Active undated")
    near = service.create_release("Active near")
    old = service.create_release("Released old")
    new = service.create_release("Released new")
    assert release["status"] == "planned"
    service.update_release_metadata(near["id"], status="in_production", release_date="2026-09-10")
    service.update_release_metadata(old["id"], status="released", release_date="2026-01-01")
    service.update_release_metadata(new["id"], status="released", release_date="2026-08-01")
    assert [item["name"] for item in service.list_releases(show_released=True)] == [
        "Active near", "Active undated", "Released new", "Released old"
    ]
    assert [item["name"] for item in service.list_releases(show_released=False)] == [
        "Active near", "Active undated"
    ]

    original_story_id = first["story_id"]
    original_edit = service.edit_folder(original_story_id)
    service.rename_workspace_title(first["workspace_id"], "Renamed Story Display")
    renamed = service.get_workspace(first["workspace_id"], include_candidates=False)
    assert renamed["title"] == "Renamed Story Display"
    assert renamed["story_id"] == original_story_id
    assert service.edit_folder(renamed["story_id"]) == original_edit

    service.assign_workspace_release(first["workspace_id"], release["id"])
    service.assign_workspace_release(second["workspace_id"], release["id"])
    upload = catalog_settings.root / "Temp" / "shared.jpg"
    _image(upload, "olive")
    asset = service.import_upload(first["workspace_id"], first["beats"][0]["id"], upload, "shared.jpg")
    service.select_asset(second["workspace_id"], second["beats"][0]["id"], asset["asset_id"])
    service.select_asset(second["workspace_id"], second["beats"][1]["id"], asset["asset_id"])
    reuse = service.get_workspace(second["workspace_id"], include_candidates=False)["beats"][0]["reuse"]
    rendered_ids = [item["asset_id"] for group in ("release", "story", "recent") for item in reuse[group]]
    assert rendered_ids == [asset["asset_id"]]
    assert len(reuse["release"][0]["used_in"]) == 2
    searched = service.get_workspace(
        second["workspace_id"], include_candidates=False, local_query="shared", local_beat_id=second["beats"][0]["id"]
    )["beats"][0]
    assert [item["asset_id"] for item in searched["existing_search"]] == [asset["asset_id"]]
    assert all(not searched["reuse"][group] for group in ("release", "story", "recent"))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
    engine.dispose()


def test_release_status_controls_story_status_and_released_assignment_is_blocked(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    release = service.create_release("Controlled release")
    service.assign_workspace_release(imported["workspace_id"], release["id"])
    assert service.get_workspace(imported["workspace_id"], include_candidates=False)["status"] == "planned"

    with pytest.raises(ProducerWorkflowError, match="controlled"):
        service.update_workspace_status(imported["workspace_id"], "completed")
    service.update_release_metadata(
        release["id"], status="in_production", release_date=None
    )
    assert service.get_workspace(imported["workspace_id"], include_candidates=False)["status"] == "in_production"
    service.update_release_metadata(release["id"], status="scheduled", release_date=None)
    assert service.get_workspace(imported["workspace_id"], include_candidates=False)["status"] == "completed"
    assert any(item["id"] == release["id"] for item in service.list_releases(show_released=False))
    service.update_release_metadata(release["id"], status="released", release_date=None)
    assert service.get_workspace(imported["workspace_id"], include_candidates=False)["status"] == "completed"
    assert all(item["id"] != release["id"] for item in service.list_releases(show_released=False))

    other_data = _plan().model_dump(mode="json")
    other_data["story"] = {"story_id": "unreleased-option-test", "title": "Other"}
    other_data["beats"][0]["beat_id"] = "other-001"
    other_data["beats"][1]["beat_id"] = "other-002"
    other = service.import_plan(VisualPlan.model_validate(other_data))
    with pytest.raises(ProducerWorkflowError, match="cannot accept"):
        service.assign_workspace_release(other["workspace_id"], release["id"])

    with Session(engine) as session:
        status_events = list(
            session.scalars(
                select(ProductionEvent).where(
                    ProductionEvent.subject_id == imported["workspace_id"],
                    ProductionEvent.event_type == "workspace.status_changed",
                )
            )
        )
        assert status_events[-1].payload_json == {
            "before": {"status": "in_production"},
            "after": {"status": "completed"},
        }
        assert status_events[-1].source == "release_status_sync"
    engine.dispose()


def test_release_public_presentation_is_immutable_and_uses_available_image(
    catalog_settings: Settings,
) -> None:
    image_path = catalog_settings.root / "Library/Images/public-thumb.jpg"
    _image(image_path, "navy")
    engine = initialize_database(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    service = ProducerWorkflowService(catalog_settings, engine)
    release = service.create_release("Internal release name")
    assert service.get_release(release["id"])["presentation"] is None
    candidate = service.list_thumbnail_candidates()[0]

    first = service.create_release_presentation(
        release["id"],
        public_title="The First Public Title",
        description="First description",
        thumbnail_asset_id=candidate["asset_id"],
        change_note="Initial producer choice",
    )
    second = service.create_release_presentation(
        release["id"],
        public_title="The Better Public Title",
        description="Updated description",
        thumbnail_asset_id=candidate["asset_id"],
        change_note="Clarity pass",
    )
    detail = service.get_release(release["id"])
    assert first["sequence"] == 1 and second["sequence"] == 2
    assert detail["presentation"]["public_title"] == "The Better Public Title"
    assert [item["public_title"] for item in detail["presentation_history"]] == [
        "The Better Public Title",
        "The First Public Title",
    ]
    assert detail["presentation"]["public_title"] != detail["name"]
    with pytest.raises(ProducerWorkflowError, match="not found"):
        service.create_release_presentation(
            release["id"],
            public_title="Invalid thumbnail revision",
            description=None,
            thumbnail_asset_id=999999,
        )
    with pytest.raises(ProducerWorkflowError, match="presentation history"):
        service.delete_release(release["id"])
    with Session(engine) as session:
        asset = session.get(MediaAsset, candidate["asset_id"])
        assert asset is not None
        asset.status = "missing"
        for location in asset.locations:
            location.status = "missing"
        session.commit()
    with pytest.raises(ProducerWorkflowError, match="available image"):
        service.create_release_presentation(
            release["id"],
            public_title="Unavailable thumbnail revision",
            description=None,
            thumbnail_asset_id=candidate["asset_id"],
        )
    with Session(engine) as session:
        revisions = list(
            session.scalars(
                select(ReleasePresentationRevision).order_by(
                    ReleasePresentationRevision.sequence
                )
            )
        )
        assert [item.public_title for item in revisions] == [
            "The First Public Title",
            "The Better Public Title",
        ]
        presentation_event = next(
            event
            for event in session.scalars(
                select(ProductionEvent).where(
                    ProductionEvent.event_type == "release.presentation_revised"
                )
            )
            if event.payload_json["after"]["sequence"] == 2
        )
        assert presentation_event is not None
        assert presentation_event.payload_json["before"]["public_title"] == "The First Public Title"
        assert presentation_event.payload_json["after"]["public_title"] == "The Better Public Title"
    engine.dispose()


def test_release_and_workspace_history_guard_destructive_deletion(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    disposable = service.create_release("Disposable empty draft")
    service.delete_release(disposable["id"])
    with Session(engine) as session:
        assert session.scalar(
            select(ProductionEvent).where(
                ProductionEvent.subject_id == disposable["id"],
                ProductionEvent.event_type == "release.deleted",
            )
        ) is not None

    historical = service.create_release("Historically assigned")
    service.assign_workspace_release(imported["workspace_id"], historical["id"])
    service.assign_workspace_release(imported["workspace_id"], None)
    with pytest.raises(ProducerWorkflowError, match="assignment history"):
        service.delete_release(historical["id"])
    with pytest.raises(ProducerWorkflowError, match="assignment history"):
        service.delete_workspace(imported["workspace_id"])
    assert service.get_release(historical["id"])["name"] == "Historically assigned"
    engine.dispose()


def test_producer_requirement_override_persists_without_rewriting_plan(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)
    imported = service.import_plan(_plan(preference="image"))
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    beat = workspace["beats"][0]
    video_path = catalog_settings.root / "Library" / "Videos" / "override.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"not-a-real-video-but-a-cataloged-selection")
    sha256 = hashlib.sha256(video_path.read_bytes()).hexdigest()
    with Session(engine) as session:
        asset = MediaAsset(
            relative_path="Library/Videos/override.mp4", media_type="video", status="active",
            file_size_bytes=video_path.stat().st_size, sha256=sha256,
        )
        session.add(asset)
        session.flush()
        session.add(MediaLocation(
            media_asset_id=asset.id, relative_path="Library/Videos/override.mp4",
            status="available", provenance_type="local_import", file_size_bytes=video_path.stat().st_size,
        ))
        session.commit()
        asset_id = asset.id
    with pytest.raises(ProducerWorkflowError, match="currently prefers an image"):
        service.select_asset(workspace["workspace_id"], beat["id"], asset_id)
    service.select_asset(workspace["workspace_id"], beat["id"], asset_id, override_media_preference=True)
    service.update_beat_requirements(
        workspace["workspace_id"], beat["id"], media_preference="video", source_requirement="exact"
    )
    refreshed = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert refreshed["beats"][0]["selected"]["asset_id"] == asset_id
    assert refreshed["beats"][0]["specification"]["media_preference"] == "video"
    assert refreshed["beats"][0]["specification"]["source_requirement"] == "exact"
    with Session(engine) as session:
        assert session.get(ProducerWorkspace, workspace["workspace_id"]).plan_json["beats"][0]["media_preference"] == "image"
    storyboard = service.generate_storyboard(workspace["workspace_id"])
    assert b"video / exact" in Path(storyboard["storyboard_path"]).read_bytes()
    engine.dispose()


def test_edit_folder_order_fallback_and_storyboard_with_unselected_beat(
    catalog_settings: Settings,
) -> None:
    master = catalog_settings.root / "Library/Images/dark-fireplace.jpg"
    original = _image(master, "black")
    engine, service, imported = _setup(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    asset_id = service.catalog.search_media(
        __import__("yt_visuals.services", fromlist=["SearchMediaRequest"]).SearchMediaRequest(
            query="dark fireplace", limit=3
        )
    ).candidates[0].asset_id
    for beat in workspace["beats"]:
        service.select_asset(workspace["workspace_id"], beat["id"], asset_id)

    copied: list[str] = []
    def unavailable_link(source, destination) -> None:  # type: ignore[no-untyped-def]
        raise OSError("hard links unavailable")
    def copy_file(source, destination):  # type: ignore[no-untyped-def]
        copied.append(Path(destination).name)
        return __import__("shutil").copy2(source, destination)

    built = service.build_edit_folder(
        workspace["workspace_id"], linker=unavailable_link, copier=copy_file
    )
    filenames = [row["filename"] for row in built["entries"]]
    assert filenames[0].startswith("001-") and filenames[1].startswith("002-")
    assert copied == filenames
    assert master.read_bytes() == original
    edit_root = Path(built["edit_folder"])
    assert sorted(path.name for path in (edit_root / "Visuals").iterdir()) == sorted(filenames)
    with (edit_root / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    assert [row["beat_id"] for row in manifest] == ["beat-001", "beat-002"]
    assert all(row["transfer_mode"] == "copy" for row in manifest)
    assert hashlib.sha256(master.read_bytes()).digest() == hashlib.sha256(original).digest()

    service.clear_selection(workspace["workspace_id"], workspace["beats"][1]["id"])
    storyboard = service.generate_storyboard(workspace["workspace_id"])
    assert storyboard["pages"] == 3
    assert Path(storyboard["storyboard_path"]).stat().st_size > 0
    assert master.read_bytes() == original
    engine.dispose()


def test_edit_plan_import_choices_review_invalidation_and_handoff(
    catalog_settings: Settings,
) -> None:
    first_path = catalog_settings.root / "Library/Images/dark-fireplace.jpg"
    second_path = catalog_settings.root / "Library/Images/alternate-fireplace.jpg"
    _image(first_path, "black")
    _image(second_path, "maroon")
    engine, service, imported = _setup(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    workspace = service.get_workspace(imported["workspace_id"], include_candidates=False)
    assets = service.search_existing_media("fireplace")
    first_asset = assets[0]["asset_id"]
    second_asset = assets[1]["asset_id"]
    for beat in workspace["beats"]:
        service.select_asset(workspace["workspace_id"], beat["id"], first_asset)

    result = service.import_edit_plan(workspace["workspace_id"], _edit_plan())
    assert result["beats"] == 2
    generated_handoff = catalog_settings.root / "Projects/producer-story/Edit/edit_plan.json"
    assert generated_handoff.is_file()
    detail = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    first_guidance = detail["beats"][0]["edit_guidance"]
    assert first_guidance["motion_recommendation"]["type"] == "slow_zoom_in"
    assert first_guidance["producer_motion_type"] == "slow_zoom_in"
    assert first_guidance["needs_review"] is False

    service.select_asset(
        workspace["workspace_id"], workspace["beats"][0]["id"], first_asset
    )
    unchanged = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert unchanged["beats"][0]["edit_guidance"]["needs_review"] is False

    incompatible_document = _edit_plan().model_dump(mode="json")
    incompatible_document["beats"][0]["motion_recommendation"]["type"] = "native"
    with pytest.raises(ProducerWorkflowError, match="uses an image"):
        service.import_edit_plan(
            workspace["workspace_id"], EditPlan.model_validate(incompatible_document)
        )

    service.update_edit_guidance_choice(
        workspace["workspace_id"],
        workspace["beats"][0]["id"],
        motion_type="pan_right",
        motion_target="mantel clock",
        transition_type="cut",
    )
    with Session(engine) as session:
        stored = session.get(ProducerBeat, workspace["beats"][0]["id"])
        assert stored is not None
        assert stored.edit_motion_recommendation_json["type"] == "slow_zoom_in"
        assert stored.producer_motion_type == "pan_right"
    assert json.loads(generated_handoff.read_text(encoding="utf-8"))["beats"][0][
        "motion"
    ]["type"] == "pan_right"

    service.select_asset(
        workspace["workspace_id"], workspace["beats"][0]["id"], second_asset
    )
    changed = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert changed["beats"][0]["edit_guidance"]["needs_review"] is True
    assert changed["beats"][1]["edit_guidance"]["needs_review"] is False

    built = service.build_edit_folder(workspace["workspace_id"])
    handoff_path = Path(built["edit_plan_path"])
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert handoff["document_type"] == "producer_edit_plan"
    assert handoff["beats"][0]["motion"] == {
        "type": "pan_right", "target": "mantel clock"
    }
    assert handoff["beats"][0]["transition_out"]["type"] == "cut"
    assert handoff["beats"][0]["selected_visual"]["edit_path"].startswith("Visuals/")
    assert handoff["beats"][0]["needs_review"] is True

    storyboard = service.generate_storyboard(workspace["workspace_id"])
    pdf = Path(storyboard["storyboard_path"]).read_bytes()
    assert b"Producer motion" in pdf and b"Pan Right" in pdf
    assert b"NEEDS REVIEW" in pdf

    service.reset_edit_guidance_choice(
        workspace["workspace_id"], workspace["beats"][0]["id"]
    )
    reset = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert reset["beats"][0]["edit_guidance"]["producer_motion_type"] == "slow_zoom_in"
    assert reset["beats"][0]["edit_guidance"]["needs_review"] is False
    assert any(event["event_type"] == "workspace.edit_plan_imported" for event in reset["history"])
    engine.dispose()


def test_edit_plan_requires_exact_workspace_identity_and_selected_visuals(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    with pytest.raises(ProducerWorkflowError, match="select a visual"):
        service.import_edit_plan(imported["workspace_id"], _edit_plan())

    wrong_story = _edit_plan().model_copy(
        update={"story": _edit_plan().story.model_copy(update={"story_id": "wrong-story"})}
    )
    with pytest.raises(ProducerWorkflowError, match="story ID"):
        service.import_edit_plan(imported["workspace_id"], wrong_story)

    reversed_beats = _edit_plan().model_copy(update={"beats": tuple(reversed(_edit_plan().beats))})
    with pytest.raises(ProducerWorkflowError, match="exactly match"):
        service.import_edit_plan(imported["workspace_id"], reversed_beats)
    engine.dispose()


def test_story_documents_are_versioned_outside_media_catalog_and_deleted_with_workspace(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    workspace_id = imported["workspace_id"]
    temp = catalog_settings.root / "Temp"
    script_pdf = temp / "script-one.pdf"
    script_pdf.write_bytes(b"%PDF-1.4\nfirst script")
    first = service.upload_story_document(
        workspace_id, "narration_script", script_pdf, "Original Script.pdf"
    )
    script_docx = temp / "script-two.docx"
    second_content = _docx(script_docx, "replacement")
    second = service.upload_story_document(
        workspace_id, "narration_script", script_docx, "Revised Script.docx"
    )
    narrator = temp / "narrator.pdf"
    narrator.write_bytes(b"%PDF-1.7\nnarrator copy")
    service.upload_story_document(
        workspace_id, "narrator_copy", narrator, "Narrator Final.pdf"
    )
    subtitles = temp / "subtitles.txt"
    subtitles.write_text("Opening subtitle\n", encoding="utf-8")
    service.upload_story_document(
        workspace_id, "subtitles", subtitles, "subtitles.txt"
    )
    notes = temp / "notes.rtf"
    notes.write_bytes(b"{\\rtf1 Production notes}")
    service.upload_story_document(workspace_id, "other", notes, "Notes.rtf")

    assert first["version"] == 1 and second["version"] == 2
    detail = service.get_workspace(workspace_id, include_candidates=False)
    script_group = next(
        item for item in detail["documents"] if item["document_type"] == "narration_script"
    )
    assert script_group["current"]["id"] == second["id"]
    assert [item["version"] for item in script_group["versions"]] == [2, 1]
    assert script_group["versions"][1]["original_filename"] == "Original Script.pdf"
    documents_root = catalog_settings.root / "Projects/producer-story/Documents"
    stored = sorted(documents_root.iterdir())
    assert len(stored) == 5
    assert any(path.read_bytes() == b"%PDF-1.4\nfirst script" for path in stored)
    assert any(path.read_bytes() == second_content for path in stored)
    path, view = service.story_document_path(workspace_id, first["id"])
    assert path.read_bytes() == b"%PDF-1.4\nfirst script"
    assert view["original_filename"] == "Original Script.pdf"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0
        assert session.scalar(select(func.count()).select_from(StoryDocumentVersion)) == 5
        event_types = list(
            session.scalars(
                select(ProductionEvent.event_type).where(
                    ProductionEvent.subject_id == workspace_id,
                    ProductionEvent.event_type.in_(
                        ["workspace.document_uploaded", "workspace.document_replaced"]
                    ),
                )
            )
        )
        assert event_types.count("workspace.document_uploaded") == 4
        assert event_types.count("workspace.document_replaced") == 1

    service.delete_workspace(workspace_id)
    assert not documents_root.parent.exists()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StoryDocumentVersion)) == 0
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0
    engine.dispose()


def test_story_document_validation_and_trusted_paths(
    catalog_settings: Settings,
) -> None:
    engine, service, imported = _setup(catalog_settings)
    workspace_id = imported["workspace_id"]
    temp = catalog_settings.root / "Temp"
    invalid_pdf = temp / "invalid.pdf"
    invalid_pdf.write_bytes(b"not a pdf")
    with pytest.raises(ProducerWorkflowError, match="valid PDF"):
        service.upload_story_document(
            workspace_id, "narration_script", invalid_pdf, "invalid.pdf"
        )
    text = temp / "copy.txt"
    text.write_text("copy", encoding="utf-8")
    with pytest.raises(ProducerWorkflowError, match="accepts only"):
        service.upload_story_document(workspace_id, "narrator_copy", text, "copy.txt")
    executable = temp / "notes.exe"
    executable.write_bytes(b"MZ")
    with pytest.raises(ProducerWorkflowError, match="accepts only"):
        service.upload_story_document(workspace_id, "other", executable, "notes.exe")

    uploaded = service.upload_story_document(
        workspace_id, "subtitles", text, "../../safe-subtitles.txt"
    )
    assert uploaded["original_filename"] == "safe-subtitles.txt"
    with Session(engine) as session:
        row = session.get(StoryDocumentVersion, uploaded["id"])
        assert row is not None
        row.stored_filename = "../../outside.txt"
        with pytest.raises(DatabaseError, match="immutable"):
            session.commit()
        session.rollback()
    with pytest.raises(ProducerWorkflowError, match="escaped"):
        service.story_documents_folder("../../outside")
    engine.dispose()
