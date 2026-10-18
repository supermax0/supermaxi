# Finora Superadmin Desktop

Windows desktop wrapper for `https://finora.company/superadmin/` using the installed Microsoft Edge WebView2 runtime.

## Build

```powershell
.\venv\Scripts\python.exe -m pip install -r .\desktop\finora_superadmin\requirements-desktop.txt
.\desktop\finora_superadmin\build.ps1
```

## Install for the current Windows user

```powershell
.\desktop\finora_superadmin\install.ps1 -Launch
```

The installer creates Desktop and Start Menu shortcuts and registers the app in Windows Installed apps.
