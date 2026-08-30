import unittest
from pathlib import Path

from svg_parser import load_svg, parse_path, transformed_paths


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


if __name__ == "__main__":
    unittest.main()
