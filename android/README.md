# Android companion app

Kotlin + Jetpack Compose app that manages sounds on the phone itself.

## What it does (first version)

- **Ringtones / Notifications / Alarms tabs:** list the sounds in each folder, preview them, and
  see which one is the current default (★).
- **Set as default:** button, then a confirmation. The first time, Android asks you to allow
  "Modify system settings" (the app explains why first).
- **Contacts tab:** search contacts, pick a ringtone for one (preview while choosing), confirm,
  and undo. A "Message sound" button opens Settings > Conversations.
- **Fold layout:** on the inner screen (600 dp and wider) the list and details sit side by side;
  on the cover screen they are shown one at a time with a back button.

## Privacy and security

- **No internet permission.** The app cannot send anything off the phone.
- Contacts: only names and the ringtone field are read; phone numbers never are.
- Backups and device-to-device transfer of app data are disabled.
- Only the launcher activity is exported; nothing else is reachable by other apps.
- Release signing keys are supplied locally and are gitignored, never committed.

## Building

Requires Android Studio (`winget install -e --id Google.AndroidStudio --source winget`).

1. Open the `android/` folder in Android Studio and let it sync. Accept any offered Gradle /
   plugin updates; the versions in `gradle/libs.versions.toml` were current in late 2026.
2. Plug in the phone (USB debugging on) and press Run.

Target: Galaxy Z Fold7 (One UI 9 / Android 17, SDK 37). Minimum SDK 26 (Android 8).

## Planned

- Notification listener that learns conversation IDs so a contact's message sound opens in
  one tap (Android hides these IDs from ADB).
- Local socket server so the desktop app can drive the phone app over `adb forward`.
- On-phone trimming (Media3 Transformer).
