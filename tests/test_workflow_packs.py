import json
from pathlib import Path

from app.core import workflow_packs


def test_z_image_pack_declares_minimal_dependencies():
    manifest = workflow_packs.get_workflow_pack("z-image-turbo")
    models = manifest["models"]

    assert manifest["recommended"] is True
    assert {model["folder"] for model in models} == {"diffusion_models", "text_encoders", "vae"}
    assert {model["filename"] for model in models} == {
        "z_image_turbo_bf16.safetensors",
        "qwen_3_4b.safetensors",
        "ae.safetensors",
    }


def test_default_z_image_workflow_uses_no_lora():
    root = Path(__file__).resolve().parents[1]
    workflow = json.loads((root / "workflows" / "defaults" / "image_z_image_turbo.json").read_text())
    class_types = {node.get("class_type") for node in workflow.values()}

    assert "LoraLoaderModelOnly" not in class_types
    assert workflow["69"]["inputs"]["model"] == ["66", 0]


def test_fresh_default_config_only_exposes_starter_tool():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "workflows" / "defaults" / "workflows-config.json").read_text())

    assert [tool["id"] for tool in config["tools"]] == ["z-image"]
    assert config["tools"][0]["workflowFile"] == "image_z_image_turbo.json"


def test_models_root_prefers_explicit_or_managed_path(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    managed = tmp_path / "ComfyUI"
    (managed / "models").mkdir(parents=True)
    monkeypatch.setenv("ORANGE_COMFYUI_DIR", str(managed))

    assert workflow_packs.resolve_models_root(str(explicit)) == str(explicit.resolve())
    assert workflow_packs.resolve_models_root() == str((managed / "models").resolve())


def test_pack_installer_skips_existing_files_and_downloads_missing(tmp_path, monkeypatch):
    models_root = tmp_path / "models"
    models_root.mkdir()
    existing = models_root / "vae" / "ae.safetensors"
    existing.parent.mkdir()
    existing.write_bytes(b"already here")

    downloaded = []

    def fake_download(url, destination):
        Path(destination).write_bytes(b"downloaded")
        downloaded.append(Path(destination).name)

    monkeypatch.setattr(workflow_packs, "_download_file", fake_download)
    result = workflow_packs.install_workflow_pack("z-image-turbo", str(models_root))

    assert result["failures"] == []
    assert existing.as_posix() in [Path(path).as_posix() for path in result["skipped"]]
    assert set(downloaded) == {"z_image_turbo_bf16.safetensors", "qwen_3_4b.safetensors"}
