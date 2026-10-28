from __future__ import annotations

import math
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
RUNNING_JOINT_MARGIN = 3.0


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
    """Check reported values; this does not validate physical calibration."""
    if pose is None or not math.isfinite(packet_age) or packet_age < 0:
        return "Aucune télémétrie reçue du robot."
    if not all(math.isfinite(getattr(pose, attr)) for attr in
               ("x", "y", "z", "r", "joint1", "joint2", "joint3", "joint4", "gripper")):
        return "Télémétrie non finie : mouvement interdit."
    if packet_age > MAX_TELEMETRY_AGE:
        return f"Télémétrie trop ancienne ({packet_age:.1f} s)."
    for label, attribute, minimum, maximum in STARTUP_JOINT_LIMITS:
        value = getattr(pose, attribute)
        if not minimum <= value <= maximum:
            return f"{label} = {value:.1f}° hors plage [{minimum:.0f}°, {maximum:.0f}°]."
    return None


def running_pose_issue(pose: Pose | None, packet_age: float) -> str | None:
    """Return a reason to stop an active trajectory immediately."""
    issue = startup_pose_issue(pose, packet_age)
    if issue is not None:
        return issue
    for label, attribute, minimum, maximum in STARTUP_JOINT_LIMITS:
        value = getattr(pose, attribute)
        if value < minimum + RUNNING_JOINT_MARGIN or value > maximum - RUNNING_JOINT_MARGIN:
            return f"{label} = {value:.1f}° trop proche d'une limite."
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
        self._motion_blocked = threading.Event()
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
        self.close()
        if self._thread is not None and self._thread.is_alive():
            raise ConnectionError("La fermeture de l'ancienne connexion n'est pas terminée")
        self._stop_event = threading.Event()
        self._motion_blocked.clear()
        self.packets_received = self.commands_sent = 0
        self.last_command_time = 0.0
        sock = socket.create_connection((host, port), timeout=3)
        sock.settimeout(1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._socket = sock
        self.connected = True
        self._emit_status("Connecté au Dobot")
        self._thread = threading.Thread(target=self._reader, args=(sock, self._stop_event), daemon=True)
        self._thread.start()
        try:
            self._wake_telemetry()
        except (OSError, ConnectionError):
            self.close()
            raise

    def _wake_telemetry(self) -> None:
        # Some V1 firmwares stay silent after the serial bridge reconnects.
        # An idle frame is harmless and restarts their telemetry stream.
        self._send(self._packet(7, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    def close(self) -> None:
        self._stop_event.set()
        self._motion_blocked.set()
        self.clear_queue()
        with self._send_lock:
            sock, self._socket = self._socket, None
            self.connected = False
            self.pose = None
            self.last_packet_time = 0.0
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)
        self._emit_status("Déconnecté")

    def _emit_status(self, status: str) -> None:
        if self.on_status:
            self.on_status(status)

    def _reader(self, sock: socket.socket, stop_event: threading.Event) -> None:
        buffer = bytearray()
        wake_attempts = 1
        last_wake = time.monotonic()
        try:
            while not stop_event.is_set():
                try:
                    chunk = sock.recv(4096)
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
                    if stop_event.is_set() or self._socket is not sock:
                        return
                    self._handle_packet(packet)
        except (OSError, ConnectionError, ValueError) as exc:
            if not stop_event.is_set():
                self._emit_status(f"Connexion perdue : {exc}")
        finally:
            with self._send_lock:
                if self._socket is sock:
                    self._socket = None
                    self.connected = False
                    self.pose = None
                    self.last_packet_time = 0.0
                    self._motion_blocked.set()
                    self.clear_queue()
            try:
                sock.close()
            except OSError:
                pass

    def _handle_packet(self, packet: bytes) -> None:
        values = FRAME.unpack(packet[1:-1])
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Télémétrie non finie")
        self.packets_received += 1
        self.last_packet_time = time.monotonic()
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
        if self._motion_blocked.is_set():
            return
        self._send(command, queued=True)

    def _send(self, packet: bytes, *, queued: bool = False) -> bool:
        with self._send_lock:
            if queued and self._motion_blocked.is_set():
                return False
            if not self.connected or self._socket is None:
                raise ConnectionError("Dobot non connecté")
            self._socket.sendall(packet)
            self.commands_sent += max(1, len(packet) // PACKET_SIZE)
            self.last_command_time = time.monotonic()
            return True

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
        if self._motion_blocked.is_set():
            raise ConnectionError("Mouvements verrouillés après un arrêt")
        self._commands.put(packet)

    def begin_motion(self) -> None:
        """Explicitly unlock a new, validated playback queue."""
        self.clear_queue()
        self._motion_blocked.clear()

    def dispatch_next(self) -> bool:
        """Send the first queued command without waiting for idle telemetry."""
        try:
            command = self._commands.get_nowait()
        except queue.Empty:
            return False
        return self._send(command, queued=True)

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
        end_type: int | None,
        laser_mode: bool,
    ) -> None:
        # The original controller can power up with zero playback limits. The
        # legacy client sends these limits before the percentage ratios.
        packets = [
            self._packet(9, 1, 200, 200, 200, 200, 200, 200, 0.1, 20),
            self._packet(10, 0, velocity, acceleration, 0, 0, 0, 0, 0, 0),
        ]
        if end_type is not None:
            packets.append(self._packet(9, 4, end_type, 0, 0, 0, 0, 0, 0, 0))
        packets.extend((
            self._packet(7, 14 if laser_mode else 10, 0, 0, 0, 0, 0, 0, 0, 0),
            self._packet(7, 10 if laser_mode else 14, 0, 0, 0, 0, 0, 0, 0, 0),
        ))
        for packet in packets:
            self.enqueue(packet)

    def probe(self) -> int:
        before = self.packets_received
        self._wake_telemetry()
        return before

    def queue_single_step_configuration(self) -> None:
        # Do not change end type/TCP: that would change the meaning of the target.
        for values in (
            (9, 1, 20, 20, 20, 20, 20, 20, 0, 0),
            (10, 0, 10, 10, 0, 0, 0, 0, 0, 0),
            (7, 10, 0, 0, 0, 0, 0, 0, 0, 0),
            (7, 14, 0, 0, 0, 0, 0, 0, 0, 0),
        ):
            self.enqueue(self._packet(*values))

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
        gripper: float = 0,
    ) -> None:
        # DobotTools V1.0 DobotClient.h: 0 JUMP, 1 MOVJ, 2 MOVL.
        self.enqueue(
            self._packet(3, 0, x, y, z, r, float(tool_on), motion, gripper, pause)
        )

    def tool(self, enabled: bool, laser: bool) -> None:
        axis = 13 if enabled and laser else 14 if laser else 9 if enabled else 10
        self.enqueue(self._packet(7, axis, 0, 0, 0, 0, 0, 0, 0, 0))

    def emergency_stop(self, laser_mode: bool = True) -> None:
        self._motion_blocked.set()
        self.clear_queue()
        if not self.connected:
            return
        # State 0 (MachineIdle) can latch the original FPGA drivers off. Send
        # the official AxisIdle command repeatedly and separately instead: a
        # single idle frame proved unreliable through this V1 serial bridge.
        try:
            idle = self._packet(2, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            for _ in range(5):
                self._send(idle)
                time.sleep(0.02)
            self._send(self._packet(7, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            self._send(self._packet(7, 10, 0, 0, 0, 0, 0, 0, 0, 0))
            self._send(self._packet(7, 14, 0, 0, 0, 0, 0, 0, 0, 0))
        except (OSError, ConnectionError):
            pass
