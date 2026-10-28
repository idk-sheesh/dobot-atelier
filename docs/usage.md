# Setup and use

## Requirements

- Windows, Python 3.12 with Tkinter, or a Windows build from Releases.
- The original Kickstarter Dobot V1 and its matching DobotTools V1.0 bridge.
- The correct USB serial driver and the robot's specified power supply.

Do not use a Magician driver, protocol or firmware merely because the product
name is similar. Do not flash firmware as part of this setup.

## Server selection

Use `python main.py --offline` to inspect SVG files without launching the server
or connecting to a robot. For a packaged build, pass `--offline` to the executable.

The application looks for `DobotServer.exe` beside the application, then in the
legacy local installation directory. A path set in **Diagnostic COM** is saved
with the application settings. `DOBOT_SERVER_EXE` sets the default path when
there is no saved choice.

```powershell
$env:DOBOT_SERVER_EXE = 'C:\DobotTools\DobotServer.exe'
python main.py
```

The server manages the USB serial connection. COM7 was used on the development
machine; it is not a required or hard-coded port. Close DobotClient before using
Dobot Atelier. Only one client should control the bridge at a time.

## First connection

1. Disconnect the laser and leave motor power off. Fix the base to a rigid
   support and support the arm if it can fall when unpowered.
2. Connect USB and check that Windows detects the serial device. USB detection
   alone does not establish that motor power or angle readings are valid.
3. Start the matching bridge, or select its executable in **Diagnostic COM**.
   Check for incoming telemetry, not just a connected TCP socket.
4. Before applying motor power or pressing RESET, verify the mechanical setup
   and follow the initialization procedure for this exact robot revision.
   Keep hands and loose objects outside the arm's reach.

On the development unit, J2/J3 readings after manual repositioning changed only
after a physical RESET. Cycling motor power while leaving USB connected was
not enough. This observation is not a general calibration procedure.

Do not move the arm by hand while powered, force a joint against a stop, or
command X=0, Y=0 as a homing routine. Reported values within the nominal ranges
do not prove that the sensors are mounted or calibrated correctly.

## SVG preview

**Ouvrir un SVG** loads a drawing. **Afficher le trajet (sans mouvement)** updates
the preview only. Text must be converted to paths in the drawing editor first.
Basic paths, lines, polylines, polygons, rectangles, circles and ellipses are
supported. This is not a complete SVG renderer.

**Deplacement sans outil** is a real motor run with the tool off, not a virtual
simulation. Its small initial-distance and joint-margin checks do not detect
every collision. Pen and laser runs remain unqualified.

The diagnostic 1 mm step sends at most one target after confirmation. It uses
a nominal 135/160 mm arm model and an inferred 55 mm tool offset. These are
controller-consistency checks, not physical calibration. A recorded attempt
locks further attempts across restarts; the UI does not offer a bypass.

## Workbench measurements

The mapping window separates measurements made with a ruler from J2/J3 telemetry
samples. Keep the base, measurement point and workbench height unchanged during
a series. Extrema are observations, not a safe rectangular workspace. Recording
points never expands motion limits or authorizes a trajectory.

## Stop and tool precautions

The stop button clears the local queue and sends repeated stop and tool-off
frames. It is a software stop, not a safety-rated emergency stop. A lost USB or
TCP link can prevent those frames from reaching the robot. Keep a physical
means of removing motor and tool power accessible; stopping distance is not
qualified on this rebuilt unit.

Do not operate the laser without a suitable closed enclosure, interlocks,
extraction and protection matched to its wavelength. Never laser-process PVC,
vinyl or an unidentified material. A vinyl-cutting attachment would use a blade,
not the laser. Do not leave an active tool unattended.

## Local files

- Settings: `%APPDATA%\DobotAtelier\atelier_config.json` in a packaged build,
  or `atelier_config.json` beside the source.
- Workbench observations and diagnostic reports: beside the executable or source.

Keep that directory writable. These files contain machine-specific data and are
ignored by Git. Do not share them as a calibrated profile for another arm.
