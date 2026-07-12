# PropSpector Update Model

## Current Model

Current release line:

```text
0.1.22
```

Desktop shortcuts point to:

```text
L:\CDA software\Feasibility App\PropSpector.exe
```

That file is now a launcher. It reads:

```text
L:\CDA software\Feasibility App\PropSpector.update.json
```

and opens the latest versioned build listed in the manifest.

## Shared Folder Layout

```text
L:\CDA software\Feasibility App
  PropSpector.exe                 # launcher, stable shortcut target
  PropSpector.update.json         # latest approved version pointer
  PropSpector.ico                 # shortcut/taskbar icon
  versions\
    PropSpector-YYYY.MM.DD.N.exe  # immutable app builds
  archive\
    PropSpector-replaced-*.exe    # prior shared launcher/app backups
```

## Why This Exists

The first installer creates a desktop shortcut. Coworkers may already have that shortcut, so the shortcut target should not change. The launcher lets those existing shortcuts keep working while the actual app moves to versioned builds behind the scenes.

## Update Procedure

From the project folder, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\deploy_propspector_update.ps1
```

By default, the script uses `parcel_packet\__init__.py` as the release version source.

Optionally override the version:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\deploy_propspector_update.ps1 -Version 2026.06.29.1
```

The deployment script:

1. builds the current PropSpector app;
2. copies it to the shared `versions` folder;
3. archives the previous shared executable;
4. builds the launcher;
5. replaces the stable shared `PropSpector.exe` with the launcher;
6. writes `PropSpector.update.json`.

## Rollback

To roll back, edit `PropSpector.update.json` so `latest_exe` points to a prior executable in `versions`.

Example:

```json
{
  "latest_exe": "versions\\PropSpector-2026.06.29.1.exe"
}
```

Do not point `latest_exe` to `PropSpector.exe`; that would point the launcher back to itself.

## Versioning Rules

PropSpector is pre-1.0 while the regulatory interpretation model is still being taught and tested.

Use semantic-style versions:

- `0.1.x`: current combined environmental and New Castle County feasibility workflow.
- `0.2.x`: stronger NCC interpretation, more calibration parcels, better limited-use and parking/access checks.
- `0.3.x`: first complete additional municipality profile.
- `0.4.x`: reusable municipality-profile architecture for multiple Delaware jurisdictions.
- `0.5.x`: cross-state regulatory interpretation model begins.
- `1.0.0`: trusted production release with documented jurisdiction profiles, source traceability, calibration testing, and repeatable update flow.

Patch versions should be small fixes. Minor versions should represent a meaningful expansion in regulatory interpretation capability.
