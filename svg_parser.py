from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


Point = tuple[float, float]
Polyline = list[Point]
Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)
NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
TOKEN_RE = re.compile(rf"[AaCcHhLlMmQqSsTtVvZz]|{NUMBER}")


@dataclass(frozen=True)
class SvgDrawing:
    paths: list[Polyline]
    width: float
    height: float
    min_x: float
    min_y: float

    @property
    def point_count(self) -> int:
        return sum(len(path) for path in self.paths)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _numbers(value: str | None) -> list[float]:
    return [float(x) for x in re.findall(NUMBER, value or "")]


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = a
    a2, b2, c2, d2, e2, f2 = b
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _transform_point(point: Point, matrix: Matrix) -> Point:
    x, y = point
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(value: str | None) -> Matrix:
    result = IDENTITY
    for name, raw in re.findall(r"([A-Za-z]+)\s*\(([^)]*)\)", value or ""):
        v = _numbers(raw)
        name = name.lower()
        current = IDENTITY
        if name == "matrix" and len(v) >= 6:
            current = tuple(v[:6])  # type: ignore[assignment]
        elif name == "translate" and v:
            current = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            current = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            angle = math.radians(v[0])
            rotation = (math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0, 0)
            if len(v) >= 3:
                current = _multiply(
                    _multiply((1, 0, 0, 1, v[1], v[2]), rotation),
                    (1, 0, 0, 1, -v[1], -v[2]),
                )
            else:
                current = rotation
        elif name == "skewx" and v:
            current = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewy" and v:
            current = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        result = _multiply(result, current)
    return result


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int) -> list[Point]:
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        points.append((
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        ))
    return points


def _quadratic(p0: Point, p1: Point, p2: Point, steps: int) -> list[Point]:
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        points.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                       u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return points


def _arc(p0: Point, rx: float, ry: float, rotation: float, large: bool, sweep: bool,
         p1: Point, steps: int) -> list[Point]:
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rotation % 360)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    xp = cos_phi * dx + sin_phi * dy
    yp = -sin_phi * dx + cos_phi * dy
    scale = xp * xp / (rx * rx) + yp * yp / (ry * ry)
    if scale > 1:
        scale = math.sqrt(scale)
        rx *= scale
        ry *= scale
    sign = -1 if large == sweep else 1
    numerator = max(0, rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp)
    denominator = rx * rx * yp * yp + ry * ry * xp * xp
    coef = sign * math.sqrt(numerator / denominator) if denominator else 0
    cxp = coef * (rx * yp / ry)
    cyp = coef * (-ry * xp / rx)
    cx = cos_phi * cxp - sin_phi * cyp + (p0[0] + p1[0]) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (p0[1] + p1[1]) / 2

    def angle(u: Point, v: Point) -> float:
        dot = u[0] * v[0] + u[1] * v[1]
        det = u[0] * v[1] - u[1] * v[0]
        return math.atan2(det, dot)

    u = ((xp - cxp) / rx, (yp - cyp) / ry)
    v = ((-xp - cxp) / rx, (-yp - cyp) / ry)
    theta = angle((1, 0), u)
    delta = angle(u, v)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    count = max(2, int(abs(delta) / (2 * math.pi) * steps))
    points = []
    for i in range(1, count + 1):
        t = theta + delta * i / count
        points.append((cx + cos_phi * rx * math.cos(t) - sin_phi * ry * math.sin(t),
                       cy + sin_phi * rx * math.cos(t) + cos_phi * ry * math.sin(t)))
    points[-1] = p1
    return points


def parse_path(data: str, curve_steps: int = 16) -> list[Polyline]:
    if TOKEN_RE.sub("", data).strip(" ,\t\r\n"):
        raise ValueError("Commande ou nombre SVG non pris en charge")
    tokens = TOKEN_RE.findall(data.replace(",", " "))
    paths: list[Polyline] = []
    path: Polyline = []
    i = 0
    command = ""
    current = (0.0, 0.0)
    start = current
    last_cubic: Point | None = None
    last_quad: Point | None = None

    counts = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4,
              "Q": 4, "T": 2, "A": 7, "Z": 0}
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        if not command:
            raise ValueError("Chemin SVG invalide")
        upper = command.upper()
        relative = command.islower()
        if upper == "Z":
            if path and path[-1] != start:
                path.append(start)
            if path:
                paths.append(path)
            path = []
            current = start
            command = ""
            last_cubic = last_quad = None
            continue
        needed = counts[upper]
        if i + needed > len(tokens) or any(token.isalpha() for token in tokens[i:i + needed]):
            raise ValueError("Commande SVG incomplète")
        values = [float(v) for v in tokens[i:i + needed]]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Coordonnée SVG non finie")
        i += needed

        def point(x: float, y: float) -> Point:
            return (x + current[0], y + current[1]) if relative else (x, y)

        if upper == "M":
            target = point(values[0], values[1])
            if path:
                paths.append(path)
            path = [target]
            current = start = target
            command = "l" if relative else "L"
        elif upper == "L":
            current = point(values[0], values[1]); path.append(current)
        elif upper == "H":
            current = (current[0] + values[0], current[1]) if relative else (values[0], current[1]); path.append(current)
        elif upper == "V":
            current = (current[0], current[1] + values[0]) if relative else (current[0], values[0]); path.append(current)
        elif upper == "C":
            p1, p2, target = point(values[0], values[1]), point(values[2], values[3]), point(values[4], values[5])
            path.extend(_cubic(current, p1, p2, target, curve_steps)); current = target; last_cubic = p2
        elif upper == "S":
            p1 = (2 * current[0] - last_cubic[0], 2 * current[1] - last_cubic[1]) if last_cubic else current
            p2, target = point(values[0], values[1]), point(values[2], values[3])
            path.extend(_cubic(current, p1, p2, target, curve_steps)); current = target; last_cubic = p2
        elif upper == "Q":
            p1, target = point(values[0], values[1]), point(values[2], values[3])
            path.extend(_quadratic(current, p1, target, curve_steps)); current = target; last_quad = p1
        elif upper == "T":
            p1 = (2 * current[0] - last_quad[0], 2 * current[1] - last_quad[1]) if last_quad else current
            target = point(values[0], values[1])
            path.extend(_quadratic(current, p1, target, curve_steps)); current = target; last_quad = p1
        elif upper == "A":
            target = point(values[5], values[6])
            path.extend(_arc(current, values[0], values[1], values[2], bool(values[3]), bool(values[4]), target, curve_steps * 2))
            current = target
        if upper not in {"C", "S"}:
            last_cubic = None
        if upper not in {"Q", "T"}:
            last_quad = None
    if path:
        paths.append(path)
    return [p for p in paths if len(p) >= 2]


def _shape_paths(element: ET.Element, curve_steps: int) -> list[Polyline]:
    tag = _local_name(element.tag).lower()
    a = element.attrib
    if tag == "path":
        return parse_path(a.get("d", ""), curve_steps)
    if tag in {"polyline", "polygon"}:
        values = _numbers(a.get("points"))
        points = list(zip(values[::2], values[1::2]))
        if tag == "polygon" and points and points[-1] != points[0]:
            points.append(points[0])
        return [points] if len(points) >= 2 else []
    if tag == "line":
        return [[(float(a.get("x1", 0)), float(a.get("y1", 0))),
                 (float(a.get("x2", 0)), float(a.get("y2", 0)))]]
    if tag == "rect":
        x, y = float(a.get("x", 0)), float(a.get("y", 0))
        w, h = float(a.get("width", 0)), float(a.get("height", 0))
        return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]] if w and h else []
    if tag in {"circle", "ellipse"}:
        cx, cy = float(a.get("cx", 0)), float(a.get("cy", 0))
        rx = float(a.get("r", a.get("rx", 0)))
        ry = float(a.get("r", a.get("ry", 0)))
        if not rx or not ry:
            return []
        count = max(16, curve_steps * 2)
        points = [(cx + rx * math.cos(2 * math.pi * i / count),
                   cy + ry * math.sin(2 * math.pi * i / count)) for i in range(count)]
        points.append(points[0])
        return [points]
    return []


def load_svg(file_name: str | Path, curve_steps: int = 16) -> SvgDrawing:
    root = ET.parse(file_name).getroot()
    paths: list[Polyline] = []

    def walk(element: ET.Element, inherited: Matrix) -> None:
        style = element.get("style", "").replace(" ", "").lower()
        if element.get("display", "").lower() == "none" or "display:none" in style:
            return
        matrix = _multiply(inherited, parse_transform(element.get("transform")))
        for path in _shape_paths(element, curve_steps):
            transformed = [_transform_point(point, matrix) for point in path]
            if not all(math.isfinite(value) for point in transformed for value in point):
                raise ValueError("Coordonnée SVG non finie")
            if len(transformed) >= 2:
                paths.append(transformed)
        for child in element:
            walk(child, matrix)

    walk(root, IDENTITY)
    if not paths:
        raise ValueError("Aucun tracé compatible trouvé dans ce SVG")
    all_points = [point for path in paths for point in path]
    min_x = min(p[0] for p in all_points); max_x = max(p[0] for p in all_points)
    min_y = min(p[1] for p in all_points); max_y = max(p[1] for p in all_points)
    return SvgDrawing(paths, max_x - min_x, max_y - min_y, min_x, min_y)


def resample(path: Polyline, max_step: float) -> Polyline:
    if max_step <= 0 or len(path) < 2:
        return path[:]
    result = [path[0]]
    for p0, p1 in zip(path, path[1:]):
        distance = math.dist(p0, p1)
        count = max(1, math.ceil(distance / max_step))
        if len(result) + count > 5000:
            raise ValueError("Trajectoire trop dense : augmente le pas maximal (5000 points maximum).")
        for i in range(1, count + 1):
            t = i / count
            result.append((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t))
    return result


def transformed_paths(
    drawing: SvgDrawing,
    width_mm: float,
    origin_x: float,
    origin_y: float,
    rotation_deg: float = 0,
    flip_y: bool = True,
    max_step_mm: float = 3,
) -> list[Polyline]:
    if not all(math.isfinite(value) for value in (drawing.width, width_mm, origin_x, origin_y, rotation_deg, max_step_mm)):
        raise ValueError("Paramètre de transformation non fini")
    if max_step_mm <= 0:
        raise ValueError("Le pas maximal doit être positif")
    if drawing.width <= 0 or width_mm <= 0:
        raise ValueError("La largeur du dessin doit être positive")
    scale = width_mm / drawing.width
    angle = math.radians(rotation_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    output: list[Polyline] = []
    for path in drawing.paths:
        converted: Polyline = []
        for x, y in path:
            local_x = (x - drawing.min_x) * scale
            local_y = (y - drawing.min_y) * scale
            if flip_y:
                local_y = drawing.height * scale - local_y
            converted.append((origin_x + local_x * cos_a - local_y * sin_a,
                              origin_y + local_x * sin_a + local_y * cos_a))
        output.append(resample(converted, max_step_mm))
    return output

