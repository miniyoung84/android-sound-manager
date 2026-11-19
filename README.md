# Android Sound Manager

Edit sounds on your PC and manage the ringtones, notification sounds, and alarm sounds on a
USB-connected Android phone, from both the desktop and the phone.

> **Status:** early development. The desktop app can detect a phone, manage the files in its
> sound folders, and set the default ringtone, notification, and alarm sounds. Everything else
> below is planned.

## Features

| | Feature | Where |
|---|---|---|
| ✅ | Detect the phone over USB (ADB) | Desktop |
| ✅ | Browse, upload, download, and delete files in `Ringtones/`, `Notifications/`, `Alarms/` | Desktop |
| 🧩 | Extract audio from video files (ffmpeg; core code ready, no UI yet) | Desktop |
| 🧩 | Download audio from YouTube (yt-dlp; core code ready, no UI yet) | Desktop |
| 🧩 | Trim, fade, change gain, and normalize loudness (core code ready, no UI yet) | Desktop |
| ⏳ | Waveform editor with preview playback | Desktop |
| ✅ | Set the default ringtone, notification, and alarm sounds (per SIM, with Undo) | Desktop |
| ⏳ | Per-contact ringtones | Phone app |
| ⏳ | One-tap jump to any app's notification category to pick its sound | Phone app |
| ⏳ | Companion Android app with sound library and basic editing | Phone app |

✅ done · 🧩 backend only · ⏳ planned

### A note on per-app notification sounds

Since Android 8, every app owns its notification categories ("channels"), such as a messaging
app's *Messages* vs. *Group messages*. Android does not let one app change another app's
category sounds. This project copies your sound into the phone's `Notifications/` folder (so it
appears in every sound picker) and then opens that exact category's settings page so you can
select it with one tap.

## TODO

Roughly in build order. Check items off as they land.

### Milestone 1: Desktop basics
- [x] Detect the phone over ADB and show its state (ready / unauthorized)
- [x] Browse, upload, download, and delete files in `Ringtones/`, `Notifications/`, `Alarms/`
- [x] Desktop and Start Menu shortcuts with an app icon
- [x] Set a phone sound as the default ringtone, notification, or alarm from the desktop
      (per SIM on dual-SIM phones, with Undo)
- [x] Show which sound is currently the default in each tab
- [ ] Drag and drop files from Explorer onto a tab to upload them
- [ ] Run ADB calls in a background thread so the UI never freezes
- [ ] Auto-detect the phone being plugged in or unplugged (poll `adb devices` or use `adb track-devices`)
- [ ] Friendly device name (e.g. "Galaxy Z Fold7" instead of "SM F966U1")

### Milestone 2: Import
- [ ] Import tab: paste a YouTube URL and download the audio, with a progress bar
- [ ] Import from a local video file (extract audio)
- [ ] Local library folder (`%USERPROFILE%\Music\Android Sound Manager`) shown as its own tab
- [ ] Keep yt-dlp up to date (in-app "check for updates" via pip)

### Milestone 3: Editor
- [ ] Waveform view with draggable start/end markers
- [ ] Preview playback of the selected region (QtMultimedia)
- [ ] Fade in/out, gain, and loudness-normalize controls
- [ ] Export to `.ogg` / `.mp3` / `.m4a` and "Send to phone as ringtone / notification / alarm"
- [ ] Undo/redo for edits

### Milestone 4: Android companion app
- [ ] Create the Kotlin + Jetpack Compose project in `android/` (requires Android Studio)
- [ ] Sound library screen with a two-pane layout for the Fold's inner screen
- [ ] Set default ringtone / notification / alarm (`WRITE_SETTINGS` special access)
- [ ] Per-contact ringtones (`ContactsContract.Contacts.CUSTOM_RINGTONE`)
- [ ] List installed apps' notification categories and deep-link to each one's sound setting
- [ ] Basic on-phone trimming (Media3 Transformer)
- [ ] Local socket server so the desktop can drive it via `adb forward`

### Milestone 5: Desktop + phone together
- [ ] Desktop: assign a sound to a contact (through the companion app)
- [ ] Desktop: assign a sound to an app's notification category (copy file, then open that settings page on the phone)
- [ ] Install or update the companion APK from the desktop (`adb install`)
- [ ] Wireless ADB pairing as an alternative to USB

### Later / maybe
- [ ] Investigate `NotificationListenerService.updateNotificationChannel` (companion-device
      loophole) for setting other apps' notification sounds directly
- [ ] Standalone `.exe` build with PyInstaller for sharing
- [ ] Back up and restore all custom sounds and assignments
- [ ] CI: lint, tests, and secret scanning on GitHub Actions

## Requirements

- Windows 10/11
- Python 3.13
- [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) (`adb`)
- [FFmpeg](https://ffmpeg.org/) (`ffmpeg` and `ffprobe`)
- [Node.js](https://nodejs.org/) 22+, which yt-dlp needs as its JavaScript runtime for YouTube

Most of these can be installed with winget:

```powershell
winget install -e --source winget --id Python.Python.3.13
winget install -e --source winget --id Gyan.FFmpeg
winget install -e --source winget --id OpenJS.NodeJS.LTS
```

If winget's `Google.PlatformTools` package fails its hash check (it often does, because Google
updates the file in place), download Platform-Tools from the link above and unzip it to
`%LOCALAPPDATA%\Android\Sdk\platform-tools`.

## Phone setup (one time)

1. **Settings → About phone → Software information** → tap **Build number** 7 times.
2. **Settings → Developer options** → turn on **USB debugging**.
3. **Samsung only:** **Settings → Security and privacy → Auto Blocker** → turn it off, or turn
   off its **Block commands by USB cable** option. Otherwise ADB is silently blocked.
4. Connect the USB cable, unlock the phone, and tap **Allow** on the *Allow USB debugging?*
   prompt (tick *Always allow from this computer*).

## Getting started

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # creates .venv, installs deps
.venv\Scripts\python -m soundmanager                          # launch the desktop app
.venv\Scripts\python -m pytest                                # run tests
.venv\Scripts\ruff check .                                    # lint
```

### Desktop and Start Menu shortcuts

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts.ps1           # create
powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts.ps1 -Remove   # remove
```

The shortcuts open the app without a console window, straight from this repo's `.venv`, so code
changes apply the next time you open it. To pin it, open it from the Start Menu and choose
**Pin to taskbar** from its taskbar icon. Errors are logged to
`%LOCALAPPDATA%\AndroidSoundManager\app.log`.

Any external tool can be pointed at a specific executable with an environment variable, for
example `SOUNDMANAGER_ADB`, `SOUNDMANAGER_FFMPEG`, `SOUNDMANAGER_FFPROBE`, or `SOUNDMANAGER_NODE`.

## Project layout

```
src/soundmanager/
  adb.py          Device discovery and file transfer over ADB
  phone_sounds.py Read and set default ringtone / notification / alarm sounds
  audio.py        ffmpeg-based extraction and editing
  youtube.py      yt-dlp audio downloads
  tools.py        Locates adb / ffmpeg / ffprobe / node
  ui/             PySide6 (Qt) desktop interface
  assets/         App icon (generated by scripts/make_icon.py)
android/          Companion Android app (planned)
scripts/          Setup, shortcut installer, icon generator
tests/            pytest suite
```

## Legal

Only download or use audio you have the rights to. Downloading from YouTube may be against
YouTube's Terms of Service unless the content's owner allows it.

## License

Copyright © 2026 Chase Choi. **All rights reserved.** The source is publicly visible for viewing
only. No permission is granted to use, copy, modify, or distribute it. See [LICENSE](LICENSE).
