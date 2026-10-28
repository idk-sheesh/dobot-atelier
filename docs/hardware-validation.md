# Hardware validation

Software tests do not establish that the rebuilt robot is safe or accurate.
The latest recorded hardware attempt, on 14 October 2026, returned the requested
coordinates but produced no movement or motor noise observed by the operator.
The motor fault is still open. No new hardware test was performed for 1.6.2.

Before calling a build hardware-validated, record the robot revision, controller,
firmware, tool, sensor mounting, supply, date and operator observations. Do not
commit private logs or assume another unit has the same calibration.

## Checks still required

- [ ] Resolve the no-motion fault and verify the physical result independently
      of reported coordinates.
- [ ] Verify sensor mounting, orientation and initialization against the actual
      arm pose. Check repeatability after power cycles and RESET.
- [ ] Establish reachable points and clear connecting paths at the chosen tool
      height. Do not derive a safe volume from independent X/Y/Z extrema.
- [ ] Verify a single bounded movement with the tool disconnected, physical
      measurement and an accessible hardware power cut.
- [ ] Measure stopping response under controlled conditions. Do not run into
      a mechanical stop to test software limits.
- [ ] Verify loss of USB, server shutdown and reconnection without command
      replay. A software stop cannot be assumed to work after link loss.
- [ ] Validate pen pressure or laser tool offset and focus only after motion
      and stopping behaviour are established.
- [ ] Validate the enclosure, interlocks, extraction and independent tool power
      control before any laser operation.

Until these checks are recorded, releases remain experimental. The automated
suite covers protocol handling, geometry, mapping and UI logic with fake hardware.
