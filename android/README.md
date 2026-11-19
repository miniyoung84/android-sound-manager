# Android companion app (planned)

Kotlin + Jetpack Compose app that runs on the phone. It will:

- Show the sound library (MediaStore entries flagged as ringtone, notification, or alarm).
- Set the default ringtone, notification, and alarm sounds (`WRITE_SETTINGS` special access).
- Assign per-contact ringtones (`ContactsContract.Contacts.CUSTOM_RINGTONE`).
- Deep-link to a specific app's notification category so a sound can be picked in one tap
  (`Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS`). Android does not allow one app to change
  another app's notification category sounds directly.
- Do basic trimming on the phone (Media3 Transformer).
- Expose a small local socket that the desktop app reaches through `adb forward`.

Target: Galaxy Z Fold7 (One UI 9 / Android 17, SDK 37) first, with a two-pane layout for the
inner screen. Minimum SDK 26 (Android 8).

Building it will require Android Studio (`winget install -e --id Google.AndroidStudio`).
