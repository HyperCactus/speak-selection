import importlib.util
from pathlib import Path


def load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "speak-selection.py"
    spec = importlib.util.spec_from_file_location("speak_selection_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_common_math_symbols_are_spoken():
    module = load_script_module()

    normalized = module.sanitize_tts_text("θ ∝ α + β, ∇φ, Δx ≤ 10, x ≠ ∞")

    assert normalized == (
        "theta proportional to alpha plus beta, nabla phi, "
        "delta x less than or equal to 10, x not equal to infinity"
    )


def test_symbols_between_words_keep_word_boundaries():
    module = load_script_module()

    normalized = module.sanitize_tts_text("rate∝θandφ")

    assert normalized == "rate proportional to theta and phi"


def test_streaming_segments_get_trailing_breaks():
    module = load_script_module()

    assert module.prepare_segment_for_synthesis("first chunk") == "first chunk."
    assert module.prepare_segment_for_synthesis("already paused,") == "already paused,"

