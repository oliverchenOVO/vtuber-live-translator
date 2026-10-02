from __future__ import annotations

import hashlib
import json
import csv
import sys
import time
from pathlib import Path

import pytest

from vlt.translation.madlad_backend import MadladTranslationBackend
from vlt.translation.base import TranslationRequest
from vlt.translation.pipeline import BoundedTranslationQueue, TranslationPipeline
from vlt.translation.translategemma_backend import TranslateGemmaBackend
from vlt.translation.faithful_first import FaithfulFirstBackend


ROOT = Path(__file__).resolve().parents[1]


def test_bakeoff_corpus_is_frozen_and_has_real_asr_rows():
    expected = json.loads((ROOT / "tests/fixtures/translation_bakeoff_650.json").read_text("utf-8"))
    assert len(expected) == 650
    assert sum(row["language"] == "ja" for row in expected) == 500
    assert sum(row["language"] == "en" for row in expected) == 150
    assert sum(row["provenance"] == "phase10_30min_chrome_soak" for row in expected) == 100
    assert all(not row["reference_zh_tw"] for row in expected[-250:])


def test_critical_22_are_separate_from_aggregate():
    rows = json.loads((ROOT / "tests/fixtures/translation_regression_critical.json").read_text("utf-8"))
    assert rows == json.loads((ROOT / "tests/fixtures/phase9_bad_22.json").read_text("utf-8"))
    assert len(rows) == 22
    assert len({row["sample_id"] for row in rows}) == 22
    assert all(row["bad_translation"] and row["issue"] for row in rows)


def test_glossary_bakeoff_has_both_source_languages_and_locales():
    rows = json.loads((ROOT / "tests/fixtures/translation_bakeoff_glossary.json").read_text("utf-8"))
    assert len(rows) == 6
    assert {row["language"] for row in rows} == {"ja", "en"}
    assert all(row["glossary"] and row["reference_zh_tw"] and row["reference_zh_cn"] for row in rows)


def test_glossary_placeholder_roundtrip_and_locale_ordering():
    glossary = ({"source": "兎田ぺこら", "aliases": ["Pekora", "ぺこら"],
                 "preferred_zh_tw": "佩克拉", "preferred_zh_cn": "佩克拉"},)
    protected, markers = MadladTranslationBackend._protect("ぺこら和兎田ぺこら", glossary, "zh-TW")
    assert "兎田ぺこら" not in protected
    assert len(markers) == 2
    sentence = "简体字 " + " 和 ".join(markers)
    result = MadladTranslationBackend._finish(sentence, markers, "zh-TW")
    assert result == "簡體字 佩克拉 和 佩克拉"


def test_placeholder_leak_or_loss_fails_closed():
    with pytest.raises(RuntimeError, match="未完整保留"):
        MadladTranslationBackend._finish("角色消失了", {"VLTTERM001": "佩克拉"}, "zh-TW")
    with pytest.raises(RuntimeError, match="外洩"):
        MadladTranslationBackend._finish("佩克拉 VLTTERM999", {}, "zh-TW")


def test_automated_flags_are_review_requests_not_semantic_grades():
    from scripts.phase10b_benchmark import automated_flags, summarize

    assert "digit_mismatch_review" in automated_flags("3 hours", "睡了4小時")
    assert "untranslated_source_review" in automated_flags("昨日", "昨日")
    row = {"translation": "我睡了3小時", "elapsed_ms": 100, "process_rss_mib": 100,
           "gpu_used_mib": 0, "automated_flags": []}
    summary = summarize([row])
    assert summary["operational_output_rate_not_safe_coverage"] == 1
    assert summary["human_semantic_review"] == "NOT_PERFORMED"


def test_corpus_digest_is_stable():
    rows = json.loads((ROOT / "tests/fixtures/translation_bakeoff_650.json").read_text("utf-8"))
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == "1e54f1a66b56f9c7fcc1302a8d6795ba7d2bc5193799814d168078e81a326b67"


def test_human_review_sheet_never_autogrades_safe_coverage(tmp_path, monkeypatch):
    from scripts import phase10b_review_sheet as sheet

    monkeypatch.setattr(sheet, "DATA", tmp_path)
    sheet.main()
    with (tmp_path / "review_650_long.tsv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 650 * 3
    assert {row["backend"] for row in rows} == {"madlad", "gemma", "qwen"}
    assert all(row["eligible_source"] == row["safe_usable"] == "UNREVIEWED" for row in rows)
    assert all(row["hallucination"] == "UNREVIEWED" for row in rows)


def test_queue_metrics_report_depth_and_oldest_age_without_growth():
    queue = BoundedTranslationQueue(capacity=3)
    old = TranslationRequest("a", "こんにちは", "ja", "zh-TW", "faithful",
                             final=True, submitted_at=time.monotonic() - 2)
    assert queue.push(old)
    assert queue.push(TranslationRequest("b", "こんばんは", "ja", "zh-TW", "faithful", final=True))
    assert queue.push(TranslationRequest("c", "ありがとう", "ja", "zh-TW", "faithful", final=True))
    for index in range(100):
        assert not queue.push(TranslationRequest(f"overflow-{index}", "またね", "ja", "zh-TW",
                                                 "faithful", final=True))
    assert len(queue) == 3
    assert queue.oldest_age_ms() >= 2000
    assert queue.final_count() == 3


def test_pipeline_throughput_metrics_track_completed_finals():
    completed = []

    class FastBackend:
        def translate_final(self, request):
            return "你好"

        def translate_partial(self, request):
            return "你好"

    pipeline = TranslationPipeline(FastBackend, lambda request, *_: completed.append(request.segment_id))
    pipeline.start()
    for index in range(10):
        assert pipeline.submit(TranslationRequest(str(index), "こんにちは", "ja", "zh-TW",
                                                  "faithful", final=True))
    deadline = time.monotonic() + 2
    while len(completed) < 10 and time.monotonic() < deadline:
        time.sleep(.01)
    metrics = pipeline.metrics()
    pipeline.stop()
    assert len(completed) == 10
    assert metrics["throughput_finals_per_minute"] == 10
    assert metrics["queue_depth"] == 0


def test_sustained_final_rate_drains_bounded_queue():
    completed = []

    class Backend:
        def translate_final(self, request):
            time.sleep(.002)
            return "你好"

    pipeline = TranslationPipeline(Backend, lambda request, *_: completed.append(request.segment_id),
                                   capacity=5)
    pipeline.start()
    peak = 0
    for index in range(50):
        request = TranslationRequest(str(index), "こんにちは", "ja", "zh-TW",
                                     "faithful", final=True)
        deadline = time.monotonic() + 2
        accepted = False
        while not accepted and time.monotonic() < deadline:
            accepted = pipeline.submit(request)
            if not accepted:
                time.sleep(.002)
        assert accepted
        peak = max(peak, pipeline.metrics()["queue_depth"])
    deadline = time.monotonic() + 2
    while len(completed) < 50 and time.monotonic() < deadline:
        time.sleep(.01)
    metrics = pipeline.metrics()
    pipeline.stop()
    assert len(completed) == 50
    assert peak <= 5
    assert metrics["throughput_finals_per_minute"] == 50
    assert metrics["queue_depth"] == 0


def test_translategemma_uses_same_backend_interface_and_restores_glossary(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"response":"VLTTERM001 is here"}'

    seen = []

    def fake_open(request, timeout):
        seen.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    backend = TranslateGemmaBackend()
    backend.set_style("faithful")
    backend.update_context(("earlier source",))
    request = TranslationRequest("x", "Pekora is here", "en", "zh-TW", "faithful",
                                 glossary=({"source": "兎田ぺこら", "aliases": ["Pekora"],
                                            "preferred_zh_tw": "佩克拉", "preferred_zh_cn": "佩克拉"},),
                                 final=True)
    assert backend.translate_final(request) == "佩克拉 is here"
    assert seen[0]["model"] == "translategemma:4b"
    assert "VLTTERM001" in seen[0]["prompt"]
    assert "Pekora" not in seen[0]["prompt"]


def test_natural_polish_failure_uses_persistable_faithful_text():
    class Faithful:
        def translate_final(self, request):
            assert request.style == "faithful"
            return "我昨天只睡了3個小時。"

    states = []
    backend = FaithfulFirstBackend(Faithful(), lambda *_: "我昨天完全沒睡。")
    backend.set_stage_callback(states.append)
    result = backend.translate_final(TranslationRequest(
        "a", "昨日3時間しか寝てない", "ja", "zh-TW", "natural", final=True))
    assert result == "我昨天只睡了3個小時。"
    assert states == ["faithful_ready", "natural_failed_using_faithful"]


def test_faithful_first_does_not_call_polish_in_faithful_mode():
    class Faithful:
        def translate_final(self, request):
            return "可能會下雨。"

    backend = FaithfulFirstBackend(Faithful(), lambda *_: (_ for _ in ()).throw(AssertionError()))
    assert backend.translate_final(TranslationRequest(
        "a", "雨かもしれない", "ja", "zh-TW", "faithful", final=True)) == "可能會下雨。"
    assert backend.last_state == "faithful_ready"


def test_benchmark_runner_resumes_without_duplicate_rows(tmp_path, monkeypatch):
    from scripts import phase10b_benchmark as bench

    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps([
        {"id": str(index), "language": "en", "source": f"Hello {index}"}
        for index in range(3)]), encoding="utf-8")

    class FakeBackend:
        def translate_final(self, request):
            return f"你好 {request.segment_id}"

    monkeypatch.setattr(bench, "ROOT", tmp_path)
    monkeypatch.setattr(bench, "CORPUS", fixture)
    monkeypatch.setattr(bench, "MODEL", tmp_path / "missing-model")
    monkeypatch.setattr(bench, "backend", lambda _: FakeBackend())
    monkeypatch.setattr(bench, "gpu_memory_mib", lambda: 0)
    monkeypatch.setattr(bench, "process_memory_mib", lambda: 100)
    monkeypatch.setattr(bench, "backend_cpu_seconds", lambda: 0.0)
    monkeypatch.setattr(sys, "argv", ["benchmark", "--backend", "madlad", "--limit", "2"])
    bench.main()
    monkeypatch.setattr(sys, "argv", ["benchmark", "--backend", "madlad"])
    bench.main()
    output = tmp_path / "data/phase10b/madlad-corpus-zh-TW.jsonl"
    rows = [json.loads(line) for line in output.read_text("utf-8").splitlines()]
    assert [row["id"] for row in rows] == ["0", "1", "2"]
    summary = json.loads(output.with_suffix(".summary.json").read_text("utf-8"))
    assert summary["complete"]
    assert summary["expected_rows"] == 3


def test_stale_live_final_is_deferred_then_can_be_retried():
    translated = []

    class FastBackend:
        def translate_final(self, request):
            translated.append(request.segment_id)
            return "你好"

    pipeline = TranslationPipeline(FastBackend, lambda *_: None, stale_after_s=1)
    pipeline.set_live_mode(True)
    pipeline.start()
    stale = TranslationRequest("durable-segment", "こんにちは", "ja", "zh-TW", "faithful",
                               final=True, submitted_at=time.monotonic() - 10)
    assert pipeline.submit(stale)
    deadline = time.monotonic() + 2
    while pipeline.pending_final_count() and time.monotonic() < deadline:
        time.sleep(.01)
    assert pipeline.pending_final_count() == 0
    assert pipeline.metrics()["deferred_stale_finals"] == 1
    assert translated == []
    # The periodic durable-pending scan must not immediately requeue a stale
    # Final while live audio is still arriving.
    assert not pipeline.submit(TranslationRequest(
        "durable-segment", "こんにちは", "ja", "zh-TW", "faithful", final=True))
    pipeline.set_live_mode(False)
    assert pipeline.submit(TranslationRequest(
        "durable-segment", "こんにちは", "ja", "zh-TW", "faithful", final=True))
    deadline = time.monotonic() + 2
    while not translated and time.monotonic() < deadline:
        time.sleep(.01)
    pipeline.stop()
    assert translated == ["durable-segment"]
