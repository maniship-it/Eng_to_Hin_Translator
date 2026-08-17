"""Model discovery and directory-layout handling."""

from __future__ import annotations

import json

import pytest

from setu import model as model_module


def _make_model_tree(root, spm_name="sentencepiece.model", nested=True):
    """Create a directory that looks like an installed model."""
    ct2 = root / "model" if nested else root
    ct2.mkdir(parents=True, exist_ok=True)
    (ct2 / "model.bin").write_bytes(b"\x00")
    (ct2 / "shared_vocabulary.json").write_text("[]", encoding="utf-8")
    (root / spm_name).write_bytes(b"\x00")
    return root


class TestDiscovery:
    def test_finds_a_nested_ct2_directory(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi")
        paths = model_module.resolve_model(root)
        assert paths.ct2_dir == root / "model"
        assert paths.source_spm == root / "sentencepiece.model"

    def test_finds_a_flat_ct2_directory(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi", nested=False)
        paths = model_module.resolve_model(root)
        assert paths.ct2_dir == root

    def test_accepts_alternative_sentencepiece_names(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi", spm_name="sp_model.model")
        paths = model_module.resolve_model(root)
        assert paths.source_spm.name == "sp_model.model"

    def test_target_model_defaults_to_the_source_model(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi")
        paths = model_module.resolve_model(root)
        assert paths.target_spm == paths.source_spm

    def test_separate_target_model_is_used(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi", spm_name="source.spm.model")
        (root / "target.spm.model").write_bytes(b"\x00")
        paths = model_module.resolve_model(root)
        assert paths.source_spm.name == "source.spm.model"
        assert paths.target_spm.name == "target.spm.model"

    def test_metadata_is_read(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi")
        (root / "metadata.json").write_text(
            json.dumps({"target_prefix_token": ">>hin<<"}), encoding="utf-8"
        )
        paths = model_module.resolve_model(root)
        assert paths.target_prefix_token == ">>hin<<"

    def test_missing_metadata_is_fine(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi")
        assert model_module.resolve_model(root).target_prefix_token is None

    def test_corrupt_metadata_is_ignored(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi")
        (root / "metadata.json").write_text("{not json", encoding="utf-8")
        assert model_module.resolve_model(root).metadata == {}

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(model_module.ModelNotFoundError):
            model_module.resolve_model(tmp_path / "nope")

    def test_directory_without_a_model_raises(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(model_module.ModelLoadError):
            model_module.resolve_model(tmp_path / "empty")

    def test_missing_sentencepiece_raises(self, tmp_path):
        root = tmp_path / "en_hi" / "model"
        root.mkdir(parents=True)
        (root / "model.bin").write_bytes(b"\x00")
        with pytest.raises(model_module.ModelLoadError):
            model_module.resolve_model(tmp_path / "en_hi")

    def test_is_model_dir(self, tmp_path):
        root = _make_model_tree(tmp_path / "en_hi")
        assert model_module.is_model_dir(root)
        assert not model_module.is_model_dir(tmp_path / "missing")

    def test_discover_prefers_the_explicit_directory(self, tmp_path):
        root = _make_model_tree(tmp_path / "custom")
        assert model_module.discover_model_dir([root]) == root

    def test_discover_uses_the_environment_variable(self, tmp_path, monkeypatch):
        root = _make_model_tree(tmp_path / "from_env")
        monkeypatch.setenv(model_module.MODEL_ENV_VAR, str(root))
        assert model_module.discover_model_dir() == root

    def test_discover_reports_where_it_looked(self, tmp_path, monkeypatch):
        monkeypatch.setenv(model_module.MODEL_ENV_VAR, str(tmp_path / "absent"))
        monkeypatch.setattr(model_module, "app_root", lambda: tmp_path / "app")
        monkeypatch.setattr(model_module, "user_data_dir", lambda: tmp_path / "user")
        with pytest.raises(model_module.ModelNotFoundError) as info:
            model_module.discover_model_dir()
        assert "absent" in str(info.value)


class TestComputeType:
    def test_pick_falls_back_to_something_supported(self, monkeypatch):
        monkeypatch.setattr(
            model_module, "supported_compute_types", lambda device="cpu": ["float32"]
        )
        assert model_module.pick_compute_type("int8") == "float32"

    def test_pick_honours_a_supported_request(self, monkeypatch):
        monkeypatch.setattr(
            model_module, "supported_compute_types",
            lambda device="cpu": ["int8", "float32"],
        )
        assert model_module.pick_compute_type("int8") == "int8"
