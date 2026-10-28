import unittest
from types import SimpleNamespace

from dobot_protocol import DobotConnection, FRAME, Pose
from main import DobotAtelier, validate_air_test


class AirTestTests(unittest.TestCase):
    def setUp(self):
        self.pose = Pose(258, 68, -123, 12, 15, 75, 55, 0, False, 0)
        self.paths = [[(253, 65), (263, 65), (263, 71), (253, 71)]]

    def test_small_centered_trace_is_allowed(self):
        validate_air_test(self.pose, self.paths, -123)

    def test_old_origin_and_lift_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_air_test(self.pose, [[(238, 62)]], -123)
        with self.assertRaises(ValueError):
            validate_air_test(self.pose, self.paths, -108)

    def test_near_limit_pose_is_rejected(self):
        pose = Pose(258, 68, -123, 0, 15, 84.1, 55, 0, False, 0)
        with self.assertRaisesRegex(ValueError, 'J2'):
            validate_air_test(pose, self.paths, -123)

    def test_simulation_has_no_jump_or_tool_activation(self):
        connection = DobotConnection()
        connection.connected = True
        dummy = SimpleNamespace(connection=connection, pose=self.pose,
                                robot_paths=self.paths + [[(258, 68), (259, 68)]])
        DobotAtelier._queue_simulation(dummy, -123)
        frames = []
        while connection.queue_size():
            frames.append(FRAME.unpack(connection._commands.get_nowait()[1:-1]))
        moves = [f for f in frames if f[0] == 3]
        self.assertEqual(len(moves), 6)
        self.assertTrue(all(f[7] == 2 and f[4] == -123 and f[5] == 12 and f[6] == 0 for f in moves))
        self.assertEqual(frames[-1][:2], (7, 14))

if __name__ == '__main__':
    unittest.main()
