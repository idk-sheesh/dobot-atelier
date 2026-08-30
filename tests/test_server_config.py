import unittest
from pathlib import Path
from unittest import mock

from server_config import default_server_executable, normalize_server_executable


class ServerConfigTests(unittest.TestCase):
    def test_environment_override_has_priority(self):
        configured = Path("C:/Dobot/Custom/DobotServer.exe")

        result = default_server_executable(
            Path("C:/Dobot/Atelier"),
            environ={"DOBOT_SERVER_EXE": str(configured)},
        )

        self.assertEqual(result, configured)

    def test_server_next_to_application_is_detected(self):
        app_dir = Path("C:/Dobot/Atelier")
        server = app_dir / "DobotServer.exe"
        with mock.patch.object(Path, "is_file", return_value=True):
            result = default_server_executable(app_dir, home=app_dir / "home", environ={})

        self.assertEqual(result, server)

    def test_path_is_trimmed(self):
        self.assertEqual(
            normalize_server_executable("  C:/Dobot/DobotServer.exe  "),
            Path("C:/Dobot/DobotServer.exe"),
        )


if __name__ == "__main__":
    unittest.main()
