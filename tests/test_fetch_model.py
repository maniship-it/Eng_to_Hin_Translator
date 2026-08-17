"""Installing a model from an .argosmodel archive.

The download itself needs the internet and is not tested here; the extraction
and layout-normalisation that follow it are, because that is where a
mis-shaped archive would break the application.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import fetch_model  # noqa: E402


def make_archive(path: Path, root_name: str = "translate-en_hi-1_1",
                 spm_name: str = "sentencepiece.model",
                 include_spm: bool = True,
                 include_model_bin: bool = True) -> Path:
    """Build an archive shaped like a real Argos package."""
    with zipfile.ZipFile(path, "w") as archive:
        if include_model_bin:
            archive.writestr("%s/model/model.bin" % root_name, b"\x00binary")
            archive.writestr("%s/model/shared_vocabulary.json" % root_name, "[]")
            archive.writestr("%s/model/config.json" % root_name, "{}")
        if include_spm:
            archive.writestr("%s/%s" % (root_name, spm_name), b"\x00spm")
        archive.writestr("%s/metadata.json" % root_name,
                         '{"package_version": "1.1", "from_code": "en"}')
    return path


class TestInstall:
    def test_normalises_the_layout(self, tmp_path):
        archive = make_archive(tmp_path / "pkg.argosmodel")
        destination = tmp_path / "models" / "en_hi"
        fetch_model.install(archive, destination)

        assert (destination / "model" / "model.bin").is_file()
        assert (destination / "model" / "shared_vocabulary.json").is_file()
        assert (destination / "sentencepiece.model").is_file()
        assert (destination / "metadata.json").is_file()

    def test_the_result_is_a_model_directory_the_app_accepts(self, tmp_path):
        from setu import model as model_module

        archive = make_archive(tmp_path / "pkg.argosmodel")
        destination = tmp_path / "models" / "en_hi"
        fetch_model.install(archive, destination)

        assert model_module.is_model_dir(destination)
        paths = model_module.resolve_model(destination)
        assert paths.ct2_dir == destination / "model"
        assert paths.source_spm == destination / "sentencepiece.model"

    def test_written_metadata_records_the_language_pair(self, tmp_path):
        import json

        archive = make_archive(tmp_path / "pkg.argosmodel")
        destination = tmp_path / "en_hi"
        fetch_model.install(archive, destination)

        metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["source"] == "en"
        assert metadata["target"] == "hi"
        assert metadata["target_prefix_token"] is None
        assert metadata["source_package_metadata"]["from_code"] == "en"

    @pytest.mark.parametrize("spm_name", ["sentencepiece.model", "sp_model.model",
                                          "spm.model", "source.spm.model"])
    def test_accepts_alternative_tokenizer_names(self, tmp_path, spm_name):
        archive = make_archive(tmp_path / "pkg.argosmodel", spm_name=spm_name)
        destination = tmp_path / "en_hi"
        fetch_model.install(archive, destination)
        assert (destination / "sentencepiece.model").is_file()

    def test_replaces_an_existing_installation(self, tmp_path):
        destination = tmp_path / "en_hi"
        destination.mkdir(parents=True)
        stale = destination / "stale.txt"
        stale.write_text("old", encoding="utf-8")

        archive = make_archive(tmp_path / "pkg.argosmodel")
        fetch_model.install(archive, destination)

        assert not stale.exists()
        assert (destination / "model" / "model.bin").is_file()

    def test_archive_without_a_model_is_rejected(self, tmp_path):
        archive = make_archive(tmp_path / "bad.argosmodel", include_model_bin=False)
        with pytest.raises(SystemExit, match="model.bin"):
            fetch_model.install(archive, tmp_path / "en_hi")

    def test_archive_without_a_tokenizer_is_rejected(self, tmp_path):
        archive = make_archive(tmp_path / "bad.argosmodel", include_spm=False)
        with pytest.raises(SystemExit, match="SentencePiece"):
            fetch_model.install(archive, tmp_path / "en_hi")

    def test_a_non_zip_file_is_reported_clearly(self, tmp_path):
        archive = tmp_path / "broken.argosmodel"
        archive.write_text("<html>404 Not Found</html>", encoding="utf-8")
        with pytest.raises(SystemExit, match="not a valid"):
            fetch_model.install(archive, tmp_path / "en_hi")

    def test_path_traversal_is_refused(self, tmp_path):
        archive = tmp_path / "evil.argosmodel"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../../escaped.txt", "nope")
            handle.writestr("pkg/model/model.bin", b"\x00")
        with pytest.raises(SystemExit, match="unsafe path"):
            fetch_model.install(archive, tmp_path / "en_hi")
        assert not (tmp_path.parent / "escaped.txt").exists()


class TestChecksum:
    def test_sha256_is_stable(self, tmp_path):
        path = tmp_path / "file.bin"
        path.write_bytes(b"hello world")
        expected = (
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        )
        assert fetch_model.sha256(path) == expected
