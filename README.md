# speak-selection

Read selected text from your screen out loud with one keyboard shortcut.

Designed for people who want reading support (for example dyslexia, eye strain, fatigue, ADHD, or just listening instead of reading).

## What It Does

- Highlight text and trigger a shortcut to hear it.
- Works on Linux, macOS, and Windows.
- Tray/menu controls on Linux/macOS (pause, stop, settings).
- Settings window for speed, volume, and voice.
- Auto-downloads a default voice if none is installed (`en_US-lessac-medium`).

## Quick Setup

### 1) Install system dependencies

Linux (Ubuntu/Debian):

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip mpv wl-clipboard xsel xclip
```

macOS:

```bash
brew install python mpv
```

Windows (PowerShell):

```powershell
winget install Python.Python.3.12
winget install mpv.mpv
```

### 2) Install Python packages

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install piper-tts onnxruntime langdetect pystray pillow
```

Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install piper-tts onnxruntime langdetect
```

## Run

Linux:

```bash
./scripts/run-linux.sh
```

macOS:

```bash
./scripts/run-macos.sh
```

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-windows.ps1
```

Quick test:

```bash
./scripts/run-linux.sh --test
./scripts/run-macos.sh --test
```

```powershell
.\scripts\run-windows.cmd --test
```

## Set A Keyboard Shortcut

### Linux (GNOME)

1. Open `Settings -> Keyboard -> Keyboard Shortcuts -> Custom Shortcuts`.
2. Add a shortcut:
   - Name: `Speak Selection`
   - Command: full path to `scripts/run-linux.sh`
3. Set your key combo (example: `Ctrl+Alt+S`).

### macOS

1. Open `Automator` -> create a `Quick Action`.
2. Set:
   - Workflow receives: `no input`
   - In: `any application`
3. Add `Run Shell Script` with:

```bash
"/absolute/path/to/speak-selection/scripts/run-macos.sh"
```

4. Save as `Speak Selection`.
5. Set the shortcut in `System Settings -> Keyboard -> Keyboard Shortcuts -> Services`.

### Windows

1. Create a shortcut to `scripts\run-windows.cmd`.
2. Open shortcut `Properties`.
3. Set `Shortcut key` (example: `Ctrl+Alt+S`).

## Everyday Use

- Select text anywhere.
- Press your shortcut to read it.
- On Linux/macOS, use tray icon -> `Open Settings` to change voice/speed/volume.
- Settings save automatically.
- `Revert Defaults` returns to `speed=1.00`, `volume=100%`.

## Voices

- Voice samples: https://rhasspy.github.io/piper-samples/
- Voice downloads: https://huggingface.co/rhasspy/piper-voices
- The app auto-downloads `en_US-lessac-medium` if no voice is installed.
- Install additional voices for better multi-language support.

## Useful Commands

```bash
python speak-selection.py --settings-ui
python speak-selection.py --pause
python speak-selection.py --stop
python speak-selection.py --read-page "https://example.com/article"
python speak-selection.py --list-voices
```

## Quick Troubleshooting

- Tray click does nothing on Linux: open tray menu and choose `Open Settings`.
- Need a clean restart:

```bash
pkill -f "speak-selection.py --settings-ui" || true
pkill -f "speak-selection.py --tray" || true
./scripts/run-linux.sh
```
