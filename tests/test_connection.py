import math
import socket
import threading
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from dobot_protocol import DobotConnection, FRAME, Pose, startup_pose_issue


class FakeSocket:
    def __init__(self, chunks=()):
        self.chunks = iter(chunks)
        self.sent = []
        self.closed = False

    def recv(self, size):
        value = next(self.chunks, b"")
        if isinstance(value, Exception):
            raise value
        return value

    def sendall(self, packet):
        self.sent.append(packet)

    def settimeout(self, value):
        pass

    def setsockopt(self, *args):
        pass

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.status = []
        self.poses = []
        self.connection = DobotConnection(self.poses.append, self.status.append)
        self.connection.connected = True
        self.pose = Pose(210, 0, 89, 0, 0, 1, 16.6, 0, False, 0)
        self.connection.pose = self.pose
        self.packet = self.connection._packet(210, 0, 89, 0, 0, 1, 16.6, 0, 0, 0)
        self.move = self.connection._packet(3, 0, 209, 0, 89, 0, 0, 2, 0, 0)

    def read(self, chunks):
        sock = FakeSocket(chunks)
        self.connection._socket = sock
        self.connection._reader(sock, threading.Event())
        return sock

    def test_eof_and_socket_error_discard_pending_motion_and_pose(self):
        for ending in (b"", OSError("link lost")):
            with self.subTest(ending=ending):
                self.connection.connected = True
                self.connection.begin_motion()
                self.connection.enqueue(self.move)
                sock = self.read([ending])
                self.assertFalse(self.connection.connected)
                self.assertIsNone(self.connection.pose)
                self.assertEqual(self.connection.queue_size(), 0)
                self.assertTrue(self.connection._motion_blocked.is_set())
                self.assertEqual(sock.sent, [])
                self.assertTrue(sock.closed)
                self.assertIn("Connexion perdue", self.status[-1])

    def test_fragmented_and_coalesced_packets_resynchronize(self):
        self.read([b"garbage\xa5" + b"x" * 41 + self.packet[:11],
                   self.packet[11:] + self.packet])
        self.assertEqual(len(self.poses), 2)
        self.assertEqual(self.poses[0].x, 210)

    def test_silent_bridge_only_gets_bounded_idle_probes(self):
        self.connection.pose = None
        self.connection.enqueue(self.move)
        with patch("dobot_protocol.time.monotonic", side_effect=range(20)):
            sock = self.read([socket.timeout()] * 6)
        self.assertEqual(len(sock.sent), 4)
        self.assertTrue(all(FRAME.unpack(p[1:-1])[:2] == (7, 0) for p in sock.sent))
        self.assertEqual(self.connection.queue_size(), 0)

    def test_nonfinite_frame_disconnects_without_dispatch(self):
        self.connection.enqueue(self.move)
        invalid = self.connection._packet(math.nan, 0, 89, 0, 0, 1, 16.6, 0, 0, 0)
        sock = self.read([invalid])
        self.assertEqual(sock.sent, [])
        self.assertEqual(self.poses, [])
        self.assertEqual(self.connection.queue_size(), 0)
        self.assertFalse(self.connection.connected)

    def test_nonfinite_reported_coordinates_and_age_block_startup(self):
        for attr in ("x", "y", "z", "r", "joint1", "joint2", "joint3", "joint4", "gripper"):
            for value in (math.nan, math.inf):
                self.assertIsNotNone(startup_pose_issue(replace(self.pose, **{attr: value}), 0.1))
        self.assertIsNotNone(startup_pose_issue(self.pose, math.nan))

    def test_stop_lock_is_checked_inside_dispatch(self):
        sock = FakeSocket()
        self.connection._socket = sock
        self.connection.enqueue(self.move)
        self.connection._motion_blocked.set()
        self.assertFalse(self.connection.dispatch_next())
        self.assertFalse(self.connection._send(self.move, queued=True))
        self.assertEqual(sock.sent, [])

    def test_reconnect_clears_old_queue_and_only_wakes_new_session(self):
        old = FakeSocket()
        new = FakeSocket()
        self.connection._socket = old
        self.connection.enqueue(self.move)
        self.connection.connected = False
        self.connection.last_packet_time = 10
        self.connection.commands_sent = 99
        with patch("dobot_protocol.socket.create_connection", return_value=new), \
                patch("dobot_protocol.threading.Thread") as thread:
            thread.return_value.is_alive.return_value = False
            self.connection.connect()
            self.assertTrue(old.closed)
            self.assertIsNone(self.connection.pose)
            self.assertEqual(self.connection.last_packet_time, 0)
            self.assertEqual(self.connection.queue_size(), 0)
            self.assertEqual(self.connection.commands_sent, 1)
            self.assertEqual(FRAME.unpack(new.sent[0][1:-1])[:2], (7, 0))
            self.connection.close()
            thread.return_value.join.assert_called_once_with(timeout=1.5)

    def test_unfinished_old_reader_prevents_new_connection(self):
        self.connection.connected = False
        self.connection._thread = Mock()
        self.connection._thread.is_alive.return_value = True
        with patch("dobot_protocol.socket.create_connection") as create:
            with self.assertRaisesRegex(ConnectionError, "ancienne connexion"):
                self.connection.connect()
            create.assert_not_called()

    def test_old_reader_cannot_close_a_new_session(self):
        current = FakeSocket()
        self.connection._socket = current
        old = FakeSocket()
        self.connection._reader(old, threading.Event())
        self.assertTrue(self.connection.connected)
        self.assertIs(self.connection._socket, current)
        self.assertFalse(current.closed)


if __name__ == "__main__":
    unittest.main()
