import unittest
import json
import tempfile
from pathlib import Path
from dataclasses import replace
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from dobot_protocol import Pose
from main import DobotAtelier


class ManualMappingTests(unittest.TestCase):
    def setUp(self):
        self.pose = Pose(136, 0, -6, 0, 0, 2.3, 61.8, 0, False, 0)
        self.snapshot = {"connected": True, "packet_age": 0.1}
        self.app = SimpleNamespace(
            pose=self.pose,
            pose_var=Mock(),
            joints_var=Mock(),
            status_var=Mock(),
            connection=SimpleNamespace(
                diagnostic_snapshot=Mock(return_value=self.snapshot),
                emergency_stop=Mock(),
            ),
            emergency_stop=Mock(),
            _mapping_window=None,
            _mapping_last_pose=None,
            _mapping_samples=0,
            _mapping_ranges={},
            _mapping_text=Mock(),
            _save_mapping=Mock(return_value=True),
            _build_plateau_mapping=Mock(),
            _plateau_points=[],
            _plateau_height=None,
            _plateau_x_var=Mock(),
            _plateau_y_var=Mock(),
            _plateau_height_var=Mock(),
            _update_plateau=Mock(),
            _mapping_axes=DobotAtelier._mapping_axes,
        )
        for name in ("_record_mapping_pose", "_update_mapping_text", "reset_manual_mapping", "record_manual_position", "apply_manual_mapping", "_close_manual_mapping", "record_measured_point", "undo_measured_point"):
            setattr(self.app, name, MethodType(getattr(DobotAtelier, name), self.app))

    def test_first_pose_after_opening_needs_no_movement(self):
        with patch("main.tk.Toplevel"), patch("main.tk.StringVar"), patch("main.ttk.Frame"), patch("main.ttk.Label"), patch("main.ttk.Button"), patch("main.ttk.Notebook"), patch("main.messagebox.showerror") as error:
            DobotAtelier.open_manual_mapping(self.app)
            self.app.record_manual_position()
            error.assert_not_called()
        self.assertEqual(self.app._mapping_samples, 1)
        self.assertEqual(self.app._mapping_ranges["J2"], [2.3, 2.3])
        self.assertIn("Positions : 1", self.app._mapping_text.set.call_args.args[0])

    def test_identical_pose_is_a_duplicate_not_a_sensor_failure(self):
        self.app.record_manual_position()
        with patch("main.messagebox.showwarning") as warning:
            self.app.record_manual_position()
            warning.assert_not_called()
        self.assertEqual(self.app._mapping_samples, 1)
        self.app.connection.emergency_stop.assert_called_once()

    def test_changed_pose_extends_ranges_and_reset_allows_same_pose(self):
        self.app.record_manual_position()
        self.app.pose = replace(self.pose, x=150, joint2=10)
        self.app.record_manual_position()
        self.assertEqual(self.app._mapping_samples, 2)
        self.assertEqual(self.app._mapping_ranges["X"], [136, 150])
        self.app.reset_manual_mapping()
        self.app.record_manual_position()
        self.assertEqual(self.app._mapping_samples, 1)
        self.assertEqual(self.app._mapping_ranges["X"], [150, 150])

    def test_missing_stale_disconnected_or_invalid_telemetry_is_rejected(self):
        for connected, age, pose in ((True, -1, self.pose), (True, 2, self.pose), (False, 0.1, self.pose), (True, 0.1, None), (True, 0.1, replace(self.pose, x=float("nan")))):
            with self.subTest(connected=connected, age=age, pose=pose):
                self.snapshot.update(connected=connected, packet_age=age)
                self.app.pose = pose
                with patch("main.messagebox.showerror") as error:
                    self.app.record_manual_position()
                    error.assert_called_once()
                self.assertEqual(self.app._mapping_samples, 0)
                self.assertEqual(self.app._mapping_ranges, {})
                self.app.connection.emergency_stop.assert_not_called()

    def test_physical_plateau_point_needs_no_robot_connection_or_command(self):
        self.app.pose = None
        self.snapshot.update(connected=False, packet_age=-1)
        self.app._plateau_x_var.get.return_value = "180,5"
        self.app._plateau_y_var.get.return_value = "-20"
        self.app._plateau_height_var.get.return_value = "15"
        self.app.record_measured_point()
        self.assertEqual(self.app._plateau_points, [(180.5, -20)])
        self.assertEqual(self.app._plateau_height, 15)
        self.app.connection.emergency_stop.assert_not_called()
        self.app.connection.diagnostic_snapshot.assert_not_called()
        self.app._save_mapping.assert_called_once()

    def test_duplicate_and_changed_height_cannot_add_points(self):
        self.app._plateau_x_var.get.return_value = "180"
        self.app._plateau_y_var.get.return_value = "20"
        self.app._plateau_height_var.get.return_value = "15"
        self.app.record_measured_point()
        with patch("main.messagebox.showerror") as error:
            self.app.record_measured_point()
            self.app._plateau_x_var.get.return_value = "200"
            self.app._plateau_height_var.get.return_value = "16"
            self.app.record_measured_point()
            self.assertEqual(error.call_count, 2)
        self.assertEqual(len(self.app._plateau_points), 1)

    def test_observed_extremes_never_apply_motion_limits(self):
        self.app.limit_x_min = Mock()
        with patch("main.messagebox.showinfo"):
            self.app.apply_manual_mapping()
        self.app.limit_x_min.set.assert_not_called()

    def test_save_and_reload_retains_points_and_joint_ranges(self):
        self.app.record_manual_position()
        self.app._plateau_points = [(200, -20), (220, 40)]
        self.app._plateau_height = -10
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder) / "measurements.json"
            self.assertTrue(DobotAtelier._save_mapping(self.app, path))
            with patch("main.MEASUREMENT_FILE", path):
                DobotAtelier._load_mapping(self.app)
            self.assertEqual(self.app._plateau_points, [(200, -20), (220, 40)])
            self.assertEqual(self.app._mapping_samples, 1)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("motion_limits", data)

    def test_invalid_saved_data_is_not_loaded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder) / "measurements.json"
            path.write_text('{"version": 1, "plateau": {"points": [[NaN, 1]]}}', encoding="utf-8")
            with patch("main.MEASUREMENT_FILE", path):
                DobotAtelier._load_mapping(self.app)
            self.assertEqual(self.app._plateau_points, [])


if __name__ == "__main__":
    unittest.main()
