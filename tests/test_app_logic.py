import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dobot_protocol import Pose
from main import AIR_TEST_MODE, DobotAtelier
from single_step import forward


class AppLogicTests(unittest.TestCase):
    def test_offline_connect_does_not_start_server_or_socket(self):
        app = SimpleNamespace(offline=True, status_var=Mock(), connection=Mock())
        with patch("main.subprocess.Popen") as launch:
            DobotAtelier.connect_robot(app)
        app.connection.connect.assert_not_called()
        launch.assert_not_called()

    def test_cached_final_pose_cannot_complete_a_trajectory(self):
        pose = Pose(201, 0, 0, 0, 0, 70, 50, 0, False, 0)
        snapshot = {"packet_age": 0.1, "packets": 5}
        app = SimpleNamespace(
            single_step=SimpleNamespace(active=False), initial_queue_size=1,
            connection=SimpleNamespace(diagnostic_snapshot=lambda: snapshot, queue_size=lambda: 0),
            pose=pose, _run_start_pose=Pose(200, 0, 0, 0, 0, 70, 50, 0, False, 0),
            _run_motion_seen=True, _run_started_at=time.monotonic(),
            _run_final_target=(201, 0, 0), _run_final_checks=0, _run_last_packet=-1,
            progress=Mock(), status_var=Mock(), run_state_var=Mock(), after=Mock(), _poll_progress=Mock(),
        )
        for _ in range(4):
            DobotAtelier._poll_progress(app)
        self.assertEqual(app._run_final_checks, 1)
        self.assertEqual(app.initial_queue_size, 1)
        for count in (6, 7):
            snapshot["packets"] = count
            DobotAtelier._poll_progress(app)
        self.assertEqual(app.initial_queue_size, 0)
        self.assertIn("Mouvement physique non confirmé", app.status_var.set.call_args.args[0])

    def test_old_simulation_mode_is_migrated_and_server_choice_preserved(self):
        names = ("server_path", "mode", "width", "origin_x", "origin_y", "z_work", "z_safe",
                 "rotation", "step", "flip_y", "velocity", "acceleration")
        app = SimpleNamespace(**{name + "_var": Mock() for name in names})
        for axis in ("x", "y", "z"):
            for side in ("min", "max"):
                setattr(app, f"limit_{axis}_{side}", Mock())
        config = Mock()
        config.read_text.return_value = json.dumps({"mode": "Simulation", "server_path": "C:/Dobot/DobotServer.exe"})
        with patch("main.CONFIG_FILE", config):
            DobotAtelier._load_config(app)
        app.mode_var.set.assert_called_once_with(AIR_TEST_MODE)
        app.server_path_var.set.assert_called_once_with("C:/Dobot/DobotServer.exe")

    def test_invalid_config_container_is_ignored(self):
        config = Mock()
        config.read_text.return_value = "[]"
        with patch("main.CONFIG_FILE", config):
            DobotAtelier._load_config(SimpleNamespace())

    def step_app(self):
        pose = Pose(*forward(0, 1, 16.6), 0, 0, 1, 16.6, 0, False, 0)
        return SimpleNamespace(
            initial_queue_size=0, single_step=Mock(active=False, used=False),
            connection=SimpleNamespace(pose=pose, diagnostic_snapshot=lambda: {"connected": True, "packet_age": 0.1}),
            _official_client_running=lambda: False, _diagnostic_window=None,
            single_step_var=Mock(), run_state_var=Mock(),
        )

    def test_attempt_is_recorded_before_any_configuration_is_sent(self):
        app = self.step_app()
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "diagnostic_pas_1mm.json"

            def start():
                self.assertTrue(json.loads(report.read_text(encoding="utf-8"))["test_started"])

            app.single_step.start.side_effect = start
            with patch("main.MEASUREMENT_DIR", Path(directory)), patch("main.messagebox.askokcancel", return_value=True):
                DobotAtelier.run_single_step(app)
            app.single_step.start.assert_called_once()

    def test_unwritable_report_prevents_the_step(self):
        app = self.step_app()
        with patch("main.messagebox.askokcancel", return_value=True), \
                patch("main.Path.write_text", side_effect=OSError("read only")), \
                patch("main.messagebox.showerror") as error:
            DobotAtelier.run_single_step(app)
        app.single_step.start.assert_not_called()
        error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
