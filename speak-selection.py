#!/usr/bin/env python3
import atexit
import argparse
import html
import hashlib
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from array import array
from pathlib import Path
from typing import Optional

def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default

    try:
        return float(raw)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default

    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
TRAY_PID_PATH = STATE_DIR / "tray.pid"
SETTINGS_UI_PID_PATH = STATE_DIR / "settings-ui.pid"
MPV_SOCKET_PATH = STATE_DIR / "mpv.sock"
VOICE_DIR = get_default_voice_dir()
CACHE_DIR = STATE_DIR / "audio-cache"
SETTINGS_PATH = STATE_DIR / "settings.json"
VOICE_CATALOG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
VOICE_SAMPLES_URL = "https://rhasspy.github.io/piper-samples/"

# Tuning
PIPER_LENGTH_SCALE = env_float("SPEAK_SELECTION_LENGTH_SCALE", 0.95)
PLAYBACK_SPEED = max(0.25, min(4.0, env_float("SPEAK_SELECTION_PLAYBACK_SPEED", 1.85)))
PLAYBACK_VOLUME = max(0.0, min(200.0, env_float("SPEAK_SELECTION_VOLUME", 100.0)))
MPV_VOLUME_MAX = 200
WAV_POST_BOOST_ENABLED = env_bool("SPEAK_SELECTION_WAV_POST_BOOST", True)
WAV_POST_GAIN = max(1.0, min(3.0, env_float("SPEAK_SELECTION_WAV_POST_GAIN", 1.6)))
WAV_POST_PEAK = max(0.1, min(0.99, env_float("SPEAK_SELECTION_WAV_POST_PEAK", 0.95)))
WAV_COMPRESS_ENABLED = env_bool("SPEAK_SELECTION_WAV_COMPRESS", True)
WAV_COMPRESS_THRESHOLD = max(
    0.05,
    min(0.99, env_float("SPEAK_SELECTION_WAV_COMPRESS_THRESHOLD", 0.60)),
)
WAV_COMPRESS_RATIO = max(
    1.01,
    min(20.0, env_float("SPEAK_SELECTION_WAV_COMPRESS_RATIO", 3.0)),
)
RESET_STREAM_VOLUME = env_bool("SPEAK_SELECTION_RESET_STREAM_VOLUME", True)
STREAM_VOLUME_PERCENT = max(1, min(200, env_int("SPEAK_SELECTION_STREAM_VOLUME", 100)))
SELECTION_READ_TIMEOUT = max(0.1, min(2.0, env_float("SPEAK_SELECTION_SELECTION_TIMEOUT", 0.8)))
SELECTION_READ_RETRIES = max(1, min(20, env_int("SPEAK_SELECTION_SELECTION_RETRIES", 6)))
SELECTION_RETRY_DELAY = max(0.01, min(0.5, env_float("SPEAK_SELECTION_SELECTION_RETRY_DELAY", 0.04)))
ALLOW_CLIPBOARD_FALLBACK = env_bool("SPEAK_SELECTION_ALLOW_CLIPBOARD_FALLBACK", False)
EMPTY_SELECTION_TOGGLES = env_bool("SPEAK_SELECTION_EMPTY_TOGGLES", False)
SENTENCE_SILENCE = 0.10
NOISE_SCALE = env_float("SPEAK_SELECTION_NOISE_SCALE", 0.667)
NOISE_W = env_float("SPEAK_SELECTION_NOISE_W", 0.8)
ARTICLE_MAX_CHARS = max(1000, env_int("SPEAK_SELECTION_ARTICLE_MAX_CHARS", 30000))
CACHE_ENABLED = env_bool("SPEAK_SELECTION_CACHE_ENABLED", True)
CACHE_MAX_FILES = max(20, env_int("SPEAK_SELECTION_CACHE_MAX_FILES", 800))
AUTO_LANGUAGE_ROUTING = env_bool("SPEAK_SELECTION_AUTO_LANGUAGE", True)
AUTO_TRAY_ENABLED = env_bool("SPEAK_SELECTION_AUTO_TRAY", True)

VOICE_MODELS = {
    "medium": VOICE_DIR / "en_US-lessac-medium.onnx",
    "high": VOICE_DIR / "en_US-lessac-high.onnx",
}
DEFAULT_VOICE_ORDER = ("medium", "high")

DEFAULT_VOICE_DOWNLOADS = {
    "medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
}

# Environment options:
# - SPEAK_SELECTION_VOICE: auto | medium | high | /path/to/voice.onnx
# - SPEAK_SELECTION_LOW_MEMORY_ORT: 1|true|yes to disable ONNX CPU memory arena
# - SPEAK_SELECTION_VOICE_DIR: override directory containing .onnx/.json voices
# - SPEAK_SELECTION_PLAYBACK_SPEED: mpv playback speed 0.25-4.0 (example: 1.5)
# - SPEAK_SELECTION_VOLUME: mpv volume percentage 0-200 (example: 100)
# - SPEAK_SELECTION_WAV_POST_BOOST: 1|true|yes to boost generated WAV safely
# - SPEAK_SELECTION_WAV_POST_GAIN: target post-gain multiplier (example: 1.6)
# - SPEAK_SELECTION_WAV_POST_PEAK: peak ceiling 0.0-1.0 (example: 0.95)
# - SPEAK_SELECTION_WAV_COMPRESS: 1|true|yes for gentle compression before gain
# - SPEAK_SELECTION_WAV_COMPRESS_THRESHOLD: compressor threshold 0.0-1.0
# - SPEAK_SELECTION_WAV_COMPRESS_RATIO: compressor ratio (>1.0, example: 3.0)
# - SPEAK_SELECTION_RESET_STREAM_VOLUME: 1|true|yes to reset Linux stream volume for mpv
# - SPEAK_SELECTION_STREAM_VOLUME: Linux stream volume target percent (example: 100)
# - SPEAK_SELECTION_SELECTION_TIMEOUT: selection command timeout in seconds
# - SPEAK_SELECTION_SELECTION_RETRIES: retry count for selection capture
# - SPEAK_SELECTION_SELECTION_RETRY_DELAY: delay between selection retries
# - SPEAK_SELECTION_ALLOW_CLIPBOARD_FALLBACK: Linux fallback to clipboard if primary is empty
# - SPEAK_SELECTION_EMPTY_TOGGLES: empty selection toggles pause/resume (default off)
# - SPEAK_SELECTION_AUTO_TRAY: auto-start tray mode on Linux/macOS when script is invoked
# - SPEAK_SELECTION_LENGTH_SCALE: Piper speaking pace (lower=faster, example: 0.9)
# - SPEAK_SELECTION_NOISE_SCALE: Piper variation (example: 0.667)
# - SPEAK_SELECTION_NOISE_W: Piper phoneme width variation (example: 0.8)
# - SPEAK_SELECTION_AUTO_LANGUAGE: 1|true|yes to route text to matching language voices
# - SPEAK_SELECTION_CACHE_ENABLED: 1|true|yes to cache synthesized audio
# - SPEAK_SELECTION_CACHE_MAX_FILES: max number of cached wav files
# - SPEAK_SELECTION_ARTICLE_MAX_CHARS: max article text length when using --read-page

DEFAULT_TEST_TEXT = "This is a hardcoded test of the speak selection script."
SEGMENT_MAX_CHARS = 220

def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def clamp_float(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def apply_post_gain_to_wav(path: str):
    if not WAV_POST_BOOST_ENABLED:
        return

    target_gain = max(1.0, WAV_POST_GAIN)
    target_peak = clamp_float(WAV_POST_PEAK, 0.1, 0.99)

    try:
        with wave.open(path, "rb") as wav_in:
            params = wav_in.getparams()
            audio_data = wav_in.readframes(wav_in.getnframes())
    except Exception:
        return

    if params.sampwidth != 2 or not audio_data:
        return

    samples = array("h")
    try:
        samples.frombytes(audio_data)
    except Exception:
        return

    if not samples:
        return

    if sys.byteorder != "little":
        samples.byteswap()

    if WAV_COMPRESS_ENABLED and WAV_COMPRESS_RATIO > 1.0:
        threshold = int(32767 * clamp_float(WAV_COMPRESS_THRESHOLD, 0.05, 0.99))
        ratio = max(1.01, WAV_COMPRESS_RATIO)
        for idx, sample in enumerate(samples):
            amplitude = abs(sample)
            if amplitude <= threshold:
                continue

            compressed = threshold + int((amplitude - threshold) / ratio)
            if compressed > 32767:
                compressed = 32767
            samples[idx] = -compressed if sample < 0 else compressed

    max_sample = max(abs(sample) for sample in samples)
    if max_sample <= 0:
        return

    peak_limit = int(32767 * target_peak)
    safe_gain = peak_limit / max_sample
    gain = min(target_gain, safe_gain)

    if gain > 1.001:
        for idx, sample in enumerate(samples):
            scaled = int(sample * gain)
            if scaled > 32767:
                scaled = 32767
            elif scaled < -32768:
                scaled = -32768
            samples[idx] = scaled

    if sys.byteorder != "little":
        samples.byteswap()

    boosted = samples.tobytes()

    try:
        with wave.open(path, "wb") as wav_out:
            wav_out.setparams(params)
            wav_out.writeframes(boosted)
    except Exception:
        return


def current_audio_settings() -> dict:
    return {
        "length_scale": PIPER_LENGTH_SCALE,
        "playback_speed": PLAYBACK_SPEED,
        "playback_volume": PLAYBACK_VOLUME,
        "wav_post_boost": WAV_POST_BOOST_ENABLED,
        "wav_post_gain": WAV_POST_GAIN,
        "wav_post_peak": WAV_POST_PEAK,
        "wav_compress": WAV_COMPRESS_ENABLED,
        "wav_compress_threshold": WAV_COMPRESS_THRESHOLD,
        "wav_compress_ratio": WAV_COMPRESS_RATIO,
    }


def apply_audio_settings(settings: dict):
    if not isinstance(settings, dict):
        return

    def _to_float(name: str, default: float) -> float:
        value = settings.get(name, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _to_bool(name: str, default: bool) -> bool:
        value = settings.get(name, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    global PIPER_LENGTH_SCALE
    global PLAYBACK_SPEED
    global PLAYBACK_VOLUME
    global WAV_POST_BOOST_ENABLED
    global WAV_POST_GAIN
    global WAV_POST_PEAK
    global WAV_COMPRESS_ENABLED
    global WAV_COMPRESS_THRESHOLD
    global WAV_COMPRESS_RATIO

    PIPER_LENGTH_SCALE = clamp_float(_to_float("length_scale", PIPER_LENGTH_SCALE), 0.5, 2.0)
    PLAYBACK_SPEED = clamp_float(_to_float("playback_speed", PLAYBACK_SPEED), 0.25, 4.0)
    PLAYBACK_VOLUME = clamp_float(_to_float("playback_volume", PLAYBACK_VOLUME), 0.0, 200.0)
    WAV_POST_BOOST_ENABLED = _to_bool("wav_post_boost", WAV_POST_BOOST_ENABLED)
    WAV_POST_GAIN = clamp_float(_to_float("wav_post_gain", WAV_POST_GAIN), 1.0, 3.0)
    WAV_POST_PEAK = clamp_float(_to_float("wav_post_peak", WAV_POST_PEAK), 0.1, 0.99)
    WAV_COMPRESS_ENABLED = _to_bool("wav_compress", WAV_COMPRESS_ENABLED)
    WAV_COMPRESS_THRESHOLD = clamp_float(
        _to_float("wav_compress_threshold", WAV_COMPRESS_THRESHOLD),
        0.05,
        0.99,
    )
    WAV_COMPRESS_RATIO = clamp_float(_to_float("wav_compress_ratio", WAV_COMPRESS_RATIO), 1.01, 20.0)


def load_user_settings() -> dict:
    try:
        if SETTINGS_PATH.exists():
            with SETTINGS_PATH.open("r", encoding="utf-8") as settings_file:
                payload = json.load(settings_file)
                if isinstance(payload, dict):
                    return payload
    except Exception:
        pass
    return {}


def save_user_settings(settings: dict):
    if not isinstance(settings, dict):
        return
    ensure_state_dir()
    tmp_path = SETTINGS_PATH.with_suffix(".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, indent=2, sort_keys=True)
        os.replace(tmp_path, SETTINGS_PATH)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def update_user_settings(updates: dict):
    if not isinstance(updates, dict):
        return
    global USER_SETTINGS
    USER_SETTINGS = {**USER_SETTINGS, **updates}
    save_user_settings(USER_SETTINGS)


def bootstrap_runtime_settings():
    audio_settings = USER_SETTINGS.get("audio_settings", {})
    if not isinstance(audio_settings, dict):
        return

    env_map = {
        "length_scale": "SPEAK_SELECTION_LENGTH_SCALE",
        "playback_speed": "SPEAK_SELECTION_PLAYBACK_SPEED",
        "playback_volume": "SPEAK_SELECTION_VOLUME",
        "wav_post_boost": "SPEAK_SELECTION_WAV_POST_BOOST",
        "wav_post_gain": "SPEAK_SELECTION_WAV_POST_GAIN",
        "wav_post_peak": "SPEAK_SELECTION_WAV_POST_PEAK",
        "wav_compress": "SPEAK_SELECTION_WAV_COMPRESS",
        "wav_compress_threshold": "SPEAK_SELECTION_WAV_COMPRESS_THRESHOLD",
        "wav_compress_ratio": "SPEAK_SELECTION_WAV_COMPRESS_RATIO",
    }

    filtered_settings = {}
    for key, value in audio_settings.items():
        env_name = env_map.get(key)
        if not env_name:
            continue
        if os.environ.get(env_name) is not None:
            continue
        filtered_settings[key] = value

    apply_audio_settings(filtered_settings)


USER_SETTINGS = load_user_settings()
bootstrap_runtime_settings()


def compute_request_hash(text: str, voice_preference: str = "", audio_settings: Optional[dict] = None) -> str:
    if audio_settings is None:
        audio_settings = current_audio_settings()

    fingerprint_obj = {
        "text": normalize_text(text),
        "voice": (voice_preference or "").strip(),
        "audio": audio_settings,
    }
    fingerprint = json.dumps(
        fingerprint_obj,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def analyze_wav_levels(path: str) -> dict:
    with wave.open(path, "rb") as wav_file:
        sample_width = wav_file.getsampwidth()
        n_channels = wav_file.getnchannels()
        frame_count = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
        data = wav_file.readframes(frame_count)

    stats = {
        "path": path,
        "sample_width": sample_width,
        "channels": n_channels,
        "sample_rate": sample_rate,
        "frames": frame_count,
    }

    if sample_width != 2 or not data:
        stats["note"] = "Only 16-bit WAV analysis is supported."
        return stats

    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()

    peak = max(abs(sample) for sample in samples) if samples else 0
    rms = int((sum(sample * sample for sample in samples) / len(samples)) ** 0.5) if samples else 0

    stats["peak"] = peak
    stats["rms"] = rms
    stats["peak_percent"] = round((peak / 32767.0) * 100.0, 2) if peak else 0.0
    stats["rms_percent"] = round((rms / 32767.0) * 100.0, 2) if rms else 0.0
    stats["peak_dbfs"] = round(20 * math.log10(max(peak / 32767.0, 1e-12)), 2) if peak else -120.0
    stats["rms_dbfs"] = round(20 * math.log10(max(rms / 32767.0, 1e-12)), 2) if rms else -120.0
    stats["crest_factor"] = round((peak / rms), 3) if rms else 0.0
    return stats


def diagnose_audio(text: str):
    text = normalize_text(text)
    if not text:
        text = DEFAULT_TEST_TEXT

    ensure_state_dir()
    daemon = Daemon()
    voice_path = choose_voice_path_for_text(text)
    voice = daemon.load_voice(voice_path)

    raw_fd, raw_path = tempfile.mkstemp(prefix="speak-selection-diag-raw-", suffix=".wav", dir=str(STATE_DIR))
    os.close(raw_fd)
    boosted_path = raw_path.replace("-raw-", "-boost-")

    try:
        daemon.synthesize_text_to_file(
            text,
            raw_path,
            voice,
            syn_config=daemon.get_synthesis_config(),
            segment_text=True,
        )
        raw_stats = analyze_wav_levels(raw_path)

        shutil.copyfile(raw_path, boosted_path)
        apply_post_gain_to_wav(boosted_path)
        boosted_stats = analyze_wav_levels(boosted_path)

        payload = {
            "audio_settings": current_audio_settings(),
            "voice_path": str(voice_path),
            "raw": raw_stats,
            "boosted": boosted_stats,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        for p in (raw_path, boosted_path):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
            except Exception:
                pass


def maybe_reset_linux_stream_volume(mpv_pid: int):
    if sys.platform != "linux":
        return
    if not RESET_STREAM_VOLUME:
        return

    wpctl = shutil.which("wpctl")
    pactl = shutil.which("pactl")
    if not wpctl and not pactl:
        return

    target_volume = f"{STREAM_VOLUME_PERCENT}%"

    def try_wpctl() -> bool:
        if not wpctl:
            return False
        try:
            subprocess.run(
                [wpctl, "set-volume", "--pid", str(mpv_pid), target_volume],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

            status_proc = subprocess.run(
                [wpctl, "status"],
                capture_output=True,
                text=True,
                check=False,
            )
            if status_proc.returncode != 0:
                return False

            stream_ids = []
            in_streams = False
            for line in status_proc.stdout.splitlines():
                stripped = line.strip()
                if "Streams:" in stripped:
                    in_streams = True
                    continue
                if in_streams and (stripped.startswith("Video") or stripped.startswith("Settings")):
                    break
                if not in_streams:
                    continue

                match_id = re.match(r"^(\d+)\.", stripped)
                if match_id:
                    stream_ids.append(match_id.group(1))

            for stream_id in stream_ids:
                inspect_proc = subprocess.run(
                    [wpctl, "inspect", stream_id],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if inspect_proc.returncode != 0:
                    continue

                inspect_text = inspect_proc.stdout
                is_output_stream = 'media.class = "Stream/Output/Audio"' in inspect_text
                is_mpv = (
                    'application.name = "mpv"' in inspect_text
                    or 'node.name = "mpv"' in inspect_text
                    or 'node.description = "mpv"' in inspect_text
                )
                if not (is_output_stream and is_mpv):
                    continue

                set_proc = subprocess.run(
                    [wpctl, "set-volume", stream_id, target_volume],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if set_proc.returncode == 0:
                    return True

            return False
        except Exception:
            return False

    def try_pactl() -> bool:
        if not pactl:
            return False

        try:
            proc = subprocess.run(
                [pactl, "list", "sink-inputs"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                return False

            current_sink_id = None
            for line in proc.stdout.splitlines():
                stripped = line.strip()
                match_sink = re.match(r"Sink Input #(\d+)", stripped)
                if match_sink:
                    current_sink_id = match_sink.group(1)
                    continue

                if current_sink_id is None:
                    continue

                match_pid = re.search(
                    r'application\.process\.id\s*=\s*"?(\d+)"?',
                    stripped,
                )
                if not match_pid:
                    continue

                if int(match_pid.group(1)) != mpv_pid:
                    continue

                subprocess.run(
                    [pactl, "set-sink-input-volume", current_sink_id, target_volume],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return True
        except Exception:
            return False

        return False

    def worker():
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if try_wpctl() or try_pactl():
                return

            time.sleep(0.05)

    threading.Thread(target=worker, daemon=True).start()


def looks_like_url(text: str) -> bool:
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def download_file(url: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(destination.suffix + ".download")
    req = urllib.request.Request(url, headers={"User-Agent": "speak-selection/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=30) as response, tmp_path.open("wb") as tmp:
            shutil.copyfileobj(response, tmp)
        os.replace(tmp_path, destination)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def ensure_default_voice_available():
    medium_path = VOICE_MODELS["medium"]
    medium_config_path = Path(str(medium_path) + ".json")
    if medium_path.exists() and medium_config_path.exists():
        return

    info = DEFAULT_VOICE_DOWNLOADS["medium"]

    try:
        if not medium_path.exists():
            download_file(info["onnx"], medium_path)
        if not medium_config_path.exists():
            download_file(info["json"], medium_config_path)
    except Exception as e:
        raise FileNotFoundError(
            "No Piper voice was found and automatic download failed.\n"
            "You can manually download voices from:\n"
            "https://rhasspy.github.io/piper-samples/\n"
            "https://huggingface.co/rhasspy/piper-voices"
        ) from e


VOICE_CATALOG_CACHE = None
VOICE_CATALOG_LOCK = threading.Lock()


def fetch_voice_catalog(force_refresh: bool = False) -> dict:
    global VOICE_CATALOG_CACHE

    with VOICE_CATALOG_LOCK:
        if VOICE_CATALOG_CACHE is not None and not force_refresh:
            return VOICE_CATALOG_CACHE

        req = urllib.request.Request(
            VOICE_CATALOG_URL,
            headers={"User-Agent": "speak-selection/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            raw_catalog = json.load(response)

        catalog = {}
        for voice_key, entry in raw_catalog.items():
            files = entry.get("files", {})
            if not isinstance(files, dict):
                continue

            onnx_rel = ""
            json_rel = ""
            for rel_path in files.keys():
                if rel_path.endswith(".onnx") and not rel_path.endswith(".onnx.json"):
                    onnx_rel = rel_path
                elif rel_path.endswith(".onnx.json"):
                    json_rel = rel_path

            if not onnx_rel or not json_rel:
                continue

            model_name = Path(onnx_rel).name
            model_path = VOICE_DIR / model_name
            config_path = VOICE_DIR / f"{model_name}.json"
            catalog[voice_key] = {
                "key": voice_key,
                "language": str(entry.get("language", {}).get("code", "")),
                "quality": str(entry.get("quality", "")),
                "onnx_rel": onnx_rel,
                "json_rel": json_rel,
                "model_path": model_path,
                "config_path": config_path,
            }

        VOICE_CATALOG_CACHE = catalog
        return catalog


def voice_catalog_entry_for_local_path(local_voice_path: Path):
    local_name = local_voice_path.name
    try:
        catalog = fetch_voice_catalog()
    except Exception:
        return None

    for entry in catalog.values():
        model_path = entry.get("model_path")
        if isinstance(model_path, Path) and model_path.name == local_name:
            return entry
    return None


def is_voice_downloaded(entry: dict) -> bool:
    model_path = entry.get("model_path")
    config_path = entry.get("config_path")
    return isinstance(model_path, Path) and isinstance(config_path, Path) and model_path.exists() and config_path.exists()


def download_voice_from_catalog(voice_key: str) -> Path:
    catalog = fetch_voice_catalog()
    entry = catalog.get(voice_key)
    if not entry:
        raise ValueError(f"Voice key not found in catalog: {voice_key}")

    model_path = entry["model_path"]
    config_path = entry["config_path"]
    if model_path.exists() and config_path.exists():
        return model_path

    onnx_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{entry['onnx_rel']}"
    json_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{entry['json_rel']}"

    download_file(onnx_url, model_path)
    download_file(json_url, config_path)
    return model_path


def list_available_voice_paths() -> list[Path]:
    if not VOICE_DIR.exists():
        return []
    return sorted(VOICE_DIR.glob("*.onnx"))


def format_voice_label(voice_path: Path) -> str:
    return voice_path.stem


def detect_text_language(text: str) -> str:
    if not AUTO_LANGUAGE_ROUTING:
        return ""

    text = normalize_text(text)
    if len(text) < 12:
        return ""

    try:
        from langdetect import detect
    except Exception:
        return ""

    try:
        detected = detect(text)
    except Exception:
        return ""

    if not detected:
        return ""

    return detected.split("-")[0].lower()


def find_voice_for_language(language_code: str):
    language_code = language_code.strip().lower()
    if not language_code:
        return None

    voices = list_available_voice_paths()
    if not voices:
        return None

    prefix = f"{language_code}_"
    matches = [voice for voice in voices if voice.stem.lower().startswith(prefix)]
    if not matches:
        return None

    for quality in ("medium", "high"):
        for voice in matches:
            if f"-{quality}" in voice.stem.lower():
                return voice

    return matches[0]


def get_voice_preference() -> str:
    env_voice = os.environ.get("SPEAK_SELECTION_VOICE")
    if env_voice is not None:
        return env_voice.strip()

    setting_voice = USER_SETTINGS.get("voice_preference")
    if isinstance(setting_voice, str) and setting_voice.strip():
        return setting_voice.strip()

    return "auto"


def low_memory_ort_enabled() -> bool:
    return os.environ.get("SPEAK_SELECTION_LOW_MEMORY_ORT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_voice_candidates(preference: Optional[str] = None) -> list[Path]:
    if preference is None:
        preference = get_voice_preference()
    preference = preference.strip()

    if not preference:
        return [VOICE_MODELS[name] for name in DEFAULT_VOICE_ORDER]

    pref_lower = preference.lower()
    if pref_lower == "auto":
        return [VOICE_MODELS[name] for name in DEFAULT_VOICE_ORDER]

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


def resolve_voice_path(preference: Optional[str] = None) -> Path:
    candidates = get_voice_candidates(preference)
    for candidate in candidates:
        if candidate.exists():
            return candidate

    pref_lower = (preference or "").strip().lower()
    if not pref_lower or pref_lower in VOICE_MODELS:
        ensure_default_voice_available()
        candidates = get_voice_candidates(preference)
        for candidate in candidates:
            if candidate.exists():
                return candidate

    raise FileNotFoundError(
        "No Piper voice found. Expected one of:\n"
        + "\n".join(str(candidate) for candidate in candidates)
    )


def choose_voice_path_for_text(text: str, preference: Optional[str] = None) -> Path:
    if preference is None:
        preference = get_voice_preference()

    normalized_preference = preference.strip().lower()
    if normalized_preference == "auto":
        normalized_preference = ""

    if normalized_preference:
        return resolve_voice_path(preference)

    language_code = detect_text_language(text)
    language_voice = find_voice_for_language(language_code)
    if language_voice is not None and language_voice.exists():
        return language_voice

    return get_voice_path()


def synthesis_cache_key(text: str, voice_path: Path) -> str:
    fingerprint = "|".join(
        [
            normalize_text(text),
            str(voice_path.resolve()),
            f"len={PIPER_LENGTH_SCALE}",
            f"noise={NOISE_SCALE}",
            f"noise_w={NOISE_W}",
            f"post_boost={WAV_POST_BOOST_ENABLED}",
            f"post_gain={WAV_POST_GAIN}",
            f"post_peak={WAV_POST_PEAK}",
            f"compress={WAV_COMPRESS_ENABLED}",
            f"compress_threshold={WAV_COMPRESS_THRESHOLD}",
            f"compress_ratio={WAV_COMPRESS_RATIO}",
        ]
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def synthesis_cache_path(text: str, voice_path: Path) -> Path:
    return CACHE_DIR / f"{synthesis_cache_key(text, voice_path)}.wav"


def is_cache_audio_path(path: str) -> bool:
    try:
        resolved = Path(path).resolve()
        return resolved.is_relative_to(CACHE_DIR.resolve())
    except Exception:
        return False

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
    return resolve_voice_path()

def _read_command_text(cmd: list[str], timeout: float) -> str:
    out = subprocess.check_output(
        cmd,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
    )
    return normalize_text(out)


def _selection_commands_for_current_os(include_clipboard_fallback: bool = False) -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbpaste"]]
    if sys.platform == "win32":
        return [["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]]

    xdg = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if xdg == "wayland":
        commands = [
            ["wl-paste", "--primary", "--no-newline"],
        ]
        if include_clipboard_fallback:
            commands.append(["wl-paste", "--no-newline"])
        return commands

    commands = [
        ["xsel", "--primary", "--output"],
        ["xclip", "-o", "-selection", "primary"],
    ]
    if include_clipboard_fallback:
        commands.extend(
            [
                ["xsel", "--clipboard", "--output"],
                ["xclip", "-o", "-selection", "clipboard"],
            ]
        )
    return commands


def get_selected_text() -> str:
    commands = _selection_commands_for_current_os(
        include_clipboard_fallback=ALLOW_CLIPBOARD_FALLBACK,
    )
    if not commands:
        return ""

    for attempt in range(SELECTION_READ_RETRIES):
        for cmd in commands:
            try:
                out = _read_command_text(cmd, timeout=SELECTION_READ_TIMEOUT)
                if out:
                    return out
            except Exception:
                pass

        if attempt < (SELECTION_READ_RETRIES - 1):
            time.sleep(SELECTION_RETRY_DELAY)

    return ""


def _safe_unlink(path: Path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _read_pid(path: Path) -> int:
    raw = path.read_text().strip()
    return int(raw)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _pid_cmdline(pid: int) -> str:
    if sys.platform == "linux":
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.exists():
            try:
                data = proc_cmdline.read_bytes()
                if data:
                    return data.decode("utf-8", errors="ignore").replace("\x00", " ").strip()
            except Exception:
                pass

    try:
        output = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "args="],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.8,
        )
        return output.strip()
    except Exception:
        return ""


def _pid_matches_flag(pid: int, required_flag: str) -> bool:
    if not required_flag:
        return True
    cmdline = _pid_cmdline(pid)
    if not cmdline:
        return False
    return required_flag in cmdline


def _pid_file_alive(path: Path, required_flag: str = "") -> bool:
    if not path.exists():
        return False

    try:
        pid = _read_pid(path)
    except Exception:
        _safe_unlink(path)
        return False

    if not _pid_exists(pid):
        _safe_unlink(path)
        return False

    if required_flag and not _pid_matches_flag(pid, required_flag):
        _safe_unlink(path)
        return False

    return True


def daemon_alive() -> bool:
    return _pid_file_alive(DAEMON_PID_PATH, required_flag="--daemon")


def tray_alive() -> bool:
    return _pid_file_alive(TRAY_PID_PATH, required_flag="--tray")


def settings_ui_alive() -> bool:
    return _pid_file_alive(SETTINGS_UI_PID_PATH, required_flag="--settings-ui")


def start_tray_background():
    ensure_state_dir()
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--tray"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    TRAY_PID_PATH.write_text(str(proc.pid))


def start_settings_ui_background():
    ensure_state_dir()
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--settings-ui"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    SETTINGS_UI_PID_PATH.write_text(str(proc.pid))


def ensure_tray_running():
    if sys.platform not in {"linux", "darwin"}:
        return
    if not AUTO_TRAY_ENABLED:
        return
    if tray_alive():
        return
    start_tray_background()


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


def make_speak_payload(text: str, voice_preference: str = "") -> dict:
    normalized = normalize_text(text)
    settings = current_audio_settings()
    return {
        "cmd": "speak",
        "text": normalized,
        "hash": compute_request_hash(normalized, voice_preference=voice_preference, audio_settings=settings)
        if normalized
        else "",
        "voice": voice_preference.strip(),
        "audio_settings": settings,
    }


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


def send_request_with_daemon_start(payload: dict, timeout: float = 2.0) -> bool:
    if not daemon_alive():
        start_daemon()
    return send_request(payload, timeout=timeout)


def speak_selection_with_daemon():
    text = get_selected_text()
    payload = make_speak_payload(text)
    if not send_request_with_daemon_start(payload):
        raise SystemExit("Could not contact speak-selection daemon.")


def extract_url_from_text(text: str) -> str:
    match = re.search(r"https?://\\S+", text or "", flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).strip(").,;\"'[]{}")


def html_to_readable_text(html_content: str) -> str:
    article_match = re.search(r"(?is)<article\\b[^>]*>(.*?)</article>", html_content)
    if article_match:
        html_content = article_match.group(1)

    html_content = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", html_content)
    html_content = re.sub(r"(?is)<br\\s*/?>", "\n", html_content)
    html_content = re.sub(
        r"(?is)</(p|div|section|article|li|h1|h2|h3|h4|h5|h6|tr|td)>",
        "\n",
        html_content,
    )
    text = re.sub(r"(?is)<[^>]+>", " ", html_content)
    text = html.unescape(text)

    lines = []
    for raw_line in text.splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        lines.append(line)

    combined = "\n".join(lines)
    if len(combined) > ARTICLE_MAX_CHARS:
        return combined[:ARTICLE_MAX_CHARS]
    return combined


def fetch_article_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = response.read(4 * 1024 * 1024)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not fetch URL: {url}") from e

    decoded = payload.decode("utf-8", errors="ignore")
    extracted = html_to_readable_text(decoded)
    extracted = normalize_text(extracted)
    if not extracted:
        raise RuntimeError("Could not extract readable text from page.")
    return extracted


def resolve_article_url(input_url: Optional[str]) -> str:
    if input_url:
        candidate = input_url.strip()
        if looks_like_url(candidate):
            return candidate

    selected = get_selected_text()
    from_selection = extract_url_from_text(selected)
    if from_selection:
        return from_selection

    raise SystemExit(
        "No URL found. Provide one with --read-page <URL> "
        "or copy/select a URL first."
    )


def read_page_mode(input_url: Optional[str] = None, voice_preference: str = ""):
    url = resolve_article_url(input_url)
    article_text = fetch_article_text(url)

    if sys.platform == "win32":
        speak_text_direct(article_text, voice_preference=voice_preference)
        return

    payload = make_speak_payload(article_text, voice_preference=voice_preference)
    if not send_request_with_daemon_start(payload, timeout=4.0):
        raise SystemExit("Could not contact speak-selection daemon for --read-page mode.")


def send_control_command(cmd: str, **extra_fields):
    if sys.platform == "win32" and cmd != "speak":
        return False

    payload = {"cmd": cmd}
    payload.update(extra_fields)
    return send_request_with_daemon_start(payload, timeout=2.0)


def _voice_option_items(catalog: Optional[dict] = None) -> list[dict]:
    options = [
        {
            "id": "auto",
            "label": "[Default] Auto language + fallback",
            "preference": "auto",
            "catalog_key": "",
            "path": None,
        }
    ]

    known_model_names = set()

    if isinstance(catalog, dict) and catalog:
        for voice_key in sorted(catalog.keys()):
            entry = catalog.get(voice_key, {})
            model_path = entry.get("model_path")
            if not isinstance(model_path, Path):
                continue

            known_model_names.add(model_path.name)
            downloaded = is_voice_downloaded(entry)
            language = str(entry.get("language", "")).strip()
            quality = str(entry.get("quality", "")).strip()

            detail_parts = [part for part in (language, quality) if part]
            detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
            prefix = "[Downloaded]" if downloaded else "[Download]"

            options.append(
                {
                    "id": f"catalog:{voice_key}",
                    "label": f"{prefix} {voice_key}{detail}",
                    "preference": str(model_path),
                    "catalog_key": voice_key,
                    "path": model_path,
                }
            )
    else:
        for name in DEFAULT_VOICE_ORDER:
            voice_path = VOICE_MODELS[name]
            config_path = Path(str(voice_path) + ".json")
            downloaded = voice_path.exists() and config_path.exists()
            prefix = "[Downloaded]" if downloaded else "[Download]"
            options.append(
                {
                    "id": f"alias:{name}",
                    "label": f"{prefix} English {name.title()} ({voice_path.stem})",
                    "preference": name,
                    "catalog_key": "",
                    "path": voice_path,
                }
            )
            known_model_names.add(voice_path.name)

    for voice_path in list_available_voice_paths():
        if voice_path.name in known_model_names:
            continue
        options.append(
            {
                "id": f"path:{voice_path}",
                "label": f"[Downloaded] Local: {format_voice_label(voice_path)}",
                "preference": str(voice_path),
                "catalog_key": "",
                "path": voice_path,
            }
        )

    return options


def _pick_voice_option_id(options: list[dict], voice_preference: str) -> str:
    if not options:
        return "auto"

    preference = (voice_preference or "").strip()
    if not preference or preference.lower() == "auto":
        return "auto"

    for option in options:
        if str(option.get("preference", "")).strip() == preference:
            return str(option.get("id", "auto"))

    pref_lower = preference.lower()
    if pref_lower in VOICE_MODELS:
        alias_path = VOICE_MODELS[pref_lower]
        for option in options:
            option_path = option.get("path")
            if isinstance(option_path, Path) and option_path.name == alias_path.name:
                return str(option.get("id", "auto"))

    try:
        normalized_pref = str(Path(preference).expanduser().resolve())
    except Exception:
        normalized_pref = str(Path(preference).expanduser())

    for option in options:
        option_path = option.get("path")
        if not isinstance(option_path, Path):
            continue
        try:
            normalized_option = str(option_path.expanduser().resolve())
        except Exception:
            normalized_option = str(option_path.expanduser())
        if normalized_option == normalized_pref:
            return str(option.get("id", "auto"))

    return "auto"


def _clear_pid_file_if_current(path: Path):
    try:
        if not path.exists():
            return
        recorded_pid = int(path.read_text().strip())
        if recorded_pid == os.getpid():
            path.unlink()
    except Exception:
        pass


def settings_ui_main():
    ensure_state_dir()
    SETTINGS_UI_PID_PATH.write_text(str(os.getpid()))
    atexit.register(_clear_pid_file_if_current, SETTINGS_UI_PID_PATH)

    try:
        import tkinter as tk
        from tkinter import ttk
        import tkinter.font as tkfont
    except Exception as e:
        raise SystemExit(
            "Settings UI requires tkinter.\n"
            "Install your platform tkinter package and try again."
        ) from e

    root = tk.Tk()
    root.title("Speak Selection")
    window_width = 380
    window_height = 360
    root.resizable(False, False)
    root.configure(bg="#f3f5f8")
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = max(0, screen_w - window_width - 20)
    y = max(0, screen_h - window_height - 64)
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    def pick_font(preferred: list[str], fallback: str = "DejaVu Sans") -> str:
        try:
            available = {name.lower(): name for name in tkfont.families(root)}
        except Exception:
            return fallback

        for name in preferred:
            matched = available.get(name.lower())
            if matched:
                return matched
        return fallback

    ui_font = pick_font(
        [
            "Cantarell",
            "Noto Sans",
            "Segoe UI",
            "Ubuntu",
            "DejaVu Sans",
            "Liberation Sans",
            "Arial",
        ]
    )

    background = "#f3f5f8"
    card_bg = "#f9fafb"
    text_primary = "#111827"
    text_muted = "#6b7280"
    accent = "#2563eb"
    input_bg = "#ffffff"

    style.configure(".", font=(ui_font, 10))
    style.configure("Root.TFrame", background=background)
    style.configure("Panel.TFrame", background=card_bg)
    style.configure("Action.TFrame", background=card_bg)
    style.configure("TLabel", background=card_bg, foreground=text_primary)
    style.configure(
        "Title.TLabel",
        background=card_bg,
        foreground=text_primary,
        font=(ui_font, 12, "bold"),
    )
    style.configure(
        "Muted.TLabel",
        background=card_bg,
        foreground=text_muted,
        font=(ui_font, 10),
    )
    style.configure(
        "Field.TLabel",
        background=card_bg,
        foreground=text_primary,
        font=(ui_font, 10, "bold"),
    )
    style.configure(
        "Value.TLabel",
        background=card_bg,
        foreground=accent,
        font=(ui_font, 10, "bold"),
    )
    style.configure(
        "Status.TLabel",
        background=card_bg,
        foreground=text_muted,
        font=(ui_font, 10),
    )
    style.configure("TButton", font=(ui_font, 10), padding=(10, 5), relief="flat")
    style.map("TButton", relief=[("pressed", "flat"), ("active", "flat")])
    style.configure(
        "Link.TLabel",
        background=card_bg,
        foreground="#1d4ed8",
        font=(ui_font, 10, "underline"),
    )
    style.configure(
        "Modern.TCombobox",
        fieldbackground=input_bg,
        background=input_bg,
        foreground=text_primary,
        bordercolor="#d1d5db",
        lightcolor="#d1d5db",
        darkcolor="#d1d5db",
        arrowsize=15,
        padding=(4, 3),
        font=(ui_font, 10),
    )
    style.map(
        "Modern.TCombobox",
        fieldbackground=[("readonly", input_bg)],
        selectbackground=[("readonly", "#dbeafe")],
        selectforeground=[("readonly", text_primary)],
    )
    style.configure("Modern.Horizontal.TScale", background=card_bg)

    try:
        ui_font_spec = f"{{{ui_font}}} 10"
        root.option_add("*TCombobox*Listbox.font", ui_font_spec)
    except Exception:
        pass

    outer = ttk.Frame(root, style="Root.TFrame", padding=12)
    outer.pack(fill="both", expand=True)

    frame = ttk.Frame(outer, style="Panel.TFrame", padding=(12, 10))
    frame.pack(fill="both", expand=True)

    audio = current_audio_settings()
    volume_var = tk.DoubleVar(
        value=clamp_float(float(audio.get("playback_volume", 100.0)), 0.0, 200.0)
    )
    speed_var = tk.DoubleVar(
        value=clamp_float(float(audio.get("playback_speed", 1.0)), 0.25, 4.0)
    )
    status_var = tk.StringVar(value="Loading voices...")
    volume_value_var = tk.StringVar(value=f"{int(round(volume_var.get()))}%")
    speed_value_var = tk.StringVar(value=f"{speed_var.get():.2f}x")

    voice_choice_var = tk.StringVar()
    voice_label_to_option = {}
    voice_options = {"items": []}
    apply_lock = threading.Lock()
    audio_apply_after_id = {"id": None}

    ttk.Label(frame, text="Playback Settings", style="Title.TLabel").grid(
        row=0,
        column=0,
        columnspan=3,
        sticky="w",
    )
    ttk.Label(
        frame,
        text="Changes save instantly. Pick a voice to auto-download and switch.",
        style="Muted.TLabel",
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))

    ttk.Label(frame, text="Volume", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(2, 0))
    volume_row = ttk.Frame(frame, style="Panel.TFrame")
    volume_row.grid(row=2, column=1, sticky="ew")
    volume_row.columnconfigure(0, weight=1)
    volume_scale = ttk.Scale(
        volume_row,
        from_=0.0,
        to=200.0,
        orient=tk.HORIZONTAL,
        variable=volume_var,
        style="Modern.Horizontal.TScale",
        command=lambda _value: on_volume_changed(),
    )
    volume_scale.grid(row=0, column=0, sticky="ew")
    ttk.Label(volume_row, textvariable=volume_value_var, width=7, style="Value.TLabel", anchor="e").grid(
        row=0, column=1, sticky="e", padx=(8, 0)
    )
    ttk.Label(frame, text="0% to 200%", style="Muted.TLabel").grid(
        row=3,
        column=1,
        sticky="w",
        pady=(2, 0),
    )

    ttk.Label(frame, text="Speed", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(10, 0))
    speed_row = ttk.Frame(frame, style="Panel.TFrame")
    speed_row.grid(row=4, column=1, sticky="ew", pady=(10, 0))
    speed_row.columnconfigure(0, weight=1)
    speed_scale = ttk.Scale(
        speed_row,
        from_=0.25,
        to=4.0,
        orient=tk.HORIZONTAL,
        variable=speed_var,
        style="Modern.Horizontal.TScale",
        command=lambda _value: on_speed_changed(),
    )
    speed_scale.grid(row=0, column=0, sticky="ew")
    ttk.Label(speed_row, textvariable=speed_value_var, width=7, style="Value.TLabel", anchor="e").grid(
        row=0, column=1, sticky="e", padx=(8, 0)
    )
    ttk.Label(frame, text="0.25x to 4.00x", style="Muted.TLabel").grid(
        row=5,
        column=1,
        sticky="w",
        pady=(2, 0),
    )

    ttk.Label(frame, text="Voice", style="Field.TLabel").grid(row=6, column=0, sticky="w", pady=(12, 0))
    voice_combo = ttk.Combobox(
        frame,
        state="readonly",
        width=30,
        textvariable=voice_choice_var,
        style="Modern.TCombobox",
    )
    voice_combo.grid(row=6, column=1, sticky="ew", pady=(12, 0))

    ttk.Label(
        frame,
        text="Voices marked [Download] will be downloaded when selected.",
        style="Muted.TLabel",
    ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

    samples_link = ttk.Label(
        frame,
        text="Listen to voice samples",
        style="Link.TLabel",
        cursor="hand2",
    )
    samples_link.grid(row=8, column=1, sticky="w", pady=(6, 0))

    ttk.Label(frame, textvariable=status_var, style="Status.TLabel", wraplength=340).grid(
        row=9,
        column=0,
        columnspan=2,
        sticky="w",
        pady=(10, 0),
    )

    button_row = ttk.Frame(frame, style="Action.TFrame")
    button_row.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))

    revert_button = ttk.Button(button_row, text="Revert Defaults", width=14)
    revert_button.grid(row=0, column=0, padx=(0, 8))
    refresh_button = ttk.Button(button_row, text="Refresh", width=10)
    refresh_button.grid(row=0, column=1, padx=(0, 8))
    close_button = ttk.Button(button_row, text="Close", command=root.destroy, width=10)
    close_button.grid(row=0, column=2)

    frame.columnconfigure(1, weight=1)

    def selected_voice_option() -> dict:
        selected_label = voice_choice_var.get()
        option = voice_label_to_option.get(selected_label)
        if option:
            return option
        for option in voice_options["items"]:
            if option.get("id") == "auto":
                return option
        return {
            "id": "auto",
            "label": "[Default] Auto language + fallback",
            "preference": "auto",
            "catalog_key": "",
            "path": None,
        }

    def ui_audio_settings() -> dict:
        settings = current_audio_settings()
        settings["playback_speed"] = round(clamp_float(float(speed_var.get()), 0.25, 4.0), 2)
        settings["playback_volume"] = round(clamp_float(float(volume_var.get()), 0.0, 200.0), 1)
        return settings

    def save_audio_settings(audio_settings: dict, voice_preference: Optional[str] = None):
        apply_audio_settings(audio_settings)
        update_payload = {"audio_settings": audio_settings}
        if voice_preference is not None:
            update_payload["voice_preference"] = voice_preference
        update_user_settings(update_payload)
        send_control_command("set_audio_settings", audio_settings=audio_settings)
        if voice_preference is not None:
            send_control_command("set_voice", voice=voice_preference)

    def restyle_voice_dropdown_items():
        try:
            popdown = str(voice_combo.tk.call("ttk::combobox::PopdownWindow", str(voice_combo)))
            listbox_path = f"{popdown}.f.l"
            voice_combo.tk.call(
                listbox_path,
                "configure",
                "-background",
                input_bg,
                "-foreground",
                text_primary,
                "-selectbackground",
                "#dbeafe",
                "-selectforeground",
                text_primary,
            )

            labels = list(voice_combo["values"])
            for idx, label in enumerate(labels):
                is_downloaded = str(label).startswith("[Downloaded]")
                row_bg = "#edf7ef" if is_downloaded else input_bg
                row_fg = "#2f6f49" if is_downloaded else text_primary
                try:
                    voice_combo.tk.call(
                        listbox_path,
                        "itemconfigure",
                        idx,
                        "-background",
                        row_bg,
                        "-foreground",
                        row_fg,
                    )
                except Exception:
                    # Some Tk builds don't support per-row listbox styling.
                    continue
        except Exception:
            pass

    def open_voice_samples(_event=None):
        try:
            import webbrowser

            webbrowser.open_new_tab(VOICE_SAMPLES_URL)
        except Exception:
            pass

    def populate_voice_choices(options: list[dict], catalog_loaded: bool):
        voice_label_to_option.clear()
        for option in options:
            voice_label_to_option[option["label"]] = option

        voice_options["items"] = options
        labels = [option["label"] for option in options]
        voice_combo["values"] = labels

        target_id = _pick_voice_option_id(options, get_voice_preference())
        selected = None
        for option in options:
            if option.get("id") == target_id:
                selected = option
                break
        if selected is None and options:
            selected = options[0]

        if selected is not None:
            voice_choice_var.set(selected["label"])

        restyle_voice_dropdown_items()

        if catalog_loaded:
            status_var.set("Ready.")
        else:
            status_var.set("Voice catalog unavailable. Showing installed/local voices only.")

    def load_voices_async(force_refresh: bool = False):
        status_var.set("Loading voices...")

        def _worker():
            catalog = None
            try:
                catalog = fetch_voice_catalog(force_refresh=force_refresh)
            except Exception:
                catalog = None

            options = _voice_option_items(catalog)

            def _apply_result():
                populate_voice_choices(options, catalog_loaded=bool(catalog))

            try:
                root.after(0, _apply_result)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def apply_audio_only_async():
        audio_settings = ui_audio_settings()

        def _worker():
            try:
                with apply_lock:
                    save_audio_settings(audio_settings)

                def _done():
                    status_var.set("Saved.")

                root.after(0, _done)
            except Exception as e:
                def _error(err=e):
                    status_var.set(f"Could not save settings: {err}")

                root.after(0, _error)

        threading.Thread(target=_worker, daemon=True).start()

    def schedule_audio_apply(delay_ms: int = 220):
        if audio_apply_after_id["id"] is not None:
            try:
                root.after_cancel(audio_apply_after_id["id"])
            except Exception:
                pass
            audio_apply_after_id["id"] = None

        def _run():
            audio_apply_after_id["id"] = None
            apply_audio_only_async()

        status_var.set("Saving...")
        audio_apply_after_id["id"] = root.after(delay_ms, _run)

    def apply_voice_selection_async():
        selected = selected_voice_option()
        requested_audio = ui_audio_settings()
        status_var.set("Saving...")

        def _worker():
            try:
                chosen_preference = str(selected.get("preference", "auto"))
                catalog_key = str(selected.get("catalog_key", "")).strip()
                downloaded_now = False

                with apply_lock:
                    if catalog_key:
                        catalog = fetch_voice_catalog()
                        entry = catalog.get(catalog_key)
                        if not entry:
                            raise RuntimeError(f"Voice not found in catalog: {catalog_key}")
                        if not is_voice_downloaded(entry):
                            downloaded_now = True
                            root.after(
                                0,
                                lambda: status_var.set(f"Downloading voice: {catalog_key} ..."),
                            )
                            model_path = download_voice_from_catalog(catalog_key)
                        else:
                            model_path = entry.get("model_path")

                        if not isinstance(model_path, Path):
                            raise RuntimeError(f"Invalid voice path for {catalog_key}")
                        chosen_preference = str(model_path)

                    save_audio_settings(requested_audio, voice_preference=chosen_preference)

                def _done():
                    status_var.set("Saved.")
                    if downloaded_now:
                        load_voices_async(force_refresh=False)

                root.after(0, _done)
            except Exception as e:
                def _error(err=e):
                    status_var.set(f"Could not save settings: {err}")

                root.after(0, _error)

        threading.Thread(target=_worker, daemon=True).start()

    def on_volume_changed():
        volume_value_var.set(f"{int(round(volume_var.get()))}%")
        schedule_audio_apply()

    def on_speed_changed():
        speed_value_var.set(f"{speed_var.get():.2f}x")
        schedule_audio_apply()

    def on_revert_defaults():
        speed_var.set(1.0)
        volume_var.set(100.0)
        speed_value_var.set("1.00x")
        volume_value_var.set("100%")
        schedule_audio_apply(delay_ms=20)
        status_var.set("Reverted to defaults and saved.")

    voice_combo.configure(postcommand=restyle_voice_dropdown_items)
    voice_combo.bind("<<ComboboxSelected>>", lambda _event: apply_voice_selection_async())
    samples_link.bind("<Button-1>", open_voice_samples)
    samples_link.bind("<Enter>", lambda _event: samples_link.configure(foreground="#1e40af"))
    samples_link.bind("<Leave>", lambda _event: samples_link.configure(foreground="#1d4ed8"))
    revert_button.configure(command=on_revert_defaults)
    refresh_button.configure(command=lambda: load_voices_async(force_refresh=True))

    populate_voice_choices(_voice_option_items(None), catalog_loaded=False)
    status_var.set("Loading voice catalog...")
    load_voices_async(force_refresh=False)
    root.bind("<Escape>", lambda _event: root.destroy())

    try:
        root.mainloop()
    finally:
        _clear_pid_file_if_current(SETTINGS_UI_PID_PATH)


def open_settings_ui():
    if settings_ui_alive():
        return
    start_settings_ui_background()


def tray_main():
    if sys.platform == "win32":
        raise SystemExit("Tray mode is currently supported on Linux/macOS only.")
    ensure_state_dir()
    TRAY_PID_PATH.write_text(str(os.getpid()))
    atexit.register(_clear_pid_file_if_current, TRAY_PID_PATH)

    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception as e:
        raise SystemExit(
            "Tray mode requires extra packages.\n"
            "Install with:\n"
            "python -m pip install pystray pillow"
        ) from e

    def run_background(target, *args, **kwargs):
        thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        thread.start()

    def make_icon_image():
        image = Image.new("RGB", (64, 64), (30, 35, 40))
        draw = ImageDraw.Draw(image)
        draw.ellipse((10, 10, 54, 54), fill=(52, 152, 219))
        draw.rectangle((30, 20, 46, 44), fill=(245, 245, 245))
        draw.rectangle((18, 25, 30, 39), fill=(245, 245, 245))
        return image

    def action_speak(icon, item):
        run_background(client_main)

    def action_pause(icon, item):
        run_background(send_control_command, "pause")

    def action_stop(icon, item):
        run_background(send_control_command, "stop")

    def action_read_page(icon, item):
        run_background(read_page_mode, None, "")

    def action_open_settings(icon, item):
        run_background(open_settings_ui)

    def action_quit(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Settings", action_open_settings, default=True),
        pystray.MenuItem("Speak Selection", action_speak),
        pystray.MenuItem("Pause / Resume", action_pause),
        pystray.MenuItem("Stop", action_stop),
        pystray.MenuItem("Read Page From URL In Clipboard", action_read_page),
        pystray.MenuItem("Quit", action_quit),
    )

    icon = pystray.Icon("speak-selection", make_icon_image(), "Speak Selection", menu)
    supports_default = bool(
        getattr(type(icon), "HAS_DEFAULT_ACTION", getattr(type(icon), "HAS_DEFAULT", False))
    )
    open_settings_on_start = (sys.platform == "linux") and (not supports_default)

    def _setup(icon_instance):
        icon_instance.visible = True
        if open_settings_on_start:
            open_settings_ui()

    icon.run(setup=_setup)


def client_main():
    ensure_state_dir()
    if sys.platform in {"linux", "darwin"}:
        ensure_tray_running()

    if sys.platform == "win32":
        text = get_selected_text()
        speak_text_direct(text)
        return

    speak_selection_with_daemon()

def speak_text_direct(text: str, voice_preference: str = ""):
    text = normalize_text(text)
    if not text:
        raise SystemExit("No text to speak.")

    daemon = Daemon()
    atexit.register(daemon.cleanup)
    voice_path = choose_voice_path_for_text(text, voice_preference or get_voice_preference())
    voice = daemon.load_voice(voice_path)
    path = daemon.synthesize_to_temp(text, voice=voice, voice_path=voice_path)
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
        f"--volume-max={MPV_VOLUME_MAX}",
        f"--volume={PLAYBACK_VOLUME}",
        f"--speed={PLAYBACK_SPEED}",
    ]
    cmd.append(path)

    player = None
    try:
        player = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        maybe_reset_linux_stream_volume(player.pid)
        player.wait()
    except KeyboardInterrupt:
        if player and player.poll() is None:
            try:
                player.terminate()
            except Exception:
                pass

class Daemon:
    def __init__(self):
        self.voice_cache = {}
        self.voice_path = None
        self.server = None
        self.mpv_proc = None
        self.current_hash = ""
        self.pending_hash = ""
        self.current_temp = None
        self.active_temps = []
        self.old_temps = []
        self.request_serial = 0
        self.state_lock = threading.Lock()
        self.voice_preference_override = ""

    def load_voice(self, voice_path: Optional[Path] = None):
        try:
            from piper.voice import PiperVoice
        except Exception as e:
            raise RuntimeError(
                "This script uses Piper's Python API for speed.\n"
                "Install it with:\n"
                "python3 -m pip install --user piper-tts"
            ) from e

        if voice_path is None:
            voice_path = get_voice_path()
        voice_path = voice_path.expanduser()

        cache_key = str(voice_path.resolve())
        if cache_key in self.voice_cache:
            self.voice_path = voice_path
            return self.voice_cache[cache_key]

        config_path = Path(str(voice_path) + ".json")
        if not config_path.exists():
            raise FileNotFoundError(
                f"Missing Piper voice config next to voice file: {config_path}"
            )

        if low_memory_ort_enabled():
            import onnxruntime
            from piper.config import PiperConfig

            with config_path.open("r", encoding="utf-8") as config_file:
                config_dict = json.load(config_file)

            sess_options = onnxruntime.SessionOptions()
            sess_options.enable_cpu_mem_arena = False

            voice = PiperVoice(
                config=PiperConfig.from_dict(config_dict),
                session=onnxruntime.InferenceSession(
                    str(voice_path),
                    sess_options=sess_options,
                    providers=["CPUExecutionProvider"],
                ),
                download_dir=Path.cwd(),
            )
        else:
            voice = PiperVoice.load(str(voice_path), config_path=str(config_path))

        self.voice_cache[cache_key] = voice
        self.voice_path = voice_path
        while len(self.voice_cache) > 4:
            oldest_key = next(iter(self.voice_cache))
            self.voice_cache.pop(oldest_key, None)

        return voice

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
            f"--volume-max={MPV_VOLUME_MAX}",
            f"--volume={PLAYBACK_VOLUME}",
        ]
        cmd.append(f"--input-ipc-server={MPV_SOCKET_PATH}")

        self.mpv_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        maybe_reset_linux_stream_volume(self.mpv_proc.pid)

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

    def synthesize_text_to_file(
        self,
        text: str,
        output_path: str,
        voice,
        syn_config=None,
        segment_text: bool = False,
    ):
        if syn_config is None:
            syn_config = self.get_synthesis_config()

        units = chunk_text_for_streaming(text) if segment_text else [normalize_text(text)]
        if not units:
            raise RuntimeError("No text to synthesize.")

        with wave.open(output_path, "wb") as wav_file:
            first_chunk = True
            for unit in units:
                for audio_chunk in voice.synthesize(unit, syn_config=syn_config):
                    if first_chunk:
                        wav_file.setframerate(audio_chunk.sample_rate)
                        wav_file.setsampwidth(audio_chunk.sample_width)
                        wav_file.setnchannels(audio_chunk.sample_channels)
                        first_chunk = False

                    wav_file.writeframes(audio_chunk.audio_int16_bytes)

            if first_chunk:
                raise RuntimeError("Piper returned no audio chunks.")

    def prune_cache_files(self):
        if not CACHE_ENABLED:
            return

        ensure_cache_dir()
        try:
            cache_files = sorted(
                CACHE_DIR.glob("*.wav"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return

        for stale in cache_files[CACHE_MAX_FILES:]:
            try:
                stale.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass

    def synthesize_segment_to_temp(self, text: str, voice, voice_path: Path, syn_config=None) -> str:
        if syn_config is None:
            syn_config = self.get_synthesis_config()

        if CACHE_ENABLED:
            ensure_cache_dir()
            cache_path = synthesis_cache_path(text, voice_path)
            if cache_path.exists():
                try:
                    os.utime(cache_path, None)
                except Exception:
                    pass
                return str(cache_path)

            fd, tmp_path = tempfile.mkstemp(
                prefix="speak-selection-cache-",
                suffix=".wav",
                dir=str(CACHE_DIR),
            )
            os.close(fd)

            try:
                self.synthesize_text_to_file(text, tmp_path, voice, syn_config=syn_config)
                apply_post_gain_to_wav(tmp_path)
                os.replace(tmp_path, cache_path)
                self.prune_cache_files()
                return str(cache_path)
            finally:
                try:
                    os.remove(tmp_path)
                except FileNotFoundError:
                    pass
                except Exception:
                    pass

        fd, path = tempfile.mkstemp(
            prefix="speak-selection-",
            suffix=".wav",
            dir=str(STATE_DIR),
        )
        os.close(fd)

        try:
            self.synthesize_text_to_file(text, path, voice, syn_config=syn_config)
            apply_post_gain_to_wav(path)
            return path
        except Exception:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            raise

    def synthesize_to_temp(self, text: str, voice, voice_path: Path) -> str:
        syn_config = self.get_synthesis_config()

        if CACHE_ENABLED:
            ensure_cache_dir()
            cache_path = synthesis_cache_path(text, voice_path)
            if cache_path.exists():
                try:
                    os.utime(cache_path, None)
                except Exception:
                    pass
                return str(cache_path)

            fd, tmp_path = tempfile.mkstemp(
                prefix="speak-selection-cache-",
                suffix=".wav",
                dir=str(CACHE_DIR),
            )
            os.close(fd)

            try:
                self.synthesize_text_to_file(
                    text,
                    tmp_path,
                    voice,
                    syn_config=syn_config,
                    segment_text=True,
                )
                apply_post_gain_to_wav(tmp_path)
                os.replace(tmp_path, cache_path)
                self.prune_cache_files()
                return str(cache_path)
            finally:
                try:
                    os.remove(tmp_path)
                except FileNotFoundError:
                    pass
                except Exception:
                    pass

        fd, path = tempfile.mkstemp(
            prefix="speak-selection-",
            suffix=".wav",
            dir=str(STATE_DIR),
        )
        os.close(fd)

        try:
            self.synthesize_text_to_file(
                text,
                path,
                voice,
                syn_config=syn_config,
                segment_text=True,
            )
            apply_post_gain_to_wav(path)
            return path
        except Exception:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            raise

    def cleanup_temp_files(self):
        keep = set(self.active_temps)
        survivors = []

        for path in self.old_temps:
            if path in keep:
                survivors.append(path)
                continue
            if is_cache_audio_path(path):
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
                for path in self.active_temps:
                    if not is_cache_audio_path(path):
                        self.old_temps.append(path)
                self.active_temps = []
                self.current_temp = None

        self.mpv_command("stop")
        self.mpv_command("playlist-clear")
        self.cleanup_temp_files()

    def queue_text(self, text: str, text_hash: str, voice_preference: str = ""):
        self.cancel_current_request()

        effective_preference = (
            voice_preference.strip()
            or self.voice_preference_override.strip()
            or get_voice_preference()
        )
        voice_path = choose_voice_path_for_text(text, preference=effective_preference)
        voice = self.load_voice(voice_path)

        with self.state_lock:
            request_id = self.request_serial
            self.pending_hash = text_hash

        worker = threading.Thread(
            target=self._synthesize_and_queue,
            args=(request_id, text, text_hash, voice, voice_path),
            daemon=True,
        )
        worker.start()

    def _synthesize_and_queue(self, request_id: int, text: str, text_hash: str, voice, voice_path: Path):
        syn_config = self.get_synthesis_config()
        playback_started = False
        queued_paths = []
        segments = chunk_text_for_streaming(text)
        initial_buffer_segments = 2 if len(segments) > 1 else 1

        try:
            for segment in segments:
                if not self.is_request_current(request_id):
                    break

                path = self.synthesize_segment_to_temp(
                    segment,
                    voice=voice,
                    voice_path=voice_path,
                    syn_config=syn_config,
                )

                if not self.is_request_current(request_id):
                    if not is_cache_audio_path(path):
                        try:
                            os.remove(path)
                        except FileNotFoundError:
                            pass
                    break

                with self.state_lock:
                    if request_id != self.request_serial:
                        if not is_cache_audio_path(path):
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
                    self.mpv_command("set_property", "volume-max", MPV_VOLUME_MAX)
                    self.mpv_command("set_property", "volume", PLAYBACK_VOLUME)
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
                self.mpv_command("set_property", "volume-max", MPV_VOLUME_MAX)
                self.mpv_command("set_property", "volume", PLAYBACK_VOLUME)
        finally:
            self.cleanup_temp_files()

    def handle_speak(self, text: str, text_hash: str, voice_preference: str = ""):
        self.ensure_mpv()

        # No current selection: toggle pause/resume on current playback
        if not text:
            if EMPTY_SELECTION_TOGGLES:
                self.toggle_pause()
            return

        # Same selected text: toggle pause/resume
        if text_hash == self.current_hash or text_hash == self.pending_hash:
            # If playback already finished, replay from the beginning.
            if self.is_idle():
                self.queue_text(text, text_hash, voice_preference=voice_preference)
            else:
                self.toggle_pause()
            return

        # New selected text: replace current playback immediately
        self.queue_text(text, text_hash, voice_preference=voice_preference)

    def handle_stop(self):
        self.cancel_current_request()

    def handle_set_voice(self, voice_preference: str):
        preference = (voice_preference or "").strip()
        if preference.lower() == "auto":
            self.voice_preference_override = ""
        else:
            self.voice_preference_override = preference

    def handle_set_audio_settings(self, settings: dict):
        apply_audio_settings(settings)
        try:
            self.ensure_mpv()
            self.mpv_command("set_property", "speed", PLAYBACK_SPEED)
            self.mpv_command("set_property", "volume-max", MPV_VOLUME_MAX)
            self.mpv_command("set_property", "volume", PLAYBACK_VOLUME)
        except Exception:
            pass

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
            if is_cache_audio_path(path):
                continue
            try:
                os.remove(path)
            except Exception:
                pass

    def run(self):
        ensure_state_dir()
        ensure_cache_dir()
        atexit.register(self.cleanup)

        self.load_voice(get_voice_path())
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

                cmd = payload.get("cmd")

                try:
                    if cmd == "speak":
                        apply_audio_settings(payload.get("audio_settings", {}))
                        self.handle_speak(
                            payload.get("text", ""),
                            payload.get("hash", ""),
                            payload.get("voice", ""),
                        )
                    elif cmd == "pause":
                        self.toggle_pause()
                    elif cmd == "stop":
                        self.handle_stop()
                    elif cmd == "set_voice":
                        self.handle_set_voice(payload.get("voice", ""))
                    elif cmd == "set_audio_settings":
                        self.handle_set_audio_settings(payload.get("audio_settings", {}))
                except Exception:
                    continue

if __name__ == "__main__":
    maybe_reexec_for_piper()

    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Run optional tray/menu-bar controls (Linux/macOS).",
    )
    parser.add_argument(
        "--settings-ui",
        action="store_true",
        help="Open a lightweight settings window for speed/volume/voice.",
    )
    parser.add_argument("--text", help="Speak this text instead of reading the current selection.")
    parser.add_argument(
        "--diagnose-audio",
        nargs="?",
        const=DEFAULT_TEST_TEXT,
        metavar="TEXT",
        help="Print synthesized WAV loudness diagnostics and exit.",
    )
    parser.add_argument(
        "--read-page",
        nargs="?",
        const="",
        metavar="URL",
        help="Read a full web page/article from URL or from URL in clipboard/selection.",
    )
    parser.add_argument(
        "--voice",
        help="Voice preference: auto, medium, high, or /path/to/voice.onnx",
    )
    parser.add_argument(
        "--set-runtime-voice",
        metavar="VOICE",
        help="Set daemon voice override: auto, medium, high, or /path/to/voice.onnx",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="Pause/resume current playback in daemon mode.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop current playback in daemon mode.",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List available .onnx voices in the voice folder.",
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

    if args.list_voices:
        ensure_default_voice_available()
        for voice_path in list_available_voice_paths():
            print(f"- {voice_path}")
        raise SystemExit(0)
    if args.diagnose_audio is not None:
        diagnose_audio(args.diagnose_audio)
        raise SystemExit(0)

    if args.daemon and sys.platform == "win32":
        raise SystemExit("Daemon mode is not supported on Windows.")
    if args.daemon:
        Daemon().run()
    elif args.tray:
        tray_main()
    elif args.settings_ui:
        settings_ui_main()
    elif args.read_page is not None:
        read_page_mode(args.read_page or None, voice_preference=args.voice or "")
    elif args.set_runtime_voice is not None:
        if sys.platform == "win32":
            raise SystemExit("Daemon voice control is not supported on Windows.")
        if not send_control_command("set_voice", voice=args.set_runtime_voice):
            raise SystemExit("Could not contact speak-selection daemon.")
    elif args.pause:
        if sys.platform == "win32":
            raise SystemExit("Pause control is not supported on Windows.")
        if not send_control_command("pause"):
            raise SystemExit("Could not contact speak-selection daemon.")
    elif args.stop:
        if sys.platform == "win32":
            raise SystemExit("Stop control is not supported on Windows.")
        if not send_control_command("stop"):
            raise SystemExit("Could not contact speak-selection daemon.")
    elif args.text is not None:
        speak_text_direct(args.text, voice_preference=args.voice or "")
    elif args.test:
        speak_text_direct(DEFAULT_TEST_TEXT, voice_preference=args.voice or "")
    else:
        client_main()
