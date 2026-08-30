import importlib.util
import struct
import threading
import time
import wave
from pathlib import Path


def load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "speak-selection.py"
    spec = importlib.util.spec_from_file_location("speak_selection_performance", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_synthesis_calls_are_serialized():
    module = load_script_module()
    daemon = module.Daemon()
    active = 0
    peak_active = 0
    counter_lock = threading.Lock()

    def fake_synthesize(*_args, **_kwargs):
        nonlocal active, peak_active
        with counter_lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.03)
        with counter_lock:
            active -= 1

    daemon._synthesize_text_to_file = fake_synthesize
    workers = [
        threading.Thread(
            target=daemon.synthesize_text_to_file,
            args=("text", "/tmp/unused.wav", None, "en"),
        )
        for _ in range(3)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert peak_active == 1


def test_superseded_synthesis_is_dropped_before_inference():
    module = load_script_module()
    daemon = module.Daemon()
    called = False

    def fake_synthesize(*_args, **_kwargs):
        nonlocal called
        called = True

    daemon._synthesize_text_to_file = fake_synthesize

    try:
        daemon.synthesize_text_to_file(
            "stale",
            "/tmp/unused.wav",
            None,
            "en",
            should_cancel=lambda: True,
        )
    except module.SynthesisCancelled:
        pass
    else:
        raise AssertionError("cancelled synthesis did not stop")

    assert called is False


def test_cache_pruning_is_rate_limited(tmp_path):
    module = load_script_module()
    module.CACHE_DIR = tmp_path
    module.CACHE_MAX_FILES = 2
    module.CACHE_PRUNE_INTERVAL = 60.0
    daemon = module.Daemon()

    for index in range(4):
        path = tmp_path / f"{index}.wav"
        path.write_bytes(b"wav")
        time.sleep(0.002)

    daemon.prune_cache_files()
    assert len(list(tmp_path.glob("*.wav"))) == 2

    (tmp_path / "new.wav").write_bytes(b"wav")
    daemon.prune_cache_files()
    assert len(list(tmp_path.glob("*.wav"))) == 3


def test_post_gain_respects_peak_ceiling(tmp_path):
    module = load_script_module()
    path = tmp_path / "levels.wav"
    samples = [-30000, -20000, -1000, 0, 1000, 20000, 30000]
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44100)
        wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    module.apply_post_gain_to_wav(str(path))

    with wave.open(str(path), "rb") as wav_file:
        result = struct.unpack(
            f"<{wav_file.getnframes()}h",
            wav_file.readframes(wav_file.getnframes()),
        )

    assert max(abs(sample) for sample in result) <= int(32767 * module.WAV_POST_PEAK)
    assert result[0] < 0 < result[-1]
