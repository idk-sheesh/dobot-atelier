from __future__ import annotations

import argparse
import json
import math
import os
import socket
import subprocess
import sys
import time
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

if os.name == "nt":
    import winreg

from dobot_protocol import (
    DobotConnection,
    Pose,
    STARTUP_JOINT_LIMITS,
    running_pose_issue,
    startup_pose_issue,
)
from svg_parser import SvgDrawing, load_svg, transformed_paths
from workspace_mapping import measured_point, measurement, observed_bounds, telemetry_badge, validate_mapping_data
from single_step import SingleStepController, plan_step
from server_config import default_server_executable, normalize_server_executable


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "1.6.2"
AIR_TEST_MODE = "Déplacement sans outil"
INSTANCE_PORT = 5556
if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "DobotAtelier"
else:
    CONFIG_DIR = APP_DIR
CONFIG_FILE = CONFIG_DIR / "atelier_config.json"
MEASUREMENT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP_DIR
MEASUREMENT_FILE = MEASUREMENT_DIR / "cartographie_mesures.json"


class DobotAtelier(tk.Tk):
    def __init__(self, *, offline: bool = False) -> None:
        super().__init__()
        self.offline = offline
        self.title(f"Dobot Atelier {APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(1060, 700)
        self.configure(bg="#f2f3f5")

        self.connection = DobotConnection(self._pose_from_thread, self._status_from_thread)
        self.single_step = SingleStepController(
            self.connection, previously_used=(MEASUREMENT_DIR / "diagnostic_pas_1mm.json").exists())
        self.pose: Pose | None = None
        self._latest_pose: Pose | None = None
        self._display_pose: tuple[float, float, float, float] | None = None
        self._robot_online = False
        self.drawing: SvgDrawing | None = None
        self.robot_paths: list[list[tuple[float, float]]] = []
        self.loaded_file: Path | None = None
        self.initial_queue_size = 0
        self._run_start_pose: Pose | None = None
        self._run_final_target: tuple[float, float, float] | None = None
        self._run_started_at = 0.0
        self._run_motion_seen = False
        self._run_final_checks = 0
        self._run_last_packet = -1
        self._server_process: subprocess.Popen | None = None
        self._instance_lock: socket.socket | None = None
        self._diagnostic_window: tk.Toplevel | None = None
        self._mapping_window: tk.Toplevel | None = None
        self._mapping_ranges: dict[str, list[float]] = {}
        self._mapping_text: tk.StringVar | None = None
        self._mapping_last_pose: Pose | None = None
        self._mapping_samples = 0
        self._plateau_points: list[tuple[float, float]] = []
        self._plateau_height: float | None = None
        self._plateau_canvas: tk.Canvas | None = None
        self._plateau_summary: tk.StringVar | None = None

        self._make_style()
        self._make_variables()
        self._build_ui()
        self._load_config()
        self._load_mapping()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.offline:
            self.status_var.set("Aperçu hors ligne · aucune connexion au robot")
        else:
            self.after(250, self.connect_robot)
        self.after(50, self._poll_pose)
        self.after(200, self._poll_progress)

    def _make_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f2f3f5")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f2f3f5", foreground="#20242a", font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background="#ffffff", foreground="#20242a", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#f2f3f5", foreground="#111318", font=("Segoe UI Semibold", 18))
        style.configure("Section.TLabel", background="#ffffff", foreground="#111318", font=("Segoe UI Semibold", 11))
        style.configure("Status.TLabel", background="#f2f3f5", foreground="#4d5663", font=("Segoe UI", 9))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("Danger.TButton", font=("Segoe UI Semibold", 10), padding=(12, 8), foreground="#a41414")
        style.configure("Connected.TLabel", background="#16784c", foreground="#ffffff", font=("Segoe UI Semibold", 9), padding=(10, 7))
        style.configure("Waiting.TLabel", background="#b36b00", foreground="#ffffff", font=("Segoe UI Semibold", 9), padding=(10, 7))
        style.configure("Disconnected.TLabel", background="#a52a2a", foreground="#ffffff", font=("Segoe UI Semibold", 9), padding=(10, 7))
        style.configure("Safe.Panel.TLabel", background="#ffffff", foreground="#16784c", font=("Segoe UI Semibold", 9))
        style.configure("Unsafe.Panel.TLabel", background="#ffffff", foreground="#a52a2a", font=("Segoe UI Semibold", 9))
        style.configure("TButton", font=("Segoe UI", 10), padding=(9, 6))
        style.configure("TCheckbutton", background="#ffffff", font=("Segoe UI", 9))
        style.configure("TNotebook", background="#f2f3f5", borderwidth=0)

    def _make_variables(self) -> None:
        self.status_var = tk.StringVar(value="Connexion au serveur...")
        self.connection_var = tk.StringVar(value="CONNEXION...")
        self.pose_var = tk.StringVar(value="X --   Y --   Z --   R --")
        self.startup_var = tk.StringVar(value="INITIALISATION EN ATTENTE")
        self.single_step_var = tk.StringVar(value=self.single_step.status)
        executable_dir = MEASUREMENT_DIR if getattr(sys, "frozen", False) else APP_DIR
        self.server_path_var = tk.StringVar(value=str(default_server_executable(executable_dir)))
        self.file_var = tk.StringVar(value="Aucun fichier chargé")
        self.info_var = tk.StringVar(value="Charge un dessin SVG pour commencer")
        self.run_state_var = tk.StringVar(value="PRÊT")
        self.mode_var = tk.StringVar(value=AIR_TEST_MODE)
        self.width_var = tk.StringVar(value="80")
        self.origin_x_var = tk.StringVar(value="200")
        self.origin_y_var = tk.StringVar(value="-40")
        self.z_work_var = tk.StringVar(value="-175")
        self.z_safe_var = tk.StringVar(value="-160")
        self.rotation_var = tk.StringVar(value="0")
        self.step_var = tk.StringVar(value="3")
        self.velocity_var = tk.IntVar(value=8)
        self.acceleration_var = tk.IntVar(value=8)
        self.flip_y_var = tk.BooleanVar(value=True)
        self.calibrated_var = tk.BooleanVar(value=False)
        self.limit_x_min = tk.StringVar(value="-300")
        self.limit_x_max = tk.StringVar(value="350")
        self.limit_y_min = tk.StringVar(value="-300")
        self.limit_y_max = tk.StringVar(value="300")
        self.limit_z_min = tk.StringVar(value="-250")
        self.limit_z_max = tk.StringVar(value="100")

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(18, 13))
        header.pack(fill="x")
        ttk.Label(header, text="Dobot Atelier", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"v{APP_VERSION}", style="Status.TLabel").pack(side="left", padx=(8, 0), pady=(7, 0))
        ttk.Label(header, textvariable=self.pose_var, style="Status.TLabel").pack(side="left", padx=(28, 0))
        ttk.Button(header, text="Connexion", command=self.connect_robot).pack(side="right", padx=(8, 0))
        ttk.Button(header, text="Diagnostic COM", command=self.open_diagnostics).pack(side="right", padx=(8, 0))
        ttk.Button(header, text="ARRÊT + LASER OFF", style="Danger.TButton", command=self.emergency_stop).pack(side="right")
        self.connection_badge = ttk.Label(header, textvariable=self.connection_var, style="Waiting.TLabel")
        self.connection_badge.pack(side="right", padx=(0, 12))
        self.joints_var = tk.StringVar(value="Angles en attente")
        ttk.Label(self, textvariable=self.joints_var, style="Status.TLabel").pack(anchor="w", padx=18, pady=(0, 5))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 12))

        controls_host = ttk.Frame(body, style="Panel.TFrame", width=365)
        preview = ttk.Frame(body, style="Panel.TFrame", padding=12)
        body.add(controls_host, weight=0)
        body.add(preview, weight=1)
        controls = self._make_scrollable_controls(controls_host)
        self._build_controls(controls)
        self._build_preview(preview)

        footer = ttk.Frame(self, padding=(18, 0, 18, 14))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        self.progress = ttk.Progressbar(footer, mode="determinate", length=260)
        self.progress.pack(side="right")

    def _make_scrollable_controls(self, host: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(host, bg="#ffffff", highlightthickness=0, width=365)
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        controls = ttk.Frame(canvas, style="Panel.TFrame", padding=(16, 14, 12, 22))
        window = canvas.create_window((0, 0), window=controls, anchor="nw")

        def resize_content(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_width(event) -> None:
            canvas.itemconfigure(window, width=event.width)

        def wheel(event) -> None:
            canvas.yview_scroll(int(-event.delta / 120), "units")

        controls.bind("<Configure>", resize_content)
        canvas.bind("<Configure>", resize_width)
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        return controls

    def _build_controls(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="1. Dessin", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        drawing_buttons = ttk.Frame(parent, style="Panel.TFrame")
        drawing_buttons.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Button(drawing_buttons, text="Ouvrir un SVG", style="Accent.TButton", command=self.open_svg).pack(side="left", fill="x", expand=True)
        ttk.Button(drawing_buttons, text="Exemple", command=self.open_example).pack(side="left", padx=(6, 0))
        ttk.Label(parent, textvariable=self.file_var, style="Panel.TLabel", wraplength=320).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(parent, text="2. Outil et dimensions", style="Section.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 8))
        self._combo_row(parent, 4, "Mode", self.mode_var, (AIR_TEST_MODE, "Stylo", "Laser"))
        self._entry_row(parent, 5, "Largeur", self.width_var, "mm")
        self._entry_row(parent, 6, "Rotation", self.rotation_var, "°")
        self._entry_row(parent, 7, "Pas maximal", self.step_var, "mm")
        ttk.Checkbutton(parent, text="Inverser l’axe Y du SVG", variable=self.flip_y_var, command=self.prepare_drawing).grid(row=8, column=0, columnspan=3, sticky="w", pady=(4, 12))

        ttk.Label(parent, text="3. Placement sur l’établi", style="Section.TLabel").grid(row=9, column=0, columnspan=3, sticky="w", pady=(2, 8))
        self._entry_row(parent, 10, "Origine X", self.origin_x_var, "mm")
        self._entry_row(parent, 11, "Origine Y", self.origin_y_var, "mm")
        self._entry_row(parent, 12, "Z travail", self.z_work_var, "mm")
        self._entry_row(parent, 13, "Z dégagé", self.z_safe_var, "mm")
        ttk.Button(parent, text="Prendre la position actuelle", command=self.use_current_pose).grid(row=14, column=0, columnspan=3, sticky="ew", pady=(6, 14))

        ttk.Label(parent, text="4. Mouvement", style="Section.TLabel").grid(row=15, column=0, columnspan=3, sticky="w", pady=(2, 6))
        ttk.Label(parent, text="Vitesse", style="Panel.TLabel").grid(row=16, column=0, sticky="w")
        ttk.Scale(parent, from_=1, to=30, variable=self.velocity_var, orient="horizontal").grid(row=16, column=1, sticky="ew", padx=6)
        ttk.Label(parent, textvariable=self.velocity_var, style="Panel.TLabel", width=3).grid(row=16, column=2)
        ttk.Label(parent, text="Accélération", style="Panel.TLabel").grid(row=17, column=0, sticky="w")
        ttk.Scale(parent, from_=1, to=30, variable=self.acceleration_var, orient="horizontal").grid(row=17, column=1, sticky="ew", padx=6)
        ttk.Label(parent, textvariable=self.acceleration_var, style="Panel.TLabel", width=3).grid(row=17, column=2)

        self.startup_label = ttk.Label(parent, textvariable=self.startup_var, style="Unsafe.Panel.TLabel", wraplength=320)
        self.startup_label.grid(row=18, column=0, columnspan=3, sticky="w", pady=(12, 3))
        ttk.Checkbutton(parent, text="J’ai vérifié l’origine, les hauteurs et la zone", variable=self.calibrated_var).grid(row=19, column=0, columnspan=3, sticky="w", pady=(4, 5))
        ttk.Button(parent, text="Afficher le trajet (sans mouvement)", command=self.prepare_drawing).grid(row=20, column=0, columnspan=3, sticky="ew", pady=(2, 5))
        ttk.Button(parent, text="DÉMARRER LE MOUVEMENT", style="Accent.TButton", command=self.execute).grid(row=21, column=0, columnspan=3, sticky="ew")
        ttk.Button(parent, text="Centrer un essai dans le vide (10 mm)", command=self.center_air_test).grid(row=22, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(parent, text="Cartographie du bras et du plateau", command=self.open_manual_mapping).grid(row=23, column=0, columnspan=3, sticky="ew")

        parent.columnconfigure(1, weight=1)
        for variable in (self.width_var, self.rotation_var, self.step_var, self.origin_x_var,
                         self.origin_y_var, self.z_work_var, self.z_safe_var):
            variable.trace_add("write", lambda *_: self.after_idle(self.prepare_drawing))

    def _entry_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, unit: str) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=variable, width=12).grid(row=row, column=1, sticky="ew", padx=6, pady=2)
        ttk.Label(parent, text=unit, style="Panel.TLabel").grid(row=row, column=2, sticky="w")

    def _combo_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, values: tuple[str, ...]) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=2)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=2)
        combo.bind("<<ComboboxSelected>>", lambda _event: self.prepare_drawing())

    def _build_preview(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Aperçu de la trajectoire", style="Section.TLabel").pack(side="left")
        ttk.Label(top, textvariable=self.info_var, style="Panel.TLabel").pack(side="right")
        ttk.Label(top, textvariable=self.run_state_var, style="Panel.TLabel").pack(side="right", padx=(0, 18))
        self.canvas = tk.Canvas(parent, bg="#fafafa", highlightthickness=1, highlightbackground="#d8dce2")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.draw_preview())

        advanced = ttk.LabelFrame(parent, text="Bornes X/Y/Z (ne prouvent pas l'accessibilité)", padding=8)
        advanced.pack(fill="x", pady=(10, 0))
        for col, (axis, low, high) in enumerate((
            ("X", self.limit_x_min, self.limit_x_max),
            ("Y", self.limit_y_min, self.limit_y_max),
            ("Z", self.limit_z_min, self.limit_z_max),
        )):
            ttk.Label(advanced, text=f"{axis} min").grid(row=0, column=col * 2, padx=(8, 3))
            ttk.Entry(advanced, textvariable=low, width=8).grid(row=0, column=col * 2 + 1)
            ttk.Label(advanced, text=f"{axis} max").grid(row=1, column=col * 2, padx=(8, 3), pady=(4, 0))
            ttk.Entry(advanced, textvariable=high, width=8).grid(row=1, column=col * 2 + 1, pady=(4, 0))

    def connect_robot(self) -> None:
        if self.offline:
            self.status_var.set("Mode hors ligne : aucune connexion autorisée")
            return
        if self._official_client_running():
            self.status_var.set("Ferme DobotClient avant de connecter Dobot Atelier")
            self._set_connection_badge("CONFLIT LOGICIEL", "Disconnected.TLabel")
            messagebox.showwarning(
                "DobotClient encore ouvert",
                "Ferme DobotClient : un seul logiciel doit piloter le serveur Dobot V1.\n\n"
                "Dobot Atelier pourra ensuite utiliser le serveur série.",
            )
            return
        if self.connection.connected:
            snapshot = self.connection.diagnostic_snapshot()
            self._set_connection_badge(*telemetry_badge(True, float(snapshot["packet_age"])))
            self.status_var.set("Serveur connecté. Si les mesures restent anciennes : mains écartées, 12 V puis RESET physique.")
            return
        try:
            self.connection.connect()
            return
        except OSError:
            pass
        server_exe = self._server_executable()
        if server_exe is not None:
            try:
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                self._server_process = subprocess.Popen([str(server_exe)], cwd=str(server_exe.parent), creationflags=flags)
                self.status_var.set("Démarrage du serveur Dobot...")
                self.after(1500, self._retry_connection)
                return
            except OSError as exc:
                self.status_var.set(f"Serveur introuvable : {exc}")
        messagebox.showerror("Connexion", "Impossible de joindre DobotServer sur le port 5555.\nChoisis DobotServer.exe dans Diagnostic COM, puis reconnecte le robot.")
        self._set_connection_badge("DÉCONNECTÉ", "Disconnected.TLabel")

    def _server_executable(self) -> Path | None:
        raw_path = self.server_path_var.get().strip()
        if not raw_path:
            return None
        path = normalize_server_executable(raw_path)
        return path if path.is_file() else None

    def _retry_connection(self) -> None:
        try:
            self.connection.connect()
        except OSError as exc:
            self.status_var.set(f"Connexion impossible : {exc}")
            self._set_connection_badge("DÉCONNECTÉ", "Disconnected.TLabel")
            self._stop_owned_server()

    def _stop_owned_server(self) -> None:
        process, self._server_process = self._server_process, None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    @staticmethod
    def _official_client_running() -> bool:
        if os.name != "nt":
            return False
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["tasklist.exe", "/FI", "IMAGENAME eq DobotClient.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=flags,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return '"dobotclient.exe"' in result.stdout.lower()

    def _pose_from_thread(self, pose: Pose) -> None:
        self._latest_pose = pose

    def _status_from_thread(self, status: str) -> None:
        self.after(0, self._apply_connection_status, status)

    def _apply_connection_status(self, status: str) -> None:
        self.status_var.set(status)
        if status == "Connecté au Dobot":
            self._set_connection_badge("SERVEUR CONNECTÉ", "Waiting.TLabel")
        elif status.startswith("Connexion perdue") or status == "Déconnecté":
            self._robot_online = False
            self._set_connection_badge("DÉCONNECTÉ", "Disconnected.TLabel")

    def _set_connection_badge(self, text: str, style: str) -> None:
        self.connection_var.set(text)
        if hasattr(self, "connection_badge"):
            self.connection_badge.configure(style=style)

    def _poll_pose(self) -> None:
        snapshot = self.connection.diagnostic_snapshot()
        if self.offline:
            self._set_connection_badge("HORS LIGNE", "Waiting.TLabel")
        else:
            self._set_connection_badge(*telemetry_badge(bool(snapshot["connected"]), float(snapshot["packet_age"])))
        latest = self._latest_pose
        if latest is not None:
            self.pose = latest
            if not self._robot_online:
                self._robot_online = True
                self.status_var.set("Robot connecté et coordonnées reçues")
            target = (latest.x, latest.y, latest.z, latest.r)
            if self._display_pose is None:
                self._display_pose = target
            else:
                self._display_pose = tuple(
                    shown + (actual - shown) * 0.5
                    for shown, actual in zip(self._display_pose, target)
                )
            x, y, z, r = self._display_pose
            self.pose_var.set(f"X {x:.1f}   Y {y:.1f}   Z {z:.1f}   R {r:.1f}")
            self.joints_var.set("   ".join(f"{label} {getattr(latest, attr):.1f}°" for label, attr, _, _ in STARTUP_JOINT_LIMITS))
        self._update_startup_status()
        self.after(50, self._poll_pose)

    def _startup_issue(self) -> str | None:
        snapshot = self.connection.diagnostic_snapshot()
        return startup_pose_issue(self.pose, float(snapshot["packet_age"]))

    def _update_startup_status(self) -> None:
        issue = self._startup_issue()
        if issue is None and self.pose is not None:
            self.startup_var.set(f"ANGLES DANS LES PLAGES · J2 {self.pose.joint2:.1f}°")
            self.startup_label.configure(style="Safe.Panel.TLabel")
        else:
            self.startup_var.set(f"MOUVEMENT BLOQUÉ · {issue}")
            self.startup_label.configure(style="Unsafe.Panel.TLabel")

    def _motion_guard(self, parent: tk.Misc | None = None) -> bool:
        if self._official_client_running():
            messagebox.showerror(
                "Conflit de pilotage",
                "DobotClient est ouvert. Ferme-le avant d’envoyer une commande depuis Dobot Atelier.",
                parent=parent,
            )
            return False
        issue = self._startup_issue()
        if issue is None:
            return True
        messagebox.showerror(
            "Initialisation robot requise",
            f"Mouvement interdit : {issue}\n\n"
            "1. Coupe le 12 V et l’USB.\n"
            "2. Vérifie le montage et la fixation des capteurs, sans forcer les axes.\n"
            "3. Suis la procédure d'initialisation du manuel de cette version du robot.\n"
            "Ne cherche pas le zéro machine ou les butées pour corriger une mesure.",
            parent=parent,
        )
        return False

    def open_svg(self) -> None:
        file_name = filedialog.askopenfilename(title="Ouvrir un dessin", filetypes=(("Dessin SVG", "*.svg"), ("Tous les fichiers", "*.*")))
        if not file_name:
            return
        self._load_svg_file(Path(file_name))

    def open_example(self) -> None:
        self.width_var.set("40")
        self._load_svg_file(APP_DIR / "exemple_gabarit.svg")

    def _load_svg_file(self, file_name: Path) -> None:
        try:
            drawing = load_svg(file_name)
        except (OSError, ValueError, ET.ParseError) as exc:
            messagebox.showerror("SVG incompatible", str(exc))
            return
        self.loaded_file = file_name
        self.drawing = drawing
        self.file_var.set(self.loaded_file.name)
        self.prepare_drawing(show_errors=True)

    def prepare_drawing(self, show_errors: bool = False) -> bool:
        if not self.drawing:
            return False
        try:
            self.robot_paths = transformed_paths(
                self.drawing,
                width_mm=self._float(self.width_var, "largeur"),
                origin_x=self._float(self.origin_x_var, "origine X"),
                origin_y=self._float(self.origin_y_var, "origine Y"),
                rotation_deg=self._float(self.rotation_var, "rotation"),
                flip_y=self.flip_y_var.get(),
                max_step_mm=self._float(self.step_var, "pas maximal"),
            )
            count = sum(len(path) for path in self.robot_paths)
            points = [p for path in self.robot_paths for p in path]
            width = max(p[0] for p in points) - min(p[0] for p in points)
            height = max(p[1] for p in points) - min(p[1] for p in points)
            self.info_var.set(f"{len(self.robot_paths)} tracés · {count} points · {width:.1f} × {height:.1f} mm")
            max_radius = max(math.hypot(x, y) for x, y in points)
            if max_radius > 300:
                self.info_var.set(self.info_var.get() + " · portée à vérifier")
            self.draw_preview()
            return True
        except (ValueError, tk.TclError) as exc:
            self.robot_paths = []
            self.info_var.set("Paramètres à corriger")
            if show_errors:
                messagebox.showerror("Paramètres", str(exc))
            return False

    @staticmethod
    def _float(variable: tk.StringVar, name: str) -> float:
        try:
            value = float(variable.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"Valeur incorrecte pour {name}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Valeur incorrecte pour {name}")
        return value

    def draw_preview(self) -> None:
        self.canvas.delete("all")
        if not self.robot_paths:
            w, h = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
            self.canvas.create_text(w / 2, h / 2, text="Aucun tracé", fill="#737b87", font=("Segoe UI", 14))
            return
        points = [p for path in self.robot_paths for p in path]
        min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
        min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
        w, h, margin = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height()), 28
        scale = min((w - 2 * margin) / max(1, max_x - min_x), (h - 2 * margin) / max(1, max_y - min_y))

        def screen(p: tuple[float, float]) -> tuple[float, float]:
            return margin + (p[0] - min_x) * scale, h - margin - (p[1] - min_y) * scale

        previous: tuple[float, float] | None = None
        for path in self.robot_paths:
            first = screen(path[0])
            if previous:
                self.canvas.create_line(*previous, *first, fill="#b8bec7", dash=(4, 5), width=1)
            coords = [value for point in path for value in screen(point)]
            self.canvas.create_line(*coords, fill="#20242a", width=2, capstyle="round", joinstyle="round")
            previous = screen(path[-1])
        start = screen(self.robot_paths[0][0])
        self.canvas.create_oval(start[0] - 5, start[1] - 5, start[0] + 5, start[1] + 5, fill="#16845b", outline="")
        self.canvas.create_text(start[0] + 10, start[1] - 10, text="Départ", fill="#16845b", anchor="sw", font=("Segoe UI", 9))

    def use_current_pose(self) -> None:
        if not self.pose:
            messagebox.showwarning("Position", "Aucune position reçue du robot")
            return
        self.origin_x_var.set(f"{self.pose.x:.2f}")
        self.origin_y_var.set(f"{self.pose.y:.2f}")
        self.z_work_var.set(f"{self.pose.z:.2f}")
        self.z_safe_var.set(f"{self.pose.z + (0 if self.mode_var.get() == AIR_TEST_MODE else 15):.2f}")
        self.calibrated_var.set(False)
        self.status_var.set("Origine prise. Vérifie et valide les deux hauteurs Z.")

    @staticmethod
    def _mapping_axes() -> tuple[tuple[str, str], ...]:
        return (
            ("X", "x"), ("Y", "y"), ("Z", "z"),
            ("J1", "joint1"), ("J2", "joint2"),
            ("J3", "joint3"), ("J4", "joint4"),
        )

    def open_manual_mapping(self) -> None:
        if self._mapping_window is not None and self._mapping_window.winfo_exists():
            self._mapping_window.lift()
            return
        self.emergency_stop()
        if not self._mapping_ranges:
            self._mapping_last_pose = None
        window = tk.Toplevel(self)
        window.title(f"Mesures du bras et du plateau - Dobot Atelier {APP_VERSION}")
        window.geometry("840x740")
        window.minsize(740, 640)
        window.transient(self)
        self._mapping_window = window
        self._mapping_text = tk.StringVar(value="Aucune position enregistrée")
        tabs = ttk.Notebook(window)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        plane_frame = ttk.Frame(tabs, padding=14)
        frame = ttk.Frame(tabs, padding=14)
        tabs.add(plane_frame, text="Plateau mesuré")
        tabs.add(frame, text="Relevés J2 / J3")
        self._build_plateau_mapping(plane_frame)
        ttk.Label(
            frame,
            text=(
                "1. Débranche le 12 V et place doucement le bras à la main.\n"
                "2. Écarte les mains, rebranche le 12 V puis appuie brièvement sur RESET du boîtier.\n"
                "3. Attends 5 secondes et vérifie que J2/J3 correspondent à la nouvelle pose.\n"
                "4. Enregistre, puis débranche de nouveau le 12 V avant de déplacer.\n\n"
                "Garde la base dans la même orientation pour ces relevés J2/J3.\n"
                "Approche les extrêmes sans appuyer sur les butées."
            ),
            wraplength=560,
        ).pack(anchor="w")
        ttk.Label(frame, textvariable=self.pose_var, font=("Consolas", 10)).pack(anchor="w", pady=(12, 0))
        ttk.Label(frame, textvariable=self.joints_var, font=("Consolas", 10)).pack(anchor="w")
        ttk.Label(frame, textvariable=self._mapping_text, font=("Consolas", 10), justify="left").pack(anchor="w", pady=8)
        self._update_mapping_text()
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Enregistrer la position après RESET", command=self.record_manual_position).pack(side="left")
        ttk.Button(buttons, text="Réinitialiser", command=self.reset_manual_mapping).pack(side="left")
        ttk.Label(frame, text="Relevés uniquement : les extrêmes ne définissent pas une zone sûre.", wraplength=650).pack(anchor="w", pady=(12, 0))
        window.protocol("WM_DELETE_WINDOW", self._close_manual_mapping)

    def record_manual_position(self) -> None:
        snapshot = self.connection.diagnostic_snapshot()
        packet_age = float(snapshot["packet_age"])
        if self.pose is None or not snapshot["connected"] or not 0 <= packet_age <= 1.5:
            messagebox.showerror(
                "Télémétrie absente",
                "Écarte les mains, branche le 12 V, appuie brièvement sur RESET du boîtier puis attends les coordonnées avant d'enregistrer.",
                parent=self._mapping_window,
            )
            return
        if not all(math.isfinite(float(getattr(self.pose, attribute))) for _label, attribute in self._mapping_axes()):
            messagebox.showerror("Télémétrie invalide", "Les coordonnées reçues ne permettent pas un relevé fiable.", parent=self._mapping_window)
            return
        if self._mapping_last_pose is not None:
            delta = max(
                abs(float(getattr(self.pose, attribute)) - float(getattr(self._mapping_last_pose, attribute)))
                for _label, attribute in self._mapping_axes()
            )
            if delta < 0.05:
                self.status_var.set("Position identique. Après un déplacement manuel, remets le 12 V puis appuie sur RESET du boîtier.")
                return
        self.connection.emergency_stop(laser_mode=True)
        self._mapping_samples += 1
        self._record_mapping_pose(self.pose)
        self._mapping_last_pose = self.pose
        if self._save_mapping():
            self.status_var.set(f"Position {self._mapping_samples} sauvegardée. Débranche le 12 V avant de déplacer le bras.")

    def reset_manual_mapping(self) -> None:
        self._mapping_ranges.clear()
        self._mapping_last_pose = None
        self._mapping_samples = 0
        self._update_mapping_text()
        self._save_mapping()

    def _record_mapping_pose(self, pose: Pose) -> None:
        for label, attribute in self._mapping_axes():
            value = float(getattr(pose, attribute))
            bounds = self._mapping_ranges.setdefault(label, [value, value])
            bounds[0] = min(bounds[0], value)
            bounds[1] = max(bounds[1], value)
        self._update_mapping_text()

    def _update_mapping_text(self) -> None:
        if self._mapping_text is not None:
            if not self._mapping_ranges:
                self._mapping_text.set("Aucune position enregistrée")
                return
            lines = [f"Positions : {self._mapping_samples}", ""]
            for label, _attribute in self._mapping_axes():
                low, high = self._mapping_ranges[label]
                unit = "mm" if label in {"X", "Y", "Z"} else "°"
                lines.append(f"{label:>2}  {low:8.1f}  à  {high:8.1f} {unit}")
            self._mapping_text.set("\n".join(lines))

    def apply_manual_mapping(self) -> None:
        messagebox.showinfo("Relevés seulement", "Des extrêmes X/Y/Z ne prouvent pas que les points intermédiaires sont accessibles. Aucune limite de mouvement n'a été modifiée.", parent=self._mapping_window)

    def _build_plateau_mapping(self, frame: ttk.Frame) -> None:
        ttk.Label(frame, text=(
            "12 V et laser débranchés. Base immobilisée, bras soutenu à la main.\n"
            "Sur une feuille quadrillée, marque l'origine sous l'axe de la base : X vers l'avant, Y vers la gauche.\n"
            "À hauteur fixe, relève à la règle les positions confortablement accessibles d'un même repère de l'outil.\n"
            "N'appuie pas sur les butées. Cette carte ne valide aucune trajectoire motorisée."
        ), wraplength=760).pack(anchor="w", pady=(0, 12))
        inputs = ttk.Frame(frame)
        inputs.pack(fill="x")
        self._plateau_height_var = tk.StringVar(value="" if self._plateau_height is None else f"{self._plateau_height:g}")
        self._plateau_x_var = tk.StringVar()
        self._plateau_y_var = tk.StringVar()
        ttk.Label(inputs, text="Hauteur du plateau / dessus du socle (mm)").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._plateau_height_entry = ttk.Entry(inputs, textvariable=self._plateau_height_var, width=10)
        self._plateau_height_entry.grid(row=0, column=1, sticky="w")
        ttk.Label(inputs, text="X mesuré (mm)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(inputs, textvariable=self._plateau_x_var, width=10).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(inputs, text="Y mesuré (mm)").grid(row=1, column=2, padx=(18, 8), pady=(8, 0))
        ttk.Entry(inputs, textvariable=self._plateau_y_var, width=10).grid(row=1, column=3, pady=(8, 0))
        ttk.Button(inputs, text="Ajouter le point", command=self.record_measured_point).grid(row=1, column=4, padx=(12, 0), pady=(8, 0))
        self._plateau_summary = tk.StringVar()
        ttk.Label(frame, textvariable=self._plateau_summary, wraplength=760).pack(anchor="w", pady=(12, 8))
        self._plateau_canvas = tk.Canvas(frame, bg="#fafafa", highlightthickness=1, highlightbackground="#d8dce2")
        self._plateau_canvas.pack(fill="both", expand=True)
        self._plateau_canvas.bind("<Configure>", lambda _event: self._draw_plateau())
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Retirer le dernier point", command=self.undo_measured_point).pack(side="left")
        ttk.Button(buttons, text="Nouveau plateau / hauteur", command=self.reset_measured_plane).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="Points mesurés seulement. Le rectangle englobant et les espaces entre points ne sont pas validés.", wraplength=760).pack(anchor="w", pady=(8, 0))
        self._update_plateau()

    def record_measured_point(self) -> None:
        try:
            point = measured_point(self._plateau_x_var.get(), self._plateau_y_var.get())
            height = measurement(self._plateau_height_var.get(), "Hauteur")
            if self._plateau_height is not None and height != self._plateau_height:
                raise ValueError("Crée un nouveau plateau pour changer de hauteur.")
            if len(self._plateau_points) >= 1000:
                raise ValueError("1000 points maximum par plateau.")
            if any(math.dist(point, previous) < 0.05 for previous in self._plateau_points):
                raise ValueError("Ce point est déjà enregistré.")
        except ValueError as exc:
            messagebox.showerror("Mesure du plateau", str(exc), parent=self._mapping_window)
            return
        self._plateau_height = height
        self._plateau_points.append(point)
        self._update_plateau()
        if self._save_mapping():
            self.status_var.set(f"Point mesuré {len(self._plateau_points)} sauvegardé. Aucun mouvement envoyé.")

    def undo_measured_point(self) -> None:
        if self._plateau_points:
            self._plateau_points.pop()
            if not self._plateau_points:
                self._plateau_height = None
            self._update_plateau()
            self._save_mapping()

    def reset_measured_plane(self) -> None:
        if self._plateau_points and not messagebox.askyesno("Nouveau plateau", "Les points actuels seront archivés avant de commencer un plateau à une autre hauteur.", parent=self._mapping_window):
            return
        if self._plateau_points:
            archive = MEASUREMENT_DIR / f"cartographie_archive_{time.time_ns()}.json"
            if not self._save_mapping(archive):
                return
        self._plateau_points.clear()
        self._plateau_height = None
        self._plateau_height_var.set("")
        self._update_plateau()
        self._save_mapping()

    def _update_plateau(self) -> None:
        if self._plateau_summary is None:
            return
        bounds = observed_bounds(self._plateau_points)
        if bounds is None:
            self._plateau_summary.set("Aucun point mesuré. Commence au centre confortable du plateau.")
        else:
            xmin, xmax, ymin, ymax = bounds
            self._plateau_summary.set(f"{len(self._plateau_points)} points · hauteur {self._plateau_height:g} mm · étendue observée {xmax - xmin:.1f} × {ymax - ymin:.1f} mm\nX {xmin:.1f} à {xmax:.1f} · Y {ymin:.1f} à {ymax:.1f} mm (pas une surface validée)")
        self._plateau_height_entry.configure(state="readonly" if self._plateau_points else "normal")
        self._draw_plateau()

    def _draw_plateau(self) -> None:
        canvas = self._plateau_canvas
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 100 or height < 100:
            return
        if not self._plateau_points:
            canvas.create_text(width / 2, height / 2, text="Aucun point mesuré", fill="#626a73")
            return
        extent = max(50, max(abs(value) for point in self._plateau_points for value in point) + 25)
        scale = min(width - 80, height - 80) / (2 * extent)
        cx, cy = width / 2, height / 2
        canvas.create_line(35, cy, width - 35, cy, fill="#a2a9b2")
        canvas.create_line(cx, height - 35, cx, 35, fill="#a2a9b2")
        canvas.create_text(width - 28, cy + 14, text="+X")
        canvas.create_text(cx + 18, 24, text="+Y")
        canvas.create_text(cx - 10, cy + 14, text="0")
        bar = max(10, 10 * math.floor(extent / 50))
        canvas.create_line(35, height - 22, 35 + bar * scale, height - 22, width=2)
        canvas.create_text(35, height - 36, text=f"{bar} mm", anchor="w")
        for index, (x, y) in enumerate(self._plateau_points, 1):
            px, py = cx + x * scale, cy - y * scale
            canvas.create_oval(px - 4, py - 4, px + 4, py + 4, fill="#16784c", outline="")
            canvas.create_text(px + 7, py - 8, text=str(index), anchor="w", fill="#20242a")

    def _save_mapping(self, destination: Path | None = None) -> bool:
        destination = destination or MEASUREMENT_FILE
        data = {"version": 1, "joint_ranges": self._mapping_ranges, "joint_samples": self._mapping_samples,
                "plateau": {"height_mm": self._plateau_height, "points": self._plateau_points}}
        try:
            data = validate_mapping_data(data)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            temporary.replace(destination)
        except (OSError, ValueError) as exc:
            self.status_var.set(f"Mesures en mémoire, sauvegarde impossible : {exc}")
            return False
        return True

    def _load_mapping(self) -> None:
        if not MEASUREMENT_FILE.exists():
            return
        try:
            if MEASUREMENT_FILE.stat().st_size > 1024 * 1024:
                raise ValueError("Fichier de mesures trop volumineux.")
            data = validate_mapping_data(json.loads(MEASUREMENT_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            self.status_var.set(f"Cartographie non chargée : {exc}")
            return
        self._mapping_ranges = data["joint_ranges"]
        self._mapping_samples = data["joint_samples"]
        self._plateau_height = data["plateau"]["height_mm"]
        self._plateau_points = data["plateau"]["points"]

    def _close_manual_mapping(self) -> None:
        if self._mapping_window is not None:
            self._mapping_window.destroy()
        self._mapping_window = None
        self._plateau_canvas = None
        self._plateau_summary = None

    def center_air_test(self) -> None:
        if self.initial_queue_size:
            return
        if not self._motion_guard():
            return
        if self.drawing is None:
            self.open_example()
        if self.drawing is None or self.pose is None:
            return
        self.mode_var.set(AIR_TEST_MODE)
        self.width_var.set("10")
        self.rotation_var.set("0")
        self.step_var.set("1")
        self.origin_x_var.set(f"{self.pose.x - 5:.2f}")
        self.origin_y_var.set(f"{self.pose.y - 5 * self.drawing.height / self.drawing.width:.2f}")
        self.z_work_var.set(f"{self.pose.z:.2f}")
        self.z_safe_var.set(f"{self.pose.z:.2f}")
        self.velocity_var.set(8)
        self.acceleration_var.set(8)
        self.calibrated_var.set(False)
        self.prepare_drawing()
        self.status_var.set("Essai centré : 10 mm, hauteur actuelle, sans saut. Vérifie la zone.")

    def _validate_limits(self, z_values: tuple[float, ...]) -> tuple[float, float, float, float, float, float]:
        limits = (
            self._float(self.limit_x_min, "X min"), self._float(self.limit_x_max, "X max"),
            self._float(self.limit_y_min, "Y min"), self._float(self.limit_y_max, "Y max"),
            self._float(self.limit_z_min, "Z min"), self._float(self.limit_z_max, "Z max"),
        )
        xmin, xmax, ymin, ymax, zmin, zmax = limits
        if xmin >= xmax or ymin >= ymax or zmin >= zmax:
            raise ValueError("Les limites min doivent être inférieures aux limites max")
        for path in self.robot_paths:
            for x, y in path:
                if not xmin <= x <= xmax or not ymin <= y <= ymax:
                    raise ValueError(f"Point hors limites : X={x:.1f}, Y={y:.1f}")
        for z in z_values:
            if not zmin <= z <= zmax:
                raise ValueError(f"Hauteur Z hors limites : {z:.1f}")
        return limits

    def execute(self) -> None:
        if self.initial_queue_size or self.single_step.active:
            return
        if not self.connection.connected:
            messagebox.showerror("Dobot", "Le robot n’est pas connecté")
            return
        if not self._motion_guard():
            return
        if not self.calibrated_var.get():
            messagebox.showwarning("Calibration requise", "Coche la validation après avoir vérifié l’origine, les hauteurs et la zone.")
            return
        if not self.prepare_drawing(show_errors=True):
            return
        try:
            z_work = self._float(self.z_work_var, "Z travail")
            z_safe = self._float(self.z_safe_var, "Z dégagé")
            self._validate_limits((z_work, z_safe))
            if self.mode_var.get() == AIR_TEST_MODE:
                validate_air_test(self.pose, self.robot_paths, z_safe)
        except ValueError as exc:
            messagebox.showerror("Limites de sécurité", str(exc))
            return
        count = sum(len(path) for path in self.robot_paths)
        if count > 5000:
            messagebox.showerror("Trajectoire trop dense", f"Le dessin contient {count} points. Augmente le pas maximal pour rester sous 5000.")
            return
        mode = self.mode_var.get()
        if mode not in {AIR_TEST_MODE, "Stylo", "Laser"}:
            messagebox.showerror("Mode inconnu", "Choisis un mode dans la liste. Aucune commande envoyée.")
            return
        warning = (
            f"Mode : {mode}\nTracés : {len(self.robot_paths)}\nPoints : {count}\n"
            f"Vitesse : {self.velocity_var.get()} %\nZ travail : {z_work:.1f}\nZ dégagé : {z_safe:.1f}\n\n"
            "Le trajet doit être libre et l’arrêt doit rester accessible."
        )
        if mode == "Laser":
            warning += "\n\nLe laser va s’allumer pendant les traits. Protection et enceinte obligatoires."
        if not messagebox.askokcancel("Confirmer un passage", warning, icon="warning"):
            return
        try:
            self.connection.begin_motion()
            self.connection.queue_playback_configuration(
                self.velocity_var.get(),
                self.acceleration_var.get(),
                end_type=None if mode == AIR_TEST_MODE else 2 if mode == "Laser" else 0,
                laser_mode=mode in {"Laser", AIR_TEST_MODE},
            )
            if mode == "Laser":
                self._queue_laser(z_work)
            elif mode == "Stylo":
                self._queue_pen(z_work, z_safe)
            else:
                self._queue_simulation(z_safe)
            self.initial_queue_size = self.connection.queue_size()
            self.progress.configure(maximum=max(1, self.initial_queue_size), value=0)
            last_x, last_y = self.robot_paths[-1][-1]
            self._run_final_target = (last_x, last_y, z_work if mode == "Laser" else z_safe)
            self._run_start_pose = self.pose
            self._run_started_at = time.monotonic()
            self._run_motion_seen = False
            self._run_final_checks = 0
            self._run_last_packet = -1
            self.connection.dispatch_next()
            self.run_state_var.set("ATTENTE MOUVEMENT")
            self.status_var.set("Initialisation Playback puis envoi de la trajectoire")
        except (ConnectionError, ValueError) as exc:
            messagebox.showerror("Envoi impossible", str(exc))

    def _queue_simulation(self, z_safe: float) -> None:
        for path in self.robot_paths:
            self.connection.goto(*path[0], z_safe, r=self.pose.r, tool_on=False, motion=2)
            for x, y in path[1:]:
                self.connection.goto(x, y, z_safe, r=self.pose.r, tool_on=False, motion=2)
        self.connection.tool(False, laser=True)

    def _queue_pen(self, z_work: float, z_safe: float) -> None:
        for path in self.robot_paths:
            x0, y0 = path[0]
            self.connection.goto(x0, y0, z_safe, tool_on=False, motion=0)
            self.connection.goto(x0, y0, z_work, tool_on=False, motion=2)
            for x, y in path[1:]:
                self.connection.goto(x, y, z_work, tool_on=False, motion=2)
            x1, y1 = path[-1]
            self.connection.goto(x1, y1, z_safe, tool_on=False, motion=2)

    def _queue_laser(self, z_work: float) -> None:
        for path in self.robot_paths:
            x0, y0 = path[0]
            self.connection.goto(x0, y0, z_work, tool_on=False, motion=0)
            self.connection.goto(x0, y0, z_work, tool_on=True, motion=2)
            for x, y in path[1:]:
                self.connection.goto(x, y, z_work, tool_on=True, motion=2)
            x1, y1 = path[-1]
            self.connection.goto(x1, y1, z_work, tool_on=False, motion=2)
        self.connection.tool(False, laser=True)

    def emergency_stop(self) -> None:
        if self.single_step.active:
            self.single_step.abort("Arrêt demandé")
            self.single_step_var.set(self.single_step.status)
        else:
            self.connection.emergency_stop(laser_mode=True)
        self.initial_queue_size = 0
        self._run_start_pose = None
        self._run_final_target = None
        self.progress.configure(value=0)
        self.run_state_var.set("ARRÊTÉ")
        self.status_var.set("ARRÊT demandé, file vidée, laser coupé")

    def _poll_progress(self) -> None:
        if self.single_step.active:
            try:
                self.single_step.tick()
            except Exception as exc:
                self.single_step.abort(f"Erreur de surveillance : {exc}")
            self.single_step_var.set(self.single_step.status)
            self.status_var.set(self.single_step.status)
            if not self.single_step.active:
                self.run_state_var.set("PHYSIQUE NON CONFIRMÉ" if self.single_step.report["telemetry_target_reached"] else "ESSAI ARRÊTÉ")
                try:
                    report = MEASUREMENT_DIR / "diagnostic_pas_1mm.json"
                    report.write_text(json.dumps(self.single_step.report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                except (OSError, ValueError):
                    self.status_var.set(self.single_step.status + " · rapport non sauvegardé")
        if self.initial_queue_size:
            snapshot = self.connection.diagnostic_snapshot()
            issue = running_pose_issue(self.pose, float(snapshot["packet_age"]))
            if issue is not None:
                self.emergency_stop()
                messagebox.showerror("Arrêt de sécurité", f"Trajectoire arrêtée : {issue}")
                self.after(200, self._poll_progress)
                return
            remaining = self.connection.queue_size()
            done = max(0, self.initial_queue_size - remaining)
            self.progress.configure(value=done)
            if self.pose is not None and self._run_start_pose is not None:
                start = self._run_start_pose
                cartesian_delta = math.dist(
                    (self.pose.x, self.pose.y, self.pose.z),
                    (start.x, start.y, start.z),
                )
                joint_delta = max(
                    abs(self.pose.joint1 - start.joint1),
                    abs(self.pose.joint2 - start.joint2),
                    abs(self.pose.joint3 - start.joint3),
                    abs(self.pose.joint4 - start.joint4),
                )
                if cartesian_delta > 0.5 or joint_delta > 0.2:
                    self._run_motion_seen = True
                    self.run_state_var.set("EN COURS")
            elapsed = time.monotonic() - self._run_started_at
            if not self._run_motion_seen and elapsed > 3.5:
                self.emergency_stop()
                messagebox.showerror(
                    "Aucune évolution de télémétrie",
                    "Le contrôleur ne renvoie pas d'évolution de position. La trajectoire a été arrêtée.\n\n"
                    "Cela ne permet pas de conclure à l'état physique des moteurs. Ouvre Diagnostic COM.",
                )
            elif remaining:
                self.status_var.set(f"Exécution : {remaining} commandes restent à transmettre")
            elif self._run_motion_seen and self._run_final_target is not None and self.pose is not None:
                distance = math.dist((self.pose.x, self.pose.y, self.pose.z), self._run_final_target)
                if snapshot["packets"] != self._run_last_packet:
                    self._run_last_packet = snapshot["packets"]
                    self._run_final_checks = self._run_final_checks + 1 if distance < 2.0 else 0
                if self._run_final_checks >= 3:
                    self.status_var.set("Cible finale annoncée par le contrôleur. Mouvement physique non confirmé.")
                    self.run_state_var.set("RETOUR CONTRÔLEUR REÇU")
                    self.initial_queue_size = 0
                    self._run_start_pose = None
                    self._run_final_target = None
                else:
                    self.status_var.set(f"Commandes transmises · écart logiciel à la cible : {distance:.1f} mm")
        self.after(200, self._poll_progress)

    @staticmethod
    def _detected_com_ports() -> list[str]:
        if os.name != "nt":
            return []
        ports: set[str] = set()
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
                index = 0
                while True:
                    try:
                        _name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    ports.add(str(value))
                    index += 1
        except OSError:
            pass
        return sorted(ports)

    def open_diagnostics(self) -> None:
        if self._diagnostic_window is not None and self._diagnostic_window.winfo_exists():
            self._diagnostic_window.lift()
            return
        window = tk.Toplevel(self)
        window.title(f"Diagnostic COM - Dobot Atelier {APP_VERSION}")
        window.resizable(False, False)
        window.transient(self)
        window.geometry(f"+{max(0, self.winfo_rootx() + 60)}+{max(0, self.winfo_rooty() + 60)}")
        self._diagnostic_window = window
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        self._diag_ports = tk.StringVar()
        self._diag_server = tk.StringVar()
        self._diag_telemetry = tk.StringVar()
        self._diag_commands = tk.StringVar()
        self._diag_queue = tk.StringVar()
        self._diag_ack = tk.StringVar()
        rows = (
            ("Ports détectés", self._diag_ports),
            ("Serveur 127.0.0.1:5555", self._diag_server),
            ("Télémétrie robot", self._diag_telemetry),
            ("Commandes envoyées", self._diag_commands),
            ("File restante", self._diag_queue),
            ("Réponse après commande", self._diag_ack),
        )
        for row, (label, variable) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 24), pady=4)
            ttk.Label(frame, textvariable=variable, font=("Segoe UI Semibold", 10)).grid(row=row, column=1, sticky="w", pady=4)
        server_frame = ttk.Frame(frame)
        server_frame.grid(row=len(rows) + 5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(server_frame, text="DobotServer.exe").pack(anchor="w")
        ttk.Entry(server_frame, textvariable=self.server_path_var, width=58).pack(fill="x", pady=4)
        ttk.Button(server_frame, text="Choisir DobotServer.exe...", command=self._choose_server_executable).pack(fill="x")
        ttk.Button(frame, text="Tester la communication (sans mouvement)", command=self._probe_com).grid(row=len(rows), column=0, columnspan=2, sticky="ew", pady=(14, 5))
        ttk.Button(frame, text="Reconnecter", command=self.connect_robot).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            frame,
            text="JOG continu désactivé. Essai ci-dessous : une seule cible à 1 mm, pas un retour au zéro machine.",
            foreground="#a52a2a",
            wraplength=430,
        ).grid(row=len(rows) + 2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(frame, text="Essai unique : 1 mm vers la base", command=self.run_single_step,
                   state="disabled" if self.single_step.used else "normal").grid(row=len(rows) + 3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(frame, textvariable=self.single_step_var, wraplength=430).grid(row=len(rows) + 4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        window.protocol("WM_DELETE_WINDOW", self._close_diagnostics)
        self._update_diagnostics()

    def _choose_server_executable(self) -> None:
        current = normalize_server_executable(self.server_path_var.get())
        file_name = filedialog.askopenfilename(
            title="Choisir DobotServer.exe",
            initialdir=current.parent if current.parent.is_dir() else Path.home(),
            filetypes=(("DobotServer", "DobotServer.exe"), ("Exécutable Windows", "*.exe")),
            parent=self._diagnostic_window,
        )
        if file_name:
            self.server_path_var.set(file_name)
            self._save_config()
            self.status_var.set("Chemin DobotServer enregistré. Clique sur Reconnecter.")

    def run_single_step(self) -> None:
        if self.initial_queue_size or self.single_step.active:
            return
        try:
            if self._official_client_running():
                raise ValueError("Ferme DobotClient avant cet essai.")
            if self.single_step.used:
                raise ValueError("L'essai unique a déjà été utilisé. Aucun nouvel essai autorisé.")
            snapshot = self.connection.diagnostic_snapshot()
            if not snapshot["connected"] or self.connection.pose is None or not 0 <= float(snapshot["packet_age"]) <= 0.5:
                raise ValueError("Mesures absentes ou anciennes : aucun mouvement.")
            plan = plan_step(self.connection.pose)
        except ValueError as exc:
            messagebox.showerror("Essai refusé", str(exc), parent=self._diagnostic_window)
            return
        x, y, z = plan.target
        if not messagebox.askokcancel("Confirmer UN seul pas de 1 mm", (
            f"Cible : X {x:.2f} · Y {y:.2f} · Z {z:.2f} mm\n"
            "Un seul millimètre vers la base, à hauteur constante. Aucun trajet jusqu'à 0,0.\n\n"
            "Base fixée, laser débranché, 12 V branché, zone libre et mains écartées.\n"
            "Le point d'outil actuel sera conservé. L'essai ne valide pas une calibration physique."
        ), parent=self._diagnostic_window):
            return
        try:
            report = MEASUREMENT_DIR / "diagnostic_pas_1mm.json"
            report.write_text(json.dumps({"test_started": True, "app_version": APP_VERSION,
                                          "physical_distance_independently_verified": False}), encoding="utf-8")
            self.single_step.start()
            self.single_step_var.set(self.single_step.status)
            self.run_state_var.set("ESSAI 1 MM")
        except (OSError, ConnectionError, ValueError) as exc:
            messagebox.showerror("Essai refusé", str(exc), parent=self._diagnostic_window)

    def _close_diagnostics(self) -> None:
        if self._diagnostic_window is not None:
            self._diagnostic_window.destroy()
        self._diagnostic_window = None

    def _update_diagnostics(self) -> None:
        if self._diagnostic_window is None or not self._diagnostic_window.winfo_exists():
            return
        snapshot = self.connection.diagnostic_snapshot()
        ports = self._detected_com_ports()
        self._diag_ports.set(", ".join(ports) if ports else "Aucun")
        self._diag_server.set("CONNECTÉ" if snapshot["connected"] else "DÉCONNECTÉ")
        age = float(snapshot["packet_age"])
        self._diag_telemetry.set(f"OUI · {snapshot['packets']} trames · dernière il y a {age:.1f} s" if age >= 0 else "NON")
        self._diag_commands.set(str(snapshot["commands"]))
        self._diag_queue.set(str(snapshot["queue"]))
        self._diag_ack.set("OUI" if snapshot["reply_after_command"] else "EN ATTENTE")
        self._diagnostic_window.after(300, self._update_diagnostics)

    def _probe_com(self) -> None:
        if not self.connection.connected:
            messagebox.showerror("Diagnostic COM", "Le serveur n’est pas connecté", parent=self._diagnostic_window)
            return
        before = self.connection.probe()

        def result() -> None:
            received = self.connection.packets_received > before
            messagebox.showinfo(
                "Diagnostic COM",
                "COM et télémétrie répondent correctement." if received else "Aucune nouvelle télémétrie. Vérifie le serveur et le port série détecté.",
                parent=self._diagnostic_window,
            )

        self.after(1200, result)

    def _load_config(self) -> None:
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        if data.get("mode") == "Simulation":
            data["mode"] = AIR_TEST_MODE
        mapping = {
            "server_path": self.server_path_var,
            "mode": self.mode_var, "width": self.width_var, "origin_x": self.origin_x_var,
            "origin_y": self.origin_y_var, "z_work": self.z_work_var, "z_safe": self.z_safe_var,
            "rotation": self.rotation_var, "step": self.step_var, "flip_y": self.flip_y_var,
            "velocity": self.velocity_var, "acceleration": self.acceleration_var,
            "xmin": self.limit_x_min, "xmax": self.limit_x_max, "ymin": self.limit_y_min,
            "ymax": self.limit_y_max, "zmin": self.limit_z_min, "zmax": self.limit_z_max,
        }
        for key, variable in mapping.items():
            if key in data:
                variable.set(data[key])

    def _save_config(self) -> None:
        data = {
            "server_path": self.server_path_var.get(),
            "mode": self.mode_var.get(), "width": self.width_var.get(),
            "origin_x": self.origin_x_var.get(), "origin_y": self.origin_y_var.get(),
            "z_work": self.z_work_var.get(), "z_safe": self.z_safe_var.get(),
            "rotation": self.rotation_var.get(), "step": self.step_var.get(),
            "flip_y": self.flip_y_var.get(), "velocity": self.velocity_var.get(),
            "acceleration": self.acceleration_var.get(), "xmin": self.limit_x_min.get(),
            "xmax": self.limit_x_max.get(), "ymin": self.limit_y_min.get(),
            "ymax": self.limit_y_max.get(), "zmin": self.limit_z_min.get(),
            "zmax": self.limit_z_max.get(),
        }
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _on_close(self) -> None:
        self._save_config()
        self.connection.emergency_stop(laser_mode=True)
        self.connection.close()
        self._stop_owned_server()
        if self._instance_lock is not None:
            self._instance_lock.close()
        self.destroy()


def validate_air_test(pose: Pose, paths: list, z: float) -> None:
    if abs(z - pose.z) > 0.5:
        raise ValueError("Essai dans le vide : conserve la hauteur actuelle (bouton Centrer un essai).")
    for label, attr, low, high in STARTUP_JOINT_LIMITS[:3]:
        value = getattr(pose, attr)
        if not low + 5 <= value <= high - 5:
            raise ValueError(f"{label} = {value:.1f}° : marge inférieure à 5°. Éloigne doucement cet axe de sa limite avant le tracé.")
    for path in paths:
        for x, y in path:
            if not all(math.isfinite(v) for v in (x, y, z)) or math.hypot(x - pose.x, y - pose.y) > 8:
                raise ValueError("Essai dans le vide limité à 8 mm autour de la position actuelle. Utilise Centrer un essai.")


def report_callback_exception(self: tk.Tk, exc_type, exc, tb) -> None:
    import traceback
    traceback.print_exception(exc_type, exc, tb)
    messagebox.showerror("Erreur Dobot Atelier", str(exc))


tk.Tk.report_callback_exception = report_callback_exception


def acquire_instance_lock() -> socket.socket | None:
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        lock.bind(("127.0.0.1", INSTANCE_PORT))
        lock.listen(1)
        return lock
    except OSError:
        lock.close()
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Dobot Atelier", "Dobot Atelier est déjà ouvert.\nUtilise la fenêtre existante.")
        root.destroy()
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dobot Atelier")
    parser.add_argument("--offline", action="store_true", help="Aperçu SVG sans connexion au robot")
    args = parser.parse_args()
    instance_lock = None if args.offline else acquire_instance_lock()
    if args.offline or instance_lock is not None:
        app = DobotAtelier(offline=args.offline)
        app._instance_lock = instance_lock
        app.mainloop()
