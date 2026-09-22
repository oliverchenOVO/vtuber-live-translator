from __future__ import annotations

import io
import asyncio
import json
import logging
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.audio.base import AudioSource
from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.database.database import Database
from vlt.product.cache import CacheManager
from vlt.product.compatibility import supports_process_loopback
from vlt.product.downloads import download_resumable, sha256
from vlt.product.hardware import HardwareProfile, preset, recommended_preset
from vlt.product.models import ModelManager
from vlt.product.paths import ProductPaths
from vlt.product.logging_setup import configure_logging
from vlt.product.single_instance import SingleInstance
from vlt.product.updates import UpdateChecker
from vlt.product.windowing import normalize_geometry
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager
from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend
from vlt.version import __version__


def test_version_is_release_version_and_pyproject_is_dynamic():
    assert __version__ == "1.0.0"
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in project
    assert 'attr = "vlt.version.__version__"' in project
    build = Path("scripts/build_release.ps1").read_text(encoding="utf-8")
    installer = Path("installer/VtuberLiveTranslator.iss").read_text(encoding="utf-8")
    assert "packaging\\version_info.txt" in build
    assert "/DMyAppVersion=$Version" in build
    assert "MyAppVersion must be supplied" in installer


def test_product_paths_create_structured_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("VLT_DATA_DIR", str(tmp_path / "data"))
    paths = ProductPaths.discover()
    paths.ensure()
    assert all(folder.is_dir() for folder in
               (paths.sessions, paths.models, paths.cache, paths.logs, paths.runtime))


def test_legacy_diarization_models_migrate_without_deletion(tmp_path, monkeypatch):
    monkeypatch.setenv("VLT_DATA_DIR", str(tmp_path))
    old = tmp_path / "diarization-models"
    old.mkdir()
    (old / "segmentation.onnx").write_bytes(b"model")
    paths = ProductPaths.discover()
    paths.ensure()
    assert (paths.models / "diarization" / "segmentation.onnx").read_bytes() == b"model"


def test_performance_presets_change_real_backend_settings():
    gaming, quality = preset("gaming"), preset("quality")
    low = FasterWhisperBackend(gaming["asr_model"], device=gaming["asr_device"],
                               cpu_threads=gaming["cpu_threads"])
    high = FasterWhisperBackend(quality["asr_model"], device=quality["asr_device"],
                                cpu_threads=quality["cpu_threads"])
    assert (low.model_name, low.device, low.cpu_threads) == ("base", "cpu", 2)
    assert (high.model_name, high.cpu_threads) == ("small", 6)
    assert not gaming["translation_fallback"] and quality["translation_fallback"]
    assert gaming["diarization_interval_ms"] > quality["diarization_interval_ms"]


def test_hardware_recommendations_cover_low_and_high_profiles():
    assert recommended_preset(HardwareProfile("cpu", 4, 8, "none", 0, False)) == "gaming"
    assert recommended_preset(HardwareProfile("cpu", 16, 32, "gpu", 12, True)) == "quality"


def test_first_run_and_startup_preferences_persist(tmp_path):
    settings = SettingsManager(tmp_path)
    settings.set("first_run_complete", True)
    settings.set("performance_preset", "gaming")
    settings.set("minimize_to_tray", False)
    settings.set("start_minimized", True)
    settings.set("remember_audio_source", False)
    settings.set("show_overlay_on_start", True)
    loaded = SettingsManager(tmp_path)
    assert loaded.values["first_run_complete"] is True
    assert loaded.values["performance_preset"] == "gaming"
    assert loaded.values["minimize_to_tray"] is False
    assert loaded.values["start_minimized"] is True
    assert loaded.values["remember_audio_source"] is False
    assert loaded.values["show_overlay_on_start"] is True


class _Response(io.BytesIO):
    status = 206
    headers = {"Content-Length": "3"}
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        self.close()


def test_model_download_resumes_and_verifies_checksum(tmp_path):
    target = tmp_path / "model.bin"
    target.with_suffix(".bin.part").write_bytes(b"abc")
    seen = {}
    def opener(request, timeout):
        seen["range"] = request.headers["Range"]
        return _Response(b"def")
    expected = "bef57ec7f53a6d40beb640a780a639c83bc29ac8a9816f1fc6c5c6dcd93c4721"
    download_resumable("https://example.invalid/model", target, expected, opener=opener)
    assert seen["range"] == "bytes=3-"
    assert target.read_bytes() == b"abcdef"


def test_bad_model_checksum_removes_partial(tmp_path):
    target = tmp_path / "bad.bin"
    with pytest.raises(RuntimeError):
        download_resumable("https://example.invalid/bad", target, "0" * 64,
                           opener=lambda *_args, **_kwargs: _Response(b"bad"))
    assert not target.with_suffix(".bin.part").exists()


def test_cache_manager_prunes_to_fixed_limit(tmp_path):
    manager = CacheManager(tmp_path, maximum_bytes=10)
    (tmp_path / "one").write_bytes(b"a" * 8)
    (tmp_path / "two").write_bytes(b"b" * 8)
    removed = manager.prune()
    assert removed == 8 and manager.size() == 8


def test_model_manager_detects_local_models(tmp_path):
    models, cache, runtime = tmp_path / "models", tmp_path / "cache", tmp_path / "runtime"
    assert ModelManager(models, cache, runtime).status()["asr"] is False
    (models / "whisper").mkdir(parents=True)
    (models / "whisper" / "model.bin").write_bytes(b"x")
    (models / "diarization").mkdir()
    (models / "diarization" / "segmentation.onnx").write_bytes(b"x")
    status = ModelManager(models, cache, runtime).status()
    assert status["asr"] and status["diarization"]


def test_model_manager_removes_asr_and_diarization_payloads(tmp_path):
    manager = ModelManager(tmp_path / "models", tmp_path / "cache", tmp_path / "runtime")
    asr = manager.root / "models--Systran--faster-whisper-base"
    diar = manager.root / "diarization"
    asr.mkdir(parents=True)
    diar.mkdir()
    (asr / "model.bin").write_bytes(b"model")
    (diar / "segmentation.onnx").write_bytes(b"model")

    manager.remove("asr")
    manager.remove("diarization")

    assert not asr.exists()
    assert not diar.exists()


def test_model_install_checks_expanded_disk_requirement(tmp_path, monkeypatch):
    manager = ModelManager(tmp_path / "models", tmp_path / "cache", tmp_path / "runtime")
    monkeypatch.setattr(manager, "ollama_executable", lambda: None)
    monkeypatch.setattr("vlt.product.models.has_disk_space", lambda *_args, **_kwargs: False)
    with pytest.raises(RuntimeError, match="7.0 GB"):
        manager.install_ollama(lambda *_args: None)


def test_gaming_translation_never_invokes_7b_fallback():
    backend = OllamaTranslationBackend(allow_fallback=False)
    calls = []
    def fail(_prompt, model):
        calls.append(model)
        raise RuntimeError("offline")
    backend._generate = fail
    request = TranslationRequest("s", "昨日", "ja", "zh-TW", "natural", (), (), True)
    with pytest.raises(RuntimeError):
        backend.translate_final(request)
    assert calls == ["qwen2.5:1.5b"]


def test_custom_session_root_preserves_database_history(tmp_path):
    db = Database(tmp_path / "app.db")
    custom = tmp_path / "external-sessions"
    manager = SessionManager(tmp_path, db, session_root=custom)
    created = manager.create("產品測試")
    assert Path(created["folder_path"]).parent == custom
    assert manager.get(created["session_id"])["title"] == "產品測試"
    db.close()


def test_update_checker_is_safe_when_source_is_not_configured():
    result = UpdateChecker().check(__version__)
    assert not result.available
    assert "尚未設定" in result.message


def test_installer_preserves_user_data_by_default():
    script = Path("installer/VtuberLiveTranslator.iss").read_text(encoding="utf-8")
    assert "UninstallSilent" in script
    assert "DelTree(DataPath" in script
    assert "PrivilegesRequired=lowest" in script
    assert "desktopicon" in script


def test_product_ui_has_wizard_and_no_phase_preview_labels():
    qml = Path("src/vlt/ui/qml/Main.qml").read_text(encoding="utf-8")
    assert "準備 AI 元件" in qml and "測試程式音訊" in qml
    assert "PHASE 6" not in qml and "Windows preview" not in qml


def test_overlay_geometry_recovers_from_removed_monitor():
    default = (500, 700, 800, 120)
    assert normalize_geometry({"x": 2000, "y": 0, "width": 800, "height": 120},
                              [(0, 0, 1920, 1080)], default) == default
    assert normalize_geometry({"x": 100, "y": 100, "width": 800, "height": 120},
                              [(0, 0, 1920, 1080)], default) == (100, 100, 800, 120)


def test_overlay_geometry_and_dpi_state_persist(tmp_path):
    settings = SettingsManager(tmp_path)
    saved = {"x": 220, "y": 180, "width": 960, "height": 144}
    settings.set("overlay_geometry", saved)
    assert SettingsManager(tmp_path).values["overlay_geometry"] == saved


def test_unsupported_windows_build_has_readable_error(monkeypatch):
    assert not supports_process_loopback(19045)
    assert supports_process_loopback(20348)
    backend = WindowsProcessLoopback()
    backend._selected = AudioSource("1", "test.exe", "process", 1, True, 1.0)
    monkeypatch.setattr("vlt.audio.windows_process_loopback.platform.version", lambda: "10.0.19045")
    with pytest.raises(RuntimeError, match="20348"):
        asyncio.run(backend.start())


def test_missing_cuda_uses_cpu_int8(monkeypatch):
    captured = {}
    def factory(_name, **kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr("vlt.asr.faster_whisper_backend.ctranslate2.get_cuda_device_count", lambda: 0)
    backend = FasterWhisperBackend(device="auto", model_factory=factory)
    async def exercise():
        await backend.start()
        await backend.stop()
    asyncio.run(exercise())
    assert captured["device"] == "cpu" and captured["compute_type"] == "int8"


def test_single_instance_rejects_second_listener():
    app = QCoreApplication.instance() or QCoreApplication([])
    name = f"VltTest-{uuid.uuid4()}"
    code = (
        "from PySide6.QtCore import QCoreApplication,QTimer; "
        "from vlt.product.single_instance import SingleInstance; "
        "import sys; app=QCoreApplication([]); instance=SingleInstance(sys.argv[1]); "
        "print(instance.acquire(),flush=True); QTimer.singleShot(3000,app.quit); app.exec()"
    )
    first = subprocess.Popen([sys.executable, "-c", code, name], stdout=subprocess.PIPE,
                             text=True)
    second = None
    try:
        assert first.stdout.readline().strip() == "True"
        second = SingleInstance(name)
        assert not second.acquire()
    finally:
        first.terminate()
        first.wait(timeout=5)
        if second:
            second.server.close()
        app.processEvents()


def test_log_rotation_keeps_bounded_backups(tmp_path):
    target = configure_logging(tmp_path)
    payload = "x" * 2048
    for _ in range(2700):
        logging.info(payload)
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert target.exists()
    assert (tmp_path / "app.log.1").exists()
    assert len(list(tmp_path.glob("app.log*"))) <= 6
