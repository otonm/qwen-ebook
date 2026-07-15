"""Unit tests for app.config.load_settings().

Phase 6 (CFG-06): OUTPUT_FORMAT was retired as a global setting — output
format is now a per-project Project.output_format DB column, validated at
the PATCH boundary against app.audio_join.CODEC_TABLE (see
test_project_config.py), not at settings-load time.
"""

from __future__ import annotations

from app.config import load_settings


def test_load_settings_honors_persistent_data_volume_overrides(monkeypatch):
    """T-03-20: the Quadlet unit/run-local.sh point DATABASE_URL/UPLOAD_DIR/
    OUTPUT_DIR at the persistent /data volume — prove those env overrides are
    actually honored and that PREVIEW_DIR derives from the overridden
    OUTPUT_DIR, not the image-baked default.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite:////data/projects.db")
    monkeypatch.setenv("UPLOAD_DIR", "/data/uploads")
    monkeypatch.setenv("OUTPUT_DIR", "/data/output")

    settings = load_settings()

    assert settings.DATABASE_URL == "sqlite:////data/projects.db"
    assert settings.UPLOAD_DIR == "/data/uploads"
    assert settings.OUTPUT_DIR == "/data/output"
    assert settings.PREVIEW_DIR == "/data/output/previews"
