import math
import unittest
from dataclasses import replace
from unittest.mock import patch

from dobot_protocol import DobotConnection, FRAME, Pose
from single_step import SingleStepController, forward, inverse, plan_step


def model_pose(j1=0, j2=1, j3=16.6):
    return Pose(*forward(j1, j2, j3), 0, j1, j2, j3, 0, False, 0)


class GeometryTests(unittest.TestCase):
    def test_inverse_round_trip_at_observed_working_poses(self):
        for values in ((0, 1, 16.6), (0, 55, 35), (30, 66.6, 69.5), (-30, 25.1, 53.7)):
            pose = model_pose(*values)
            result = inverse(pose.x, pose.y, pose.z, pose)
            for actual, expected in zip(result, values):
                self.assertAlmostEqual(actual, expected, places=8)

    def test_exactly_one_mm_radial_step_at_constant_height(self):
        for j1 in (0, 30, -90):
            pose = model_pose(j1=j1)
            plan = plan_step(pose)
            self.assertAlmostEqual(math.dist(plan.target, (pose.x, pose.y, pose.z)), 1)
            self.assertEqual(plan.target[2], pose.z)
            self.assertAlmostEqual(math.hypot(*plan.target[:2]), math.hypot(pose.x, pose.y) - 1)
            self.assertGreater(plan.target_joints[1], 0)

    def test_wrong_tcp_or_nonfinite_or_near_joint_limit_is_rejected(self):
        for pose in (replace(model_pose(), x=model_pose().x + 5), replace(model_pose(), z=float("nan")),
                     model_pose(j2=0), model_pose(j2=84), replace(model_pose(), joint4=89)):
            with self.subTest(pose=pose), self.assertRaises(ValueError):
                plan_step(pose)

    def test_central_zero_and_full_extension_are_not_test_targets(self):
        for pose in (replace(model_pose(), x=0, y=0), model_pose(j2=80, j3=10)):
            with self.assertRaises(ValueError):
                plan_step(pose)


class FakeClock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        self.now += 0.000001
        return self.now


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendall(self, packet):
        self.sent.append(FRAME.unpack(packet[1:-1]))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.time_patch = patch("dobot_protocol.time.monotonic", side_effect=self.clock)
        self.sleep_patch = patch("dobot_protocol.time.sleep")
        self.time_patch.start()
        self.sleep_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.addCleanup(self.sleep_patch.stop)
        self.connection = DobotConnection()
        self.connection.connected = True
        self.connection._socket = FakeSocket()
        self.source = model_pose()
        self.feed(self.source)
        self.controller = SingleStepController(self.connection, clock=self.clock)

    def feed(self, pose):
        self.clock.now += 0.05
        self.connection._handle_packet(self.connection._packet(
            pose.x, pose.y, pose.z, pose.r, pose.joint1, pose.joint2, pose.joint3,
            pose.joint4, float(pose.tool_on), pose.gripper))

    @property
    def moves(self):
        return [frame for frame in self.connection._socket.sent if frame[0] == 3]

    def start_motion(self):
        self.controller.start()
        self.assertEqual(self.moves, [])
        for _ in range(5):
            self.feed(self.source)
        self.controller.tick()
        self.assertEqual(self.controller.phase, "moving")
        self.assertEqual(len(self.moves), 1)

    def test_configuration_keeps_tcp_and_tools_off_before_target(self):
        self.start_motion()
        frames = self.connection._socket.sent
        self.assertFalse(any(frame[:2] == (9, 4) for frame in frames))
        self.assertIn((7, 10), [frame[:2] for frame in frames])
        self.assertIn((7, 14), [frame[:2] for frame in frames])
        move = self.moves[0]
        self.assertEqual(move[6:8], (0, 2))
        self.assertAlmostEqual(move[2], self.source.x - 1, places=4)
        self.assertAlmostEqual(move[4], self.source.z, places=4)
        self.assertFalse(any(frame[0] in (1, 2, 4, 6) for frame in frames))

    def test_three_fresh_target_readings_complete_then_stop(self):
        self.start_motion()
        plan = self.controller.plan
        final = Pose(*plan.target, self.source.r, *plan.target_joints, 0, False, 0)
        for _ in range(3):
            self.feed(final)
            self.controller.tick()
        self.assertFalse(self.controller.active)
        self.assertTrue(self.controller.report["telemetry_target_reached"])
        self.assertNotIn("completed", self.controller.report)
        self.assertIn("Mouvement physique non confirmé", self.controller.status)
        self.assertFalse(self.controller.report["physical_distance_independently_verified"])
        self.assertEqual(len(self.moves), 1)
        self.assertEqual(self.connection.queue_size(), 0)
        self.assertTrue(self.connection._motion_blocked.is_set())
        with self.assertRaises(ValueError):
            self.controller.start()

    def test_previous_attempt_stays_locked_after_restart_without_sending(self):
        controller = SingleStepController(self.connection, clock=self.clock, previously_used=True)
        with self.assertRaisesRegex(ValueError, "déjà été utilisé"):
            controller.start()
        self.assertFalse(controller.active)
        self.assertTrue(controller.used)
        self.assertIn("Mouvement physique non confirmé", controller.status)
        self.assertEqual(self.connection._socket.sent, [])

    def test_repeated_cached_pose_does_not_finish(self):
        self.start_motion()
        plan = self.controller.plan
        self.feed(Pose(*plan.target, 0, *plan.target_joints, 0, False, 0))
        for _ in range(3):
            self.controller.tick()
        self.assertTrue(self.controller.active)
        self.assertEqual(self.controller.final_checks, 1)

    def test_tcp_shift_during_configuration_aborts_before_any_move(self):
        self.controller.start()
        self.feed(replace(self.source, x=self.source.x + 1))
        self.controller.tick()
        self.assertFalse(self.controller.active)
        self.assertEqual(self.moves, [])
        self.assertEqual(self.connection.queue_size(), 0)

    def test_lost_telemetry_stops_without_another_target(self):
        self.start_motion()
        self.clock.now += 0.6
        self.controller.tick()
        self.assertFalse(self.controller.active)
        self.assertIn("Télémétrie", self.controller.status)
        self.assertEqual(len(self.moves), 1)

    def test_large_displacement_stops(self):
        self.start_motion()
        self.feed(replace(self.source, x=self.source.x - 2))
        self.controller.tick()
        self.assertFalse(self.controller.active)
        self.assertIn("tolérance", self.controller.status)
        self.assertEqual(len(self.moves), 1)

    def test_stale_initial_pose_or_existing_queue_sends_nothing(self):
        self.clock.now += 1
        with self.assertRaises(ValueError):
            self.controller.start()
        self.feed(self.source)
        self.connection.enqueue(self.connection._packet(7, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with self.assertRaises(ValueError):
            self.controller.start()
        self.assertEqual(self.connection._socket.sent, [])

    def test_configuration_and_motion_timeouts_abort(self):
        self.controller.start()
        self.clock.now += 3.1
        self.feed(self.source)
        self.controller.tick()
        self.assertFalse(self.controller.active)
        self.assertEqual(self.moves, [])

    def test_motion_timeout_with_fresh_unchanged_pose_aborts(self):
        self.start_motion()
        self.clock.now += 5.1
        self.feed(self.source)
        self.controller.tick()
        self.assertFalse(self.controller.active)
        self.assertIn("délai", self.controller.status)
        self.assertEqual(len(self.moves), 1)

    def test_second_start_during_configuration_cannot_queue_a_move(self):
        self.controller.start()
        with self.assertRaises(ValueError):
            self.controller.start()
        self.assertEqual(self.moves, [])


if __name__ == "__main__":
    unittest.main()
