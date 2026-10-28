"""One bounded V1 diagnostic step. This is not a workspace calibration."""

import math
import time
from dataclasses import asdict, dataclass

from dobot_protocol import Pose, STARTUP_JOINT_LIMITS, running_pose_issue


REAR_MM = 135.0
FRONT_MM = 160.0
TCP_MM = 55.0  # Nominal controller point inferred from the observed V1 telemetry.
JOINT_MARGIN_DEG = 5.0


@dataclass(frozen=True)
class StepPlan:
    source: Pose
    target: tuple[float, float, float]
    target_joints: tuple[float, float, float]


def forward(j1: float, j2: float, j3: float) -> tuple[float, float, float]:
    base, rear, front = map(math.radians, (j1, j2, j3))
    radius = REAR_MM * math.sin(rear) + FRONT_MM * math.cos(front) + TCP_MM
    return radius * math.cos(base), radius * math.sin(base), REAR_MM * math.cos(rear) - FRONT_MM * math.sin(front)


def finite_pose(pose: Pose) -> bool:
    return all(math.isfinite(getattr(pose, name)) for name in
               ("x", "y", "z", "r", "joint1", "joint2", "joint3", "joint4", "gripper"))


def inverse(x: float, y: float, z: float, reference: Pose) -> tuple[float, float, float]:
    radius = math.hypot(x, y) - TCP_MM
    length = math.hypot(radius, z)
    if length < 1e-9:
        raise ValueError("Cible cinématique singulière.")
    cosine = (REAR_MM ** 2 - FRONT_MM ** 2 + length ** 2) / (2 * REAR_MM * length)
    if not -1 <= cosine <= 1:
        raise ValueError("Cible hors de portée géométrique.")
    solutions = []
    for sign in (-1, 1):
        rear = math.atan2(z, radius) + sign * math.acos(cosine)
        j1 = math.degrees(math.atan2(y, x))
        j2 = 90 - math.degrees(rear)
        j3 = math.degrees(math.atan2(REAR_MM * math.sin(rear) - z, radius - REAR_MM * math.cos(rear)))
        joints = (j1, j2, j3)
        if all(low + JOINT_MARGIN_DEG <= value <= high - JOINT_MARGIN_DEG
               for value, (_, _, low, high) in zip(joints, STARTUP_JOINT_LIMITS[:3])):
            solutions.append(joints)
    if not solutions:
        raise ValueError("Cible refusée : marge articulaire de 5° insuffisante.")
    current = (reference.joint1, reference.joint2, reference.joint3)
    return min(solutions, key=lambda candidate: max(abs(a - b) for a, b in zip(candidate, current)))


def plan_step(pose: Pose) -> StepPlan:
    if not finite_pose(pose):
        raise ValueError("Télémétrie non finie : essai refusé.")
    for _, attr, low, high in STARTUP_JOINT_LIMITS:
        if not low + JOINT_MARGIN_DEG <= getattr(pose, attr) <= high - JOINT_MARGIN_DEG:
            raise ValueError("Pose initiale trop proche d'une limite pour cet essai.")
    radius = math.hypot(pose.x, pose.y)
    if not 151 <= radius <= 310:
        raise ValueError("Essai refusé près de la base ou de l'extension maximale. Le zéro machine n'est pas une cible de test.")
    xyz = (pose.x, pose.y, pose.z)
    if math.dist(forward(pose.joint1, pose.joint2, pose.joint3), xyz) > 0.35:
        raise ValueError("Le point d'outil reçu ne correspond pas au modèle nominal. Aucun mouvement.")
    target = (pose.x * (radius - 1) / radius, pose.y * (radius - 1) / radius, pose.z)
    current = (pose.joint1, pose.joint2, pose.joint3)
    joints = current
    # Check the whole 1 mm Cartesian segment, not just its endpoint.
    for index in range(11):
        fraction = index / 10
        point = tuple(a + (b - a) * fraction for a, b in zip(xyz, target))
        joints = inverse(*point, pose)
        if max(abs(a - b) for a, b in zip(joints, current)) > 1:
            raise ValueError("Essai refusé : variation articulaire supérieure à 1°.")
    return StepPlan(pose, target, joints)


class SingleStepController:
    def __init__(self, connection, clock=time.monotonic, previously_used=False):
        self.connection = connection
        self.clock = clock
        self.active = False
        self.used = previously_used
        self.plan: StepPlan | None = None
        self.phase = ""
        self.started = 0.0
        self.last_checked_packet = -1
        self.final_checks = 0
        self.status = ("Essai déjà enregistré : aucun nouvel essai autorisé. Mouvement physique non confirmé."
                       if previously_used else "Essai non effectué")
        self.report: dict | None = None

    def start(self) -> None:
        if self.used:
            raise ValueError("Cet essai unique a déjà été utilisé. Aucun nouvel essai autorisé.")
        snapshot = self.connection.diagnostic_snapshot()
        pose = self.connection.pose
        if not snapshot["connected"] or pose is None or not 0 <= float(snapshot["packet_age"]) <= 0.5:
            raise ValueError("Mesures absentes ou anciennes : aucun essai.")
        if self.connection.queue_size():
            raise ValueError("Une file de commandes existe déjà : essai refusé.")
        plan = plan_step(pose)
        self.plan = plan
        self.used = self.active = True
        self.phase = "configuration"
        self.started = self.clock()
        self.status = "Préparation lente, outil inchangé, aucune cible envoyée"
        try:
            self.connection.begin_motion()
            self.connection.queue_single_step_configuration()
            self.connection.dispatch_next()
        except (OSError, ConnectionError, ValueError) as exc:
            self.abort(str(exc))

    def tick(self) -> None:
        if not self.active:
            return
        snapshot = self.connection.diagnostic_snapshot()
        pose = self.connection.pose
        if not snapshot["connected"] or pose is None or not 0 <= float(snapshot["packet_age"]) <= 0.5 or not finite_pose(pose):
            self.abort("Télémétrie perdue ou invalide")
            return
        issue = running_pose_issue(pose, float(snapshot["packet_age"]))
        if issue:
            self.abort(issue)
            return
        source = self.plan.source
        distance = math.dist((pose.x, pose.y, pose.z), (source.x, source.y, source.z))
        angle_delta = max(abs(getattr(pose, attr) - getattr(source, attr)) for _, attr, _, _ in STARTUP_JOINT_LIMITS)
        if self.phase == "configuration":
            if distance > 0.2 or angle_delta > 0.2 or abs(pose.r - source.r) > 0.2:
                self.abort("Pose ou référence d'outil modifiée pendant la préparation")
            elif self.clock() - self.started > 3:
                self.abort("Préparation sans réponse dans le délai")
            elif not self.connection.queue_size() and snapshot["reply_after_command"]:
                try:
                    # Revalidate the unchanged source before dispatching exactly one target.
                    plan_step(pose)
                    self.connection.goto(*self.plan.target, r=source.r, tool_on=False, motion=2, gripper=source.gripper)
                    self.phase = "moving"
                    self.started = self.clock()
                    self.connection.dispatch_next()
                    self.status = "Un seul pas de 1 mm envoyé, surveillance active"
                except (OSError, ConnectionError, ValueError) as exc:
                    self.abort(str(exc))
            return
        if distance > 1.6 or angle_delta > 1.5 or abs(pose.z - source.z) > 0.4 or abs(pose.r - source.r) > 0.4:
            self.abort("Déplacement reçu hors de la tolérance de l'essai")
            return
        if self.clock() - self.started > 5:
            self.abort("Cible non renvoyée par le contrôleur dans le délai")
            return
        if snapshot["reply_after_command"] and snapshot["packets"] != self.last_checked_packet:
            self.last_checked_packet = snapshot["packets"]
            at_target = math.dist((pose.x, pose.y, pose.z), self.plan.target) <= 0.15
            self.final_checks = self.final_checks + 1 if at_target else 0
            if self.final_checks >= 3:
                self._finish(True, f"Cible annoncée par le contrôleur ({distance:.2f} mm). Mouvement physique non confirmé.", pose)

    def abort(self, reason: str) -> None:
        self._finish(False, f"Essai arrêté : {reason}", self.connection.pose)

    def _finish(self, telemetry_target_reached: bool, message: str, pose: Pose | None) -> None:
        self.active = False
        self.status = message
        self.connection.emergency_stop(laser_mode=True)
        self.report = {
            "telemetry_target_reached": telemetry_target_reached, "status": message,
            "source": asdict(self.plan.source) if self.plan else None,
            "target": self.plan.target if self.plan else None,
            "received_pose": asdict(pose) if pose is not None and finite_pose(pose) else None,
            "requested_distance_mm": 1,
            "physical_distance_independently_verified": False,
            "workspace_calibrated": False,
        }
