from __future__ import annotations

import queue
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable


FRAME = struct.Struct("<10f")
PACKET_SIZE = 42
MAX_TELEMETRY_AGE = 1.5


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    r: float
    joint1: float
    joint2: float
    joint3: float
    joint4: float
    tool_on: bool
    gripper: float


STARTUP_JOINT_LIMITS = (
    ("J1", "joint1", -135.0, 135.0),
    ("J2", "joint2", -5.0, 85.0),
    ("J3", "joint3", -10.0, 95.0),
    ("J4", "joint4", -90.0, 90.0),
)


def startup_pose_issue(pose: Pose | None, packet_age: float) -> str | None:
    """Return the reason motion must stay locked, or None when startup is safe."""
    if pose is None or packet_age < 0:
        return "Aucune télémétrie reçue du robot."
    if packet_age > MAX_TELEMETRY_AGE:
        return f"Télémétrie trop ancienne ({packet_age:.1f} s)."
    for label, attribute, minimum, maximum in STARTUP_JOINT_LIMITS:
        value = getattr(pose, attribute)
        if not minimum <= value <= maximum:
            return f"{label} = {value:.1f}° hors plage [{minimum:.0f}°, {maximum:.0f}°]."
    return None


class DobotConnection:
    """Small client for the original Dobot V1 TCP bridge."""

    def __init__(
        self,
        on_pose: Callable[[Pose], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.on_pose = on_pose
        self.on_status = on_status
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._commands: queue.Queue[bytes] = queue.Queue()
        self._send_lock = threading.Lock()
        self.connected = False
        self.pose: Pose | None = None
        self.packets_received = 0
        self.commands_sent = 0
        self.last_packet_time = 0.0
        self.last_command_time = 0.0

    @staticmethod
    def _packet(*values: float) -> bytes:
        payload = FRAME.pack(*values)
        return b"\xa5" + payload + b"\x5a"

    def connect(self, host: str = "127.0.0.1", port: int = 5555) -> None:
        if self.connected:
            return
        self._stop_event.clear()
        sock = socket.create_connection((host, port), timeout=3)
        sock.settimeout(1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._socket = sock
        self.connected = True
        self._emit_status("Connecté au Dobot")
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        self._wake_telemetry()

    def _wake_telemetry(self) -> None:
        # Some V1 firmwares stay silent after the serial bridge reconnects.
        # An idle frame is harmless and restarts their telemetry stream.
        self._send(self._packet(7, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    def close(self) -> None:
        self._stop_event.set()
        self.clear_queue()
        sock, self._socket = self._socket, None
        self.connected = False
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._emit_status("Déconnecté")

    def _emit_status(self, status: str) -> None:
        if self.on_status:
            self.on_status(status)

    def _reader(self) -> None:
        buffer = bytearray()
        wake_attempts = 1
        last_wake = time.monotonic()
        try:
            while not self._stop_event.is_set():
                try:
                    chunk = self._socket.recv(4096) if self._socket else b""
                except socket.timeout:
                    if self.pose is None and wake_attempts < 5 and time.monotonic() - last_wake >= 0.8:
                        self._wake_telemetry()
                        wake_attempts += 1
                        last_wake = time.monotonic()
                    continue
                if not chunk:
                    raise ConnectionError("Le serveur Dobot a fermé la connexion")
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xa5")
                    if start < 0:
                        buffer.clear()
                        break
                    if start:
                        del buffer[:start]
                    if len(buffer) < PACKET_SIZE:
                        break
                    if buffer[PACKET_SIZE - 1] != 0x5A:
                        del buffer[0]
                        continue
                    packet = bytes(buffer[:PACKET_SIZE])
                    del buffer[:PACKET_SIZE]
                    self._handle_packet(packet)
        except (OSError, ConnectionError) as exc:
            if not self._stop_event.is_set():
                self._emit_status(f"Connexion perdue : {exc}")
        finally:
            self.connected = False

    def _handle_packet(self, packet: bytes) -> None:
        self.packets_received += 1
        self.last_packet_time = time.monotonic()
        values = FRAME.unpack(packet[1:-1])
        self.pose = Pose(
            x=values[0], y=values[1], z=values[2], r=values[3],
            joint1=values[4], joint2=values[5], joint3=values[6],
            joint4=values[7], tool_on=values[8] != 0, gripper=values[9],
        )
        if self.on_pose:
            self.on_pose(self.pose)
        try:
            command = self._commands.get_nowait()
        except queue.Empty:
            return
        self._send(command)

    def _send(self, packet: bytes) -> None:
        if not self.connected or self._socket is None:
            raise ConnectionError("Dobot non connecté")
        with self._send_lock:
            self._socket.sendall(packet)
            self.commands_sent += max(1, len(packet) // PACKET_SIZE)
            self.last_command_time = time.monotonic()

    def queue_size(self) -> int:
        return self._commands.qsize()

    def clear_queue(self) -> None:
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return

    def enqueue(self, packet: bytes) -> None:
        if not self.connected:
            raise ConnectionError("Dobot non connecté")
        self._commands.put(packet)

    def dispatch_next(self) -> bool:
        """Send the first queued command without waiting for idle telemetry."""
        try:
            command = self._commands.get_nowait()
        except queue.Empty:
            return False
        self._send(command)
        return True

    def set_end_type(self, end_type: int) -> None:
        # state=Parameter, axis=4, x: 0 pump, 1 gripper, 2 laser
        self.enqueue(self._packet(9, 4, end_type, 0, 0, 0, 0, 0, 0, 0))

    def set_playback_speed(self, velocity: float, acceleration: float) -> None:
        # state=JogParameter is also used by the legacy client for playback ratios.
        self.enqueue(self._packet(10, 0, velocity, acceleration, 0, 0, 0, 0, 0, 0))

    def queue_playback_configuration(
        self,
        velocity: float,
        acceleration: float,
        end_type: int,
        laser_mode: bool,
    ) -> None:
        # The original controller can power up with zero playback limits. The
        # legacy client sends these limits before the percentage ratios.
        packets = (
            self._packet(9, 1, 200, 200, 200, 200, 200, 200, 0.1, 20),
            self._packet(10, 0, velocity, acceleration, 0, 0, 0, 0, 0, 0),
            self._packet(9, 4, end_type, 0, 0, 0, 0, 0, 0, 0),
            self._packet(7, 14 if laser_mode else 10, 0, 0, 0, 0, 0, 0, 0, 0),
        )
        for packet in packets:
            self.enqueue(packet)

    def jog_joint(self, axis: int, speed: float = 8) -> None:
        """Send the same joint-jog frame as the official V1 client."""
        if axis not in range(1, 9):
            raise ValueError("Axe de jog invalide")
        self._send(self._packet(2, axis, 0, 0, 0, 0, 0, speed, 0, 0))

    def configure_jog(self) -> None:
        """Restore the official V1 jog limits after a controller reset."""
        self._send(self._packet(9, 0, 15, 50, 30, 10, 40, 40, 0, 0))

    def stop_jog(self) -> None:
        self._send(self._packet(2, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    def probe(self) -> int:
        before = self.packets_received
        self._wake_telemetry()
        return before

    def diagnostic_snapshot(self) -> dict[str, float | int | bool]:
        now = time.monotonic()
        return {
            "connected": self.connected,
            "packets": self.packets_received,
            "commands": self.commands_sent,
            "queue": self.queue_size(),
            "packet_age": now - self.last_packet_time if self.last_packet_time else -1,
            "command_age": now - self.last_command_time if self.last_command_time else -1,
            "reply_after_command": self.last_packet_time >= self.last_command_time > 0,
        }

    def goto(
        self,
        x: float,
        y: float,
        z: float,
        r: float = 0,
        tool_on: bool = False,
        motion: int = 2,
        pause: float = 0,
    ) -> None:
        # state=ReProc, motion: 0 JUMP, 1 MOVJ, 2 MOVL
        self.enqueue(
            self._packet(3, 0, x, y, z, r, float(tool_on), motion, 0, pause)
        )

    def tool(self, enabled: bool, laser: bool) -> None:
        axis = 13 if enabled and laser else 14 if laser else 9 if enabled else 10
        self.enqueue(self._packet(7, axis, 0, 0, 0, 0, 0, 0, 0, 0))

    def emergency_stop(self, laser_mode: bool = True) -> None:
        self.clear_queue()
        if not self.connected:
            return
        # Match the legacy client's stop behavior. State 0 (MachineIdle) can
        # latch the original FPGA motor drivers off until a full power cycle.
        try:
            packets = (
                self._packet(2, 0, 0, 0, 0, 0, 0, 0, 0, 0),
                self._packet(7, 0, 0, 0, 0, 0, 0, 0, 0, 0),
                self._packet(7, 10, 0, 0, 0, 0, 0, 0, 0, 0),
                self._packet(7, 14, 0, 0, 0, 0, 0, 0, 0, 0),
            )
            self._send(b"".join(packets))
        except (OSError, ConnectionError):
            pass
