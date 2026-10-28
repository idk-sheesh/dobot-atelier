import unittest

from workspace_mapping import measured_point, observed_bounds, telemetry_badge, validate_mapping_data


class WorkspaceMeasurementTests(unittest.TestCase):
    def test_signed_coordinates_and_french_decimals(self):
        self.assertEqual(measured_point("200,5", "-40"), (200.5, -40))

    def test_invalid_measurements(self):
        for value in ("", "abc", float("nan"), float("inf"), True, 1001, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                measured_point(value, 0)

    def test_bounds_describe_only_observed_extent(self):
        self.assertIsNone(observed_bounds([]))
        self.assertEqual(observed_bounds([(200, -80), (220, 40)]), (200, 220, -80, 40))

    def test_height_required_for_saved_points(self):
        with self.assertRaises(ValueError):
            validate_mapping_data({"version": 1, "plateau": {"points": [[200, 40]]}})

    def test_invalid_file_shapes_are_rejected(self):
        for data in ([], {"version": 2}, {"version": 1, "joint_samples": True},
                     {"version": 1, "joint_samples": 1, "joint_ranges": {}},
                     {"version": 1, "plateau": {"height_mm": 0, "points": [[1]]}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_mapping_data(data)

    def test_green_badge_requires_fresh_telemetry(self):
        self.assertEqual(telemetry_badge(True, 0.1)[1], "Connected.TLabel")
        for age in (-1, 2, float("nan")):
            self.assertEqual(telemetry_badge(True, age)[1], "Waiting.TLabel")
        self.assertEqual(telemetry_badge(False, 0.1)[1], "Disconnected.TLabel")


if __name__ == "__main__":
    unittest.main()
