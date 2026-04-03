#!/usr/bin/env python3
import atexit
import argparse
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default

    try:
        return float(raw)
    except ValueError:
        return default


def get_default_state_dir() -> Path:
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "speak-selection"
        return Path.home() / "AppData" / "Local" / "speak-selection"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "speak-selection"

    return Path.home() / ".cache" / "speak-selection"


def get_default_voice_dir() -> Path:
    voice_dir_override = os.environ.get("SPEAK_SELECTION_VOICE_DIR", "").strip()
    if voice_dir_override:
        return Path(voice_dir_override).expanduser()

    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "piper" / "voices"
        return Path.home() / "AppData" / "Local" / "piper" / "voices"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "piper" / "voices"

    return Path.home() / ".local" / "share" / "piper" / "voices"


DEFAULT_STATE_DIR = get_default_state_dir()
STATE_DIR = Path(os.environ.get("SPEAK_SELECTION_STATE_DIR", str(DEFAULT_STATE_DIR))).expanduser()
SOCKET_PATH = STATE_DIR / "control.sock"
DAEMON_PID_PATH = STATE_DIR / "daemon.pid"
MPV_SOCKET_PATH = STATE_DIR / "mpv.sock"
VOICE_DIR = get_default_voice_dir()

# Tuning
PIPER_LENGTH_SCALE = env_float("SPEAK_SELECTION_LENGTH_SCALE", 0.95)
PLAYBACK_SPEED = env_float("SPEAK_SELECTION_PLAYBACK_SPEED", 1.85)
SENTENCE_SILENCE = 0.10
NOISE_SCALE = env_float("SPEAK_SELECTION_NOISE_SCALE", 0.667)
NOISE_W = env_float("SPEAK_SELECTION_NOISE_W", 0.8)

VOICE_MODELS = {
    "medium": VOICE_DIR / "en_US-lessac-medium.onnx",
    "high": VOICE_DIR / "en_US-lessac-high.onnx",
}
DEFAULT_VOICE_ORDER = ("medium", "high")

# Environment options:
# - SPEAK_SELECTION_VOICE: medium | high | /path/to/voice.onnx
# - SPEAK_SELECTION_LOW_MEMORY_ORT: 1|true|yes to disable ONNX CPU memory arena
# - SPEAK_SELECTION_VOICE_DIR: override directory containing .onnx/.json voices
# - SPEAK_SELECTION_PLAYBACK_SPEED: mpv playback speed (example: 1.5)
# - SPEAK_SELECTION_LENGTH_SCALE: Piper speaking pace (lower=faster, example: 0.9)
# - SPEAK_SELECTION_NOISE_SCALE: Piper variation (example: 0.667)
# - SPEAK_SELECTION_NOISE_W: Piper phoneme width variation (example: 0.8)

DEFAULT_TEST_TEXT = "This is a hardcoded test of the speak selection script."
SEGMENT_MAX_CHARS = 220

def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_voice_preference() -> str:
    return os.environ.get("SPEAK_SELECTION_VOICE", "medium").strip()


def low_memory_ort_enabled() -> bool:
    return os.environ.get("SPEAK_SELECTION_LOW_MEMORY_ORT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_voice_candidates() -> list[Path]:
    preference = get_voice_preference()
    if not preference:
        return [VOICE_MODELS[name] for name in DEFAULT_VOICE_ORDER]

    pref_lower = preference.lower()
    if pref_lower in VOICE_MODELS:
        ordered = [VOICE_MODELS[pref_lower]]
        ordered.extend(
            VOICE_MODELS[name] for name in DEFAULT_VOICE_ORDER if name != pref_lower
        )
        return ordered

    preferred_path = Path(preference).expanduser()
    candidates = [preferred_path]
    candidates.extend(VOICE_MODELS[name] for name in DEFAULT_VOICE_ORDER)
    return candidates

def maybe_reexec_for_piper():
    if os.environ.get("SPEAK_SELECTION_REEXECED") == "1":
        return

    try:
        from piper.voice import PiperVoice  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    candidates = [
        Path.home() / "miniconda3" / "envs" / "speak-selection" / "bin" / "python3",
        Path.home() / "miniconda3" / "envs" / "speak-selection" / "bin" / "python",
    ]

    for candidate in candidates:
        if not candidate.exists():
            continue

        probe = subprocess.run(
            [str(candidate), "-c", "from piper.voice import PiperVoice"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            env = os.environ.copy()
            env["SPEAK_SELECTION_REEXECED"] = "1"
            os.execve(str(candidate), [str(candidate), *sys.argv], env)

def normalize_text(text: str) -> str:
    return " ".join(text.replace("\r", "\n").split())

def chunk_text_for_streaming(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []

    segments = []
    sentence_parts = re.split(r"(?<=[.!?])\s+", text)

    for part in sentence_parts:
        part = part.strip()
        if not part:
            continue

        if len(part) <= SEGMENT_MAX_CHARS:
            segments.append(part)
            continue

        clause_parts = re.split(r"(?<=[,;:])\s+", part)
        current = ""

        for clause in clause_parts:
            clause = clause.strip()
            if not clause:
                continue

            candidate = f"{current} {clause}".strip() if current else clause
            if current and len(candidate) > SEGMENT_MAX_CHARS:
                segments.append(current)
                current = clause
                continue

            if len(clause) <= SEGMENT_MAX_CHARS:
                current = candidate
                continue

            if current:
                segments.append(current)
                current = ""

            words = clause.split()
            word_chunk = ""
            for word in words:
                candidate = f"{word_chunk} {word}".strip() if word_chunk else word
                if word_chunk and len(candidate) > SEGMENT_MAX_CHARS:
                    segments.append(word_chunk)
                    word_chunk = word
                else:
                    word_chunk = candidate

            if word_chunk:
                segments.append(word_chunk)

        if current:
            segments.append(current)

    return segments

def get_voice_path() -> Path:
    candidates = get_voice_candidates()
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No Piper voice found. Expected one of:\n"
        + "\n".join(str(p) for p in candidates)
    )

def get_selected_text() -> str:
    if sys.platform == "darwin":
        commands = [["pbpaste"]]
    elif sys.platform == "win32":
        commands = [["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]]
    else:
        xdg = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if xdg == "wayland":
            commands = [
                ["wl-paste", "--primary", "--no-newline"],
                ["wl-paste", "--no-newline"],
            ]
        else:
            commands = [
                ["xsel", "--primary"],
                ["xclip", "-o", "-selection", "primary"],
                ["xsel", "--clipboard", "--output"],
                ["xclip", "-o", "-selection", "clipboard"],
            ]

    for cmd in commands:
        try:
            out = subprocess.check_output(
                cmd,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.25,
            )
            out = normalize_text(out)
            if out:
                return out
        except Exception:
            pass

    return ""

def daemon_alive() -> bool:
    try:
        if DAEMON_PID_PATH.exists():
            pid = int(DAEMON_PID_PATH.read_text().strip())
            os.kill(pid, 0)
            return True
    except Exception:
        pass
    return False

def start_daemon():
    ensure_state_dir()
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )

def send_request(payload: dict, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(str(SOCKET_PATH))
                s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                return True
        except OSError:
            time.sleep(0.03)
    return False

def client_main():
    ensure_state_dir()

    text = get_selected_text()
    if sys.platform == "win32":
        speak_text_direct(text)
        return

    payload = {
        "cmd": "speak",
        "text": text,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
    }

    if not daemon_alive():
        start_daemon()

    if not send_request(payload):
        raise SystemExit("Could not contact speak-selection daemon.")

def speak_text_direct(text: str):
    text = normalize_text(text)
    if not text:
        raise SystemExit("No text to speak.")

    daemon = Daemon()
    atexit.register(daemon.cleanup)
    daemon.load_voice()
    path = daemon.synthesize_to_temp(text)
    daemon.current_temp = path
    daemon.active_temps = [path]

    cmd = [
        "mpv",
        "--no-config",
        "--no-video",
        "--terminal=no",
        "--really-quiet",
        "--force-window=no",
        "--audio-display=no",
        "--audio-pitch-correction=yes",
        f"--speed={PLAYBACK_SPEED}",
        path,
    ]

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        pass

class Daemon:
    def __init__(self):
        self.voice = None
        self.server = None
        self.mpv_proc = None
        self.current_hash = ""
        self.pending_hash = ""
        self.current_temp = None
        self.active_temps = []
        self.old_temps = []
        self.request_serial = 0
        self.state_lock = threading.Lock()

    def load_voice(self):
        try:
            from piper.voice import PiperVoice
        except Exception as e:
            raise RuntimeError(
                "This script uses Piper's Python API for speed.\n"
                "Install it with:\n"
                "python3 -m pip install --user piper-tts"
            ) from e

        voice_path = get_voice_path()
        config_path = Path(str(voice_path) + ".json")

        if low_memory_ort_enabled():
            import onnxruntime
            from piper.config import PiperConfig

            with config_path.open("r", encoding="utf-8") as config_file:
                config_dict = json.load(config_file)

            sess_options = onnxruntime.SessionOptions()
            sess_options.enable_cpu_mem_arena = False

            self.voice = PiperVoice(
                config=PiperConfig.from_dict(config_dict),
                session=onnxruntime.InferenceSession(
                    str(voice_path),
                    sess_options=sess_options,
                    providers=["CPUExecutionProvider"],
                ),
                download_dir=Path.cwd(),
            )
            return

        self.voice = PiperVoice.load(str(voice_path), config_path=str(config_path))

    def start_mpv(self):
        ensure_state_dir()

        try:
            MPV_SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass

        cmd = [
            "mpv",
            "--idle=yes",
            "--keep-open=no",
            "--no-config",
            "--no-video",
            "--terminal=no",
            "--really-quiet",
            "--force-window=no",
            "--audio-display=no",
            "--audio-pitch-correction=yes",
            f"--input-ipc-server={MPV_SOCKET_PATH}",
        ]

        self.mpv_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if MPV_SOCKET_PATH.exists():
                return
            time.sleep(0.02)

        raise RuntimeError("mpv IPC socket did not appear.")

    def ensure_mpv(self):
        if self.mpv_proc is None or self.mpv_proc.poll() is not None or not MPV_SOCKET_PATH.exists():
            self.start_mpv()

    def mpv_json(self, payload: dict) -> dict:
        self.ensure_mpv()

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(MPV_SOCKET_PATH))
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))

            data = b""
            while b"\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk

        if not data:
            return {}

        try:
            return json.loads(data.decode("utf-8", errors="ignore").strip())
        except Exception:
            return {}

    def mpv_command(self, *args):
        return self.mpv_json({"command": list(args)})

    def is_paused(self) -> bool:
        resp = self.mpv_command("get_property", "pause")
        return bool(resp.get("data", False))

    def is_idle(self) -> bool:
        resp = self.mpv_command("get_property", "idle-active")
        return bool(resp.get("data", False))

    def toggle_pause(self):
        paused = self.is_paused()
        self.mpv_command("set_property", "pause", not paused)

    def get_synthesis_config(self):
        from piper.config import SynthesisConfig

        return SynthesisConfig(
            speaker_id=None,
            length_scale=PIPER_LENGTH_SCALE,
            noise_scale=NOISE_SCALE,
            noise_w_scale=NOISE_W,
        )

    def write_chunk_to_temp(self, audio_chunk) -> str:
        fd, path = tempfile.mkstemp(
            prefix="speak-selection-",
            suffix=".wav",
            dir=str(STATE_DIR),
        )
        os.close(fd)

        try:
            with wave.open(path, "wb") as wav_file:
                wav_file.setframerate(audio_chunk.sample_rate)
                wav_file.setsampwidth(audio_chunk.sample_width)
                wav_file.setnchannels(audio_chunk.sample_channels)
                wav_file.writeframes(audio_chunk.audio_int16_bytes)
        except Exception:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            raise

        return path

    def synthesize_segment_to_temp(self, text: str, syn_config=None) -> str:
        fd, path = tempfile.mkstemp(
            prefix="speak-selection-",
            suffix=".wav",
            dir=str(STATE_DIR),
        )
        os.close(fd)

        if syn_config is None:
            syn_config = self.get_synthesis_config()

        try:
            with wave.open(path, "wb") as wav_file:
                first_chunk = True
                for audio_chunk in self.voice.synthesize(text, syn_config=syn_config):
                    if first_chunk:
                        wav_file.setframerate(audio_chunk.sample_rate)
                        wav_file.setsampwidth(audio_chunk.sample_width)
                        wav_file.setnchannels(audio_chunk.sample_channels)
                        first_chunk = False

                    wav_file.writeframes(audio_chunk.audio_int16_bytes)

                if first_chunk:
                    raise RuntimeError("Piper returned no audio chunks.")
        except Exception:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            raise

        return path

    def synthesize_to_temp(self, text: str) -> str:
        fd, path = tempfile.mkstemp(
            prefix="speak-selection-",
            suffix=".wav",
            dir=str(STATE_DIR),
        )
        os.close(fd)

        try:
            with wave.open(path, "wb") as wav_file:
                first_chunk = True
                syn_config = self.get_synthesis_config()
                for segment in chunk_text_for_streaming(text):
                    for audio_chunk in self.voice.synthesize(
                        segment,
                        syn_config=syn_config,
                    ):
                        if first_chunk:
                            wav_file.setframerate(audio_chunk.sample_rate)
                            wav_file.setsampwidth(audio_chunk.sample_width)
                            wav_file.setnchannels(audio_chunk.sample_channels)
                            first_chunk = False

                        wav_file.writeframes(audio_chunk.audio_int16_bytes)

                if first_chunk:
                    raise RuntimeError("Piper returned no audio chunks.")
        except Exception:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            raise

        return path

    def cleanup_temp_files(self):
        keep = set(self.active_temps)
        survivors = []

        for path in self.old_temps:
            if path in keep:
                survivors.append(path)
                continue

            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except Exception:
                survivors.append(path)

        self.old_temps = survivors

    def is_request_current(self, request_id: int) -> bool:
        with self.state_lock:
            return request_id == self.request_serial

    def cancel_current_request(self):
        with self.state_lock:
            self.request_serial += 1
            self.pending_hash = ""
            self.current_hash = ""

            if self.active_temps:
                self.old_temps.extend(self.active_temps)
                self.active_temps = []
                self.current_temp = None

        self.mpv_command("stop")
        self.mpv_command("playlist-clear")
        self.cleanup_temp_files()

    def queue_text(self, text: str, text_hash: str):
        self.cancel_current_request()

        with self.state_lock:
            request_id = self.request_serial
            self.pending_hash = text_hash

        worker = threading.Thread(
            target=self._synthesize_and_queue,
            args=(request_id, text, text_hash),
            daemon=True,
        )
        worker.start()

    def _synthesize_and_queue(self, request_id: int, text: str, text_hash: str):
        syn_config = self.get_synthesis_config()
        playback_started = False
        queued_paths = []
        segments = chunk_text_for_streaming(text)
        initial_buffer_segments = 2 if len(segments) > 1 else 1

        try:
            for segment in segments:
                if not self.is_request_current(request_id):
                    break

                path = self.synthesize_segment_to_temp(segment, syn_config=syn_config)

                if not self.is_request_current(request_id):
                    try:
                        os.remove(path)
                    except FileNotFoundError:
                        pass
                    break

                with self.state_lock:
                    if request_id != self.request_serial:
                        try:
                            os.remove(path)
                        except FileNotFoundError:
                            pass
                        break

                    self.active_temps.append(path)
                    self.current_temp = path
                    self.current_hash = text_hash
                    self.pending_hash = text_hash

                queued_paths.append(path)

                if not playback_started and len(queued_paths) >= initial_buffer_segments:
                    self.mpv_command("loadfile", queued_paths[0], "replace")
                    for queued_path in queued_paths[1:]:
                        self.mpv_command("loadfile", queued_path, "append")
                    self.mpv_command("set_property", "pause", False)
                    self.mpv_command("set_property", "speed", PLAYBACK_SPEED)
                    queued_paths = []
                    playback_started = True
                elif playback_started:
                    self.mpv_command("loadfile", path, "append")

            if not playback_started and queued_paths and self.is_request_current(request_id):
                self.mpv_command("loadfile", queued_paths[0], "replace")
                for queued_path in queued_paths[1:]:
                    self.mpv_command("loadfile", queued_path, "append")
                self.mpv_command("set_property", "pause", False)
                self.mpv_command("set_property", "speed", PLAYBACK_SPEED)
        finally:
            self.cleanup_temp_files()

    def handle_speak(self, text: str, text_hash: str):
        self.ensure_mpv()

        # No current selection: toggle pause/resume on current playback
        if not text:
            self.toggle_pause()
            return

        # Same selected text: toggle pause/resume
        if text_hash == self.current_hash or text_hash == self.pending_hash:
            # If playback already finished, replay from the beginning.
            if self.is_idle():
                self.queue_text(text, text_hash)
            else:
                self.toggle_pause()
            return

        # New selected text: replace current playback immediately
        self.queue_text(text, text_hash)

    def cleanup(self):
        try:
            if self.server:
                self.server.close()
        except Exception:
            pass

        for path in [SOCKET_PATH, DAEMON_PID_PATH, MPV_SOCKET_PATH]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass

        try:
            if self.mpv_proc and self.mpv_proc.poll() is None:
                self.mpv_proc.terminate()
        except Exception:
            pass

        paths = list(self.old_temps)
        paths.extend(self.active_temps)
        if self.current_temp:
            paths.append(self.current_temp)

        for path in paths:
            try:
                os.remove(path)
            except Exception:
                pass

    def run(self):
        ensure_state_dir()
        atexit.register(self.cleanup)

        self.load_voice()
        self.start_mpv()

        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(SOCKET_PATH))
        self.server.listen(8)
        os.chmod(SOCKET_PATH, 0o600)

        DAEMON_PID_PATH.write_text(str(os.getpid()))

        def _exit_handler(signum, frame):
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, _exit_handler)
        signal.signal(signal.SIGINT, _exit_handler)

        while True:
            conn, _ = self.server.accept()
            with conn:
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk

                if not data:
                    continue

                try:
                    payload = json.loads(data.decode("utf-8", errors="ignore").strip())
                except Exception:
                    continue

                if payload.get("cmd") == "speak":
                    self.handle_speak(
                        payload.get("text", ""),
                        payload.get("hash", ""),
                    )

if __name__ == "__main__":
    maybe_reexec_for_piper()

    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--text", help="Speak this text instead of reading the current selection.")
    parser.add_argument(
        "--voice",
        help="Voice preference: medium, high, or /path/to/voice.onnx",
    )
    parser.add_argument(
        "--low-memory-ort",
        action="store_true",
        help="Reduce ONNX memory by disabling the CPU memory arena.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Speak built-in hardcoded test text.",
    )
    args = parser.parse_args()

    if args.voice is not None:
        os.environ["SPEAK_SELECTION_VOICE"] = args.voice
    if args.low_memory_ort:
        os.environ["SPEAK_SELECTION_LOW_MEMORY_ORT"] = "1"

    if args.daemon and sys.platform == "win32":
        raise SystemExit("Daemon mode is not supported on Windows.")
    if args.daemon:
        Daemon().run()
    elif args.text is not None:
        speak_text_direct(args.text)
    elif args.test:
        speak_text_direct(DEFAULT_TEST_TEXT)
    else:
        client_main()
