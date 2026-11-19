# Create (or remove) Desktop and Start Menu shortcuts for Android Sound Manager.
#   powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts.ps1 -Remove
#
# The shortcut runs the app from this repo's .venv with pythonw (no console window), so code
# changes take effect the next time it is opened. Run scripts\setup.ps1 first.

param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$name = 'Android Sound Manager'
$appId = 'ChaseChoi.AndroidSoundManager'   # must match APP_ID in src/soundmanager/__main__.py

$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$name.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$name.lnk")
)

if ($Remove) {
    foreach ($lnk in $targets) {
        if (Test-Path $lnk) { Remove-Item $lnk -Confirm:$false; Write-Host "Removed $lnk" }
    }
    return
}

$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$icon = Join-Path $root 'src\soundmanager\assets\icon.ico'
if (-not (Test-Path $pythonw)) { throw "Missing $pythonw - run scripts\setup.ps1 first." }

# Stamps the AppUserModelID onto a .lnk so the taskbar groups/pins the app under its own icon.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ShortcutAppId {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PROPERTYKEY { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Explicit)]
    struct PROPVARIANT { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PROPERTYKEY key);
        [PreserveSig] int GetValue(ref PROPERTYKEY key, out PROPVARIANT value);
        [PreserveSig] int SetValue(ref PROPERTYKEY key, ref PROPVARIANT value);
        [PreserveSig] int Commit();
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHGetPropertyStoreFromParsingName(
        string path, IntPtr bindCtx, int flags, ref Guid riid, out IPropertyStore store);

    public static void Set(string lnkPath, string appId) {
        Guid iid = typeof(IPropertyStore).GUID;
        IPropertyStore store;
        SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, 2 /* GPS_READWRITE */, ref iid, out store);
        var key = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        var value = new PROPVARIANT { vt = 31 /* VT_LPWSTR */, p = Marshal.StringToCoTaskMemUni(appId) };
        try {
            Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value));
            Marshal.ThrowExceptionForHR(store.Commit());
        } finally {
            Marshal.FreeCoTaskMem(value.p);
            Marshal.ReleaseComObject(store);
        }
    }
}
'@

$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in $targets) {
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $pythonw
    $sc.Arguments = '-m soundmanager'
    $sc.WorkingDirectory = $root
    $sc.Description = 'Edit sounds and manage ringtones on your Android phone'
    if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
    $sc.Save()
    [ShortcutAppId]::Set($lnk, $appId)
    Write-Host "Created $lnk"
}
Write-Host "`nTip: open it from the Start Menu, then right-click its taskbar icon > Pin to taskbar."
