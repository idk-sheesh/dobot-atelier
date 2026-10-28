# Dobot Atelier

A Windows application I built to reuse an original Kickstarter-era Dobot arm.
It imports SVG drawings, prepares paths and talks to the robot through the old
DobotTools V1.0 TCP bridge. The interface is in French.

## What it does

- Imports SVG paths and basic shapes, with scale, rotation and placement controls.
- Shows drawing paths and travel moves before sending commands.
- Displays connection status, reported coordinates and joint angles.
- Records workbench measurements separately from the robot's reported positions.
- Checks telemetry freshness, numeric values and nominal joint ranges before motion.
- Clears pending commands after a stop or connection loss.

The pen and laser command paths are implemented, but those workflows have not
been validated. This is not a replacement for the robot's hardware protections.

## My work

The project started with getting an older arm working on a current Windows PC.
I worked on the TCP frame handling, SVG conversion, the Tkinter interface and
the connection and motion checks. Rebuilding the arm also meant checking sensor
mounting and revisiting assumptions about its coordinates.

A change in reported coordinates does not prove that the arm moved. An earlier
diagnostic treated it that way; the application now distinguishes controller
feedback from physical verification.

## Stack

Python 3.12, Tkinter, TCP sockets, SVG/XML and unittest. No third-party Python
packages are required to run the source. PyInstaller is used for Windows builds.

## Run

The application targets the **original Dobot V1**, not the Magician or newer arms.
It needs the matching `DobotServer.exe` from DobotTools V1.0, which is not included.

```powershell
git clone https://github.com/idk-sheesh/dobot-atelier.git
cd dobot-atelier
python main.py --offline
```

This opens the preview without starting the bridge or connecting to the robot.
To enable the connection, run without `--offline` after following the setup guide.
Choose the server executable in **Diagnostic COM**, or set `DOBOT_SERVER_EXE`.
The bridge listens locally on `127.0.0.1:5555`; the app does not select the COM port
itself. See [setup and use](docs/usage.md) before connecting hardware.

The on-screen preview sends no motion commands. **Deplacement sans outil**
(previously called Simulation) moves the real arm with the tool off; it is not
a virtual simulator.

## Tests and builds

```powershell
python -m unittest discover -s tests -v
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm "Dobot Atelier.spec"
```

The tests use fake sockets and mocked UI objects, not a connected robot.
CI runs them on Windows and Linux. The GUI and packaged executable target Windows.

## Status

Current source version: **1.6.2**, experimental.

[Download the Windows prerelease](https://github.com/idk-sheesh/dobot-atelier/releases/tag/v1.6.2).

The arm has moved during earlier bench tests. The latest recorded hardware test
produced no visible movement or motor noise despite changing telemetry. That
fault remains unresolved. Sensor calibration, the usable workspace, physical
stopping behaviour and drawing or engraving accuracy still need validation.

Tagged builds are published as prereleases. A successful build or test run is
not a hardware qualification. The remaining checks are listed in
[hardware validation](docs/hardware-validation.md).

The original bridge sources are available from [DobotTeam](https://github.com/DobotTeam/Dobot_for_Developers).
This is an independent project, not an official Dobot application.
