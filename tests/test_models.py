from __future__ import annotations

from sqlalchemy.orm import Session

from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.models import (
    AssetLicense,
    AssetUsage,
    MediaAsset,
    MediaProvider,
    MediaSource,
    Project,
    Story,
    Tag,
)


def test_basic_catalog_relationships_and_usage_counters(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)

    with Session(engine) as session:
        provider = MediaProvider(name="Example Stock", website_url="https://example.test")
        tag = Tag(name="forest")
        project = Project(
            slug="episode-001",
            title="Episode 1",
            season_number=1,
            episode_number=1,
            project_path="Projects/Episode-001",
        )
        story = Story(position=1, title="Forest Story", target_duration_seconds=360)
        project.stories.append(story)

        asset = MediaAsset(
            relative_path="Library/Images/forest.jpg",
            media_type="image",
            mime_type="image/jpeg",
            file_size_bytes=12345,
            sha256="a" * 64,
            width=1920,
            height=1080,
        )
        asset.tags.append(tag)
        asset.sources.append(
            MediaSource(
                provider=provider,
                provider_asset_id="asset-42",
                source_url="https://example.test/assets/42",
                creator_name="Example Creator",
                original_filename="forest-original.jpg",
            )
        )
        asset.license = AssetLicense(
            license_name="Example License",
            attribution_required=True,
            attribution_text="Example Creator / Example Stock",
            commercial_use_allowed=True,
        )
        asset.usages.append(
            AssetUsage(
                story=story,
                segment_label="Opening",
                narration_start_ms=0,
                narration_end_ms=8000,
                usage_role="b-roll",
            )
        )
        session.add_all([asset, project])
        session.commit()
        session.refresh(asset)

        assert asset.usage_count == 1
        assert asset.last_used_at is not None
        assert asset.tags[0].name == "forest"
        assert asset.sources[0].provider is provider
        assert asset.license is not None
        assert asset.license.attribution_required is True
        assert asset.usages[0].story.project is project

        session.delete(asset.usages[0])
        session.commit()
        session.refresh(asset)
        assert asset.usage_count == 0
        assert asset.last_used_at is None

    engine.dispose()

