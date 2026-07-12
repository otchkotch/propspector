# PropSpector

PropSpector is CDA's parcel research workspace. It combines environmental resource screening, live parcel preview mapping, PDF map package creation, and zoning feasibility yield screening in one full-screen desktop app.

## Current Deployment

The shared Windows deployment lives here:

```text
L:\CDA software\Feasibility App\PropSpector.exe
```

The desktop shortcut should point to that executable.

## Release Package

The clean shareable Windows package is:

```text
release\PropSpector Windows.zip
```

That zip contains `PropSpector.exe` and a short readme.

## Build

From this project folder:

```powershell
.\build_propspector.ps1
```

The build output is:

```text
dist\PropSpector.exe
```

## Source Entry Point

```text
propspector_main.py
```

## Notes

- PropSpector uses the New Castle County GIS REST services and needs internet or office network access.
- The Windows app enables high-DPI awareness before opening the UI so app windows, browse dialogs, and error dialogs render at full display resolution.
- The app sets a Windows taskbar identity and bundled icon so the taskbar and app window show the PropSpector icon instead of a generic Python/Tk icon.
