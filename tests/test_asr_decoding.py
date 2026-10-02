from vlt.asr.faster_whisper_backend import FasterWhisperBackend


def test_final_uses_accuracy_beam_while_partial_stays_fast():
    options = []

    class Model:
        def transcribe(self, _samples, **kwargs):
            options.append(kwargs)
            segment = type("Segment", (), {"text": "こんにちは", "avg_logprob": -.3})()
            info = type("Info", (), {"language": "ja"})()
            return [segment], info

    backend = FasterWhisperBackend(model_factory=lambda *_args, **_kwargs: Model())
    backend._model = Model()
    backend.set_language("ja")
    pcm = b"\0" * 32000
    assert backend._transcribe(pcm, False)[0] == "こんにちは"
    assert backend._transcribe(pcm, True)[0] == "こんにちは"
    assert [(item["beam_size"], item["best_of"]) for item in options] == [(1, 1), (3, 3)]
    assert all(item["condition_on_previous_text"] is False for item in options)
