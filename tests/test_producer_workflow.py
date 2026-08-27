from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import yt_visuals.producer.service as producer_service_module

from yt_visuals.acquisition import AcquisitionService
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.library import LibraryScanner
from yt_visuals.models import (
    MediaAsset,
    MediaDownload,
    MediaSource,
    ProducerBeatHiddenAsset,
)
from yt_visuals.producer.contracts import VisualPlan
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
