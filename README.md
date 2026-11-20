# Sound Manager by The Bakery

<img src="branding/bakery_logo.svg" alt="Sound Manager logo: a strawberry cake whose candles rise and fall like a sound wave" width="96" align="right">

Edit sounds on your PC and manage the ringtones, notification sounds, and alarm sounds on a
USB-connected Android phone, from both the desktop and the phone.

> **Status:** early development. The desktop app can download audio from YouTube, extract
> audio from videos, keep a local sound library, manage the phone's sound folders, set the
> default ringtone, notification, and alarm sounds, set per-contact ringtones, trim/fade
> sounds in a waveform editor, and show every app's notification categories. The Android phone
> app lists, adds, edits, and deletes sounds and sets defaults and contact ringtones.

## Features

| | Feature | Where |
|---|---|---|
| ✅ | Detect the phone over USB (ADB) | Desktop |
| ✅ | Browse, upload, download, and delete files in `Ringtones/`, `Notifications/`, `Alarms/` | Desktop |
| ✅ | Extract audio from video files, keeping the original quality when possible | Desktop |
| ✅ | Download audio from YouTube and other video sites (progress, cancel, size/length limits) | Desktop |
| ✅ | Local sound library: preview, import by drag-and-drop, send to the phone | Desktop |
| ✅ | Waveform editor: trim, fade, volume, loudness normalize, preview, undo/redo | Desktop |
| ✅ | Set the default ringtone, notification, and alarm sounds (per SIM, with Undo) | Desktop |
| ✅ | Per-contact ringtones (search, batch apply, Undo) | Desktop |
| ✅ | Per-contact message sounds (guided: desktop opens the right screen on the phone) | Desktop + phone |
| ✅ | App sounds: every app's notification categories, the sound each plays, one click to open it on the phone | Desktop + phone |
| ✅ | Phone app: browse, preview, and set default sounds; per-contact ringtones | Phone app |
| ✅ | Phone app: add any audio or video file, edit a copy (trim, fade, volume, normalize), delete to trash | Phone app |

✅ done · 🧩 backend only · ⏳ planned

### A note on per-app notification sounds

Since Android 8, every app owns its notification categories ("channels"), such as a messaging
app's *Messages* vs. *Group messages*. Android does not let one app change another app's
category sounds. This project copies your sound into the phone's `Notifications/` folder (so it
appears in every sound picker) and then opens that exact category's settings page so you can
select it with one tap.

## Safety

- **Disconnects:** uploads go to a hidden temp file and are renamed into place only after the
  size checks out, so pulling the cable never leaves a broken or half-replaced sound. Downloads
  land as `.part` files first. Multi-setting changes (default sounds) are written in one command
  and journaled on the PC; if a disconnect interrupts one, it is rolled back when the phone
  reconnects. Contact ringtone changes are single atomic writes.
- **Scope:** the app only writes to the phone's three sound folders, the sound settings, and
  contacts' ringtone field. Everything sent to the phone is validated and shell-quoted.
- **Downloads and imports:** only http(s) links, one video per link, size and length limits,
  partial downloads kept in a temp folder, ffmpeg inputs forced to local files, and phone file
  names sanitized before they are saved on Windows. Imports never overwrite library files.
- **Privacy:** contact names stay in memory for display; phone numbers are never read. A
  pre-commit hook blocks emails, tokens, and anything in your local `.private-patterns` file.

## TODO

Roughly in build order. Check items off as they land.

### Milestone 1: Desktop basics
- [x] Detect the phone over ADB and show its state (ready / unauthorized)
- [x] Browse, upload, download, and delete files in `Ringtones/`, `Notifications/`, `Alarms/`
- [x] Desktop and Start Menu shortcuts with an app icon
- [x] Set a phone sound as the default ringtone, notification, or alarm from the desktop
      (per SIM on dual-SIM phones, with Undo)
- [x] Show which sound is currently the default in each tab
- [x] Changing a default takes a menu pick plus a confirmation (no accidental one-click changes)
- [x] Drag and drop files from Explorer onto a tab to upload them (asks before replacing)
- [x] Run ADB calls in a background thread so the UI never freezes
- [x] Auto-detect the phone being plugged in, unplugged, or authorized
- [x] Show the phone's own name (Settings > About phone) instead of its model code

### Milestone 2: Contacts
- [x] Contacts tab: search contacts and show each one's custom ringtone
      (ADB already has contacts access, so no companion app needed)
- [x] Set or clear a contact's ringtone (`custom_ringtone`), for one or many contacts, with
      confirmation and Undo
- [x] Per-contact message sound: pick a sound from `Notifications/`, then the desktop opens
      Settings > Conversations on the phone and says exactly what to tap (Android masks
      conversation IDs from ADB, so the final pick happens on the phone)
- [ ] Companion app: jump straight to one conversation's sound setting (needs the conversation ID,
      which only an on-phone notification listener can see)
- [x] Never read phone numbers; never write contact names to logs, files, or the repo

### Milestone 3: Import
- [x] Import tab: paste a YouTube URL and download the audio, with a progress bar and Cancel
      (http(s) only, one video per link, max 1 hour / 200 MB)
- [x] Import from a local video or audio file (extract audio; copy without re-encoding when possible)
- [x] Local library folder (`%USERPROFILE%\Music\Android Sound Manager`) shown as its own tab,
      with preview playback, drag-and-drop import, Recycle Bin delete, and "Send to phone"
- [x] Keep yt-dlp up to date ("Update downloader" button; Dependabot also proposes updates)

### Milestone 4: Editor
- [x] Waveform view with draggable start/end markers (Shift+drag slides the selection)
- [x] Preview playback of the edit, including fades and volume (Space to play/stop)
- [x] Fade in/out, volume, and loudness-normalize controls
- [x] Save as `.m4a` / `.mp3` / `.ogg` into the library (originals are never changed)
- [x] Undo/redo for edits (Ctrl+Z / Ctrl+Y)
- [ ] Zoom in on the waveform for precise edits in long files
- [ ] "Save and set as ringtone / notification / alarm" in one step

### Milestone 5: Android companion app
- [x] Create the Kotlin + Jetpack Compose project in `android/`
- [x] Build, lint, and install it on the phone (also built and linted in CI)
- [x] Sound library screen with a two-pane layout for the Fold's inner screen
- [x] Set default ringtone / notification / alarm (`WRITE_SETTINGS` special access)
- [x] Per-contact ringtones on the phone itself (`ContactsContract.Contacts.CUSTOM_RINGTONE`)
- [x] Hands-on check of the main screens on the Fold (inner and cover screens)
- [x] Add sounds from any audio or video file on the phone (saved crash-safe: hidden until complete)
- [x] On-phone editor: waveform, trim, fade in/out, volume or normalize, preview; saves a copy
  using the phone's own decoders and AAC encoder (device tests run the real codecs)
- [x] Delete a sound to the phone's trash (recoverable for 30 days)
- [ ] App sounds on the phone itself (Android only shows other apps' categories to the desktop)
- [ ] Local socket server so the desktop can drive it via `adb forward`

### Milestone 6: Desktop + phone together
- [x] Desktop App sounds tab: every app's notification categories with their current sound;
  opens the exact category's settings on the phone (Android doesn't let other apps change it)
- [ ] Install or update the companion APK from the desktop (`adb install`)
- [ ] Wireless ADB pairing as an alternative to USB

### Later / maybe
- [ ] Investigate `NotificationListenerService.updateNotificationChannel` (companion-device
      loophole) for setting other apps' notification sounds directly
- [ ] Standalone `.exe` build with PyInstaller for sharing
- [ ] Back up and restore all custom sounds and assignments
- [x] CI: lint, tests, and secret scanning (gitleaks) on GitHub Actions; Dependabot updates

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
  phone_contacts.py  Read and set per-contact ringtones
  journal.py      Write-ahead journal that repairs changes interrupted by a disconnect
  audio.py        ffmpeg-based extraction and editing
  library.py      Local sound library (import, list)
  youtube.py      yt-dlp audio downloads with safety limits
  tools.py        Locates adb / ffmpeg / ffprobe / node
  ui/             PySide6 (Qt) desktop interface (tabs, editor, waveform, task runner)
  assets/         App icon (generated by scripts/make_icon.py)
android/          Companion Android app (Kotlin + Jetpack Compose)
branding/         Logo artwork (SVG master for all icons)
scripts/          Setup, shortcut installer, icon generator
tests/            pytest suite
```

## Legal

Only download or use audio you have the rights to. Downloading from YouTube may be against
YouTube's Terms of Service unless the content's owner allows it.

## License

Copyright © 2026 Chase Choi. **All rights reserved.** The source is publicly visible for viewing
only. No permission is granted to use, copy, modify, or distribute it. See [LICENSE](LICENSE).
