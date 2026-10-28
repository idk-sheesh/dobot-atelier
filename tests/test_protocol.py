import struct
import unittest

from dobot_protocol import DobotConnection, FRAME, Pose, running_pose_issue, startup_pose_issue


class ProtocolTests(unittest.TestCase):
    def test_packet_matches_legacy_frame(self):
        packet = DobotConnection._packet(9, 4, 2, 0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(len(packet), 42)
        self.assertEqual(packet[0], 0xA5)
        self.assertEqual(packet[-1], 0x5A)
        values = FRAME.unpack(packet[1:-1])
        self.assertEqual(values[:3], (9.0, 4.0, 2.0))

    def test_emergency_stop_repeats_idle_and_blocks_old_queue(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendall(self, data):
                self.sent.append(data)

        connection = DobotConnection()
        connection.connected = True
        connection._socket = FakeSocket()
        connection.enqueue(connection._packet(3, 0, 200, 0, -180, 0, 0, 2, 0, 0))
        connection.emergency_stop(laser_mode=True)
        frames = [FRAME.unpack(packet[1:-1]) for packet in connection._socket.sent]
        self.assertEqual([frame[:2] for frame in frames[:5]], [(2.0, 0.0)] * 5)
        self.assertNotIn(0.0, [frame[0] for frame in frames])
        self.assertIn((7.0, 14.0), [frame[:2] for frame in frames])
        self.assertEqual(connection.queue_size(), 0)
        with self.assertRaises(ConnectionError):
            connection.enqueue(connection._packet(3, 0, 210, 0, -180, 0, 0, 2, 0, 0))
        connection.begin_motion()
        connection.enqueue(connection._packet(3, 0, 210, 0, -180, 0, 0, 2, 0, 0))

    def test_dispatch_next_starts_a_silent_queue(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendall(self, data):
                self.sent.append(data)

        connection = DobotConnection()
        connection.connected = True
        connection._socket = FakeSocket()
        connection.enqueue(connection._packet(3, 0, 200, 0, -180, 0, 0, 2, 0, 0))
        self.assertTrue(connection.dispatch_next())
        self.assertEqual(connection.queue_size(), 0)
        self.assertEqual(len(connection._socket.sent), 1)

    def test_playback_configuration_includes_physical_limits(self):
        connection = DobotConnection()
        connection.connected = True
        connection.queue_playback_configuration(12, 8, end_type=2, laser_mode=True)
        self.assertEqual(connection.queue_size(), 5)
        first = FRAME.unpack(connection._commands.get_nowait()[1:-1])
        self.assertEqual(first[:2], (9.0, 1.0))
        self.assertEqual(first[2:8], (200.0, 200.0, 200.0, 200.0, 200.0, 200.0))
        self.assertAlmostEqual(first[8], 0.1, places=5)
        self.assertEqual(first[9], 20.0)

    def test_tool_free_preparation_keeps_tcp_and_turns_both_outputs_off(self):
        connection = DobotConnection()
        connection.connected = True
        connection.queue_playback_configuration(12, 8, end_type=None, laser_mode=True)
        frames = []
        while connection.queue_size():
            frames.append(FRAME.unpack(connection._commands.get_nowait()[1:-1]))
        self.assertEqual(len(frames), 4)
        self.assertNotIn((9, 4), [frame[:2] for frame in frames])
        self.assertIn((7, 10), [frame[:2] for frame in frames])
        self.assertIn((7, 14), [frame[:2] for frame in frames])

    def test_startup_pose_accepts_the_verified_robot_position(self):
        pose = Pose(289, 0, -128, 0, 2.85, 76.43, 57.35, 0, False, 0)
        self.assertIsNone(startup_pose_issue(pose, packet_age=0.1))

    def test_startup_pose_rejects_joint2_above_official_limit(self):
        pose = Pose(241, 0, -207, 0, 0, 117.25, 65.61, 0, False, 0)
        self.assertIn("J2", startup_pose_issue(pose, packet_age=0.1))

    def test_startup_pose_rejects_stale_telemetry(self):
        pose = Pose(289, 0, -128, 0, 0, 76, 57, 0, False, 0)
        self.assertIn("ancienne", startup_pose_issue(pose, packet_age=2.0))

    def test_running_pose_requires_margin_from_joint_limits(self):
        safe = Pose(200, 0, -100, 0, 0, 70, 50, 0, False, 0)
        near_limit = Pose(200, 0, -100, 0, 0, 83, 50, 0, False, 0)
        self.assertIsNone(running_pose_issue(safe, 0.1))
        self.assertIn("J2", running_pose_issue(near_limit, 0.1))


if __name__ == "__main__":
    unittest.main()
