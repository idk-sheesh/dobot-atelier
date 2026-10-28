import math
import tempfile
import unittest
from pathlib import Path

from svg_parser import load_svg, parse_path, resample, transformed_paths


class SvgParserTests(unittest.TestCase):
    def test_all_path_commands_are_flattened(self):
        paths = parse_path("M0 0 L10 0 H20 V10 C20 20 30 20 30 10 Q40 0 50 10 A5 5 0 0 1 55 15 Z")
        self.assertEqual(len(paths), 1)
        self.assertGreater(len(paths[0]), 20)
        self.assertEqual(paths[0][0], paths[0][-1])

    def test_shapes_and_group_transform(self):
        drawing = load_svg(Path(__file__).parent / "fixture_transform.svg")
        self.assertEqual(len(drawing.paths), 2)
        self.assertAlmostEqual(drawing.min_x, 10)
        self.assertAlmostEqual(drawing.min_y, 20)

    def test_robot_transform_respects_requested_width(self):
        drawing = load_svg(Path(__file__).parents[1] / "exemple_gabarit.svg")
        paths = transformed_paths(drawing, 80, 200, -40, max_step_mm=200)
        xs = [p[0] for path in paths for p in path]
        self.assertAlmostEqual(max(xs) - min(xs), 80)
        self.assertAlmostEqual(paths[0][0][0], 200)

    def test_incomplete_or_unsupported_path_is_not_silently_truncated(self):
        for data in ("M0 0 L10 0 L", "M0 0 C10 10 L20 20", "M0 0 R10 10", "M0 0 L1e999 0"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_path(data)

    def test_nonfinite_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.svg"
            path.write_text('<svg><line x1="0" y1="0" x2="inf" y2="0"/></svg>', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_svg(path)

    def test_tiny_step_is_rejected_before_allocating_unbounded_points(self):
        with self.assertRaisesRegex(ValueError, "5000"):
            resample([(0, 0), (100, 0)], 1e-12)

    def test_invalid_transform_values_are_rejected(self):
        drawing = load_svg(Path(__file__).parents[1] / "exemple_gabarit.svg")
        for kwargs in ({"width_mm": math.nan}, {"origin_x": math.inf}, {"max_step_mm": 0}):
            values = {"width_mm": 80, "origin_x": 200, "origin_y": -40, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                transformed_paths(drawing, **values)


if __name__ == "__main__":
    unittest.main()
