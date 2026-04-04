# speak-selection

Speak text from your screen out loud with one shortcut.

This project is designed for people who want reading support (for example: dyslexia, eye strain, fatigue, ADHD, or just wanting to listen instead of read).

You highlight text on screen, press a shortcut, and it reads it to you.

## What this project does

- Reads selected text out loud with natural-sounding Piper voices.
- Works on Linux, macOS, and Windows.
- Supports quick pause/resume/stop.
- Can auto-detect language and switch to a matching installed voice.
- Caches synthesized audio so repeated phrases play faster.
- Can read an entire web page/article from a URL.
- Tray/menu-bar app (enabled by default on Linux/macOS) for quick controls and settings.

## Important default behavior

If you do **not** install a voice manually, the script will automatically download:

- `en_US-lessac-medium.onnx`

So you can get started quickly.

The default tuning keeps the original faster voice style and uses a safe post-process boost (instead of aggressive mpv gain) to avoid distortion.

## Voice samples and downloads

- Listen to voice samples: https://rhasspy.github.io/piper-samples/
- Download voices: https://huggingface.co/rhasspy/piper-voices

## Files in this repo

- `speak-selection.py`: main app
- `scripts/run-linux.sh`: Linux launcher
- `scripts/run-macos.sh`: macOS launcher
- `scripts/run-windows.ps1`: Windows launcher
- `scripts/run-windows.cmd`: Windows shortcut wrapper

## 1) Install dependencies

### Linux (Ubuntu/Debian example)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mpv wl-clipboard xsel xclip
```

### macOS

```bash
brew install python mpv
```

### Windows (PowerShell)

```powershell
winget install Python.Python.3.12
winget install mpv.mpv
```

## 2) Create Python environment and install packages

Run these commands inside the project folder.

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install piper-tts onnxruntime langdetect
```

### Windows

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install piper-tts onnxruntime langdetect
```

Recommended (needed for default tray/menu app on Linux/macOS):

```bash
python -m pip install pystray pillow
```

## 3) Run it

### Linux

```bash
./scripts/run-linux.sh
```

The tray app starts automatically by default.

### macOS

```bash
./scripts/run-macos.sh
```

### Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-windows.ps1
```

Quick test:

```bash
./scripts/run-linux.sh --test
```

```bash
./scripts/run-macos.sh --test
```

```powershell
.\scripts\run-windows.cmd --test
```

## 4) Set keyboard shortcut

### Linux (GNOME)

1. Open `Settings -> Keyboard -> Keyboard Shortcuts -> Custom Shortcuts`.
2. Add:
   - Name: `Speak Selection`
   - Command: absolute path to `scripts/run-linux.sh`
3. Set key combo (example: `Ctrl+Alt+S`).

### macOS

1. Open `Automator` and create a `Quick Action`.
2. Set:
   - `Workflow receives`: `no input`
   - `in`: `any application`
3. Add `Run Shell Script` with:

```bash
"/absolute/path/to/speak-selection/scripts/run-macos.sh"
```

4. Save as `Speak Selection`.
5. Assign shortcut in `System Settings -> Keyboard -> Keyboard Shortcuts -> Services`.

Note: macOS may ask for Accessibility/Automation permission the first time.

### Windows

1. Create a shortcut to `scripts\run-windows.cmd`.
2. Open shortcut `Properties`.
3. Set `Shortcut key` (example: `Ctrl+Alt+S`).
4. Keep the shortcut in Desktop or Start Menu.

## New features

### 1) Tray/menu-bar mode

Linux/macOS only.

The tray app starts automatically by default when you run normally.

You can still run tray-only mode manually:

```bash
python speak-selection.py --tray
```

Left-click tray icon (or choose `Open Settings`) to open a small settings window.

Linux note: some tray backends do not support left-click default actions. If left-click does nothing, open the tray menu and choose `Open Settings` (or run `python speak-selection.py --settings-ui`).

Settings window includes:

- Volume slider
- Speed slider
- Voice dropdown with all catalog voices
- Download state in dropdown (`[Downloaded]` / `[Download]`)
- Auto-save (no Apply button)
- Revert-to-defaults button (`speed=1.00`, `volume=100%`)
- Auto-download when you choose a missing voice

You can also open settings directly:

```bash
python speak-selection.py --settings-ui
```

Tray menu actions:

- Open Settings
- Speak Selection
- Pause / Resume
- Stop
- Read Page From URL In Clipboard
- Quit

### 2) Auto language detect + voice routing

This is enabled by default.

How it works:

- The script detects language from text.
- It tries to pick a matching installed voice (for example, `es_*` for Spanish).
- If no matching voice is found, it falls back to default English voice.
- By default only English `en_US-lessac-medium` is auto-downloaded, so install more voices for multilingual output.

You can force a specific voice:

```bash
python speak-selection.py --voice high
```

Or return to auto mode:

```bash
python speak-selection.py --set-runtime-voice auto
```

### 3) Cached synthesis

Caching is enabled by default.

- Repeated text is faster because existing WAV output is reused.
- Cache lives in the state folder (`audio-cache` subfolder).

Tune cache size:

- `SPEAK_SELECTION_CACHE_MAX_FILES` (default: `800`)

### 4) Read full page/article mode

Read URL currently in clipboard/selection:

```bash
python speak-selection.py --read-page
```

Read a specific URL:

```bash
python speak-selection.py --read-page "https://example.com/article"
```

## Voice and speed settings

You can set these as environment variables in your launcher script.

- `SPEAK_SELECTION_VOICE`: `auto`, `medium`, `high`, or full voice path
- `SPEAK_SELECTION_VOICE_DIR`: custom voice folder
- `SPEAK_SELECTION_PLAYBACK_SPEED`: mpv speed (range `0.25` to `4.0`, default `1.85`)
- `SPEAK_SELECTION_VOLUME`: mpv volume percent (range `0` to `200`, default `100`)
- `SPEAK_SELECTION_WAV_POST_BOOST`: safe post-boost on generated WAV (default `1`/enabled)
- `SPEAK_SELECTION_WAV_POST_GAIN`: target post-gain multiplier (default `1.6`)
- `SPEAK_SELECTION_WAV_POST_PEAK`: max peak ceiling to prevent clipping (default `0.95`)
- `SPEAK_SELECTION_WAV_COMPRESS`: apply gentle compression before makeup gain (default `1`)
- `SPEAK_SELECTION_WAV_COMPRESS_THRESHOLD`: compressor threshold (default `0.60`)
- `SPEAK_SELECTION_WAV_COMPRESS_RATIO`: compressor ratio (default `3.0`)
- `SPEAK_SELECTION_RESET_STREAM_VOLUME`: on Linux, reset mpv stream volume via `pactl` (default `1`)
- `SPEAK_SELECTION_STREAM_VOLUME`: target Linux stream volume percent (default `100`)
- `SPEAK_SELECTION_SELECTION_TIMEOUT`: timeout for selection read commands (default `0.8`)
- `SPEAK_SELECTION_SELECTION_RETRIES`: retries for selection capture timing races (default `6`)
- `SPEAK_SELECTION_SELECTION_RETRY_DELAY`: delay between retries (default `0.04`)
- `SPEAK_SELECTION_ALLOW_CLIPBOARD_FALLBACK`: Linux fallback to clipboard when primary selection is empty (default `0`)
- `SPEAK_SELECTION_EMPTY_TOGGLES`: if `1`, empty selection toggles pause/resume (default `0`)
- `SPEAK_SELECTION_LENGTH_SCALE`: speaking pace (default `0.95`)
- `SPEAK_SELECTION_NOISE_SCALE`: variation (default `0.667`)
- `SPEAK_SELECTION_NOISE_W`: phoneme width variation (default `0.8`)
- `SPEAK_SELECTION_LOW_MEMORY_ORT`: set `1` for lower memory use
- `SPEAK_SELECTION_AUTO_LANGUAGE`: set `0` to disable language routing
- `SPEAK_SELECTION_CACHE_ENABLED`: set `0` to disable cache
- `SPEAK_SELECTION_CACHE_MAX_FILES`: max cached wav files
- `SPEAK_SELECTION_ARTICLE_MAX_CHARS`: max chars for `--read-page`
- `SPEAK_SELECTION_AUTO_TRAY`: set `0` to disable auto tray startup (Linux/macOS)

If voice sounds too quiet or slurred, try:

- `SPEAK_SELECTION_VOLUME=100` (leave mpv gain neutral)
- `SPEAK_SELECTION_WAV_POST_GAIN=1.8`
- `SPEAK_SELECTION_WAV_POST_PEAK=0.95`
- `SPEAK_SELECTION_WAV_COMPRESS_THRESHOLD=0.55`
- `SPEAK_SELECTION_WAV_COMPRESS_RATIO=3.5`
- `SPEAK_SELECTION_PLAYBACK_SPEED=1.85`
- `SPEAK_SELECTION_LENGTH_SCALE=0.95`

If you are testing new settings while daemon mode is running, run `python speak-selection.py --stop` once, then trigger speech again.

## Useful commands

```bash
python speak-selection.py --list-voices
python speak-selection.py --pause
python speak-selection.py --stop
python speak-selection.py --set-runtime-voice medium
python speak-selection.py --text "Hello from speak-selection"
python speak-selection.py --diagnose-audio
```

## Behavior notes by OS

- Linux: full daemon mode (toggle/pause/replace behavior)
- macOS: launcher copies selected text, then speaks
- Windows: launcher copies selected text, then speaks (one-shot mode)
