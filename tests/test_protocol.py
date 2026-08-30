import struct
import unittest

from dobot_protocol import DobotConnection, FRAME, Pose, startup_pose_issue


class ProtocolTests(unittest.TestCase):
    def test_packet_matches_legacy_frame(self):
        packet = DobotConnection._packet(9, 4, 2, 0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(len(packet), 42)
        self.assertEqual(packet[0], 0xA5)
        self.assertEqual(packet[-1], 0x5A)
        values = FRAME.unpack(packet[1:-1])
        self.assertEqual(values[:3], (9.0, 4.0, 2.0))

    def test_emergency_stop_is_sent_as_one_priority_burst(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendall(self, data):
                self.sent.append(data)

        connection = DobotConnection()
        connection.connected = True
        connection._socket = FakeSocket()
        connection.emergency_stop(laser_mode=True)
        burst = connection._socket.sent[0]
        self.assertEqual(len(burst), 42 * 4)
        frames = [FRAME.unpack(burst[i + 1:i + 41]) for i in range(0, len(burst), 42)]
        self.assertEqual(frames[0][:2], (2.0, 0.0))
        self.assertNotIn(0.0, [frame[0] for frame in frames])
        self.assertIn((7.0, 14.0), [frame[:2] for frame in frames])

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
        self.assertEqual(connection.queue_size(), 4)
        first = FRAME.unpack(connection._commands.get_nowait()[1:-1])
        self.assertEqual(first[:2], (9.0, 1.0))
        self.assertEqual(first[2:8], (200.0, 200.0, 200.0, 200.0, 200.0, 200.0))
        self.assertAlmostEqual(first[8], 0.1, places=5)
        self.assertEqual(first[9], 20.0)

    def test_joint_jog_uses_official_start_velocity_field(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendall(self, data):
                self.sent.append(data)

        connection = DobotConnection()
        connection.connected = True
        connection._socket = FakeSocket()
        connection.jog_joint(1, speed=8)
        frame = FRAME.unpack(connection._socket.sent[0][1:-1])
        self.assertEqual(frame[:2], (2.0, 1.0))
        self.assertEqual(frame[6], 0.0)
        self.assertEqual(frame[7], 8.0)

    def test_startup_pose_accepts_the_verified_robot_position(self):
        pose = Pose(289, 0, -128, 0, 2.85, 76.43, 57.35, 0, False, 0)
        self.assertIsNone(startup_pose_issue(pose, packet_age=0.1))

    def test_startup_pose_rejects_joint2_above_official_limit(self):
        pose = Pose(241, 0, -207, 0, 0, 117.25, 65.61, 0, False, 0)
        self.assertIn("J2", startup_pose_issue(pose, packet_age=0.1))

    def test_startup_pose_rejects_stale_telemetry(self):
        pose = Pose(289, 0, -128, 0, 0, 76, 57, 0, False, 0)
        self.assertIn("ancienne", startup_pose_issue(pose, packet_age=2.0))

    def test_configure_jog_uses_official_limits(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []

            def sendall(self, data):
                self.sent.append(data)

        connection = DobotConnection()
        connection.connected = True
        connection._socket = FakeSocket()
        connection.configure_jog()
        frame = FRAME.unpack(connection._socket.sent[0][1:-1])
        self.assertEqual(frame[:2], (9.0, 0.0))
        self.assertEqual(frame[2:8], (15.0, 50.0, 30.0, 10.0, 40.0, 40.0))


if __name__ == "__main__":
    unittest.main()
