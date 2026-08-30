from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import sys
import time
import tkinter as tk
import xml.etree.ElementTree as ET
import winreg
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from dobot_protocol import DobotConnection, Pose, startup_pose_issue
from svg_parser import SvgDrawing, load_svg, transformed_paths


APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "1.3.0"
INSTANCE_PORT = 5556
if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "DobotAtelier"
else:
    CONFIG_DIR = APP_DIR
CONFIG_FILE = CONFIG_DIR / "atelier_config.json"
SERVER_EXE = Path.home() / "Documents" / "Codex" / "DobotTools-V1.0" / "installed" / "DobotServer.exe"


class DobotAtelier(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Dobot Atelier {APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(1060, 700)
        self.configure(bg="#f2f3f5")

        self.connection = DobotConnection(self._pose_from_thread, self._status_from_thread)
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
        self._server_process: subprocess.Popen | None = None
        self._instance_lock: socket.socket | None = None
        self._diagnostic_window: tk.Toplevel | None = None

        self._make_style()
        self._make_variables()
        self._build_ui()
        self._load_config()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
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
        self.file_var = tk.StringVar(value="Aucun fichier chargé")
        self.info_var = tk.StringVar(value="Charge un dessin SVG pour commencer")
        self.run_state_var = tk.StringVar(value="PRÊT")
        self.mode_var = tk.StringVar(value="Simulation")
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
        self._combo_row(parent, 4, "Mode", self.mode_var, ("Simulation", "Stylo", "Laser"))
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

        advanced = ttk.LabelFrame(parent, text="Limites absolues de sécurité", padding=8)
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
        if self._official_client_running():
            self.status_var.set("Ferme DobotClient avant de connecter Dobot Atelier")
            self._set_connection_badge("CONFLIT LOGICIEL", "Disconnected.TLabel")
            messagebox.showwarning(
                "DobotClient encore ouvert",
                "Ferme DobotClient : un seul logiciel doit piloter le serveur Dobot V1.\n\n"
                "Dobot Atelier pourra ensuite se connecter à COM7.",
            )
            return
        if self.connection.connected:
            self.status_var.set("Le Dobot est déjà connecté")
            if self.pose is not None:
                self._set_connection_badge("ROBOT CONNECTÉ", "Connected.TLabel")
            else:
                self._set_connection_badge("SERVEUR CONNECTÉ", "Waiting.TLabel")
            return
        try:
            self.connection.connect()
            return
        except OSError:
            pass
        if SERVER_EXE.exists():
            try:
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                self._server_process = subprocess.Popen([str(SERVER_EXE)], cwd=str(SERVER_EXE.parent), creationflags=flags)
                self.status_var.set("Démarrage du serveur Dobot...")
                self.after(1500, self._retry_connection)
                return
            except OSError as exc:
                self.status_var.set(f"Serveur introuvable : {exc}")
        messagebox.showerror("Connexion", "Impossible de joindre DobotServer sur le port 5555.\nFerme l’ancien DobotClient puis démarre DobotServer.")
        self._set_connection_badge("DÉCONNECTÉ", "Disconnected.TLabel")

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
        latest = self._latest_pose
        if latest is not None:
            self.pose = latest
            if not self._robot_online:
                self._robot_online = True
                self._set_connection_badge("ROBOT CONNECTÉ", "Connected.TLabel")
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
        self._update_startup_status()
        self.after(50, self._poll_pose)

    def _startup_issue(self) -> str | None:
        snapshot = self.connection.diagnostic_snapshot()
        return startup_pose_issue(self.pose, float(snapshot["packet_age"]))

    def _update_startup_status(self) -> None:
        issue = self._startup_issue()
        if issue is None and self.pose is not None:
            self.startup_var.set(f"INITIALISATION OK · J2 {self.pose.joint2:.1f}°")
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
            "2. Place J2 entre 70° et 82° sans replier l’avant-bras.\n"
            "3. Rebranche le 12 V 5 A puis l’USB.\n"
            "4. Appuie brièvement sur RESET.",
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
        self.z_safe_var.set(f"{self.pose.z + 15:.2f}")
        self.calibrated_var.set(False)
        self.status_var.set("Origine prise. Vérifie et valide les deux hauteurs Z.")

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
        except ValueError as exc:
            messagebox.showerror("Limites de sécurité", str(exc))
            return
        count = sum(len(path) for path in self.robot_paths)
        if count > 5000:
            messagebox.showerror("Trajectoire trop dense", f"Le dessin contient {count} points. Augmente le pas maximal pour rester sous 5000.")
            return
        mode = self.mode_var.get()
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
            self.connection.clear_queue()
            self.connection.queue_playback_configuration(
                self.velocity_var.get(),
                self.acceleration_var.get(),
                end_type=2 if mode in {"Laser", "Simulation"} else 0,
                laser_mode=mode in {"Laser", "Simulation"},
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
            self.connection.dispatch_next()
            self.run_state_var.set("ATTENTE MOUVEMENT")
            self.status_var.set(f"Initialisation Playback puis {self.initial_queue_size - 4} mouvements")
        except (ConnectionError, ValueError) as exc:
            messagebox.showerror("Envoi impossible", str(exc))

    def _queue_simulation(self, z_safe: float) -> None:
        for path in self.robot_paths:
            self.connection.goto(*path[0], z_safe, tool_on=False, motion=0)
            for x, y in path[1:]:
                self.connection.goto(x, y, z_safe, tool_on=False, motion=2)
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
        self.connection.emergency_stop(laser_mode=True)
        self.initial_queue_size = 0
        self._run_start_pose = None
        self._run_final_target = None
        self.progress.configure(value=0)
        self.run_state_var.set("ARRÊTÉ")
        self.status_var.set("ARRÊT demandé, file vidée, laser coupé")

    def _poll_progress(self) -> None:
        if self.initial_queue_size:
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
                    "Aucun mouvement détecté",
                    "Le port répond, mais les moteurs n’ont pas bougé. La trajectoire a été arrêtée.\n\n"
                    "Vérifie la position de démarrage, appuie sur RESET puis ouvre Diagnostic COM.",
                )
            elif remaining:
                self.status_var.set(f"Exécution : {remaining} commandes restent à transmettre")
            elif self._run_motion_seen and self._run_final_target is not None and self.pose is not None:
                distance = math.dist((self.pose.x, self.pose.y, self.pose.z), self._run_final_target)
                self._run_final_checks = self._run_final_checks + 1 if distance < 2.0 else 0
                if self._run_final_checks >= 3:
                    self.status_var.set("Trajectoire terminée et position finale confirmée")
                    self.run_state_var.set("TERMINÉ")
                    self.initial_queue_size = 0
                    self._run_start_pose = None
                    self._run_final_target = None
                else:
                    self.status_var.set(f"Commandes transmises, mouvement en cours · cible à {distance:.1f} mm")
        self.after(200, self._poll_progress)

    @staticmethod
    def _detected_com_ports() -> list[str]:
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
        ttk.Button(frame, text="Tester la communication (sans mouvement)", command=self._probe_com).grid(row=len(rows), column=0, columnspan=2, sticky="ew", pady=(14, 5))
        ttk.Button(frame, text="Tester le moteur J1 (0,30 s)", command=self._probe_motor).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Button(frame, text="Reconnecter", command=self.connect_robot).grid(row=len(rows) + 2, column=0, columnspan=2, sticky="ew")
        window.protocol("WM_DELETE_WINDOW", self._close_diagnostics)
        self._update_diagnostics()

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
                "COM et télémétrie répondent correctement." if received else "Aucune réponse du robot. Réinitialise COM7.",
                parent=self._diagnostic_window,
            )

        self.after(1200, result)

    def _probe_motor(self) -> None:
        if not self.connection.connected or self.pose is None:
            messagebox.showerror("Test moteur", "Aucune télémétrie robot disponible.", parent=self._diagnostic_window)
            return
        if not self._motion_guard(parent=self._diagnostic_window):
            return
        if not messagebox.askokcancel(
            "Test moteur J1",
            "Le socle va tourner très légèrement pendant 0,30 seconde à 50 %.\n\n"
            "Vérifie que la zone est libre et garde l’arrêt accessible.",
            icon="warning",
            parent=self._diagnostic_window,
        ):
            return
        start = self.pose
        axis = 1 if start.joint1 < 80 else 2
        try:
            self.connection.clear_queue()
            self.connection.configure_jog()
        except (ConnectionError, ValueError) as exc:
            messagebox.showerror("Test moteur", str(exc), parent=self._diagnostic_window)
            return

        def move() -> None:
            try:
                self.connection.jog_joint(axis, speed=50)
            except (ConnectionError, ValueError) as exc:
                messagebox.showerror("Test moteur", str(exc), parent=self._diagnostic_window)

        def stop() -> None:
            try:
                self.connection.stop_jog()
            except ConnectionError:
                pass

        def result() -> None:
            pose = self.pose
            moved = pose is not None and (
                abs(pose.joint1 - start.joint1) > 0.1
                or math.dist((pose.x, pose.y, pose.z), (start.x, start.y, start.z)) > 0.2
            )
            messagebox.showinfo(
                "Test moteur",
                "MOTEUR ET COMMANDE CONFIRMÉS : le robot a réellement bougé."
                if moved
                else "ÉCHEC : la liaison répond, mais aucun mouvement moteur n’a été mesuré.",
                parent=self._diagnostic_window,
            )

        self.after(500, move)
        self.after(800, stop)
        self.after(1800, result)

    def _load_config(self) -> None:
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        mapping = {
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
    instance_lock = acquire_instance_lock()
    if instance_lock is not None:
        app = DobotAtelier()
        app._instance_lock = instance_lock
        app.mainloop()
