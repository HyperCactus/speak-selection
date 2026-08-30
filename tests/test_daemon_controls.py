import importlib.util
from pathlib import Path


def load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "speak-selection.py"
    spec = importlib.util.spec_from_file_location("speak_selection_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ControlOnlyDaemon:
    def __init__(self, module):
        self.current_hash = "same"
        self.pending_hash = ""
        self.queued = []
        self.toggles = 0
        self.idle = False
        self.module = module

    def ensure_mpv(self):
        pass

    def is_idle(self):
        return self.idle

    def queue_text(self, text, text_hash, voice_preference="", lang="na"):
        self.queued.append((text, text_hash, voice_preference, lang))

    def toggle_pause(self):
        self.toggles += 1


def test_same_selection_toggles_pause_when_playing():
    module = load_script_module()
    daemon = ControlOnlyDaemon(module)

    module.Daemon.handle_speak(daemon, "hello", "same")

    assert daemon.toggles == 1
    assert daemon.queued == []


def test_same_selection_requeues_when_idle():
    module = load_script_module()
    daemon = ControlOnlyDaemon(module)
    daemon.idle = True

    module.Daemon.handle_speak(daemon, "hello", "same", voice_preference="M2", lang="en")

    assert daemon.toggles == 0
    assert daemon.queued == [("hello", "same", "M2", "en")]


def test_new_selection_queues_instead_of_toggling():
    module = load_script_module()
    daemon = ControlOnlyDaemon(module)

    module.Daemon.handle_speak(daemon, "new text", "new")

    assert daemon.toggles == 0
    assert daemon.queued == [("new text", "new", "", "na")]
