"""Physical measurements for planning a workbench, not motion authorization."""

import math


AXES = ("X", "Y", "Z", "J1", "J2", "J3", "J4")


def measurement(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} : mesure invalide.")
    try:
        number = float(value.replace(",", ".") if isinstance(value, str) else value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} : entre une mesure en mm.") from None
    if not math.isfinite(number) or abs(number) > 1000:
        raise ValueError(f"{name} : mesure finie entre -1000 et 1000 mm requise.")
    return number


def measured_point(x, y) -> tuple[float, float]:
    return measurement(x, "X"), measurement(y, "Y")


def observed_bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    return min(p[0] for p in points), max(p[0] for p in points), min(p[1] for p in points), max(p[1] for p in points)


def validate_mapping_data(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Format de cartographie inconnu.")
    ranges = data.get("joint_ranges", {})
    count = data.get("joint_samples", 0)
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 10000:
        raise ValueError("Nombre de releves invalide.")
    if not isinstance(ranges, dict) or (set(ranges) != set(AXES) if count else bool(ranges)):
        raise ValueError("Releves articulaires incomplets.")
    clean_ranges = {}
    for axis, bounds in ranges.items():
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError("Plage de mesure invalide.")
        low, high = (measurement(v, axis) for v in bounds)
        if low > high:
            raise ValueError("Plage de mesure inversee.")
        clean_ranges[axis] = [low, high]
    plane = data.get("plateau", {})
    if not isinstance(plane, dict):
        raise ValueError("Plateau invalide.")
    points = plane.get("points", [])
    if not isinstance(points, list) or len(points) > 1000:
        raise ValueError("Liste de points invalide.")
    clean_points = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("Point incomplet.")
        clean_points.append(measured_point(*point))
    height = plane.get("height_mm")
    if height is not None:
        height = measurement(height, "Hauteur")
    if clean_points and height is None:
        raise ValueError("Hauteur du plateau manquante.")
    return {"version": 1, "joint_ranges": clean_ranges, "joint_samples": count,
            "plateau": {"height_mm": height, "points": clean_points}}


def telemetry_badge(connected: bool, packet_age: float) -> tuple[str, str]:
    if not connected:
        return "DÉCONNECTÉ", "Disconnected.TLabel"
    if not 0 <= packet_age <= 1.5:
        return "MESURES ANCIENNES", "Waiting.TLabel"
    return "ROBOT CONNECTÉ", "Connected.TLabel"
