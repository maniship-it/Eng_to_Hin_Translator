"""Settings loading, saving and conversion to engine options."""

from __future__ import annotations

import json

from setu.config import Settings


class TestSettings:
    def test_defaults_are_sane(self):
        settings = Settings()
        assert settings.beam_size >= 1
        assert settings.max_batch_size >= 1
        assert settings.protect_entities is True

    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Settings, "path", classmethod(
            lambda cls: tmp_path / "settings.json"))
        original = Settings(beam_size=6, font_size=15, hindi_font_family="Mangal")
        original.save()
        loaded = Settings.load()
        assert loaded.beam_size == 6
        assert loaded.font_size == 15
        assert loaded.hindi_font_family == "Mangal"

    def test_missing_file_gives_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Settings, "path", classmethod(
            lambda cls: tmp_path / "absent.json"))
        assert Settings.load().beam_size == Settings().beam_size

    def test_corrupt_file_gives_defaults(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text("{not json at all", encoding="utf-8")
        monkeypatch.setattr(Settings, "path", classmethod(lambda cls: path))
        assert Settings.load().beam_size == Settings().beam_size

    def test_unknown_keys_are_ignored(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"beam_size": 3, "nonsense": True}),
                        encoding="utf-8")
        monkeypatch.setattr(Settings, "path", classmethod(lambda cls: path))
        settings = Settings.load()
        assert settings.beam_size == 3
        assert not hasattr(settings, "nonsense")

    def test_wrongly_typed_values_are_dropped(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"beam_size": "not a number"}), encoding="utf-8")
        monkeypatch.setattr(Settings, "path", classmethod(lambda cls: path))
        assert Settings.load().beam_size == Settings().beam_size

    def test_saving_to_an_unwritable_path_does_not_raise(self, tmp_path, monkeypatch):
        blocked = tmp_path / "file"
        blocked.write_text("", encoding="utf-8")
        monkeypatch.setattr(Settings, "path", classmethod(
            lambda cls: blocked / "settings.json"))
        Settings().save()  # must not raise


class TestToOptions:
    def test_values_carry_across(self):
        options = Settings(beam_size=5, max_batch_size=32).to_options()
        assert options.beam_size == 5
        assert options.max_batch_size == 32

    def test_out_of_range_values_are_clamped(self):
        assert Settings(beam_size=999).to_options().beam_size == 10
        assert Settings(beam_size=0).to_options().beam_size == 1
        assert Settings(max_batch_size=0).to_options().max_batch_size == 1

    def test_empty_compute_type_falls_back(self):
        assert Settings(compute_type="").to_options().compute_type == "int8"
