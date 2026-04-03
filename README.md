# speak-selection

Read selected text aloud with Piper + mpv using a single keyboard shortcut.

## What is included

- `speak-selection.py`: main script
- `scripts/run-linux.sh`: Linux launcher (selection + daemon mode)
- `scripts/run-macos.sh`: macOS launcher (copies current selection, then speaks)
- `scripts/run-windows.ps1`: Windows launcher (copies current selection, then speaks)
- `scripts/run-windows.cmd`: Windows wrapper for easy keyboard shortcut setup

## 1) Install dependencies

### Linux (Debian/Ubuntu example)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mpv wl-clipboard xsel xclip
```

### macOS (Homebrew)

```bash
brew install python mpv
```

### Windows (PowerShell)

```powershell
winget install Python.Python.3.12
winget install mpv.mpv
```

## 2) Set up Python environment

Run this in the project folder:

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install piper-tts onnxruntime
```

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install piper-tts onnxruntime
```

## 3) Download a Piper voice

Download one voice `.onnx` file and its matching `.onnx.json` config file (same base filename).

Default voice folders:

- Linux: `~/.local/share/piper/voices`
- macOS: `~/Library/Application Support/piper/voices`
- Windows: `%LOCALAPPDATA%\piper\voices`

Recommended filenames (already supported automatically):

- `en_US-lessac-medium.onnx`
- `en_US-lessac-high.onnx`

## 4) Run it

### Linux

```bash
./scripts/run-linux.sh
```

### macOS

```bash
./scripts/run-macos.sh
```

### Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-windows.ps1
```

Quick test (all OS):

```bash
# Linux/macOS
./scripts/run-linux.sh --test
# or
./scripts/run-macos.sh --test
```

```powershell
# Windows
.\scripts\run-windows.cmd --test
```

## 5) Keyboard shortcut setup

### Linux (GNOME)

1. Open `Settings -> Keyboard -> Keyboard Shortcuts -> Custom Shortcuts`.
2. Add a new shortcut:
   - Name: `Speak Selection`
   - Command: absolute path to `scripts/run-linux.sh`
3. Set a hotkey (example: `Ctrl+Alt+S`).

### macOS

Use Automator so the script can run globally from a shortcut.

1. Open `Automator` and create a new `Quick Action`.
2. Set:
   - `Workflow receives`: `no input`
   - `in`: `any application`
3. Add `Run Shell Script` action.
4. Set shell to `/bin/bash` and script to:

```bash
"/absolute/path/to/speak-selection/scripts/run-macos.sh"
```

5. Save as `Speak Selection`.
6. Open `System Settings -> Keyboard -> Keyboard Shortcuts -> Services` and assign a keybinding.

Note: on first use, macOS may ask for Accessibility/Automation permission so the script can send `Cmd+C` to copy selected text.

### Windows

1. Right-click `scripts\run-windows.cmd` and create a shortcut.
2. Right-click the new shortcut -> `Properties`.
3. In `Shortcut key`, press your desired combo (example: `Ctrl+Alt+S`).
4. Keep that shortcut in Desktop or Start Menu so Windows can trigger it globally.

## Voice and tuning settings

You can control voice and style with environment variables.

- `SPEAK_SELECTION_VOICE`
  - `medium`, `high`, or absolute path to a `.onnx` voice file
- `SPEAK_SELECTION_VOICE_DIR`
  - override default voice directory
- `SPEAK_SELECTION_PLAYBACK_SPEED`
  - mpv speed, default `1.85` (lower = slower)
- `SPEAK_SELECTION_LENGTH_SCALE`
  - Piper pace, default `0.95` (lower = faster voice)
- `SPEAK_SELECTION_NOISE_SCALE`
  - Piper variation, default `0.667`
- `SPEAK_SELECTION_NOISE_W`
  - Piper phoneme-width variation, default `0.8`
- `SPEAK_SELECTION_LOW_MEMORY_ORT`
  - set to `1` to reduce ONNX memory usage

You can also pass options directly:

```bash
python speak-selection.py --voice high
python speak-selection.py --low-memory-ort
python speak-selection.py --text "Hello world"
python speak-selection.py --test
```

### Example: set defaults in launchers

Linux/macOS launcher (`scripts/run-linux.sh` or `scripts/run-macos.sh`):

```bash
export SPEAK_SELECTION_VOICE="high"
export SPEAK_SELECTION_PLAYBACK_SPEED="1.5"
export SPEAK_SELECTION_LENGTH_SCALE="1.0"
```

Windows launcher (`scripts/run-windows.ps1`):

```powershell
$env:SPEAK_SELECTION_VOICE = "high"
$env:SPEAK_SELECTION_PLAYBACK_SPEED = "1.5"
$env:SPEAK_SELECTION_LENGTH_SCALE = "1.0"
```

## Behavior notes by OS

- Linux launcher uses selection/daemon mode from the Python script.
- macOS/Windows launchers capture current selection via copy (`Cmd+C` / `Ctrl+C`) and run one-shot speech.

## Feature ideas

- Add optional tray/menu-bar app with play/pause/stop and quick voice switching.
- Add “auto language detect” and multi-language voice routing.
- Add optional per-app profiles (different speed/voice for browser, IDE, docs).
- Add cached synthesis for repeated phrases to improve response time.
- Add optional “read full page/article” mode for browser content.
