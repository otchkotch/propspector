from __future__ import annotations

import ctypes
import io
import logging
import os
import queue
import re
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import filedialog
import tkinter.font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageTk

from . import __version__
from .environmental_config import ENVIRONMENTAL_LAYER_SOURCES, ENVIRONMENTAL_MENU_GROUPS, IMAGERY_2025_MAPSERVER_URL, RESOURCE_STATUS_ORDER, ResourcePresence
from .environmental_widget_runner import EnvironmentalWidgetRunner, MAP_SPATIAL_REFERENCE, PREVIEW_DPI, PREVIEW_HEIGHT, PREVIEW_MIN_CONTEXT_FEET, PREVIEW_WIDTH, PREVIEW_CONTEXT_RATIO, PreviewBundle, PreviewResult
from .fonts import load_bundled_fonts
from .logging_utils import configure_logging
from .settings import AppSettings, load_settings, save_settings
from .zoning_feasibility_runner import (
    APARTMENT_UNIT_SIZE_MIX,
    MIXED_USE_COMMERCIAL_GFA_SHARE,
    MIXED_USE_PROGRAM_GFA_UTILIZATION,
    MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY,
    FeasibilityResult,
    YieldRecommendation,
    ZoningFeasibilityRunner,
)


APP_NAME = "PropSpector"
APP_VERSION = f"v{__version__}"
APP_USER_MODEL_ID = "CDA.PropSpector.Desktop"


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)


def enable_high_dpi() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        logging.getLogger("parcel_packet").exception("Could not set PropSpector taskbar identity")
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            logging.getLogger("parcel_packet").exception("Could not set DPI awareness")


class PropSpectorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        configure_logging()
        load_bundled_fonts()
        ctk.set_appearance_mode("dark")

        self.font_family = self._pick_font_family()
        self.settings = load_settings()
        self.events: queue.Queue[tuple[int, str, object] | tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.env_worker: threading.Thread | None = None
        self.zoning_worker: threading.Thread | None = None
        self.package_worker: threading.Thread | None = None
        self.running_jobs = 0
        self.run_id = 0
        self.job_statuses: dict[str, str] = {}
        self.busy_tick = 0
        self.last_activity_message = ""
        self.had_error = False
        self.active_research_key = ""

        self.preview_bundle: PreviewBundle | None = None
        self.preview_image: ctk.CTkImage | None = None
        self.preview_layer_vars: dict[str, ctk.BooleanVar] = {}
        self.resource_status_by_name: dict[str, ResourcePresence] = {}
        self.zoning_result: FeasibilityResult | None = None
        self.ready_for_package = False

        self.title(f"{APP_NAME} {APP_VERSION}")
        self._apply_window_icon()
        self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        self.minsize(1160, 740)
        self.configure(fg_color="#05080a")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self.after(80, self._maximize)
        self.after(150, self._drain_events)
        self.after(300, self._animate_activity)

    def _apply_window_icon(self) -> None:
        try:
            self.iconbitmap(resource_path("assets", "PropspectorIcon.ico"))
        except Exception:
            logging.getLogger("parcel_packet").exception("Could not apply PropSpector window icon")

    def _font(self, size: int, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family=self.font_family, size=size, weight=weight)

    def _pick_font_family(self) -> str:
        available = set(tkfont.families(self))
        for family in ("Nunito Sans Normal", "Nunito Sans", "NunitoSans", "Avenir Next", "Avenir", "Segoe UI Variable Text", "Segoe UI"):
            if family in available:
                return family
        return "TkDefaultFont"

    def _maximize(self) -> None:
        self.update_idletasks()
        try:
            self.state("zoomed")
        except Exception:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        self.after(350, self._ensure_fullscreen_geometry)

    def _ensure_fullscreen_geometry(self) -> None:
        try:
            if self.state() != "zoomed":
                self.state("zoomed")
        except Exception:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, minsize=292)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=370)
        self.grid_rowconfigure(0, weight=1)

        self.logo_image = self._load_logo_image(34)
        self.placeholder_aerial = self._make_placeholder_aerial(1500, 760)

        self.left_rail = ctk.CTkFrame(self, width=292, corner_radius=0, fg_color="#04080b")
        self.left_rail.grid(row=0, column=0, sticky="nsew")
        self.left_rail.grid_columnconfigure(0, weight=1)
        self.left_rail.grid_rowconfigure(2, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#05080b")
        self.preview_shell.grid(row=0, column=1, sticky="nsew")
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self.right_rail = ctk.CTkFrame(self, width=370, corner_radius=0, fg_color="#05080b")
        self.right_rail.grid(row=0, column=2, sticky="nsew")
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

        self._build_left_rail()
        self._build_preview_area()
        self._build_details_panel()

    def _build_left_rail(self) -> None:
        accent = ctk.CTkFrame(self.left_rail, height=42, corner_radius=0, fg_color="#285a48")
        accent.grid(row=0, column=0, sticky="ew")
        accent.grid_propagate(False)

        header = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=f"Integrated Research · {APP_VERSION}", font=self._font(13, "bold"), text_color="#83bda8").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=APP_NAME, font=self._font(30, "bold"), text_color="#f2f5f3").grid(row=1, column=0, sticky="w")
        self.status_badge = ctk.CTkLabel(header, text="Ready", width=82, height=30, corner_radius=8, fg_color="#0e1814", text_color="#91c7a9", font=self._font(12, "bold"))
        self.status_badge.grid(row=1, column=1, sticky="e")
        ctk.CTkLabel(
            header,
            text="Quickly visualize mapped environmental resources and development options in one reference workspace.",
            text_color="#8c9692",
            font=self._font(13),
            justify="left",
            wraplength=370,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))

        form = self._card(self.left_rail, row=2)
        form.grid_columnconfigure(0, weight=1)
        self.parcel_entry = self._entry(form, "Parcel number or address")
        self.parcel_entry.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 7))
        self.parcel_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())

        self.folder_row = ctk.CTkFrame(form, fg_color="transparent")
        self.folder_row.grid(row=1, column=0, sticky="ew", padx=12, pady=7)
        self.folder_row.grid_columnconfigure(0, weight=1)
        self.folder_entry = self._entry(self.folder_row, "Destination folder")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(self.folder_row, text="Browse", width=82, height=38, corner_radius=8, fg_color="#2d5a47", hover_color="#376d56", command=self._browse, font=self._font(13, "bold")).grid(row=0, column=1)

        self.group_menu = ctk.CTkOptionMenu(
            form,
            values=list(ENVIRONMENTAL_MENU_GROUPS),
            height=38,
            corner_radius=8,
            fg_color="#080d0c",
            button_color="#2d5a47",
            button_hover_color="#376d56",
            dropdown_fg_color="#111917",
            dropdown_hover_color="#1f382e",
            font=self._font(14),
            command=lambda _value: self._sync_run_button_state(),
        )
        self.group_menu.set("All Resources")
        self.group_menu.grid(row=2, column=0, sticky="ew", padx=12, pady=7)

        self.intended_use_entry = self._entry(form, "Optional intended use: solar, hospital, apartments...")
        self.intended_use_entry.grid(row=3, column=0, sticky="ew", padx=12, pady=7)
        self.intended_use_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())

        button_row = ctk.CTkFrame(form, fg_color="transparent")
        button_row.grid(row=4, column=0, sticky="ew", padx=12, pady=(7, 12))
        button_row.grid_columnconfigure((0, 1), weight=1)
        self.run_button = ctk.CTkButton(button_row, text="Run Research", height=42, corner_radius=9, fg_color="#4f8b6d", hover_color="#5a9b7a", font=self._font(14, "bold"), command=self._run_or_cancel)
        self.run_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.package_button = ctk.CTkButton(button_row, text="Create Maps", height=42, corner_radius=9, fg_color="#18231f", hover_color="#24362f", text_color="#8da69a", font=self._font(14, "bold"), command=self._create_package, state="disabled")
        self.package_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self._build_zoning_panel(self.left_rail, row=3)
        self._build_log_panel(self.left_rail, row=4)

    def _build_layer_controls(self, parent, row: int) -> None:
        card = self._card(parent, row=row, padx=12)
        card.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Preview Layers", font=self._font(17, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="Present", width=72, height=28, corner_radius=7, fg_color="#20312b", hover_color="#2d493d", command=self._show_present_layers, font=self._font(12, "bold")).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(header, text="Clear", width=58, height=28, corner_radius=7, fg_color="#141b19", hover_color="#202a27", command=self._clear_layers, font=self._font(12, "bold")).grid(row=0, column=2, padx=(6, 0))

        self.layer_controls = ctk.CTkScrollableFrame(card, height=430, corner_radius=10, fg_color="#070a0d", border_color="#1b332b", border_width=1)
        self.layer_controls.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.layer_controls.grid_columnconfigure(0, weight=1)
        for index, name in enumerate(RESOURCE_STATUS_ORDER):
            var = ctk.BooleanVar(value=False)
            self.preview_layer_vars[name] = var
            checkbox = ctk.CTkCheckBox(
                self.layer_controls,
                text=name,
                variable=var,
                command=self._refresh_preview,
                fg_color="#4f8b6d",
                hover_color="#335f4b",
                border_color="#49645b",
                font=self._font(12),
                state="disabled",
            )
            checkbox.grid(row=index, column=0, sticky="w", padx=10, pady=4)

    def _build_resource_panel(self, parent, row: int) -> None:
        self.resource_card = self._card(parent, row=row, padx=12)
        self.resource_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.resource_card, text="Environmental Resources", font=self._font(17, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.resource_rows = ctk.CTkFrame(self.resource_card, fg_color="transparent")
        self.resource_rows.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.resource_rows.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.resource_rows, text="Run research to populate mapped resource presence.", font=self._font(12), text_color="#728078", wraplength=360, justify="left").grid(row=0, column=0, sticky="w")

    def _build_zoning_panel(self, parent, row: int) -> None:
        self.zoning_card = self._card(parent, row=row)
        self.zoning_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.zoning_card, text="Development Options", font=self._font(17, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.zoning_snapshot = ctk.CTkLabel(self.zoning_card, text="Development options will appear here.", font=self._font(12), text_color="#8f9c98", justify="left", anchor="w", wraplength=410)
        self.zoning_snapshot.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.zoning_activity = ctk.CTkProgressBar(self.zoning_card, height=8, corner_radius=4, progress_color="#4f8b6d", fg_color="#14201c", mode="indeterminate")
        self.zoning_activity.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.zoning_activity.grid_remove()
        self.zoning_rows = ctk.CTkFrame(self.zoning_card, fg_color="transparent")
        self.zoning_rows.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.zoning_rows.grid_columnconfigure(0, weight=1)

    def _build_log_panel(self, parent, row: int) -> None:
        card = self._card(parent, row=row)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="Progress", font=self._font(17, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.log_box = ctk.CTkTextbox(card, height=110, corner_radius=9, fg_color="#070a0d", border_color="#223830", border_width=1, font=self._font(12), text_color="#b9c4bf")
        self.log_box.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

    def _build_preview_area(self) -> None:
        top = ctk.CTkFrame(self.preview_shell, height=74, fg_color="#08100f", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Live Environmental Preview", font=self._font(24, "bold"), text_color="#f2f5f3").grid(row=0, column=0, sticky="w", padx=20, pady=(13, 0))
        self.preview_status = ctk.CTkLabel(top, text="Run a parcel to build the preview.", font=self._font(13), text_color="#90a19a")
        self.preview_status.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))
        self.preview_facts = ctk.CTkLabel(top, text="", font=self._font(12), text_color="#b8c9c1", justify="right")
        self.preview_facts.grid(row=0, column=1, rowspan=2, sticky="e", padx=20, pady=10)

        body = ctk.CTkFrame(self.preview_shell, corner_radius=0, fg_color="#020403")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, minsize=370)
        body.grid_rowconfigure(0, weight=1)

        self.preview_frame = ctk.CTkFrame(body, corner_radius=0, fg_color="#020403")
        self.preview_frame.grid(row=0, column=0, sticky="nsew")
        self.preview_frame.grid_columnconfigure(0, weight=1)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_image_label = ctk.CTkLabel(self.preview_frame, text="Preview will appear here", fg_color="#030606", text_color="#6f7b76", font=self._font(18))
        self.preview_image_label.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.preview_image_label.bind("<Configure>", lambda _event: self._refresh_preview())

        self.right_rail = ctk.CTkScrollableFrame(body, width=370, corner_radius=0, fg_color="#060a09")
        self.right_rail.grid(row=0, column=1, sticky="nsew")
        self.right_rail.grid_columnconfigure(0, weight=1)
        self._build_layer_controls(self.right_rail, row=0)
        self._build_resource_panel(self.right_rail, row=1)

    def _card(self, parent, row: int, padx: int = 16) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, corner_radius=16, fg_color="#0b100f", border_color="#1b332b", border_width=1)
        card.grid(row=row, column=0, sticky="ew", padx=padx, pady=(0, 12))
        return card

    def _entry(self, parent, placeholder: str) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            height=38,
            corner_radius=8,
            fg_color="#050807",
            border_color="#30453d",
            text_color="#edf3ef",
            placeholder_text_color="#68756f",
            font=self._font(14),
        )

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_entry.get().strip() or str(Path.home() / "Documents"))
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

    def _run_or_cancel(self) -> None:
        if self.running_jobs > 0:
            if self._current_research_key() != self.active_research_key:
                self._cancel_current("Starting new research")
                self.after(80, self._start)
            else:
                self._cancel_current("Canceled by user")
            return
        self._start()

    def _start(self) -> None:
        parcel = self.parcel_entry.get().strip()
        if not parcel:
            self._log("Enter a parcel number or address first.")
            return
        folder = self.folder_entry.get().strip()
        if folder:
            self.settings = AppSettings(last_destination=folder, project_prefix="")
            save_settings(self.settings)

        self.run_id += 1
        run_id = self.run_id
        self.stop_event = threading.Event()
        self.active_research_key = self._research_key(parcel, self.intended_use_entry.get().strip(), self.group_menu.get())
        self.preview_bundle = None
        self.zoning_result = None
        self.ready_for_package = False
        self.resource_status_by_name.clear()
        self.job_statuses = {"environmental": "Running", "zoning": "Running"}
        self.last_activity_message = "Starting research"
        self.had_error = False
        self._set_running(True, jobs=2)
        self._reset_visuals()

        self.env_worker = threading.Thread(target=self._environmental_worker, args=(run_id, parcel, Path(folder or Path.home() / "Documents"), self.group_menu.get()), daemon=True)
        self.zoning_worker = threading.Thread(target=self._zoning_worker, args=(run_id, parcel, self.intended_use_entry.get().strip()), daemon=True)
        self.env_worker.start()
        self.zoning_worker.start()

    def _cancel_current(self, reason: str = "Canceled by user") -> None:
        self.run_id += 1
        self.stop_event.set()
        self.job_statuses = {name: "Canceled" if status == "Running" else status for name, status in self.job_statuses.items()}
        self.running_jobs = 0
        self.last_activity_message = reason
        self._log("Canceled stale research. Starting the new parcel." if reason == "Starting new research" else "Canceled current research. You can run a new parcel now.")
        self._set_running(False)

    def _emit(self, run_id: int, event: str, payload: object = "") -> None:
        self.events.put((run_id, event, payload))

    def _environmental_worker(self, run_id: int, parcel: str, destination: Path, group: str) -> None:
        try:
            runner = EnvironmentalWidgetRunner(
                parcel_number=parcel,
                destination=destination,
                progress=lambda message: self._emit(run_id, "log", f"Environmental: {message}"),
                stop_event=self.stop_event,
                environmental_group=group,
                resource_status_callback=lambda statuses: self._emit(run_id, "resources", statuses),
                preview_callback=lambda preview: self._emit(run_id, "preview", preview),
            )
            result = runner.prepare_preview()
            self._emit(run_id, "env_done", result)
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("PropSpector environmental research failed")
            self._emit(run_id, "error", f"Environmental preview failed: {exc}")
        finally:
            self._emit(run_id, "job_done", "environmental")

    def _zoning_worker(self, run_id: int, parcel: str, intended_use: str) -> None:
        try:
            runner = ZoningFeasibilityRunner(parcel, intended_use=intended_use, progress=lambda message: self._emit(run_id, "log", f"Zoning: {message}"))
            result = runner.analyze()
            self._emit(run_id, "zoning", result)
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("PropSpector zoning research failed")
            self._emit(run_id, "error", f"Zoning feasibility failed: {exc}")
        finally:
            self._emit(run_id, "job_done", "zoning")

    def _create_package(self) -> None:
        parcel = self.parcel_entry.get().strip()
        folder = self.folder_entry.get().strip()
        if not parcel or not folder:
            self._log("Enter a parcel number or address and destination folder before creating maps.")
            return
        self.run_id += 1
        run_id = self.run_id
        self.stop_event = threading.Event()
        self.job_statuses = {"package": "Running"}
        self._set_running(True, jobs=1)
        self.package_worker = threading.Thread(target=self._package_worker, args=(run_id, parcel, Path(folder), self.group_menu.get()), daemon=True)
        self.package_worker.start()

    def _package_worker(self, run_id: int, parcel: str, destination: Path, group: str) -> None:
        try:
            runner = EnvironmentalWidgetRunner(parcel, destination, lambda message: self._emit(run_id, "log", f"Maps: {message}"), self.stop_event, environmental_group=group)
            paths = runner.build_pdf_package()
            self._emit(run_id, "package_done", paths)
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("PropSpector map package failed")
            self._emit(run_id, "error", f"Map package failed: {exc}")
        finally:
            self._emit(run_id, "job_done", "package")

    def _drain_events(self) -> None:
        while True:
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            if len(item) == 3:
                event_run_id, event, payload = item
                if event_run_id != self.run_id:
                    continue
            else:
                event, payload = item
            if event == "log":
                self._log(str(payload))
                self.last_activity_message = str(payload)
            elif event == "resources":
                self._apply_resources(payload)  # type: ignore[arg-type]
            elif event == "preview" and isinstance(payload, PreviewBundle):
                self._apply_preview(payload)
            elif event == "env_done" and isinstance(payload, PreviewResult):
                self._apply_resources(payload.resource_statuses)
                self.ready_for_package = True
                self.package_button.configure(state="normal", fg_color="#2d5a47", text_color="#eef7f2")
            elif event == "zoning" and isinstance(payload, FeasibilityResult):
                self._apply_zoning(payload)
            elif event == "package_done":
                paths = payload if isinstance(payload, tuple) else ()
                self._log(f"Created {len(paths)} environmental PDF file(s).")
            elif event == "error":
                self._log(str(payload))
                self.had_error = True
                if str(payload).startswith("Zoning feasibility failed:"):
                    self._apply_zoning_failure(str(payload))
                    self.job_statuses["zoning"] = "Failed"
                elif str(payload).startswith("Environmental preview failed:"):
                    self.job_statuses["environmental"] = "Failed"
                self.status_badge.configure(text="Review", fg_color="#2d2415", text_color="#d0a96d")
            elif event == "job_done":
                job = str(payload)
                if self.job_statuses.get(job) == "Running":
                    self.job_statuses[job] = "Done"
                self.running_jobs = max(0, self.running_jobs - 1)
                if self.running_jobs == 0:
                    self._set_running(False)
        self.after(150, self._drain_events)

    def _set_running(self, running: bool, jobs: int | None = None) -> None:
        if jobs is not None:
            self.running_jobs = jobs
        self._sync_run_button_state(running)
        if not running and self.ready_for_package:
            self.package_button.configure(state="normal", fg_color="#2d5a47", text_color="#eef7f2")
        else:
            self.package_button.configure(state="disabled", fg_color="#18231f", text_color="#8da69a")
        self.status_badge.configure(
            text="Running" if running else "Review" if self.had_error else "Ready",
            fg_color="#0f1d18" if running else "#2d2415" if self.had_error else "#0d1512",
            text_color="#94c6d8" if running else "#d0a96d" if self.had_error else "#91c7a9",
        )
        if running:
            self.zoning_activity.grid()
            self.zoning_activity.start()
        else:
            self.zoning_activity.stop()
            self.zoning_activity.grid_remove()

    def _sync_run_button_state(self, running: bool | None = None) -> None:
        is_running = self.running_jobs > 0 if running is None else running
        new_search_pending = is_running and self._current_research_key() != self.active_research_key
        self.run_button.configure(
            state="normal",
            text="Run New Search" if new_search_pending else "Cancel" if is_running else "Run Research",
            fg_color="#4f8b6d" if new_search_pending or not is_running else "#7a3d3d",
            hover_color="#5a9b7a" if new_search_pending or not is_running else "#914848",
        )

    def _current_research_key(self) -> str:
        return self._research_key(
            self.parcel_entry.get().strip(),
            self.intended_use_entry.get().strip(),
            self.group_menu.get(),
        )

    def _research_key(self, parcel: str, intended_use: str, group: str) -> str:
        return "\n".join(
            (
                " ".join(parcel.upper().split()),
                " ".join(intended_use.upper().split()),
                " ".join(group.upper().split()),
            )
        )

    def _reset_visuals(self) -> None:
        self.preview_image_label.configure(image=None, text="Building preview...")
        self.preview_status.configure(text="Querying GIS layers...")
        self.preview_facts.configure(text="")
        self.zoning_snapshot.configure(text="Running development options...")
        self.zoning_activity.grid()
        self.zoning_activity.start()
        for child in self.zoning_rows.winfo_children():
            child.destroy()
        for child in self.resource_rows.winfo_children():
            child.destroy()
        for var in self.preview_layer_vars.values():
            var.set(False)
        for child in self.layer_controls.winfo_children():
            child.configure(state="disabled")
        self._clear_log()

    def _apply_preview(self, preview: PreviewBundle) -> None:
        self.preview_bundle = preview
        for name, var in self.preview_layer_vars.items():
            var.set(name in preview.default_visible_layers)
        for child in self.layer_controls.winfo_children():
            child.configure(state="normal")
        self.preview_status.configure(text="Preview ready" if preview.layer_images else "Aerial ready; loading resources")
        self.preview_facts.configure(text=self._preview_facts_text(preview))
        self._refresh_preview()

    def _apply_resources(self, statuses: tuple[ResourcePresence, ...]) -> None:
        self.resource_status_by_name = {status.name: status for status in statuses}
        for child in self.resource_rows.winfo_children():
            child.destroy()
        present_statuses = [status for status in statuses if status.status == "Present"]
        present_count = len(present_statuses)
        ctk.CTkLabel(self.resource_rows, text=f"{present_count} mapped resource categories present", font=self._font(12, "bold"), text_color="#91c7a9").grid(row=0, column=0, sticky="w", pady=(0, 6))
        if not present_statuses:
            ctk.CTkLabel(
                self.resource_rows,
                text="No mapped environmental resources were found on this parcel.",
                font=self._font(12),
                text_color="#728078",
                wraplength=320,
                justify="left",
            ).grid(row=1, column=0, sticky="w", pady=(0, 6))
            return
        for index, status in enumerate(present_statuses, start=1):
            fg = "#3a1718"
            text = self._resource_metric_text(status)
            chip_color = "#b95050"
            row = ctk.CTkFrame(self.resource_rows, corner_radius=8, fg_color="#070a0d", border_color="#162722", border_width=1)
            row.grid(row=index, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=status.name, font=self._font(12), text_color="#d5dfdb", anchor="w").grid(row=0, column=0, sticky="ew", padx=8, pady=7)
            ctk.CTkLabel(row, text=text, width=72, height=22, corner_radius=6, fg_color=fg, text_color=chip_color, font=self._font(12, "bold")).grid(row=0, column=1, padx=(4, 8), pady=7)

    def _resource_metric_text(self, status: ResourcePresence) -> str:
        if status.status != "Present":
            return "OK"
        if status.raw_acres is not None:
            if status.raw_acres < 0.01:
                return "<0.01 ac"
            return f"{status.raw_acres:,.2f} ac"
        if status.count:
            return f"{status.count}"
        return "Present"

    def _apply_zoning(self, result: FeasibilityResult) -> None:
        self.zoning_result = result
        self.job_statuses["zoning"] = "Done"
        self.zoning_activity.stop()
        self.zoning_activity.grid_remove()
        best = self._best_recommendation(result)
        zoning = ", ".join(district.code for district in result.zoning_districts) or "-"
        headline = self._yield_breakdown(result, best) if best else result.summary
        name = self._display_option_name(best) if best else "Feasibility Result"
        self.zoning_snapshot.configure(
            text=(
                f"{name}: {headline}\n"
                f"Parcel: {result.parcel.parcel_number}\n"
                f"Zoning: {zoning} / {result.municipality}\n"
                f"Area: {result.parcel_area_sf / 43560:,.2f} ac"
            )
        )
        for child in self.zoning_rows.winfo_children():
            child.destroy()
        for index, recommendation in enumerate(self._visible_recommendations(result)):
            self._zoning_card(result, recommendation, index)

    def _apply_zoning_failure(self, message: str) -> None:
        self.zoning_activity.stop()
        self.zoning_activity.grid_remove()
        clean = message.replace("Zoning feasibility failed:", "", 1).strip()
        self.zoning_snapshot.configure(
            text=(
                "Development options need review.\n"
                "The environmental preview may still be usable, but zoning/development options did not finish.\n"
                f"Reason: {clean or 'Unknown zoning error'}"
            )
        )
        for child in self.zoning_rows.winfo_children():
            child.destroy()
        card = ctk.CTkFrame(self.zoning_rows, corner_radius=10, fg_color="#130d0d", border_color="#663636", border_width=1)
        card.grid(row=0, column=0, sticky="ew", pady=4)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="Zoning feasibility failed", font=self._font(13, "bold"), text_color="#f1d6d6", anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        ctk.CTkLabel(
            card,
            text=clean or "The zoning service did not return a usable result. Try again or review the municipal profile manually.",
            font=self._font(12),
            text_color="#d0a0a0",
            wraplength=405,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

    def _animate_activity(self) -> None:
        if self.running_jobs > 0:
            self.busy_tick = (self.busy_tick + 1) % 4
            dots = "." * self.busy_tick
            parts = [f"{name.title()}: {status}" for name, status in self.job_statuses.items()]
            summary = " / ".join(parts) if parts else "Working"
            self.status_badge.configure(text=f"Working{dots}", fg_color="#0f1d18", text_color="#94c6d8")
            if self.last_activity_message:
                self.preview_status.configure(text=f"{summary} - {self.last_activity_message}")
            else:
                self.preview_status.configure(text=summary)
        self.after(450, self._animate_activity)

    def _zoning_card(self, result: FeasibilityResult, recommendation: YieldRecommendation, index: int) -> None:
        has_screened_yield = recommendation.conservative_yield is not None and recommendation.conservative_yield > 0
        review_profile = recommendation.status in {
            "Seed Profile Active",
            "Seed Bot Created",
            "Further Code Review Required",
            "Next Interpreter Required",
            "Bot Classification Required",
            "Municipal Review Required",
            "Municipal Review Active",
            "Municipal Context Review",
            "Use Translation Required",
            "Profile Active",
            "Commercial District Matrix Required",
            "Industrial District Matrix Required",
            "Waterfront District Matrix Required",
            "Residential Matrix Required",
            "District Use Answer",
            "Board Review Path",
            "Use Translator Active",
            "Source Cache Required",
            "Cached Code Interpreter Active",
            "District Cache Match",
            "District Mapping Needed",
            "Cached Use Answer",
            "Cached Permission Signals",
            "Implementation Profile Needed",
        }
        likely_not_feasible = not review_profile and (not has_screened_yield or recommendation.status in {"Not By Right", "Dimensional Variance Likely"})
        border = "#315f4a" if recommendation.status == "By Right" else "#6a5a2a" if has_screened_yield or review_profile else "#663636"
        card = ctk.CTkFrame(self.zoning_rows, corner_radius=10, fg_color="#070d0c", border_color=border, border_width=1)
        card.grid(row=index, column=0, sticky="ew", pady=4)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)
        title = f"{self._display_option_name(recommendation)}"
        ctk.CTkLabel(card, text=title, font=self._font(13, "bold"), text_color="#f1f6f3", anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 4))
        if likely_not_feasible:
            ctk.CTkLabel(
                card,
                text="Likely not feasible. Further code review required.",
                font=self._font(12),
                text_color="#c7b98a",
                anchor="w",
                wraplength=405,
            ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
            return
        if review_profile and not has_screened_yield:
            ctk.CTkLabel(
                card,
                text=recommendation.note,
                font=self._font(12),
                text_color="#c7b98a",
                anchor="w",
                wraplength=405,
                justify="left",
            ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
            return

        ctk.CTkLabel(card, text="Estimated Yield", font=self._font(10, "bold"), text_color="#789188", anchor="w").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 1))
        ctk.CTkLabel(card, text="Estimated Income", font=self._font(10, "bold"), text_color="#789188", anchor="e").grid(row=1, column=1, sticky="e", padx=10, pady=(0, 1))
        ctk.CTkLabel(card, text=self._yield_breakdown(result, recommendation), font=self._font(13, "bold"), text_color="#dfe9e4", anchor="w").grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkLabel(card, text=self._market_range_text(recommendation), font=self._font(13, "bold"), text_color="#dfe9e4", anchor="e").grid(row=2, column=1, sticky="e", padx=10, pady=(0, 10))
        if recommendation.status not in {"By Right", "Preliminary Municipal Yield"}:
            ctk.CTkLabel(
                card,
                text="Further code review required.",
                font=self._font(11),
                text_color="#c7b98a",
                anchor="w",
            ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))

    def _show_present_layers(self) -> None:
        for name, var in self.preview_layer_vars.items():
            status = self.resource_status_by_name.get(name)
            var.set(status is not None and status.status == "Present")
        self._refresh_preview()

    def _clear_layers(self) -> None:
        for var in self.preview_layer_vars.values():
            var.set(False)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if self.preview_bundle is None:
            return
        canvas = self.preview_bundle.base_image.copy()
        for name in RESOURCE_STATUS_ORDER:
            if self.preview_layer_vars[name].get():
                layer = self.preview_bundle.layer_images.get(name)
                if layer is not None:
                    canvas.alpha_composite(layer)
        canvas.alpha_composite(self.preview_bundle.parcel_outline_image)
        canvas.alpha_composite(self.preview_bundle.road_overlay_image)

        image = canvas.convert("RGB")
        max_width = max(780, self.preview_image_label.winfo_width() - 20)
        max_height = max(560, self.preview_image_label.winfo_height() - 20)
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self.preview_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.preview_image_label.configure(image=self.preview_image, text="")

    def _preview_facts_text(self, preview: PreviewBundle) -> str:
        facts = preview.parcel_facts
        zoning = "Split Zoned: " + ", ".join(preview.zoning_districts) if len(preview.zoning_districts) > 1 else (preview.zoning_districts[0] if preview.zoning_districts else "-")
        return f"Parcel: {facts.get('Parcel') or '-'}\nAddress: {facts.get('Address') or '-'}\nOwner: {facts.get('Owner') or '-'}\nZoning: {zoning}"

    def _log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _best_recommendation(self, result: FeasibilityResult) -> YieldRecommendation | None:
        return result.recommendations[0] if result.recommendations else None

    def _visible_recommendations(self, result: FeasibilityResult) -> tuple[YieldRecommendation, ...]:
        yielded = tuple(
            recommendation
            for recommendation in result.recommendations
            if recommendation.conservative_yield is not None or recommendation.gross_area_yield is not None
        )
        return (yielded or result.recommendations)[:8]

    def _display_option_name(self, recommendation: YieldRecommendation | None) -> str:
        if recommendation is None:
            return "-"
        option = recommendation.development_option
        clean = option.lower()
        if clean == "mixed use development":
            return "Mixed Use"
        if clean == "commercial apartments":
            return "Apartments"
        if clean == "other / custom use":
            return "Civic / Utility / Solar / Other"
        return option

    def _yield_breakdown(self, result: FeasibilityResult, recommendation: YieldRecommendation | None) -> str:
        if recommendation is None or recommendation.conservative_yield is None:
            return "Review required"
        option = recommendation.development_option.lower()
        if "mixed use" in option:
            commercial_gfa, units = self._mixed_use_split(recommendation)
            return f"{recommendation.conservative_yield or 0:,} sf GFA envelope / {units:,} derived units"
        if "solar" in option:
            return f"{recommendation.conservative_yield:,} sf site area"
        if any(label in option for label in ("single-family", "two-family", "townhouse", "semi-detached")):
            return f"{recommendation.conservative_yield:,} lots"
        if "apartment" in option or "manufactured" in option or "mobile" in option or "home" in option:
            return f"{recommendation.conservative_yield:,} units"
        if recommendation.status == "Preliminary Municipal Screen" or recommendation.gross_area_yield:
            return f"{recommendation.conservative_yield:,} sf GFA"
        if result.capacity_matrix and result.capacity_matrix.capacity_type == "nonresidential":
            return f"{recommendation.conservative_yield:,} sf GFA"
        return f"{recommendation.conservative_yield:,}"

    def _market_range_text(self, recommendation: YieldRecommendation) -> str:
        if recommendation.market_basis.startswith("public-owner"):
            return "Public-owner context"
        low = recommendation.market_value_low
        high = recommendation.market_value_high
        if low is None or high is None:
            return "-"
        if low == high:
            return self._money_text(low)
        return f"{self._money_text(low)}-{self._money_text(high)}"

    def _money_text(self, value: int) -> str:
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"${value / 1_000:.0f}k"
        return f"${value:,}"

    def _mixed_use_split(self, recommendation: YieldRecommendation) -> tuple[int, int]:
        if recommendation.program_scenario:
            return recommendation.program_scenario.commercial_gfa or 0, recommendation.program_scenario.modeled_units or 0
        note_units = [value for value in (self._note_units(recommendation.note, "residential unit support"), self._note_units(recommendation.note, "site support")) if value]
        allowed_gfa = recommendation.conservative_yield or 0
        program_gfa = int(allowed_gfa * MIXED_USE_PROGRAM_GFA_UTILIZATION)
        commercial_gfa = int(program_gfa * MIXED_USE_COMMERCIAL_GFA_SHARE)
        residential_gfa = max(0, program_gfa - commercial_gfa)
        average_net_area = sum(share * area for _bedroom, share, area in APARTMENT_UNIT_SIZE_MIX)
        average_gross_area = average_net_area / MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY
        gfa_units = int(residential_gfa / average_gross_area) if average_gross_area else 0
        return commercial_gfa, min([gfa_units, *note_units]) if note_units else gfa_units

    def _note_units(self, note: str, label: str) -> int:
        match = re.search(rf"{re.escape(label)} ([\d,]+)", note)
        return int(match.group(1).replace(",", "")) if match else 0

    def _build_left_rail(self) -> None:
        header = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(26, 24))
        header.grid_columnconfigure(1, weight=1)
        if self.logo_image:
            ctk.CTkLabel(header, image=self.logo_image, text="").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ctk.CTkLabel(header, text="Prop", font=self._font(25, "bold"), text_color="#f3fbfb").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(header, text="Spector", font=self._font(25, "bold"), text_color="#00d6d6").grid(row=0, column=1, sticky="w", padx=(55, 0))

        nav = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=14)
        nav.grid_columnconfigure(0, weight=1)
        nav_items = [
            ("⌂", "Dashboard", True),
            ("◇", "Map Explorer", False),
            ("⌕", "Parcel Search", False),
            ("☷", "Lists", False),
            ("▥", "Reports", False),
            ("♢", "Alerts", False),
            ("⇩", "Imports", False),
            ("♙", "Contacts", False),
            ("⚙", "Settings", False),
        ]
        for index, (icon, label, active) in enumerate(nav_items):
            self._nav_item(nav, icon, label, active).grid(row=index, column=0, sticky="ew", pady=3)

        ctk.CTkFrame(self.left_rail, fg_color="transparent").grid(row=2, column=0, sticky="nsew")

        quick = self._panel(self.left_rail, row=3, padx=16, pady=(0, 12))
        quick.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(quick, text="QUICK ACTIONS", font=self._font(11, "bold"), text_color="#8c98a4").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))
        self.run_button = self._quick_button(quick, "+", "New Search", self._run_or_cancel)
        self.run_button.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        self._quick_button(quick, "⇩", "Import Parcels", self._browse).grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        self._quick_button(quick, "☷", "Create List", lambda: None).grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        self.package_button = self._quick_button(quick, "▧", "Generate Report", self._create_package)
        self.package_button.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 12))
        self.package_button.configure(state="disabled", fg_color="#0d151a", text_color="#6f7d86")

        account = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        account.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))
        account.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(account, text="ZM", width=44, height=44, corner_radius=22, fg_color="#111820", text_color="#ffffff", font=self._font(15, "bold")).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(account, text="Zak Morris", font=self._font(13, "bold"), text_color="#f0f4f6").grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(account, text="Administrator", font=self._font(12), text_color="#8d99a4").grid(row=1, column=1, sticky="nw")
        ctk.CTkLabel(account, text="⌄", font=self._font(18), text_color="#85929c").grid(row=0, column=2, rowspan=2, sticky="e")

    def _build_preview_area(self) -> None:
        top = ctk.CTkFrame(self.preview_shell, height=80, fg_color="#05080b", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew", padx=(18, 8), pady=(16, 0))
        top.grid_columnconfigure(0, weight=1)

        search = ctk.CTkFrame(top, height=52, corner_radius=8, fg_color="#0b1115", border_color="#1d3036", border_width=1)
        search.grid(row=0, column=0, sticky="ew", padx=(0, 14))
        search.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search, text="⌕", font=self._font(24), text_color="#a5b2bb").grid(row=0, column=0, padx=(16, 8))
        self.parcel_entry = ctk.CTkEntry(
            search,
            placeholder_text="Search by Address, Owner, Parcel ID...",
            height=40,
            border_width=0,
            fg_color="transparent",
            text_color="#eef6f7",
            placeholder_text_color="#7f878d",
            font=self._font(14),
        )
        self.parcel_entry.grid(row=0, column=1, sticky="ew")
        self.parcel_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())
        self.parcel_entry.bind("<Return>", lambda _event: self._run_or_cancel())
        ctk.CTkLabel(search, text="⌘  K", width=46, height=28, corner_radius=6, fg_color="#0f171b", text_color="#b8c2c9", font=self._font(12, "bold")).grid(row=0, column=2, padx=10)

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.grid(row=0, column=1, sticky="e")
        for idx, icon in enumerate(("☾", "♢", "?", "ZM", "⌄")):
            size = 38 if icon != "ZM" else 42
            color = "#121a22" if icon == "ZM" else "transparent"
            ctk.CTkButton(
                tools,
                text=icon,
                width=size,
                height=size,
                corner_radius=size // 2,
                fg_color=color,
                hover_color="#121b21",
                text_color="#dbe5e8",
                font=self._font(15, "bold" if icon == "ZM" else "normal"),
            ).grid(row=0, column=idx, padx=4)

        content = ctk.CTkFrame(self.preview_shell, corner_radius=0, fg_color="#05080b")
        content.grid(row=1, column=0, sticky="nsew", padx=(18, 8), pady=(8, 18))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        kpis = ctk.CTkFrame(content, fg_color="transparent")
        kpis.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for col in range(5):
            kpis.grid_columnconfigure(col, weight=1, uniform="kpi")
        for col, card in enumerate((
            ("♧", "PARCELS TRACKED", "4,982", "↑ 12% vs last 30 days", "#00d6d6"),
            ("▣", "NEW PARCELS", "214", "↑ 8% vs last 7 days", "#00d6d6"),
            ("☆", "POTENTIAL LEADS", "87", "↑ 15% vs last 30 days", "#e4b451"),
            ("◉", "WATCHLIST", "12", "— No change", "#00d6d6"),
            ("☷", "LISTS", "18", "↑ 4% vs last 7 days", "#00d6d6"),
        )):
            self._kpi_card(kpis, *card).grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 5, 0 if col == 4 else 5))

        self.preview_frame = self._panel(content, row=1, padx=0, pady=(0, 10), radius=8)
        self.preview_frame.grid_columnconfigure(0, weight=1)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_image_label = ctk.CTkLabel(self.preview_frame, text="", fg_color="#030608", text_color="#6f7b76", font=self._font(18), anchor="nw")
        self.preview_image_label.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.preview_image_label.bind("<Configure>", lambda _event: self._refresh_preview())
        self._build_map_overlays()

        self._build_recent_table(content, row=2)

        self.folder_entry = self._entry(content, "Destination folder")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid_remove()
        self.group_menu = ctk.CTkOptionMenu(content, values=list(ENVIRONMENTAL_MENU_GROUPS))
        self.group_menu.set("All Resources")
        self.group_menu.grid_remove()
        self.intended_use_entry = self._entry(content, "Optional intended use")
        self.intended_use_entry.grid_remove()

        self.preview_status = ctk.CTkLabel(content, text="Dashboard ready. Press Enter or New Search to run parcel research.", font=self._font(12), text_color="#8fa1aa")
        self.preview_status.grid(row=3, column=0, sticky="w", pady=(2, 0))
        self.preview_facts = ctk.CTkLabel(content, text="", font=self._font(12), text_color="#b8c9c1", justify="right")
        self.preview_facts.grid(row=3, column=0, sticky="e", pady=(2, 0))

        self._refresh_preview()

    def _build_details_panel(self) -> None:
        panel = ctk.CTkScrollableFrame(self.right_rail, corner_radius=8, fg_color="#070b0f", border_color="#1b2b32", border_width=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(8, 14), pady=(80, 18))
        panel.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="26-017.00-123 ☆", font=self._font(20, "bold"), text_color="#f4fbfb").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="×", font=self._font(24), text_color="#a9b4bb").grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(header, text="POTENTIAL LEAD", height=22, corner_radius=5, fg_color="#063d42", text_color="#00f0e6", font=self._font(10, "bold")).grid(row=1, column=0, sticky="w", pady=(7, 9))
        ctk.CTkLabel(header, text="1021 Gilpin Ave\nWilmington, DE 19806\nNew Castle County", font=self._font(13), text_color="#d6e1e6", justify="left").grid(row=2, column=0, sticky="w")

        tabs = ctk.CTkFrame(panel, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 10))
        for col, tab in enumerate(("Overview", "Details", "Owner", "History")):
            active = col == 0
            ctk.CTkLabel(tabs, text=tab, height=34, fg_color="transparent", text_color="#00e1df" if active else "#a6b0b8", font=self._font(12, "bold" if active else "normal")).grid(row=0, column=col, padx=(0, 20), sticky="w")

        details = ctk.CTkFrame(panel, fg_color="transparent")
        details.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        details.grid_columnconfigure(1, weight=1)
        for idx, (label, value) in enumerate((
            ("Parcel ID", "26-017.00-123"),
            ("Acres", "1.24"),
            ("Zoning", "C-2 (Commercial)"),
            ("Land Use", "Vacant Land"),
            ("Last Sale", "$950,000 on 06/12/2021"),
            ("Assessed Value", "$1,125,400"),
            ("Tax Map", "26-17.00-123.00"),
        )):
            self._detail_row(details, idx, label, value)

        self._notes_section(panel, row=3)
        self._tags_section(panel, row=4)
        self._documents_section(panel, row=5)
        self._build_zoning_panel(panel, row=6)
        self._build_resource_panel(panel, row=7)
        self._build_layer_controls(panel, row=8)
        self._build_log_panel(panel, row=9)

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=10, column=0, sticky="ew", padx=12, pady=(0, 14))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Add to List      ⌄", height=44, corner_radius=6, fg_color="#0096a3", hover_color="#00aeba", text_color="#f1ffff", font=self._font(14, "bold")).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(footer, text="▥  Generate Report", height=42, corner_radius=6, fg_color="#061116", hover_color="#0b2027", border_color="#006e79", border_width=1, text_color="#00d6d6", font=self._font(14, "bold"), command=self._create_package).grid(row=1, column=0, sticky="ew")

    def _panel(self, parent, row: int, padx: int = 16, pady: tuple[int, int] | int = (0, 12), radius: int = 8) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(parent, corner_radius=radius, fg_color="#080d11", border_color="#1a2b32", border_width=1)
        panel.grid(row=row, column=0, sticky="ew", padx=padx, pady=pady)
        return panel

    def _card(self, parent, row: int, padx: int = 16) -> ctk.CTkFrame:
        return self._panel(parent, row=row, padx=padx)

    def _entry(self, parent, placeholder: str) -> ctk.CTkEntry:
        return ctk.CTkEntry(parent, placeholder_text=placeholder, height=38, corner_radius=7, fg_color="#05090d", border_color="#263a42", text_color="#edf6f7", placeholder_text_color="#68757c", font=self._font(14))

    def _nav_item(self, parent, icon: str, label: str, active: bool) -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, height=46, corner_radius=6, fg_color="#0c1b22" if active else "transparent")
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text=icon, width=34, font=self._font(18), text_color="#00d6d6" if active else "#c3ccd2").grid(row=0, column=0, padx=(12, 4), pady=8)
        ctk.CTkLabel(row, text=label, font=self._font(13, "bold" if active else "normal"), text_color="#00e5e2" if active else "#c7d0d6").grid(row=0, column=1, sticky="w")
        if active:
            ctk.CTkFrame(row, width=2, corner_radius=1, fg_color="#00d6d6").grid(row=0, column=0, sticky="nsw")
        return row

    def _quick_button(self, parent, icon: str, label: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(parent, text=f"{icon}   {label}", height=42, corner_radius=6, anchor="w", fg_color="#101820", hover_color="#15242b", text_color="#e2ecef", font=self._font(13), command=command)

    def _kpi_card(self, parent, icon: str, title: str, value: str, trend: str, accent: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, height=112, corner_radius=8, fg_color="#0a1015", border_color="#1c3037", border_width=1)
        card.grid_propagate(False)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=icon, width=40, height=40, corner_radius=20, fg_color="#07373b" if accent == "#00d6d6" else "#2a210d", text_color=accent, font=self._font(21)).grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=(16, 0), sticky="n")
        ctk.CTkLabel(card, text=title, font=self._font(11, "bold"), text_color="#c5cdd2").grid(row=0, column=1, sticky="w", pady=(18, 0))
        ctk.CTkLabel(card, text=value, font=self._font(25, "bold"), text_color="#ffffff").grid(row=1, column=1, sticky="w", pady=(4, 0))
        ctk.CTkLabel(card, text=trend, font=self._font(11), text_color="#00d6d6" if trend.startswith("↑") else "#9aa5ab").grid(row=2, column=1, sticky="w", pady=(4, 14))
        return card

    def _build_map_overlays(self) -> None:
        toggle = ctk.CTkFrame(self.preview_frame, fg_color="#071015", corner_radius=6, border_color="#13262d", border_width=1)
        toggle.grid(row=0, column=0, sticky="nw", padx=18, pady=18)
        ctk.CTkLabel(toggle, text="Aerial", width=72, height=36, corner_radius=5, fg_color="#006b78", text_color="#eaffff", font=self._font(13, "bold")).grid(row=0, column=0)
        ctk.CTkLabel(toggle, text="Satellite", width=84, height=36, text_color="#aab5bc", font=self._font(13)).grid(row=0, column=1)
        controls = ctk.CTkFrame(self.preview_frame, fg_color="#071015", corner_radius=7, border_color="#1a2d34", border_width=1)
        controls.grid(row=0, column=0, sticky="ne", padx=18, pady=18)
        for idx, icon in enumerate(("+", "−", "▧", "▽", "⊙")):
            ctk.CTkLabel(controls, text=icon, width=42, height=42, text_color="#e6eef1", font=self._font(20)).grid(row=idx, column=0)
        legend = ctk.CTkFrame(self.preview_frame, width=190, corner_radius=7, fg_color="#071015", border_color="#20343b", border_width=1)
        legend.grid(row=0, column=0, sticky="sw", padx=18, pady=18)
        ctk.CTkLabel(legend, text="PARCEL STATUS", font=self._font(11, "bold"), text_color="#f3f7f8").grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 8))
        for row, (dot, label, value) in enumerate((("#00d6d6", "Selected", "1"), ("#31d296", "Potential Lead", "87"), ("#ffc642", "Watchlist", "12"), ("#6e7a85", "Other", "4,882")), start=1):
            ctk.CTkLabel(legend, text="●", text_color=dot, font=self._font(13)).grid(row=row, column=0, sticky="w", padx=(12, 6), pady=(0, 7))
            ctk.CTkLabel(legend, text=label, text_color="#bdc8ce", font=self._font(12)).grid(row=row, column=1, sticky="w", pady=(0, 7))
            ctk.CTkLabel(legend, text=value, text_color="#ffffff", font=self._font(12, "bold")).grid(row=row, column=2, sticky="e", padx=(18, 12), pady=(0, 7))

    def _build_recent_table(self, parent, row: int) -> None:
        table = self._panel(parent, row=row, padx=0, pady=(0, 0), radius=8)
        table.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(table, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Recent Parcels", font=self._font(18, "bold"), text_color="#f3f7f8").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text="View All", font=self._font(13, "bold"), text_color="#00d6d6").grid(row=0, column=1, sticky="e")

        grid = ctk.CTkFrame(table, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        widths = (120, 190, 178, 78, 82, 130, 78)
        headers = ("PARCEL ID", "ADDRESS", "OWNER", "ACRES", "ZONING", "STATUS", "UPDATED")
        for col, (header, width) in enumerate(zip(headers, widths)):
            grid.grid_columnconfigure(col, minsize=width, weight=1 if col in (1, 2) else 0)
            ctk.CTkLabel(grid, text=header, font=self._font(10, "bold"), text_color="#8c99a4").grid(row=0, column=col, sticky="w", pady=(0, 8))
        rows = (
            ("26-017.00-123", "1021 Gilpin Ave\nWilmington, DE 19806", "Gilpin Holdings LLC", "1.24", "C-2", "POTENTIAL LEAD", "2h ago"),
            ("26-045.00-087", "3407 Cranston Ave\nWilmington, DE 19808", "Cranston Property Group", "0.18", "R-5", "WATCHLIST", "5h ago"),
            ("26-032.00-156", "3924 Kirkwood Hwy\nWilmington, DE 19808", "3924 Kirkwood LLC", "2.35", "C-3", "SELECTED", "1d ago"),
            ("26-019.00-044", "Sojourners Pl\nWilmington, DE 19801", "Sojourners Place Inc", "0.67", "R-3", "OTHER", "2d ago"),
            ("26-110.00-201", "1205 N French St\nWilmington, DE 19801", "NF Street Holdings", "0.92", "C-1", "POTENTIAL LEAD", "2d ago"),
        )
        for r, data in enumerate(rows, start=1):
            for c, value in enumerate(data):
                if c == 5:
                    self._status_pill(grid, value).grid(row=r, column=c, sticky="w", pady=7)
                else:
                    ctk.CTkLabel(grid, text=value, font=self._font(12), text_color="#d5dde1" if c != 1 else "#c8d2d8", justify="left").grid(row=r, column=c, sticky="w", pady=7)

    def _status_pill(self, parent, text: str) -> ctk.CTkLabel:
        colors = {
            "POTENTIAL LEAD": ("#063f3e", "#00f0df"),
            "WATCHLIST": ("#33250a", "#ffc642"),
            "SELECTED": ("#063340", "#00d6d6"),
            "OTHER": ("#141b22", "#c5cdd2"),
        }
        fg, tc = colors.get(text, ("#141b22", "#c5cdd2"))
        return ctk.CTkLabel(parent, text=text, height=26, corner_radius=13, fg_color=fg, text_color=tc, font=self._font(10, "bold"), padx=10)

    def _detail_row(self, parent, row: int, label: str, value: str) -> None:
        ctk.CTkLabel(parent, text=label, font=self._font(12), text_color="#8c99a3").grid(row=row, column=0, sticky="w", pady=7)
        ctk.CTkLabel(parent, text=value, font=self._font(12), text_color="#e0e9ed", justify="right").grid(row=row, column=1, sticky="e", pady=7)

    def _notes_section(self, parent, row: int) -> None:
        section = self._panel(parent, row=row, padx=0, pady=(0, 10), radius=0)
        section.configure(border_width=0, fg_color="#080d11")
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text="Notes", font=self._font(14, "bold"), text_color="#f0f5f7").grid(row=0, column=0, sticky="w", padx=18, pady=(14, 6))
        ctk.CTkLabel(section, text="+ Add Note", font=self._font(12, "bold"), text_color="#00d6d6").grid(row=0, column=1, sticky="e", padx=18)
        ctk.CTkLabel(section, text="Great redevelopment potential.\nSurrounded by new construction.\nCheck zoning variance history.", font=self._font(12), text_color="#d1dae0", justify="left").grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 14))

    def _tags_section(self, parent, row: int) -> None:
        section = self._panel(parent, row=row, padx=0, pady=(0, 10), radius=0)
        section.configure(border_width=0, fg_color="#080d11")
        ctk.CTkLabel(section, text="Tags", font=self._font(14, "bold"), text_color="#f0f5f7").grid(row=0, column=0, sticky="w", padx=18, pady=(14, 8))
        ctk.CTkLabel(section, text="+ Add Tag", font=self._font(12, "bold"), text_color="#00d6d6").grid(row=0, column=1, sticky="e", padx=18)
        ctk.CTkLabel(section, text="Redevelopment  ×", height=26, corner_radius=5, fg_color="#062f3d", text_color="#00d6d6", font=self._font(11)).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 14))
        ctk.CTkLabel(section, text="High Potential  ×", height=26, corner_radius=5, fg_color="#181d3a", text_color="#c7b5ff", font=self._font(11)).grid(row=1, column=1, sticky="w", padx=(0, 18), pady=(0, 14))

    def _documents_section(self, parent, row: int) -> None:
        section = self._panel(parent, row=row, padx=0, pady=(0, 10), radius=0)
        section.configure(border_width=0, fg_color="#080d11")
        ctk.CTkLabel(section, text="Documents", font=self._font(14, "bold"), text_color="#f0f5f7").grid(row=0, column=0, sticky="w", padx=18, pady=(14, 8))
        ctk.CTkLabel(section, text="View All", font=self._font(12, "bold"), text_color="#00d6d6").grid(row=0, column=2, sticky="e", padx=18)
        for idx, (name, size) in enumerate((("Deed_2021.pdf", "248 KB"), ("Survey_2021.pdf", "1.2 MB"), ("Zoning_Letter.pdf", "532 KB")), start=1):
            ctk.CTkLabel(section, text=f"▧  {name}", font=self._font(12), text_color="#b9c5cb").grid(row=idx, column=0, sticky="w", padx=18, pady=(0, 8))
            ctk.CTkLabel(section, text=size, font=self._font(11), text_color="#87939b").grid(row=idx, column=1, sticky="e", padx=8, pady=(0, 8))
            ctk.CTkLabel(section, text="⇩", font=self._font(14), text_color="#8f9aa2").grid(row=idx, column=2, sticky="e", padx=18, pady=(0, 8))

    def _load_logo_image(self, size: int) -> ctk.CTkImage | None:
        try:
            image = Image.open(resource_path("assets", "PropspectorIcon.png"))
            return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
        except Exception:
            logging.getLogger("parcel_packet").exception("Could not load PropSpector logo image")
            return None

    def _make_placeholder_aerial(self, width: int, height: int) -> Image.Image:
        image = Image.new("RGBA", (width, height), "#101417")
        draw = ImageDraw.Draw(image, "RGBA")
        for x in range(-200, width, 190):
            draw.polygon([(x, 0), (x + 74, 0), (x + 450, height), (x + 360, height)], fill=(38, 43, 42, 255))
            draw.line([(x + 34, 0), (x + 404, height)], fill=(96, 101, 96, 115), width=4)
        for y in range(-120, height, 150):
            draw.polygon([(0, y), (width, y + 180), (width, y + 220), (0, y + 42)], fill=(36, 39, 38, 255))
            draw.line([(0, y + 22), (width, y + 202)], fill=(92, 96, 90, 105), width=3)
        for x in range(40, width, 150):
            for y in range(28, height, 116):
                w = 70 + ((x + y) % 50)
                h = 38 + ((x * y) % 38)
                shade = 48 + ((x + y) % 34)
                draw.rounded_rectangle((x, y, x + w, y + h), radius=3, fill=(shade, shade, shade - 3, 230), outline=(118, 122, 114, 55))
        poly = [(760, 270), (830, 245), (900, 375), (780, 430), (725, 315)]
        draw.polygon(poly, fill=(0, 214, 214, 72), outline=(0, 237, 232, 255))
        draw.line(poly + [poly[0]], fill=(0, 237, 232, 255), width=3)
        draw.ellipse((805, 304, 842, 341), fill=(0, 214, 214, 255))
        draw.polygon([(823, 365), (805, 331), (842, 331)], fill=(0, 214, 214, 255))
        draw.ellipse((819, 318, 829, 328), fill=(2, 18, 24, 255))
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 65))
        image = Image.alpha_composite(image, overlay).filter(ImageFilter.GaussianBlur(0.25))
        return image

    def _refresh_preview(self) -> None:
        if not hasattr(self, "preview_image_label"):
            return
        if self.preview_bundle is None:
            canvas = self.placeholder_aerial.copy()
        else:
            canvas = self.preview_bundle.base_image.copy()
            for name in RESOURCE_STATUS_ORDER:
                var = self.preview_layer_vars.get(name)
                if var is not None and var.get():
                    layer = self.preview_bundle.layer_images.get(name)
                    if layer is not None:
                        canvas.alpha_composite(layer)
            canvas.alpha_composite(self.preview_bundle.parcel_outline_image)
            canvas.alpha_composite(self.preview_bundle.road_overlay_image)
        max_width = max(780, self.preview_image_label.winfo_width() - 2)
        max_height = max(460, self.preview_image_label.winfo_height() - 2)
        image = canvas.copy()
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self.preview_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.preview_image_label.configure(image=self.preview_image, text="")

    def _build_left_rail(self) -> None:
        header = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(30, 30))
        header.grid_columnconfigure(1, weight=1)
        if self.logo_image:
            ctk.CTkLabel(header, image=self.logo_image, text="").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ctk.CTkLabel(header, text="Prop", font=self._font(25, "bold"), text_color="#f4fbfb").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(header, text="Spector", font=self._font(25, "bold"), text_color="#00d8d8").grid(row=0, column=1, sticky="w", padx=(55, 0))

        nav = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=14)
        nav.grid_columnconfigure(0, weight=1)
        for index, (icon, label, active) in enumerate((
            ("⌂", "Dashboard", True),
            ("◇", "Map Explorer", False),
            ("‹›", "Code Logic", False),
            ("▥", "Reports", False),
            ("▧", "Development Options", False),
            ("♙", "Demographics", False),
            ("⚙", "Settings", False),
        )):
            self._nav_item(nav, icon, label, active).grid(row=index, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkFrame(self.left_rail, fg_color="transparent").grid(row=2, column=0, sticky="nsew")

        quick = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        quick.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 28))
        quick.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(quick, text="QUICK ACTIONS", font=self._font(11), text_color="#9aa3aa").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.run_button = self._quick_button(quick, "+", "New Search", self._run_or_cancel)
        self.run_button.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._quick_button(quick, "⇩", "Import Parcels", self._browse).grid(row=2, column=0, sticky="ew")

        account = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        account.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 24))
        account.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(account, text="ZM", width=48, height=48, corner_radius=24, fg_color="#101820", border_color="#1c2b32", border_width=1, text_color="#f8ffff", font=self._font(15, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(account, text="Zak Morris", font=self._font(13, "bold"), text_color="#eef5f7").grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(account, text="Administrator", font=self._font(12), text_color="#9aa5ab").grid(row=1, column=1, sticky="nw")
        ctk.CTkLabel(account, text="⌄", font=self._font(18), text_color="#d4dde1").grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(account, text="⚙", font=self._font(15), text_color="#aeb8be").grid(row=1, column=2, sticky="e")

    def _build_preview_area(self) -> None:
        top = ctk.CTkFrame(self.preview_shell, height=74, fg_color="#05080b", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(16, 0))
        top.grid_columnconfigure(0, weight=1)

        search = ctk.CTkFrame(top, height=56, corner_radius=8, fg_color="#0b1014", border_color="#1d3038", border_width=1)
        search.grid(row=0, column=0, sticky="w", padx=(0, 0))
        search.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search, text="⌕", font=self._font(24), text_color="#bac7ce").grid(row=0, column=0, padx=(16, 8))
        self.parcel_entry = ctk.CTkEntry(
            search,
            width=520,
            placeholder_text="Search by Address, Owner, Parcel ID...",
            height=44,
            border_width=0,
            fg_color="transparent",
            text_color="#eef6f7",
            placeholder_text_color="#858e94",
            font=self._font(14),
        )
        self.parcel_entry.grid(row=0, column=1, sticky="ew")
        self.parcel_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())
        self.parcel_entry.bind("<Return>", lambda _event: self._run_or_cancel())
        ctk.CTkLabel(search, text="⌘  K", width=52, height=30, corner_radius=6, fg_color="#0f171c", border_color="#1b2a31", border_width=1, text_color="#c3cbd0", font=self._font(12, "bold")).grid(row=0, column=2, padx=10)

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.grid(row=0, column=1, sticky="e")
        for idx, (icon, badge) in enumerate((("☾", ""), ("♢", "3"), ("?", ""), ("ZM", ""), ("⌄", ""))):
            button = ctk.CTkButton(
                tools,
                text=icon if not badge else f"{icon}",
                width=40 if icon != "ZM" else 44,
                height=40 if icon != "ZM" else 44,
                corner_radius=22,
                fg_color="#111922" if icon == "ZM" else "transparent",
                hover_color="#121d24",
                text_color="#e4edf0",
                font=self._font(15, "bold" if icon == "ZM" else "normal"),
            )
            button.grid(row=0, column=idx, padx=(6, 0))
            if badge:
                ctk.CTkLabel(tools, text=badge, width=17, height=17, corner_radius=8, fg_color="#00d6d6", text_color="#041012", font=self._font(9, "bold")).grid(row=0, column=idx, sticky="ne", padx=(0, 0), pady=(0, 22))

        content = ctk.CTkFrame(self.preview_shell, corner_radius=0, fg_color="#05080b")
        content.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(4, 16))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, minsize=455)
        content.grid_rowconfigure(1, weight=1)

        self.preview_frame = self._panel(content, row=0, padx=0, pady=(0, 12), radius=8)
        self.preview_frame.grid(sticky="nsew")
        self.preview_frame.grid_columnconfigure(0, weight=1)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_image_label = ctk.CTkLabel(self.preview_frame, text="", fg_color="#030608", text_color="#6f7b76", font=self._font(18))
        self.preview_image_label.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.preview_image_label.bind("<Configure>", lambda _event: self._refresh_preview())
        self._build_map_overlays()
        self._build_layer_manager(content, row=1)

        self.folder_entry = self._entry(content, "Destination folder")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid_remove()
        self.group_menu = ctk.CTkOptionMenu(content, values=list(ENVIRONMENTAL_MENU_GROUPS))
        self.group_menu.set("All Resources")
        self.group_menu.grid_remove()
        self.intended_use_entry = self._entry(content, "Optional intended use")
        self.intended_use_entry.grid_remove()
        self.preview_status = ctk.CTkLabel(content, text="", font=self._font(12), text_color="#8fa1aa")
        self.preview_status.grid_remove()
        self.preview_facts = ctk.CTkLabel(content, text="", font=self._font(12), text_color="#b8c9c1", justify="right")
        self.preview_facts.grid_remove()
        self._build_hidden_runtime_panels(content)
        self._refresh_preview()

    def _build_details_panel(self) -> None:
        panel = ctk.CTkScrollableFrame(self.right_rail, corner_radius=8, fg_color="#070b0f", border_color="#1b2b32", border_width=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(4, 14), pady=(74, 16))
        panel.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="26-017.00-123 ☆", font=self._font(20, "bold"), text_color="#f4fbfb").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="×", font=self._font(26), text_color="#a8b3b9").grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(header, text="POTENTIAL LEAD", height=22, corner_radius=5, fg_color="#063d42", text_color="#00f0e6", font=self._font(10, "bold")).grid(row=1, column=0, sticky="w", pady=(7, 9))
        ctk.CTkLabel(header, text="1021 Gilpin Ave\nWilmington, DE 19806\nNew Castle County", font=self._font(13), text_color="#d6e1e6", justify="left").grid(row=2, column=0, sticky="w")

        tabs = ctk.CTkFrame(panel, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 10))
        for col, tab in enumerate(("Overview", "Details", "Owner", "History")):
            active = col == 0
            ctk.CTkLabel(tabs, text=tab, height=34, text_color="#00e1df" if active else "#a6b0b8", font=self._font(12, "bold" if active else "normal")).grid(row=0, column=col, padx=(0, 26), sticky="w")
        ctk.CTkFrame(tabs, height=2, fg_color="#00d6d6").grid(row=1, column=0, sticky="ew")

        details_card = ctk.CTkFrame(panel, corner_radius=6, fg_color="#0a1014", border_color="#172830", border_width=1)
        details_card.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        details_card.grid_columnconfigure(1, weight=1)
        for idx, (label, value) in enumerate((
            ("▧  Parcel ID", "26-017.00-123"),
            ("♧  Acres", "1.24"),
            ("▣  Zoning", "C-2 (Commercial)"),
            ("▢  Land Use", "Vacant Land"),
            ("◇  Last Sale", "$950,000 on 06/12/2021"),
            ("⌂  Assessed Value", "$1,125,400"),
            ("▤  Tax Map", "26-17.00-123.00"),
        )):
            ctk.CTkLabel(details_card, text=label, font=self._font(12), text_color="#9aa6ad").grid(row=idx, column=0, sticky="w", padx=(12, 8), pady=8)
            ctk.CTkLabel(details_card, text=value, font=self._font(12), text_color="#e0e9ed").grid(row=idx, column=1, sticky="e", padx=(8, 12), pady=8)

        self._notes_section(panel, row=3)
        self._tags_section(panel, row=4)
        self._documents_section(panel, row=5)

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=12, pady=(4, 14))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Add to List                         ⌄", height=44, corner_radius=6, fg_color="#0096a3", hover_color="#00aeba", text_color="#f1ffff", font=self._font(14, "bold")).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.package_button = ctk.CTkButton(footer, text="▥  Generate Report", height=42, corner_radius=6, fg_color="#061116", hover_color="#0b2027", border_color="#006e79", border_width=1, text_color="#00d6d6", font=self._font(14, "bold"), command=self._create_package)
        self.package_button.grid(row=1, column=0, sticky="ew")
        self.package_button.configure(state="disabled")

    def _build_map_overlays(self) -> None:
        toggle = ctk.CTkFrame(self.preview_frame, fg_color="#071015", corner_radius=6, border_color="#13262d", border_width=1)
        toggle.grid(row=0, column=0, sticky="nw", padx=16, pady=14)
        ctk.CTkLabel(toggle, text="Aerial", width=74, height=40, corner_radius=5, fg_color="#006b78", text_color="#eaffff", font=self._font(13, "bold")).grid(row=0, column=0)
        ctk.CTkLabel(toggle, text="Satellite", width=86, height=40, text_color="#aab5bc", font=self._font(13)).grid(row=0, column=1)
        controls = ctk.CTkFrame(self.preview_frame, fg_color="#071015", corner_radius=7, border_color="#1a2d34", border_width=1)
        controls.grid(row=0, column=0, sticky="ne", padx=16, pady=14)
        for idx, icon in enumerate(("+", "−", "▧", "▽", "⊙")):
            ctk.CTkLabel(controls, text=icon, width=44, height=44, text_color="#e6eef1", font=self._font(21)).grid(row=idx, column=0)
        legend = ctk.CTkFrame(self.preview_frame, width=178, corner_radius=7, fg_color="#071015", border_color="#20343b", border_width=1)
        legend.grid(row=0, column=0, sticky="sw", padx=14, pady=14)
        ctk.CTkLabel(legend, text="Parcel Status", font=self._font(13, "bold"), text_color="#f3f7f8").grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
        for row, (dot, label, value) in enumerate((("#00d6d6", "Selected", "1"), ("#25d2bb", "Potential Lead", "87"), ("#ffc642", "Watchlist", "12"), ("#6e7a85", "Other", "4,882")), start=1):
            ctk.CTkLabel(legend, text="●", text_color=dot, font=self._font(13)).grid(row=row, column=0, sticky="w", padx=(14, 6), pady=(0, 9))
            ctk.CTkLabel(legend, text=label, text_color="#bdc8ce", font=self._font(12)).grid(row=row, column=1, sticky="w", pady=(0, 9))
            ctk.CTkLabel(legend, text=value, text_color="#ffffff", font=self._font(12, "bold")).grid(row=row, column=2, sticky="e", padx=(18, 14), pady=(0, 9))

    def _build_layer_manager(self, parent, row: int) -> None:
        manager = self._panel(parent, row=row, padx=0, pady=(0, 0), radius=8)
        manager.grid(sticky="nsew")
        manager.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(manager, text="Layer Manager", font=self._font(17, "bold"), text_color="#f2f7f8").grid(row=0, column=0, sticky="w", padx=18, pady=(16, 10))
        ctk.CTkLabel(manager, text="⌁", font=self._font(16), text_color="#c8d2d8").grid(row=0, column=0, sticky="e", padx=20)
        tabs = ctk.CTkFrame(manager, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        for col, tab in enumerate(("Environmental", "Physical", "Zoning & Planning", "Infrastructure", "Boundaries", "Risk")):
            ctk.CTkLabel(tabs, text=tab, height=30, text_color="#00dedb" if col == 0 else "#a7b0b7", font=self._font(12, "bold" if col == 0 else "normal")).grid(row=0, column=col, padx=(0, 28), sticky="w")
        ctk.CTkFrame(tabs, height=2, fg_color="#00d6d6").grid(row=1, column=0, sticky="ew")
        rows = ctk.CTkFrame(manager, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 16))
        rows.grid_columnconfigure(0, weight=1)
        layer_rows = (
            ("≋", "Flood Hazard Zones (FEMA)", "1% Annual Chance Flood Hazard", "#063849", True, "65%"),
            ("♧", "Wetlands (NWI)", "National Wetlands Inventory", "#0c3d28", True, "70%"),
            ("▱", "Soils (SSURGO)", "Soil Survey Geographic Database", "#3a2315", True, "60%"),
            ("⌂", "Protected Areas", "Conservation & Protected Lands", "#3b310c", True, "50%"),
            ("♙", "Environmental Justice Index", "EPA EJScreen 2.0", "#18333b", False, "0%"),
            ("♦", "Wildfire Risk", "Wildfire Hazard Potential", "#3d2410", False, "0%"),
        )
        for idx, item in enumerate(layer_rows):
            self._layer_row(rows, idx, *item)

    def _layer_row(self, parent, row: int, icon: str, title: str, sub: str, icon_bg: str, visible: bool, pct: str) -> None:
        item = ctk.CTkFrame(parent, height=56, corner_radius=6, fg_color="#10171c", border_color="#111d23", border_width=1)
        item.grid(row=row, column=0, columnspan=7, sticky="ew", pady=3)
        item.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(item, text=icon, width=34, height=34, corner_radius=5, fg_color=icon_bg, text_color="#00d6d6" if visible else "#9aa5ab", font=self._font(16)).grid(row=0, column=0, rowspan=2, padx=(10, 12), pady=10)
        ctk.CTkLabel(item, text=title, font=self._font(14), text_color="#eef5f7").grid(row=0, column=1, sticky="sw", pady=(8, 0))
        ctk.CTkLabel(item, text=sub, font=self._font(11), text_color="#9aa5ab").grid(row=1, column=1, sticky="nw", pady=(0, 8))
        ctk.CTkLabel(item, text="◉" if visible else "◌", font=self._font(17), text_color="#00d6d6" if visible else "#66727a").grid(row=0, column=2, rowspan=2, padx=16)
        bar = ctk.CTkFrame(item, width=170, height=3, fg_color="#263039")
        bar.grid(row=0, column=3, rowspan=2, padx=(8, 10))
        fill_width = int(170 * int(pct.rstrip("%")) / 100)
        ctk.CTkFrame(bar, width=max(fill_width, 0), height=3, fg_color="#00d6d6").place(x=0, y=0)
        ctk.CTkLabel(bar, text="", width=10, height=10, corner_radius=5, fg_color="#edf4f6").place(x=max(fill_width - 5, 0), y=-4)
        ctk.CTkLabel(item, text=pct, font=self._font(12), text_color="#b9c4ca").grid(row=0, column=4, rowspan=2, padx=(0, 22))
        ctk.CTkLabel(item, text="ⓘ", font=self._font(15), text_color="#aeb8be").grid(row=0, column=5, rowspan=2, padx=(0, 22))
        ctk.CTkLabel(item, text="⋮", font=self._font(20), text_color="#aeb8be").grid(row=0, column=6, rowspan=2, padx=(0, 14))

    def _build_hidden_runtime_panels(self, parent) -> None:
        hidden = ctk.CTkFrame(parent, fg_color="transparent")
        hidden.grid(row=99, column=0)
        hidden.grid_remove()
        self.layer_controls = ctk.CTkFrame(hidden, fg_color="transparent")
        self.layer_controls.grid(row=0, column=0)
        for index, name in enumerate(RESOURCE_STATUS_ORDER):
            var = ctk.BooleanVar(value=False)
            self.preview_layer_vars[name] = var
            ctk.CTkCheckBox(self.layer_controls, text=name, variable=var, command=self._refresh_preview, state="disabled").grid(row=index, column=0)
        self.resource_rows = ctk.CTkFrame(hidden, fg_color="transparent")
        self.resource_rows.grid(row=1, column=0)
        self.zoning_snapshot = ctk.CTkLabel(hidden, text="")
        self.zoning_snapshot.grid(row=2, column=0)
        self.zoning_activity = ctk.CTkProgressBar(hidden)
        self.zoning_activity.grid(row=3, column=0)
        self.zoning_activity.grid_remove()
        self.zoning_rows = ctk.CTkFrame(hidden, fg_color="transparent")
        self.zoning_rows.grid(row=4, column=0)
        self.log_box = ctk.CTkTextbox(hidden)
        self.log_box.grid(row=5, column=0)
        self.log_box.configure(state="disabled")

    def _make_placeholder_aerial(self, width: int, height: int) -> Image.Image:
        image = Image.new("RGBA", (width, height), "#111517")
        draw = ImageDraw.Draw(image, "RGBA")
        for x in range(-120, width, 140):
            for y in range(-80, height, 92):
                shade = 42 + ((x * 7 + y * 3) % 38)
                draw.rounded_rectangle((x, y, x + 82, y + 46), radius=2, fill=(shade, shade, shade - 2, 230), outline=(120, 124, 116, 50))
        for x in (430, 720, 1010):
            draw.polygon([(x, -50), (x + 60, -50), (x + 250, height + 50), (x + 185, height + 50)], fill=(48, 51, 49, 245))
            draw.line([(x + 30, -50), (x + 218, height + 50)], fill=(126, 126, 116, 120), width=3)
        for y in (105, 330, 575):
            draw.polygon([(-50, y), (width + 50, y + 80), (width + 50, y + 120), (-50, y + 40)], fill=(43, 46, 45, 245))
            draw.line([(-50, y + 20), (width + 50, y + 100)], fill=(116, 118, 108, 100), width=3)
        for x in range(0, width, 54):
            draw.ellipse((x, 20 + (x * 3) % height, x + 48, 68 + (x * 3) % height), fill=(20, 42, 27, 150))
        poly = [(765, 205), (895, 160), (1010, 475), (840, 555), (710, 255)]
        draw.polygon(poly, fill=(0, 214, 214, 72), outline=(0, 237, 232, 255))
        draw.line(poly + [poly[0]], fill=(0, 237, 232, 255), width=3)
        draw.ellipse((845, 315, 884, 354), fill=(0, 214, 214, 255))
        draw.polygon([(865, 386), (845, 347), (884, 347)], fill=(0, 214, 214, 255))
        draw.ellipse((860, 330, 870, 340), fill=(2, 18, 24, 255))
        vignette = Image.new("RGBA", (width, height), (0, 0, 0, 70))
        image = Image.alpha_composite(image, vignette).filter(ImageFilter.GaussianBlur(0.2))
        return image

    def _sync_run_button_state(self, running: bool | None = None) -> None:
        is_running = self.running_jobs > 0 if running is None else running
        new_search_pending = is_running and self._current_research_key() != self.active_research_key
        self.run_button.configure(
            state="normal",
            text="+   New Search" if new_search_pending or not is_running else "×   Cancel Search",
            fg_color="#101820" if new_search_pending or not is_running else "#32191c",
            hover_color="#15242b" if new_search_pending or not is_running else "#482128",
            text_color="#e2ecef",
        )

    def _build_map_overlays(self) -> None:
        return

    def _make_placeholder_aerial(self, width: int, height: int) -> Image.Image:
        placeholder_path = resource_path("assets", "dashboard_aerial_placeholder.png")
        if placeholder_path.exists():
            return Image.open(placeholder_path).convert("RGBA")
        image = Image.new("RGBA", (width, height), "#111517")
        draw = ImageDraw.Draw(image, "RGBA")
        for x in range(-120, width, 140):
            for y in range(-80, height, 92):
                shade = 42 + ((x * 7 + y * 3) % 38)
                draw.rounded_rectangle((x, y, x + 82, y + 46), radius=2, fill=(shade, shade, shade - 2, 230), outline=(120, 124, 116, 50))
        for x in (430, 720, 1010):
            draw.polygon([(x, -50), (x + 60, -50), (x + 250, height + 50), (x + 185, height + 50)], fill=(48, 51, 49, 245))
            draw.line([(x + 30, -50), (x + 218, height + 50)], fill=(126, 126, 116, 120), width=3)
        for y in (105, 330, 575):
            draw.polygon([(-50, y), (width + 50, y + 80), (width + 50, y + 120), (-50, y + 40)], fill=(43, 46, 45, 245))
            draw.line([(-50, y + 20), (width + 50, y + 100)], fill=(116, 118, 108, 100), width=3)
        poly = [(765, 205), (895, 160), (1010, 475), (840, 555), (710, 255)]
        draw.polygon(poly, fill=(0, 214, 214, 72), outline=(0, 237, 232, 255))
        draw.line(poly + [poly[0]], fill=(0, 237, 232, 255), width=3)
        draw.ellipse((845, 315, 884, 354), fill=(0, 214, 214, 255))
        draw.polygon([(865, 386), (845, 347), (884, 347)], fill=(0, 214, 214, 255))
        return image

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, minsize=292)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=640)
        self.grid_rowconfigure(0, weight=1)

        self.logo_image = self._load_logo_image(34)
        self.placeholder_aerial = self._make_placeholder_aerial(1500, 760)

        self.left_rail = ctk.CTkFrame(self, width=292, corner_radius=0, fg_color="#04080b")
        self.left_rail.grid(row=0, column=0, sticky="nsew")
        self.left_rail.grid_columnconfigure(0, weight=1)
        self.left_rail.grid_rowconfigure(2, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#05080b")
        self.preview_shell.grid(row=0, column=1, sticky="nsew")
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self.right_rail = ctk.CTkFrame(self, width=640, corner_radius=0, fg_color="#05080b")
        self.right_rail.grid(row=0, column=2, sticky="nsew")
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

        self._build_left_rail()
        self._build_preview_area()
        self._build_details_panel()

    def _refresh_preview(self) -> None:
        if not hasattr(self, "preview_image_label"):
            return
        if self.preview_bundle is None:
            canvas = self.placeholder_aerial.copy()
        else:
            canvas = self.preview_bundle.base_image.copy()
            for name in RESOURCE_STATUS_ORDER:
                var = self.preview_layer_vars.get(name)
                if var is not None and var.get():
                    layer = self.preview_bundle.layer_images.get(name)
                    if layer is not None:
                        canvas.alpha_composite(layer)
            canvas.alpha_composite(self.preview_bundle.parcel_outline_image)
            canvas.alpha_composite(self.preview_bundle.road_overlay_image)
        width = min(max(900, self.preview_image_label.winfo_width() - 2), 1500)
        height = 450
        image = canvas.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
        self.preview_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.preview_image_label.configure(image=self.preview_image, text="")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, minsize=292)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=520)
        self.grid_rowconfigure(0, weight=1)

        self.logo_image = self._load_logo_image(34)
        self.layer_manager_visible = True

        self.left_rail = ctk.CTkFrame(self, width=292, corner_radius=0, fg_color="#04080b")
        self.left_rail.grid(row=0, column=0, sticky="nsew")
        self.left_rail.grid_columnconfigure(0, weight=1)
        self.left_rail.grid_rowconfigure(2, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#05080b")
        self.preview_shell.grid(row=0, column=1, sticky="nsew")
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self.right_rail = ctk.CTkFrame(self, width=520, corner_radius=0, fg_color="#05080b")
        self.right_rail.grid(row=0, column=2, sticky="nsew")
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

        self._build_left_rail()
        self._build_preview_area()
        self._build_details_panel()

    def _build_preview_area(self) -> None:
        top = ctk.CTkFrame(self.preview_shell, height=74, fg_color="#05080b", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(16, 0))
        top.grid_columnconfigure(0, weight=1)

        search = ctk.CTkFrame(top, height=56, corner_radius=8, fg_color="#0b1014", border_color="#1d3038", border_width=1)
        search.grid(row=0, column=0, sticky="w")
        search.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search, text="⌕", font=self._font(24), text_color="#bac7ce").grid(row=0, column=0, padx=(16, 8))
        self.parcel_entry = ctk.CTkEntry(
            search,
            width=520,
            placeholder_text="Search by Address, Owner, Parcel ID...",
            height=44,
            border_width=0,
            fg_color="transparent",
            text_color="#eef6f7",
            placeholder_text_color="#858e94",
            font=self._font(14),
        )
        self.parcel_entry.grid(row=0, column=1, sticky="ew")
        self.parcel_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())
        self.parcel_entry.bind("<Return>", lambda _event: self._run_or_cancel())
        ctk.CTkLabel(search, text="⌘  K", width=52, height=30, corner_radius=6, fg_color="#0f171c", border_color="#1b2a31", border_width=1, text_color="#c3cbd0", font=self._font(12, "bold")).grid(row=0, column=2, padx=10)

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.grid(row=0, column=1, sticky="e")
        for idx, (icon, badge) in enumerate((("☾", ""), ("♢", "3"), ("?", ""), ("ZM", ""), ("⌄", ""))):
            ctk.CTkButton(
                tools,
                text=icon,
                width=40 if icon != "ZM" else 44,
                height=40 if icon != "ZM" else 44,
                corner_radius=22,
                fg_color="#111922" if icon == "ZM" else "transparent",
                hover_color="#121d24",
                text_color="#e4edf0",
                font=self._font(15, "bold" if icon == "ZM" else "normal"),
            ).grid(row=0, column=idx, padx=(6, 0))
            if badge:
                ctk.CTkLabel(tools, text=badge, width=17, height=17, corner_radius=8, fg_color="#00d6d6", text_color="#041012", font=self._font(9, "bold")).grid(row=0, column=idx, sticky="ne", pady=(0, 22))

        content = ctk.CTkFrame(self.preview_shell, corner_radius=0, fg_color="#05080b")
        content.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(4, 16))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=3, minsize=450)
        content.grid_rowconfigure(1, weight=2, minsize=340)
        self.main_content = content

        self.map_viewport = self._panel(content, row=0, padx=0, pady=(0, 12), radius=8)
        self.map_viewport.grid(sticky="nsew")
        self.map_viewport.grid_columnconfigure(0, weight=1)
        self.map_viewport.grid_rowconfigure(0, weight=1)
        self.map_canvas = ctk.CTkCanvas(self.map_viewport, bg="#05090c", highlightthickness=0, bd=0)
        self.map_canvas.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.map_canvas.bind("<Configure>", lambda _event: self._draw_map_surface())
        self._build_map_chrome()

        self._build_layer_manager(content, row=1)

        self.folder_entry = self._entry(content, "Destination folder")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid_remove()
        self.group_menu = ctk.CTkOptionMenu(content, values=list(ENVIRONMENTAL_MENU_GROUPS))
        self.group_menu.set("All Resources")
        self.group_menu.grid_remove()
        self.intended_use_entry = self._entry(content, "Optional intended use")
        self.intended_use_entry.grid_remove()
        self.preview_status = ctk.CTkLabel(content, text="", font=self._font(12), text_color="#8fa1aa")
        self.preview_status.grid_remove()
        self.preview_facts = ctk.CTkLabel(content, text="", font=self._font(12), text_color="#b8c9c1", justify="right")
        self.preview_facts.grid_remove()
        self._build_hidden_runtime_panels(content)
        self.after(80, self._draw_map_surface)

    def _build_map_chrome(self) -> None:
        toggle = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=6, border_color="#13262d", border_width=1)
        toggle.place(x=16, y=14)
        ctk.CTkLabel(toggle, text="Aerial", width=74, height=40, corner_radius=5, fg_color="#006b78", text_color="#eaffff", font=self._font(13, "bold")).grid(row=0, column=0)
        ctk.CTkLabel(toggle, text="Satellite", width=86, height=40, text_color="#aab5bc", font=self._font(13)).grid(row=0, column=1)

        controls = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#1a2d34", border_width=1)
        controls.place(relx=1, x=-16, y=14, anchor="ne")
        for idx, icon in enumerate(("+", "−", "▧", "▽", "⊙")):
            ctk.CTkButton(controls, text=icon, width=44, height=44, corner_radius=0, fg_color="transparent", hover_color="#101b22", text_color="#e6eef1", font=self._font(21)).grid(row=idx, column=0)

        legend = ctk.CTkFrame(self.map_viewport, width=178, corner_radius=7, fg_color="#071015", border_color="#20343b", border_width=1)
        legend.place(x=16, rely=1, y=-16, anchor="sw")
        ctk.CTkLabel(legend, text="Parcel Status", font=self._font(13, "bold"), text_color="#f3f7f8").grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
        for row, (dot, label, value) in enumerate((("#00d6d6", "Selected", "1"), ("#25d2bb", "Potential Lead", "87"), ("#ffc642", "Watchlist", "12"), ("#6e7a85", "Other", "4,882")), start=1):
            ctk.CTkLabel(legend, text="●", text_color=dot, font=self._font(13)).grid(row=row, column=0, sticky="w", padx=(14, 6), pady=(0, 9))
            ctk.CTkLabel(legend, text=label, text_color="#bdc8ce", font=self._font(12)).grid(row=row, column=1, sticky="w", pady=(0, 9))
            ctk.CTkLabel(legend, text=value, text_color="#ffffff", font=self._font(12, "bold")).grid(row=row, column=2, sticky="e", padx=(18, 14), pady=(0, 9))

        self.layers_restore_button = ctk.CTkButton(
            self.map_viewport,
            text="▤",
            width=44,
            height=38,
            corner_radius=7,
            fg_color="#071015",
            hover_color="#102029",
            border_color="#1a2d34",
            border_width=1,
            text_color="#00d6d6",
            font=self._font(18),
            command=self._toggle_layer_manager,
        )

    def _build_layer_manager(self, parent, row: int) -> None:
        manager = self._panel(parent, row=row, padx=0, pady=(0, 0), radius=8)
        manager.grid(sticky="nsew")
        manager.grid_columnconfigure(0, weight=1)
        self.layer_manager = manager

        header = ctk.CTkFrame(manager, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Layer Manager", font=self._font(17, "bold"), text_color="#f2f7f8").grid(row=0, column=0, sticky="w")
        self.layer_toggle_button = ctk.CTkButton(
            header,
            text="⌄",
            width=34,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#101b22",
            text_color="#c8d2d8",
            font=self._font(16),
            command=self._toggle_layer_manager,
        )
        self.layer_toggle_button.grid(row=0, column=1, sticky="e")

        tabs = ctk.CTkFrame(manager, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        for col, tab in enumerate(("Environmental", "Physical", "Zoning & Planning", "Infrastructure", "Boundaries", "Risk")):
            ctk.CTkLabel(tabs, text=tab, height=30, text_color="#00dedb" if col == 0 else "#a7b0b7", font=self._font(12, "bold" if col == 0 else "normal")).grid(row=0, column=col, padx=(0, 28), sticky="w")
        ctk.CTkFrame(tabs, height=2, fg_color="#00d6d6").grid(row=1, column=0, sticky="ew")

        rows = ctk.CTkFrame(manager, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 16))
        rows.grid_columnconfigure(0, weight=1)
        for idx, item in enumerate((
            ("≋", "Flood Hazard Zones (FEMA)", "1% Annual Chance Flood Hazard", "#063849", True, "65%"),
            ("♧", "Wetlands (NWI)", "National Wetlands Inventory", "#0c3d28", True, "70%"),
            ("▱", "Soils (SSURGO)", "Soil Survey Geographic Database", "#3a2315", True, "60%"),
            ("⌂", "Protected Areas", "Conservation & Protected Lands", "#3b310c", True, "50%"),
            ("♙", "Environmental Justice Index", "EPA EJScreen 2.0", "#18333b", False, "0%"),
            ("♦", "Wildfire Risk", "Wildfire Hazard Potential", "#3d2410", False, "0%"),
        )):
            self._layer_row(rows, idx, *item)

    def _toggle_layer_manager(self) -> None:
        self.layer_manager_visible = not self.layer_manager_visible
        if self.layer_manager_visible:
            self.layer_manager.grid()
            self.main_content.grid_rowconfigure(0, weight=3, minsize=450)
            self.main_content.grid_rowconfigure(1, weight=2, minsize=340)
            self.layers_restore_button.place_forget()
            self.layer_toggle_button.configure(text="⌄")
        else:
            self.layer_manager.grid_remove()
            self.main_content.grid_rowconfigure(0, weight=1, minsize=0)
            self.main_content.grid_rowconfigure(1, weight=0, minsize=0)
            self.layers_restore_button.place(relx=1, x=-70, y=14, anchor="ne")
            self.layer_toggle_button.configure(text="⌃")
        self.after(80, self._draw_map_surface)

    def _draw_map_surface(self) -> None:
        if not hasattr(self, "map_canvas"):
            return
        canvas = self.map_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#071012", outline="")

        for x in range(-80, width + 120, 128):
            for y in range(-50, height + 100, 84):
                shade = 35 + ((x * 5 + y * 3) % 38)
                fill = f"#{shade:02x}{shade:02x}{max(shade - 4, 0):02x}"
                canvas.create_rectangle(x, y, x + 78, y + 38, fill=fill, outline="#3c4544")

        for offset in (-120, 170, 470, 760, 1040):
            canvas.create_polygon(offset, -80, offset + 58, -80, offset + width * 0.16 + 120, height + 80, offset + width * 0.16 + 55, height + 80, fill="#272d2c", outline="")
            canvas.create_line(offset + 30, -80, offset + width * 0.16 + 88, height + 80, fill="#515a55", width=2)
        for y in (height * 0.2, height * 0.47, height * 0.77):
            canvas.create_polygon(-80, y, width + 80, y + 62, width + 80, y + 100, -80, y + 38, fill="#242a29", outline="")
            canvas.create_line(-80, y + 18, width + 80, y + 80, fill="#4a514d", width=2)

        for x in range(20, width, 185):
            y = 25 + ((x * 7) % max(height - 80, 1))
            canvas.create_oval(x, y, x + 54, y + 54, fill="#062011", outline="")

        parcel = (
            width * 0.47, height * 0.28,
            width * 0.59, height * 0.22,
            width * 0.69, height * 0.72,
            width * 0.54, height * 0.83,
            width * 0.43, height * 0.36,
        )
        canvas.create_polygon(parcel, fill="#003f40", outline="#00d6d6", width=3)
        canvas.create_polygon(parcel, fill="#008b8b", outline="", stipple="gray50")

        pin_x = width * 0.57
        pin_y = height * 0.50
        pin_r = max(16, min(width, height) * 0.035)
        canvas.create_oval(pin_x - pin_r, pin_y - pin_r, pin_x + pin_r, pin_y + pin_r, fill="#00cbd4", outline="")
        canvas.create_polygon(pin_x - pin_r * 0.55, pin_y + pin_r * 0.45, pin_x + pin_r * 0.55, pin_y + pin_r * 0.45, pin_x, pin_y + pin_r * 2.1, fill="#00cbd4", outline="")
        canvas.create_oval(pin_x - pin_r * 0.25, pin_y - pin_r * 0.25, pin_x + pin_r * 0.25, pin_y + pin_r * 0.25, fill="#061217", outline="")
        canvas.create_rectangle(0, 0, width, height, fill="#000000", outline="", stipple="gray75")

    def _refresh_preview(self) -> None:
        self._draw_map_surface()

    def _reset_visuals(self) -> None:
        if hasattr(self, "preview_status"):
            self.preview_status.configure(text="Querying GIS layers...")
        if hasattr(self, "preview_facts"):
            self.preview_facts.configure(text="")
        self.zoning_snapshot.configure(text="Running development options...")
        self.zoning_activity.grid()
        self.zoning_activity.start()
        for child in self.zoning_rows.winfo_children():
            child.destroy()
        for child in self.resource_rows.winfo_children():
            child.destroy()
        for var in self.preview_layer_vars.values():
            var.set(False)
        for child in self.layer_controls.winfo_children():
            child.configure(state="disabled")
        self._clear_log()
        self._draw_map_surface()

    def _motion_allowed(self) -> bool:
        cached = getattr(self, "_motion_allowed_cache", None)
        if cached is not None:
            return bool(cached)
        env_value = os.environ.get("PROSPECTOR_REDUCED_MOTION", "").strip().lower()
        if env_value in {"1", "true", "yes", "on"}:
            self._motion_allowed_cache = False
            return False
        allowed = True
        try:
            animation_enabled = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(animation_enabled), 0)
            allowed = bool(animation_enabled.value)
        except Exception:
            allowed = True
        self._motion_allowed_cache = allowed
        return allowed

    def _ease_out_cubic(self, t: float) -> float:
        return 1 - pow(1 - t, 3)

    def _rgb(self, color: str) -> tuple[int, int, int]:
        color = color.lstrip("#")
        return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)

    def _blend(self, start: str, end: str, t: float) -> str:
        a = self._rgb(start)
        b = self._rgb(end)
        return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * t):02x}" for i in range(3))

    def _animate(self, duration: int, step, done=None, delay: int = 0, frames: int | None = None) -> None:
        if not self._motion_allowed():
            step(1.0)
            if done:
                done()
            return
        total_frames = frames or max(5, duration // 16)

        def tick(index: int = 0) -> None:
            progress = self._ease_out_cubic(min(index / total_frames, 1))
            step(progress)
            if index < total_frames:
                self.after(max(1, duration // total_frames), lambda: tick(index + 1))
            elif done:
                done()

        self.after(delay, tick)

    def _animate_color(self, widget, option: str, start: str, end: str, duration: int = 160, delay: int = 0) -> None:
        self._animate(duration, lambda t: widget.configure(**{option: self._blend(start, end, t)}), delay=delay)

    def _animate_width(self, widget, start: int, end: int, duration: int = 180, delay: int = 0) -> None:
        self._animate(duration, lambda t: widget.configure(width=max(0, int(start + (end - start) * t))), delay=delay)

    def _bind_all_children(self, widget, sequence: str, callback) -> None:
        widget.bind(sequence, callback)
        for child in widget.winfo_children():
            self._bind_all_children(child, sequence, callback)

    def _bind_card_hover(self, widget, normal_fg: str = "#080d11", hover_fg: str = "#0d151a", normal_border: str = "#1a2b32", hover_border: str = "#24545c") -> None:
        def enter(_event=None) -> None:
            if self._motion_allowed():
                self._animate_color(widget, "fg_color", normal_fg, hover_fg, 130)
                self._animate_color(widget, "border_color", normal_border, hover_border, 130)
            else:
                widget.configure(fg_color=hover_fg, border_color=hover_border)

        def leave(_event=None) -> None:
            if self._motion_allowed():
                self._animate_color(widget, "fg_color", hover_fg, normal_fg, 150)
                self._animate_color(widget, "border_color", hover_border, normal_border, 150)
            else:
                widget.configure(fg_color=normal_fg, border_color=normal_border)

        self._bind_all_children(widget, "<Enter>", enter)
        self._bind_all_children(widget, "<Leave>", leave)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, minsize=292)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=8)
        self.grid_columnconfigure(3, minsize=410)
        self.grid_rowconfigure(0, weight=1)

        self.logo_image = self._load_logo_image(34)
        self.layer_manager_visible = True
        self.details_width = 230
        self._resize_start_x = 0
        self._resize_start_width = self.details_width
        self._map_animation_started = False

        self.left_rail = ctk.CTkFrame(self, width=292, corner_radius=0, fg_color="#03070a")
        self.left_rail.grid(row=0, column=0, sticky="nsew")
        self.left_rail.grid_columnconfigure(0, weight=1)
        self.left_rail.grid_rowconfigure(2, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#05080b")
        self.preview_shell.grid(row=0, column=1, sticky="nsew")
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self.details_resize_handle = ctk.CTkFrame(self, width=8, corner_radius=0, fg_color="#071016")
        self.details_resize_handle.grid(row=0, column=2, sticky="ns")
        self.details_resize_handle.bind("<ButtonPress-1>", self._start_details_resize)
        self.details_resize_handle.bind("<B1-Motion>", self._drag_details_resize)
        self.details_resize_handle.bind("<Double-Button-1>", lambda _event: self._set_details_width(460))
        self.details_resize_handle.bind("<Enter>", lambda _event: self.details_resize_handle.configure(fg_color="#0f3440"))
        self.details_resize_handle.bind("<Leave>", lambda _event: self.details_resize_handle.configure(fg_color="#071016"))

        self.right_rail = ctk.CTkFrame(self, width=self.details_width, corner_radius=0, fg_color="#05080b")
        self.right_rail.grid(row=0, column=3, sticky="nsew")
        self.right_rail.grid_propagate(False)
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

        self._build_left_rail()
        self._build_preview_area()
        self._build_details_panel()
        self._run_entrance_animations()

    def _start_details_resize(self, event) -> None:
        self._resize_start_x = event.x_root
        self._resize_start_width = self.details_width
        self.details_resize_handle.configure(fg_color="#00aeb7")

    def _drag_details_resize(self, event) -> None:
        delta = self._resize_start_x - event.x_root
        self._set_details_width(self._resize_start_width + delta)

    def _set_details_width(self, width: int) -> None:
        self.details_width = max(360, min(720, int(width)))
        self.grid_columnconfigure(3, minsize=self.details_width)
        self.right_rail.configure(width=self.details_width)

    def _build_left_rail(self) -> None:
        header = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(30, 30))
        header.grid_columnconfigure(1, weight=1)
        if self.logo_image:
            ctk.CTkLabel(header, image=self.logo_image, text="").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ctk.CTkLabel(header, text="Prop", font=self._font(25, "bold"), text_color="#f4fbfb").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(header, text="Spector", font=self._font(25, "bold"), text_color="#00d8d8").grid(row=0, column=1, sticky="w", padx=(55, 0))

        nav = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=14)
        nav.grid_columnconfigure(0, weight=1)
        for index, (icon, label, active) in enumerate((
            ("D", "Dashboard", True),
            ("M", "Map Explorer", False),
            ("C", "Code Logic", False),
            ("R", "Reports", False),
            ("O", "Development Options", False),
            ("G", "Demographics", False),
            ("S", "Settings", False),
        )):
            self._premium_nav_item(nav, icon, label, active).grid(row=index, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkFrame(self.left_rail, fg_color="transparent").grid(row=2, column=0, sticky="nsew")

        quick = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        quick.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 28))
        quick.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(quick, text="QUICK ACTIONS", font=self._font(11), text_color="#9aa3aa").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.run_button = self._premium_button(quick, "+  New Search", self._start_new_search)
        self.run_button.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._premium_button(quick, "v  Import Parcels", self._browse).grid(row=2, column=0, sticky="ew")

        account = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        account.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 24))
        account.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(account, text="ZM", width=48, height=48, corner_radius=24, fg_color="#101820", border_color="#1c2b32", border_width=1, text_color="#f8ffff", font=self._font(15, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(account, text="Zak Morris", font=self._font(13, "bold"), text_color="#eef5f7").grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(account, text="Administrator", font=self._font(12), text_color="#9aa5ab").grid(row=1, column=1, sticky="nw")
        ctk.CTkLabel(account, text="v", font=self._font(18), text_color="#d4dde1").grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(account, text="*", font=self._font(15), text_color="#aeb8be").grid(row=1, column=2, sticky="e")

    def _premium_nav_item(self, parent, icon: str, label: str, active: bool) -> ctk.CTkFrame:
        base = "#081116"
        hover = "#0d2027"
        active_bg = "#0a2630"
        row = ctk.CTkFrame(parent, height=50, corner_radius=8, fg_color=active_bg if active else "transparent", border_color="#143842" if active else "#04080b", border_width=1 if active else 0)
        row.grid_propagate(False)
        row.grid_columnconfigure(2, weight=1)
        bar = ctk.CTkFrame(row, width=3, corner_radius=2, fg_color="#00d6d6" if active else "transparent")
        bar.grid(row=0, column=0, sticky="nsw", pady=8)
        ctk.CTkLabel(row, text=icon, width=36, font=self._font(12, "bold"), text_color="#00d6d6" if active else "#aeb8be").grid(row=0, column=1, padx=(12, 6), pady=12)
        ctk.CTkLabel(row, text=label, font=self._font(13, "bold" if active else "normal"), text_color="#00e5e2" if active else "#c7d0d6").grid(row=0, column=2, sticky="w")

        def enter(_event=None) -> None:
            if active:
                self._animate_color(row, "border_color", "#143842", "#00a9b3", 130)
                self._animate_width(bar, 3, 5, 130)
            else:
                row.configure(border_width=1)
                self._animate_color(row, "fg_color", base, hover, 130)
                self._animate_color(row, "border_color", "#061318", "#183d46", 130)

        def leave(_event=None) -> None:
            if active:
                self._animate_color(row, "border_color", "#00a9b3", "#143842", 150)
                self._animate_width(bar, 5, 3, 150)
            else:
                self._animate_color(row, "fg_color", hover, "#04080b", 150)
                self._animate_color(row, "border_color", "#183d46", "#04080b", 150)

        self._bind_all_children(row, "<Enter>", enter)
        self._bind_all_children(row, "<Leave>", leave)
        return row

    def _premium_button(self, parent, text: str, command) -> ctk.CTkButton:
        button = ctk.CTkButton(
            parent,
            text=text,
            height=44,
            corner_radius=7,
            anchor="w",
            fg_color="#101820",
            hover_color="#15242b",
            border_color="#101820",
            border_width=1,
            text_color="#e2ecef",
            font=self._font(13),
            command=command,
        )
        button.bind("<Enter>", lambda _event: button.configure(fg_color="#14242b", border_color="#0b6570", text_color="#f2ffff"))
        button.bind("<Leave>", lambda _event: button.configure(fg_color="#101820", border_color="#101820", text_color="#e2ecef"))
        button.bind("<ButtonPress-1>", lambda _event: button.configure(fg_color="#0c171d"))
        button.bind("<ButtonRelease-1>", lambda _event: button.configure(fg_color="#14242b"))
        return button

    def _build_preview_area(self) -> None:
        top = ctk.CTkFrame(self.preview_shell, height=74, fg_color="#05080b", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(16, 0))
        top.grid_columnconfigure(0, weight=1)

        self.search_shell = ctk.CTkFrame(top, height=56, corner_radius=9, fg_color="#0a1014", border_color="#1d3038", border_width=1)
        self.search_shell.grid(row=0, column=0, sticky="w")
        self.search_shell.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.search_shell, text="Search", font=self._font(12, "bold"), text_color="#7f8d94").grid(row=0, column=0, padx=(16, 8))
        self.parcel_entry = ctk.CTkEntry(
            self.search_shell,
            width=520,
            placeholder_text="Search by Address, Owner, Parcel ID...",
            height=44,
            border_width=0,
            fg_color="transparent",
            text_color="#eef6f7",
            placeholder_text_color="#858e94",
            font=self._font(14),
        )
        self.parcel_entry.grid(row=0, column=1, sticky="ew")
        self.parcel_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())
        self.parcel_entry.bind("<Return>", lambda _event: self._run_or_cancel())
        self.parcel_entry.bind("<FocusIn>", lambda _event: self._search_focus(True))
        self.parcel_entry.bind("<FocusOut>", lambda _event: self._search_focus(False))
        ctk.CTkLabel(self.search_shell, text="Ctrl K", width=58, height=30, corner_radius=6, fg_color="#0f171c", border_color="#1b2a31", border_width=1, text_color="#c3cbd0", font=self._font(12, "bold")).grid(row=0, column=2, padx=10)

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.grid(row=0, column=1, sticky="e")
        for idx, (icon, badge) in enumerate((("Moon", ""), ("Bell", "3"), ("?", ""), ("ZM", ""), ("v", ""))):
            ctk.CTkButton(
                tools,
                text=icon,
                width=42 if icon != "ZM" else 50,
                height=42 if icon != "ZM" else 46,
                corner_radius=23,
                fg_color="#111922" if icon == "ZM" else "transparent",
                hover_color="#122229",
                text_color="#e4edf0",
                font=self._font(11 if icon not in {"?", "ZM", "v"} else 15, "bold" if icon == "ZM" else "normal"),
            ).grid(row=0, column=idx, padx=(6, 0))
            if badge:
                ctk.CTkLabel(tools, text=badge, width=18, height=18, corner_radius=9, fg_color="#00d6d6", text_color="#041012", font=self._font(9, "bold")).grid(row=0, column=idx, sticky="ne", pady=(0, 22))

        content = ctk.CTkFrame(self.preview_shell, corner_radius=0, fg_color="#05080b")
        content.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(4, 16))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=3, minsize=450)
        content.grid_rowconfigure(1, weight=2, minsize=340)
        self.main_content = content

        self.map_viewport = self._panel(content, row=0, padx=0, pady=(0, 12), radius=9)
        self.map_viewport.configure(fg_color="#050a0e", border_color="#173843")
        self.map_viewport.grid(sticky="nsew")
        self.map_viewport.grid_columnconfigure(0, weight=1)
        self.map_viewport.grid_rowconfigure(0, weight=1)
        self.map_canvas = ctk.CTkCanvas(self.map_viewport, bg="#05090c", highlightthickness=0, bd=0)
        self.map_canvas.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.map_canvas.bind("<Configure>", lambda _event: self._draw_map_surface())
        self._bind_card_hover(self.map_viewport, "#050a0e", "#071015", "#173843", "#237382")
        self._build_map_chrome()

        self._build_layer_manager(content, row=1)

        self.folder_entry = self._entry(content, "Destination folder")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid_remove()
        self.group_menu = ctk.CTkOptionMenu(content, values=list(ENVIRONMENTAL_MENU_GROUPS))
        self.group_menu.set("All Resources")
        self.group_menu.grid_remove()
        self.intended_use_entry = self._entry(content, "Optional intended use")
        self.intended_use_entry.grid_remove()
        self.preview_status = ctk.CTkLabel(content, text="", font=self._font(12), text_color="#8fa1aa")
        self.preview_status.grid_remove()
        self.preview_facts = ctk.CTkLabel(content, text="", font=self._font(12), text_color="#b8c9c1", justify="right")
        self.preview_facts.grid_remove()
        self._build_hidden_runtime_panels(content)
        self.after(80, self._draw_map_surface)
        self.after(320, self._animate_map_selection_once)

    def _search_focus(self, focused: bool) -> None:
        if focused:
            self.search_shell.configure(border_color="#00cdd2", fg_color="#0c1519")
        else:
            self.search_shell.configure(border_color="#1d3038", fg_color="#0a1014")

    def _build_map_chrome(self) -> None:
        toggle = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#163743", border_width=1)
        toggle.place(x=16, y=14)
        ctk.CTkLabel(toggle, text="Aerial", width=74, height=40, corner_radius=6, fg_color="#007783", text_color="#eaffff", font=self._font(13, "bold")).grid(row=0, column=0)
        ctk.CTkLabel(toggle, text="Satellite", width=86, height=40, text_color="#aab5bc", font=self._font(13)).grid(row=0, column=1)

        controls = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#1a2d34", border_width=1)
        controls.place(relx=1, x=-16, y=14, anchor="ne")
        for idx, icon in enumerate(("+", "-", "Layers", "Filter", "Locate")):
            button = ctk.CTkButton(controls, text=icon, width=54 if idx > 1 else 44, height=44, corner_radius=0, fg_color="transparent", hover_color="#102934", text_color="#e6eef1", font=self._font(11 if idx > 1 else 21))
            button.grid(row=idx, column=0)

        legend = ctk.CTkFrame(self.map_viewport, width=178, corner_radius=7, fg_color="#071015", border_color="#20343b", border_width=1)
        legend.place(x=16, rely=1, y=-16, anchor="sw")
        ctk.CTkLabel(legend, text="Parcel Status", font=self._font(13, "bold"), text_color="#f3f7f8").grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
        for row, (dot, label, value) in enumerate((("#00d6d6", "Selected", "1"), ("#25d2bb", "Potential Lead", "87"), ("#ffc642", "Watchlist", "12"), ("#6e7a85", "Other", "4,882")), start=1):
            ctk.CTkLabel(legend, text="o", text_color=dot, font=self._font(13, "bold")).grid(row=row, column=0, sticky="w", padx=(14, 6), pady=(0, 9))
            ctk.CTkLabel(legend, text=label, text_color="#bdc8ce", font=self._font(12)).grid(row=row, column=1, sticky="w", pady=(0, 9))
            ctk.CTkLabel(legend, text=value, text_color="#ffffff", font=self._font(12, "bold")).grid(row=row, column=2, sticky="e", padx=(18, 14), pady=(0, 9))

        self.layers_restore_button = ctk.CTkButton(self.map_viewport, text="Layer Manager", width=116, height=38, corner_radius=7, fg_color="#071015", hover_color="#102029", border_color="#1a2d34", border_width=1, text_color="#00d6d6", font=self._font(12, "bold"), command=self._toggle_layer_manager)

    def _build_layer_manager(self, parent, row: int) -> None:
        manager = self._panel(parent, row=row, padx=0, pady=(0, 0), radius=9)
        manager.configure(fg_color="#070c10", border_color="#1b333b")
        manager.grid(sticky="nsew")
        manager.grid_columnconfigure(0, weight=1)
        self.layer_manager = manager
        self.layer_row_frames = []
        self.layer_states = []

        header = ctk.CTkFrame(manager, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Layer Manager", font=self._font(18, "bold"), text_color="#f2f7f8").grid(row=0, column=0, sticky="w")
        self.layer_toggle_button = ctk.CTkButton(header, text="Hide", width=58, height=28, corner_radius=6, fg_color="#0c171d", hover_color="#102934", text_color="#c8d2d8", font=self._font(12, "bold"), command=self._toggle_layer_manager)
        self.layer_toggle_button.grid(row=0, column=1, sticky="e")

        tabs = ctk.CTkFrame(manager, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        for col, tab in enumerate(("Environmental", "Physical", "Zoning & Planning", "Infrastructure", "Boundaries", "Risk")):
            ctk.CTkLabel(tabs, text=tab, height=30, text_color="#00dedb" if col == 0 else "#a7b0b7", font=self._font(12, "bold" if col == 0 else "normal")).grid(row=0, column=col, padx=(0, 28), sticky="w")
        ctk.CTkFrame(tabs, height=2, fg_color="#00d6d6").grid(row=1, column=0, sticky="ew")

        rows = ctk.CTkFrame(manager, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 16))
        rows.grid_columnconfigure(0, weight=1)
        for idx, item in enumerate((
            ("F", "Flood Hazard Zones (FEMA)", "1% Annual Chance Flood Hazard", "#063849", True, "65%"),
            ("W", "Wetlands (NWI)", "National Wetlands Inventory", "#0c3d28", True, "70%"),
            ("S", "Soils (SSURGO)", "Soil Survey Geographic Database", "#3a2315", True, "60%"),
            ("P", "Protected Areas", "Conservation & Protected Lands", "#3b310c", True, "50%"),
            ("E", "Environmental Justice Index", "EPA EJScreen 2.0", "#18333b", False, "0%"),
            ("R", "Wildfire Risk", "Wildfire Hazard Potential", "#3d2410", False, "0%"),
        )):
            self._layer_row(rows, idx, *item)
        self._bind_card_hover(manager, "#070c10", "#0b1217", "#1b333b", "#24545c")
        self.after(220, self._stagger_layer_rows)

    def _layer_row(self, parent, row: int, icon: str, title: str, sub: str, icon_bg: str, visible: bool, pct: str) -> None:
        item = ctk.CTkFrame(parent, height=62, corner_radius=7, fg_color="#0e171c", border_color="#132229", border_width=1)
        item.grid(row=row, column=0, columnspan=7, sticky="ew", pady=4)
        item.grid_propagate(False)
        item.grid_columnconfigure(2, weight=1)
        accent = ctk.CTkFrame(item, width=3, corner_radius=2, fg_color="#00d6d6" if visible else "#1b2b32")
        accent.grid(row=0, column=0, rowspan=2, sticky="nsw", pady=8)
        ctk.CTkLabel(item, text=icon, width=38, height=38, corner_radius=6, fg_color=icon_bg, text_color="#00d6d6" if visible else "#9aa5ab", font=self._font(13, "bold")).grid(row=0, column=1, rowspan=2, padx=(12, 12), pady=10)
        ctk.CTkLabel(item, text=title, font=self._font(14), text_color="#eef5f7").grid(row=0, column=2, sticky="sw", pady=(9, 0))
        ctk.CTkLabel(item, text=sub, font=self._font(11), text_color="#9aa5ab").grid(row=1, column=2, sticky="nw", pady=(0, 8))
        eye = ctk.CTkButton(item, text="On" if visible else "Off", width=42, height=28, corner_radius=14, fg_color="#073d44" if visible else "#121b21", hover_color="#0a5660", text_color="#00d6d6" if visible else "#748089", font=self._font(11, "bold"))
        eye.grid(row=0, column=3, rowspan=2, padx=(16, 14))
        bar = ctk.CTkFrame(item, width=170, height=4, fg_color="#263039")
        bar.grid(row=0, column=4, rowspan=2, padx=(0, 10))
        pct_value = int(pct.rstrip("%"))
        fill = ctk.CTkFrame(bar, width=int(170 * pct_value / 100), height=4, fg_color="#00d6d6" if visible else "#6d7780")
        fill.place(x=0, y=0)
        knob = ctk.CTkFrame(bar, width=10, height=10, corner_radius=5, fg_color="#edf4f6")
        knob.place(x=max(int(170 * pct_value / 100) - 5, 0), y=-3)
        ctk.CTkLabel(item, text=pct, font=self._font(12), text_color="#b9c4ca").grid(row=0, column=5, rowspan=2, padx=(0, 22))
        ctk.CTkLabel(item, text="i", font=self._font(14, "bold"), text_color="#aeb8be").grid(row=0, column=6, rowspan=2, padx=(0, 22))
        ctk.CTkLabel(item, text="...", font=self._font(14), text_color="#aeb8be").grid(row=0, column=7, rowspan=2, padx=(0, 14))

        state = {"visible": visible, "pct": pct_value, "item": item, "accent": accent, "eye": eye, "fill": fill, "knob": knob}
        eye.configure(command=lambda state=state: self._toggle_layer_row(state))
        self.layer_states.append(state)
        self.layer_row_frames.append(item)
        self._bind_layer_row_hover(item, visible)

    def _bind_layer_row_hover(self, item, active: bool) -> None:
        normal = "#0e171c"
        hover = "#132229" if active else "#101a20"
        item.bind("<Enter>", lambda _event: item.configure(fg_color=hover, border_color="#23525c"))
        item.bind("<Leave>", lambda _event: item.configure(fg_color=normal, border_color="#132229"))

    def _toggle_layer_row(self, state: dict) -> None:
        state["visible"] = not state["visible"]
        visible = state["visible"]
        state["eye"].configure(text="On" if visible else "Off", fg_color="#073d44" if visible else "#121b21", text_color="#00d6d6" if visible else "#748089")
        state["accent"].configure(fg_color="#00d6d6" if visible else "#1b2b32")
        target = int(170 * state["pct"] / 100) if visible else 0
        start = state["fill"].winfo_width()
        state["fill"].configure(fg_color="#00d6d6" if visible else "#6d7780")
        self._animate_width(state["fill"], start, target, 180)
        self._animate(180, lambda t: state["knob"].place_configure(x=max(int(start + (target - start) * t) - 5, 0), y=-3))
        state["item"].configure(border_color="#00a6b0" if visible else "#25323a")

    def _stagger_layer_rows(self) -> None:
        for index, row in enumerate(getattr(self, "layer_row_frames", [])):
            self._animate_color(row, "fg_color", "#091014", "#0e171c", 160, delay=index * 36)
            self._animate_color(row, "border_color", "#091014", "#132229", 160, delay=index * 36)

    def _toggle_layer_manager(self) -> None:
        self.layer_manager_visible = not self.layer_manager_visible
        if self.layer_manager_visible:
            self.layer_manager.grid()
            self.layers_restore_button.place_forget()
            self.layer_toggle_button.configure(text="Hide")
            self._animate(180, lambda t: self.main_content.grid_rowconfigure(1, weight=2, minsize=int(340 * t)))
            self.main_content.grid_rowconfigure(0, weight=3, minsize=450)
        else:
            def finish() -> None:
                self.layer_manager.grid_remove()
                self.layers_restore_button.place(relx=1, x=-78, y=14, anchor="ne")
                self._draw_map_surface()

            self.layer_toggle_button.configure(text="Show")
            self._animate(180, lambda t: self.main_content.grid_rowconfigure(1, weight=0, minsize=int(340 * (1 - t))), done=finish)
            self.main_content.grid_rowconfigure(0, weight=1, minsize=0)
        self.after(80, self._draw_map_surface)

    def _draw_map_surface(self) -> None:
        if not hasattr(self, "map_canvas"):
            return
        canvas = self.map_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#050a0c", outline="")

        for y in range(0, height, 10):
            shade = 7 + min(12, int(y / max(height, 1) * 10))
            canvas.create_rectangle(0, y, width, y + 10, fill=f"#{shade:02x}{shade + 3:02x}{shade + 5:02x}", outline="")

        for x in range(-80, width + 120, 116):
            for y in range(-50, height + 100, 74):
                shade = 31 + ((x * 5 + y * 3) % 34)
                fill = f"#{shade:02x}{shade:02x}{max(shade - 5, 0):02x}"
                canvas.create_rectangle(x, y, x + 74, y + 34, fill=fill, outline="#343d3d")

        for offset in (-120, 160, 440, 720, 1000, 1280):
            canvas.create_polygon(offset, -80, offset + 56, -80, offset + width * 0.15 + 120, height + 80, offset + width * 0.15 + 56, height + 80, fill="#242c2b", outline="")
            canvas.create_line(offset + 28, -80, offset + width * 0.15 + 88, height + 80, fill="#4d5752", width=2)
        for y in (height * 0.18, height * 0.48, height * 0.78):
            canvas.create_polygon(-80, y, width + 80, y + 58, width + 80, y + 98, -80, y + 40, fill="#222928", outline="")
            canvas.create_line(-80, y + 18, width + 80, y + 76, fill="#4d5752", width=2)

        for x in range(20, width, 175):
            y = 25 + ((x * 7) % max(height - 80, 1))
            canvas.create_oval(x, y, x + 54, y + 54, fill="#061f11", outline="")

        parcel = (
            width * 0.47, height * 0.28,
            width * 0.59, height * 0.22,
            width * 0.69, height * 0.72,
            width * 0.54, height * 0.83,
            width * 0.43, height * 0.36,
        )
        glow = tuple(coord + (0 if i % 2 == 0 else 0) for i, coord in enumerate(parcel))
        canvas.create_polygon(glow, fill="", outline="#006b72", width=8, tags=("parcel_glow",))
        canvas.create_polygon(parcel, fill="#003f40", outline="#00d6d6", width=3, tags=("parcel",))
        canvas.create_polygon(parcel, fill="#008b8b", outline="", stipple="gray50", tags=("parcel",))

        pin_x = width * 0.57
        pin_y = height * 0.50
        pin_r = max(16, min(width, height) * 0.035)
        canvas.create_oval(pin_x - pin_r, pin_y - pin_r, pin_x + pin_r, pin_y + pin_r, fill="#00cbd4", outline="", tags=("pin",))
        canvas.create_polygon(pin_x - pin_r * 0.55, pin_y + pin_r * 0.45, pin_x + pin_r * 0.55, pin_y + pin_r * 0.45, pin_x, pin_y + pin_r * 2.1, fill="#00cbd4", outline="", tags=("pin",))
        canvas.create_oval(pin_x - pin_r * 0.25, pin_y - pin_r * 0.25, pin_x + pin_r * 0.25, pin_y + pin_r * 0.25, fill="#061217", outline="", tags=("pin",))
        canvas.create_rectangle(0, 0, width, height, fill="#000000", outline="", stipple="gray75")

    def _animate_map_selection_once(self) -> None:
        if self._map_animation_started or not self._motion_allowed() or not hasattr(self, "map_canvas"):
            return
        self._map_animation_started = True
        canvas = self.map_canvas
        canvas.move("pin", 0, -14)
        self._animate(260, lambda t: canvas.move("pin", 0, 14 / max(1, 260 // 16)))

        def pulse(frame: int = 0) -> None:
            if frame > 14 or not canvas.winfo_exists():
                canvas.delete("selection_pulse")
                return
            width = max(canvas.winfo_width(), 1)
            height = max(canvas.winfo_height(), 1)
            grow = frame * 1.8
            parcel = (
                width * 0.47 - grow, height * 0.28 - grow,
                width * 0.59 + grow, height * 0.22 - grow,
                width * 0.69 + grow, height * 0.72 + grow,
                width * 0.54 + grow, height * 0.83 + grow,
                width * 0.43 - grow, height * 0.36 + grow,
            )
            canvas.delete("selection_pulse")
            canvas.create_polygon(parcel, fill="", outline="#00e9e6", width=max(1, 4 - frame // 5), tags=("selection_pulse",))
            self.after(24, lambda: pulse(frame + 1))

        pulse()

    def _build_details_panel(self) -> None:
        panel = ctk.CTkScrollableFrame(self.right_rail, corner_radius=9, fg_color="#070b0f", border_color="#1b2b32", border_width=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(10, 14), pady=(74, 16))
        panel.grid_columnconfigure(0, weight=1)
        self.details_panel = panel

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="26-017.00-123  *", font=self._font(20, "bold"), text_color="#f4fbfb").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="x", font=self._font(22), text_color="#a8b3b9").grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(header, text="POTENTIAL LEAD", height=22, corner_radius=5, fg_color="#063d42", text_color="#00f0e6", font=self._font(10, "bold")).grid(row=1, column=0, sticky="w", pady=(7, 9))
        ctk.CTkLabel(header, text="1021 Gilpin Ave\nWilmington, DE 19806\nNew Castle County", font=self._font(13), text_color="#d6e1e6", justify="left").grid(row=2, column=0, sticky="w")

        tabs = ctk.CTkFrame(panel, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 10))
        self.detail_tabs = []
        for col, tab in enumerate(("Overview", "Details", "Owner", "History")):
            label = ctk.CTkLabel(tabs, text=tab, height=34, text_color="#00e1df" if col == 0 else "#a6b0b8", font=self._font(12, "bold" if col == 0 else "normal"))
            label.grid(row=0, column=col, padx=(0, 24), sticky="w")
            label.bind("<Button-1>", lambda _event, name=tab: self._select_detail_tab(name))
            self.detail_tabs.append(label)
        self.detail_underline = ctk.CTkFrame(tabs, height=2, fg_color="#00d6d6")
        self.detail_underline.grid(row=1, column=0, sticky="ew")

        details_card = ctk.CTkFrame(panel, corner_radius=7, fg_color="#0a1014", border_color="#172830", border_width=1)
        details_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))
        details_card.grid_columnconfigure(0, weight=1)
        details_card.grid_columnconfigure(1, weight=1)
        self.details_card = details_card
        for idx, (label, value) in enumerate((
            ("Parcel ID", "26-017.00-123"),
            ("Acres", "1.24"),
            ("Zoning", "C-2 (Commercial)"),
            ("Land Use", "Vacant Land"),
            ("Last Sale", "$950,000 on 06/12/2021"),
            ("Assessed Value", "$1,125,400"),
            ("Tax Map", "26-17.00-123.00"),
        )):
            self._detail_row(details_card, idx, label, value)

        self._notes_section(panel, row=3)
        self._tags_section(panel, row=4)
        self._documents_section(panel, row=5)

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=14, pady=(4, 14))
        footer.grid_columnconfigure(0, weight=1)
        add_button = ctk.CTkButton(footer, text="Add to List                         v", height=44, corner_radius=7, fg_color="#0096a3", hover_color="#00aeba", text_color="#f1ffff", font=self._font(14, "bold"))
        add_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        report = ctk.CTkButton(footer, text="Generate Report", height=42, corner_radius=7, fg_color="#061116", hover_color="#0b2027", border_color="#006e79", border_width=1, text_color="#00d6d6", font=self._font(14, "bold"), command=self._create_package)
        report.grid(row=1, column=0, sticky="ew")
        self.package_button = report
        self.package_button.configure(state="disabled")
        for button in (add_button, report):
            button.bind("<Enter>", lambda _event, b=button: b.configure(border_color="#00d6d6"))
            button.bind("<Leave>", lambda _event, b=button: b.configure(border_color="#006e79" if b is report else "#0096a3"))
        self._bind_card_hover(panel, "#070b0f", "#0a1115", "#1b2b32", "#24545c")

    def _detail_row(self, parent, row: int, label: str, value: str) -> None:
        frame = ctk.CTkFrame(parent, fg_color="#0a1014", corner_radius=5)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=2)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=label, font=self._font(12), text_color="#9aa6ad").grid(row=0, column=0, sticky="w", padx=8, pady=7)
        ctk.CTkLabel(frame, text=value, font=self._font(12), text_color="#e0e9ed").grid(row=0, column=1, sticky="e", padx=8, pady=7)
        frame.bind("<Enter>", lambda _event: frame.configure(fg_color="#0f1a20"))
        frame.bind("<Leave>", lambda _event: frame.configure(fg_color="#0a1014"))

    def _select_detail_tab(self, name: str) -> None:
        for tab in getattr(self, "detail_tabs", []):
            active = tab.cget("text") == name
            tab.configure(text_color="#00e1df" if active else "#a6b0b8", font=self._font(12, "bold" if active else "normal"))
        self.details_card.configure(fg_color="#0d151a")
        self.after(120, lambda: self.details_card.configure(fg_color="#0a1014"))

    def _run_entrance_animations(self) -> None:
        if not self._motion_allowed():
            return
        for delay, widget, normal, glow in (
            (80, self.left_rail, "#03070a", "#061219"),
            (150, self.map_viewport, "#050a0e", "#07141a"),
            (220, self.layer_manager, "#070c10", "#0b151a"),
            (290, self.details_panel, "#070b0f", "#0a1419"),
        ):
            self._animate_color(widget, "fg_color", "#020507", glow, 180, delay=delay)
            self.after(delay + 190, lambda w=widget, n=normal: w.configure(fg_color=n))

    def _sync_run_button_state(self, running: bool | None = None) -> None:
        is_running = self.running_jobs > 0 if running is None else running
        new_search_pending = is_running and self._current_research_key() != self.active_research_key
        self.run_button.configure(
            state="normal",
            text="+  New Search" if new_search_pending or not is_running else "x  Cancel Search",
            fg_color="#101820" if new_search_pending or not is_running else "#32191c",
            hover_color="#15242b" if new_search_pending or not is_running else "#482128",
            text_color="#e2ecef",
        )

    def _refresh_preview(self) -> None:
        self._draw_map_surface()

    def _layer_row(self, parent, row: int, icon: str, title: str, sub: str, icon_bg: str, visible: bool, pct: str) -> None:
        item = ctk.CTkFrame(parent, height=60, corner_radius=7, fg_color="#0e171c", border_color="#132229", border_width=1)
        item.grid(row=row, column=0, sticky="ew", pady=4)
        item.grid_propagate(False)

        accent = ctk.CTkFrame(item, width=3, height=44, corner_radius=2, fg_color="#00d6d6" if visible else "#1b2b32")
        icon_label = ctk.CTkLabel(item, text=icon, width=38, height=38, corner_radius=6, fg_color=icon_bg, text_color="#00d6d6" if visible else "#9aa5ab", font=self._font(13, "bold"))
        title_label = ctk.CTkLabel(item, text=title, font=self._font(14), text_color="#eef5f7")
        sub_label = ctk.CTkLabel(item, text=sub, font=self._font(11), text_color="#9aa5ab")
        eye = ctk.CTkButton(item, text="On" if visible else "Off", width=42, height=28, corner_radius=14, fg_color="#073d44" if visible else "#121b21", hover_color="#0a5660", text_color="#00d6d6" if visible else "#748089", font=self._font(11, "bold"))
        bar = ctk.CTkFrame(item, width=170, height=4, fg_color="#263039")
        pct_value = int(pct.rstrip("%"))
        fill = ctk.CTkFrame(bar, width=int(170 * pct_value / 100), height=4, fg_color="#00d6d6" if visible else "#6d7780")
        fill.place(x=0, y=0)
        knob = ctk.CTkFrame(bar, width=10, height=10, corner_radius=5, fg_color="#edf4f6")
        knob.place(x=max(int(170 * pct_value / 100) - 5, 0), y=-3)
        pct_label = ctk.CTkLabel(item, text=pct, font=self._font(12), text_color="#b9c4ca")
        info_label = ctk.CTkLabel(item, text="i", font=self._font(14, "bold"), text_color="#aeb8be")
        more_label = ctk.CTkLabel(item, text="...", font=self._font(14), text_color="#aeb8be")

        state = {
            "visible": visible,
            "pct": pct_value,
            "item": item,
            "accent": accent,
            "icon": icon_label,
            "title": title_label,
            "sub": sub_label,
            "eye": eye,
            "bar": bar,
            "fill": fill,
            "knob": knob,
            "pct_label": pct_label,
            "info": info_label,
            "more": more_label,
        }

        accent.place(x=0, y=8)
        icon_label.place(x=14, y=11)
        title_label.place(x=64, y=11)
        sub_label.place(x=64, y=33)
        item.bind("<Configure>", lambda _event, state=state: self._layout_layer_row(state))
        eye.configure(command=lambda state=state: self._toggle_layer_row(state))
        self.layer_states.append(state)
        self.layer_row_frames.append(item)
        self._bind_layer_row_hover(item, visible)

    def _layout_layer_row(self, state: dict) -> None:
        width = max(state["item"].winfo_width(), 760)
        state["eye"].place(x=width - 380, y=16)
        state["bar"].place(x=width - 260, y=28)
        state["pct_label"].place(x=width - 76, y=17)
        state["info"].place(x=width - 42, y=18)
        state["more"].place(x=width - 22, y=18)

    def _motion_allowed(self) -> bool:
        return False

    def _run_entrance_animations(self) -> None:
        return

    def _animate_map_selection_once(self) -> None:
        return

    def _stagger_layer_rows(self) -> None:
        return

    def _toggle_layer_manager(self) -> None:
        self.layer_manager_visible = not self.layer_manager_visible
        if self.layer_manager_visible:
            self.layer_manager.grid()
            self.layers_restore_button.place_forget()
            self.layer_toggle_button.configure(text="Hide")
            self.main_content.grid_rowconfigure(0, weight=3, minsize=450)
            self.main_content.grid_rowconfigure(1, weight=2, minsize=340)
        else:
            self.layer_toggle_button.configure(text="Show")
            self.layer_manager.grid_remove()
            self.main_content.grid_rowconfigure(0, weight=1, minsize=0)
            self.main_content.grid_rowconfigure(1, weight=0, minsize=0)
            self.layers_restore_button.place(relx=1, x=-78, y=14, anchor="ne")
        self.after_idle(self._draw_map_surface)

    def _draw_map_surface(self) -> None:
        if not hasattr(self, "map_canvas"):
            return
        canvas = self.map_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        size = (width, height)
        if getattr(self, "_last_drawn_map_size", None) == size and getattr(self, "_map_drawn_once", False):
            return
        self._last_drawn_map_size = size
        self._map_drawn_once = True
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#050a0c", outline="")

        for y in range(0, height, 14):
            shade = 7 + min(11, int(y / max(height, 1) * 9))
            canvas.create_rectangle(0, y, width, y + 14, fill=f"#{shade:02x}{shade + 3:02x}{shade + 5:02x}", outline="")

        for x in range(-80, width + 120, 124):
            for y in range(-50, height + 100, 82):
                shade = 28 + ((x * 5 + y * 3) % 32)
                fill = f"#{shade:02x}{shade:02x}{max(shade - 5, 0):02x}"
                canvas.create_rectangle(x, y, x + 72, y + 34, fill=fill, outline="#313a3a")

        for offset in (-120, 160, 440, 720, 1000, 1280):
            canvas.create_polygon(offset, -80, offset + 56, -80, offset + width * 0.15 + 120, height + 80, offset + width * 0.15 + 56, height + 80, fill="#242c2b", outline="")
            canvas.create_line(offset + 28, -80, offset + width * 0.15 + 88, height + 80, fill="#46514d", width=2)
        for y in (height * 0.18, height * 0.48, height * 0.78):
            canvas.create_polygon(-80, y, width + 80, y + 58, width + 80, y + 98, -80, y + 40, fill="#222928", outline="")
            canvas.create_line(-80, y + 18, width + 80, y + 76, fill="#46514d", width=2)

        for x in range(20, width, 175):
            y = 25 + ((x * 7) % max(height - 80, 1))
            canvas.create_oval(x, y, x + 54, y + 54, fill="#061f11", outline="")

        parcel = (
            width * 0.47, height * 0.28,
            width * 0.59, height * 0.22,
            width * 0.69, height * 0.72,
            width * 0.54, height * 0.83,
            width * 0.43, height * 0.36,
        )
        canvas.create_polygon(parcel, fill="", outline="#006b72", width=7)
        canvas.create_polygon(parcel, fill="#003f40", outline="#00d6d6", width=3)
        canvas.create_polygon(parcel, fill="#008b8b", outline="", stipple="gray50")

        pin_x = width * 0.57
        pin_y = height * 0.50
        pin_r = max(16, min(width, height) * 0.035)
        canvas.create_oval(pin_x - pin_r, pin_y - pin_r, pin_x + pin_r, pin_y + pin_r, fill="#00cbd4", outline="")
        canvas.create_polygon(pin_x - pin_r * 0.55, pin_y + pin_r * 0.45, pin_x + pin_r * 0.55, pin_y + pin_r * 0.45, pin_x, pin_y + pin_r * 2.1, fill="#00cbd4", outline="")
        canvas.create_oval(pin_x - pin_r * 0.25, pin_y - pin_r * 0.25, pin_x + pin_r * 0.25, pin_y + pin_r * 0.25, fill="#061217", outline="")
        canvas.create_rectangle(0, 0, width, height, fill="#000000", outline="", stipple="gray75")

    def _refresh_preview(self) -> None:
        self._last_drawn_map_size = None
        self._draw_map_surface()

    def _on_close(self) -> None:
        self.stop_event.set()
        self.destroy()


class StablePropSpectorApp(PropSpectorApp):
    """Stable premium shell for the existing PropSpector research workflow."""

    def _build_ui(self) -> None:
        self.configure(fg_color="#03070a")
        self.grid_columnconfigure(0, minsize=290)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=8)
        self.grid_columnconfigure(3, minsize=430)
        self.grid_rowconfigure(0, weight=1)
        self.details_width = 430
        self.layer_manager_visible = True

        self.left_rail = ctk.CTkFrame(self, width=290, corner_radius=0, fg_color="#04090d")
        self.left_rail.grid(row=0, column=0, sticky="nsew")
        self.left_rail.grid_columnconfigure(0, weight=1)
        self.left_rail.grid_rowconfigure(2, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#05090d")
        self.preview_shell.grid(row=0, column=1, sticky="nsew")
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self.details_resize_handle = ctk.CTkFrame(self, width=8, corner_radius=0, fg_color="#07131a")
        self.details_resize_handle.grid(row=0, column=2, sticky="ns")
        self.details_resize_handle.bind("<ButtonPress-1>", self._start_details_resize)
        self.details_resize_handle.bind("<B1-Motion>", self._drag_details_resize)
        self.details_resize_handle.bind("<Double-Button-1>", lambda _event: self._set_details_width(430))
        self.details_resize_handle.bind("<Enter>", lambda _event: self.details_resize_handle.configure(fg_color="#0c4650"))
        self.details_resize_handle.bind("<Leave>", lambda _event: self.details_resize_handle.configure(fg_color="#07131a"))

        self.right_rail = ctk.CTkFrame(self, width=self.details_width, corner_radius=0, fg_color="#05090d")
        self.right_rail.grid(row=0, column=3, sticky="nsew")
        self.right_rail.grid_propagate(False)
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

        self._build_left_rail()
        self._build_preview_area()
        self._build_details_panel()

    def _start_details_resize(self, event) -> None:
        self._resize_start_x = event.x_root
        self._resize_start_width = self.details_width
        self.details_resize_handle.configure(fg_color="#00b9c2")

    def _drag_details_resize(self, event) -> None:
        self._set_details_width(self._resize_start_width + self._resize_start_x - event.x_root)

    def _set_details_width(self, width: int) -> None:
        self.details_width = max(360, min(720, int(width)))
        self.grid_columnconfigure(3, minsize=self.details_width)
        self.right_rail.configure(width=self.details_width)

    def _font_label(self, parent, text: str, size: int = 13, weight: str = "normal", color: str = "#cbd5da", **grid):
        label = ctk.CTkLabel(parent, text=text, font=self._font(size, weight), text_color=color)
        label.grid(**grid)
        return label

    def _build_left_rail(self) -> None:
        header = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(30, 28))
        header.grid_columnconfigure(1, weight=1)
        try:
            logo = ctk.CTkImage(light_image=Image.open(resource_path("assets", "PropspectorIcon.png")), dark_image=Image.open(resource_path("assets", "PropspectorIcon.png")), size=(36, 36))
            ctk.CTkLabel(header, image=logo, text="").grid(row=0, column=0, padx=(0, 10))
            self.logo_image = logo
        except Exception:
            ctk.CTkLabel(header, text="PS", width=36, height=36, corner_radius=8, fg_color="#062a30", text_color="#00d6d6", font=self._font(13, "bold")).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(header, text="Prop", font=self._font(25, "bold"), text_color="#f4fbfb").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(header, text="Spector", font=self._font(25, "bold"), text_color="#00d8d8").grid(row=0, column=1, sticky="w", padx=(55, 0))

        nav = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=16)
        nav.grid_columnconfigure(0, weight=1)
        for index, (icon, text, active) in enumerate((
            ("D", "Dashboard", True),
            ("M", "Map Explorer", False),
            ("C", "Code Logic", False),
            ("R", "Reports", False),
            ("O", "Development Options", False),
            ("G", "Demographics", False),
            ("S", "Settings", False),
        )):
            self._nav_item(nav, icon, text, active).grid(row=index, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkFrame(self.left_rail, fg_color="transparent").grid(row=2, column=0, sticky="nsew")

        quick = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        quick.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 24))
        quick.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(quick, text="QUICK ACTIONS", font=self._font(11), text_color="#8f9ca4").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.run_button = self._action_button(quick, "+  New Search", self._run_or_cancel)
        self.run_button.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._action_button(quick, "v  Import Parcels", self._browse).grid(row=2, column=0, sticky="ew")

        account = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        account.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 22))
        account.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(account, text="ZM", width=48, height=48, corner_radius=24, fg_color="#101b24", border_color="#1d333c", border_width=1, text_color="#f7ffff", font=self._font(15, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(account, text="Zak Morris", font=self._font(13, "bold"), text_color="#eef6f8").grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(account, text="Administrator", font=self._font(12), text_color="#9aa6ad").grid(row=1, column=1, sticky="nw")

    def _nav_item(self, parent, icon: str, text: str, active: bool) -> ctk.CTkFrame:
        row = ctk.CTkFrame(parent, height=48, corner_radius=8, fg_color="#0b2630" if active else "transparent", border_color="#164550" if active else "#04090d", border_width=1 if active else 0)
        row.grid_propagate(False)
        row.grid_columnconfigure(2, weight=1)
        ctk.CTkFrame(row, width=3, corner_radius=2, fg_color="#00d6d6" if active else "transparent").grid(row=0, column=0, sticky="nsw", pady=8)
        ctk.CTkLabel(row, text=icon, width=36, font=self._font(12, "bold"), text_color="#00d6d6" if active else "#aeb9bf").grid(row=0, column=1, padx=(12, 6))
        ctk.CTkLabel(row, text=text, font=self._font(13, "bold" if active else "normal"), text_color="#00e5e2" if active else "#c7d0d6").grid(row=0, column=2, sticky="w")
        row.bind("<Enter>", lambda _event: row.configure(fg_color="#10232b" if not active else "#0d303a", border_color="#245d68"))
        row.bind("<Leave>", lambda _event: row.configure(fg_color="#0b2630" if active else "transparent", border_color="#164550" if active else "#04090d"))
        return row

    def _action_button(self, parent, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(parent, text=text, height=44, corner_radius=7, anchor="w", fg_color="#111b23", hover_color="#172832", border_color="#17242c", border_width=1, text_color="#e4eef2", font=self._font(13), command=command)

    def _build_preview_area(self) -> None:
        top = ctk.CTkFrame(self.preview_shell, height=74, fg_color="#05090d", corner_radius=0)
        top.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=(16, 0))
        top.grid_columnconfigure(0, weight=1)
        self.search_shell = ctk.CTkFrame(top, height=56, corner_radius=9, fg_color="#0a1015", border_color="#20343d", border_width=1)
        self.search_shell.grid(row=0, column=0, sticky="w")
        self.search_shell.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.search_shell, text="Search", font=self._font(12, "bold"), text_color="#82919a").grid(row=0, column=0, padx=(16, 8))
        self.parcel_entry = ctk.CTkEntry(self.search_shell, width=520, height=44, border_width=0, fg_color="transparent", placeholder_text="Search by Address, Owner, Parcel ID...", placeholder_text_color="#7f8b92", text_color="#eef7f8", font=self._font(14))
        self.parcel_entry.grid(row=0, column=1, sticky="ew")
        self.parcel_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())
        self.parcel_entry.bind("<Return>", lambda _event: self._run_or_cancel())
        self.parcel_entry.bind("<FocusIn>", lambda _event: self.search_shell.configure(border_color="#00cdd2"))
        self.parcel_entry.bind("<FocusOut>", lambda _event: self.search_shell.configure(border_color="#20343d"))
        ctk.CTkLabel(self.search_shell, text="Ctrl K", width=58, height=30, corner_radius=6, fg_color="#0f171c", border_color="#1b2a31", border_width=1, text_color="#c3cbd0", font=self._font(12, "bold")).grid(row=0, column=2, padx=10)

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.grid(row=0, column=1, sticky="e")
        for col, label in enumerate(("Moon", "Bell 3", "?", "ZM", "v")):
            ctk.CTkButton(tools, text=label, width=48, height=42, corner_radius=21, fg_color="#111922" if label == "ZM" else "transparent", hover_color="#12242c", text_color="#e4edf0", font=self._font(11 if len(label) > 2 else 14, "bold" if label == "ZM" else "normal")).grid(row=0, column=col, padx=(6, 0))

        content = ctk.CTkFrame(self.preview_shell, fg_color="#05090d")
        content.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(4, 16))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=3, minsize=450)
        content.grid_rowconfigure(1, weight=2, minsize=330)
        self.main_content = content

        self.map_viewport = self._panel(content, row=0, padx=0, pady=(0, 12), radius=9)
        self.map_viewport.configure(fg_color="#050a0e", border_color="#173843")
        self.map_viewport.grid(sticky="nsew")
        self.map_viewport.grid_columnconfigure(0, weight=1)
        self.map_viewport.grid_rowconfigure(0, weight=1)
        self.map_canvas = ctk.CTkCanvas(self.map_viewport, bg="#05090c", highlightthickness=0, bd=0)
        self.map_canvas.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.map_canvas.bind("<Configure>", self._on_map_canvas_configure)
        self._build_map_chrome()

        self._build_layer_manager(content, row=1)
        self._build_hidden_runtime_panels(content)
        self.after_idle(self._refresh_preview)

    def _build_map_chrome(self) -> None:
        toggle = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#163743", border_width=1)
        toggle.place(x=16, y=14)
        ctk.CTkLabel(toggle, text="Aerial", width=74, height=40, corner_radius=6, fg_color="#007783", text_color="#eaffff", font=self._font(13, "bold")).grid(row=0, column=0)
        ctk.CTkLabel(toggle, text="Satellite", width=86, height=40, text_color="#aab5bc", font=self._font(13)).grid(row=0, column=1)
        controls = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#1a2d34", border_width=1)
        controls.place(relx=1, x=-16, y=14, anchor="ne")
        for idx, label in enumerate(("+", "-", "Layers", "Filter", "Locate")):
            ctk.CTkButton(controls, text=label, width=54, height=42, corner_radius=0, fg_color="transparent", hover_color="#102934", text_color="#e6eef1", font=self._font(11 if len(label) > 1 else 18)).grid(row=idx, column=0)
        legend = ctk.CTkFrame(self.map_viewport, corner_radius=7, fg_color="#071015", border_color="#20343b", border_width=1)
        legend.place(x=16, rely=1, y=-16, anchor="sw")
        ctk.CTkLabel(legend, text="Parcel Status", font=self._font(13, "bold"), text_color="#f3f7f8").grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 8))
        for row, (dot, label, value) in enumerate((("#00d6d6", "Selected", "1"), ("#25d2bb", "Potential Lead", "87"), ("#ffc642", "Watchlist", "12"), ("#6e7a85", "Other", "4,882")), start=1):
            ctk.CTkLabel(legend, text="o", text_color=dot, font=self._font(13, "bold")).grid(row=row, column=0, sticky="w", padx=(14, 6), pady=(0, 9))
            ctk.CTkLabel(legend, text=label, text_color="#bdc8ce", font=self._font(12)).grid(row=row, column=1, sticky="w", pady=(0, 9))
            ctk.CTkLabel(legend, text=value, text_color="#ffffff", font=self._font(12, "bold")).grid(row=row, column=2, sticky="e", padx=(18, 14), pady=(0, 9))
        self.layers_restore_button = ctk.CTkButton(self.map_viewport, text="Layer Manager", width=116, height=38, corner_radius=7, fg_color="#071015", hover_color="#102029", border_color="#1a2d34", border_width=1, text_color="#00d6d6", font=self._font(12, "bold"), command=self._toggle_layer_manager)

    def _build_layer_manager(self, parent, row: int) -> None:
        self.layer_manager = self._panel(parent, row=row, padx=0, pady=(0, 0), radius=9)
        self.layer_manager.configure(fg_color="#070c10", border_color="#1b333b")
        self.layer_manager.grid(sticky="nsew")
        self.layer_manager.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Layer Manager", font=self._font(18, "bold"), text_color="#f2f7f8").grid(row=0, column=0, sticky="w")
        self.layer_toggle_button = ctk.CTkButton(header, text="Hide", width=64, height=30, corner_radius=6, fg_color="#0c171d", hover_color="#102934", text_color="#c8d2d8", font=self._font(12, "bold"), command=self._toggle_layer_manager)
        self.layer_toggle_button.grid(row=0, column=1, sticky="e")
        tabs = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        for col, tab in enumerate(("Environmental", "Physical", "Zoning & Planning", "Infrastructure", "Boundaries", "Risk")):
            ctk.CTkLabel(tabs, text=tab, height=30, text_color="#00dedb" if col == 0 else "#a7b0b7", font=self._font(12, "bold" if col == 0 else "normal")).grid(row=0, column=col, padx=(0, 28), sticky="w")
        ctk.CTkFrame(tabs, height=2, fg_color="#00d6d6").grid(row=1, column=0, sticky="ew")
        rows = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 16))
        rows.grid_columnconfigure(0, weight=1)
        for index, item in enumerate((
            ("F", "Flood Hazard Zones (FEMA)", "1% Annual Chance Flood Hazard", "#063849", True, "65%"),
            ("W", "Wetlands (NWI)", "National Wetlands Inventory", "#0c3d28", True, "70%"),
            ("S", "Soils (SSURGO)", "Soil Survey Geographic Database", "#3a2315", True, "60%"),
            ("P", "Protected Areas", "Conservation & Protected Lands", "#3b310c", True, "50%"),
            ("E", "Environmental Justice Index", "EPA EJScreen 2.0", "#18333b", False, "0%"),
            ("R", "Wildfire Risk", "Wildfire Hazard Potential", "#3d2410", False, "0%"),
        )):
            self._layer_row(rows, index, *item)

    def _layer_row(self, parent, row: int, icon: str, title: str, sub: str, icon_bg: str, visible: bool, pct: str) -> None:
        item = ctk.CTkFrame(parent, height=60, corner_radius=7, fg_color="#0e171c", border_color="#132229", border_width=1)
        item.grid(row=row, column=0, sticky="ew", pady=4)
        item.grid_propagate(False)
        item.grid_columnconfigure(2, weight=1)
        ctk.CTkFrame(item, width=3, corner_radius=2, fg_color="#00d6d6" if visible else "#1b2b32").grid(row=0, column=0, rowspan=2, sticky="nsw", pady=8)
        ctk.CTkLabel(item, text=icon, width=38, height=38, corner_radius=6, fg_color=icon_bg, text_color="#00d6d6" if visible else "#9aa5ab", font=self._font(13, "bold")).grid(row=0, column=1, rowspan=2, padx=(12, 12), pady=10)
        ctk.CTkLabel(item, text=title, font=self._font(14), text_color="#eef5f7").grid(row=0, column=2, sticky="sw", pady=(9, 0))
        ctk.CTkLabel(item, text=sub, font=self._font(11), text_color="#9aa5ab").grid(row=1, column=2, sticky="nw", pady=(0, 8))
        ctk.CTkLabel(item, text="On" if visible else "Off", width=42, height=26, corner_radius=13, fg_color="#073d44" if visible else "#121b21", text_color="#00d6d6" if visible else "#748089", font=self._font(11, "bold")).grid(row=0, column=3, rowspan=2, padx=(16, 12))
        ctk.CTkProgressBar(item, width=150, height=4, progress_color="#00d6d6" if visible else "#6d7780", fg_color="#263039").grid(row=0, column=4, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(item, text=pct, font=self._font(12), text_color="#b9c4ca").grid(row=0, column=5, rowspan=2, padx=(0, 16))

    def _build_hidden_runtime_panels(self, parent) -> None:
        hidden = ctk.CTkFrame(parent, fg_color="transparent")
        hidden.grid(row=99, column=0)
        hidden.grid_remove()
        self.status_badge = ctk.CTkLabel(hidden, text="Ready")
        self.status_badge.grid(row=0, column=0)
        self.layer_controls = ctk.CTkFrame(hidden, fg_color="transparent")
        self.layer_controls.grid(row=1, column=0)
        for index, name in enumerate(RESOURCE_STATUS_ORDER):
            var = ctk.BooleanVar(value=False)
            self.preview_layer_vars[name] = var
            ctk.CTkCheckBox(self.layer_controls, text=name, variable=var, command=self._refresh_preview, state="disabled").grid(row=index, column=0)
        self.resource_rows = ctk.CTkFrame(hidden, fg_color="transparent")
        self.resource_rows.grid(row=2, column=0)
        self.zoning_snapshot = ctk.CTkLabel(hidden, text="")
        self.zoning_snapshot.grid(row=3, column=0)
        self.zoning_activity = ctk.CTkProgressBar(hidden)
        self.zoning_activity.grid(row=4, column=0)
        self.zoning_activity.grid_remove()
        self.zoning_rows = ctk.CTkFrame(hidden, fg_color="transparent")
        self.zoning_rows.grid(row=5, column=0)
        self.log_box = ctk.CTkTextbox(hidden)
        self.log_box.grid(row=6, column=0)
        self.log_box.configure(state="disabled")
        self.folder_entry = self._entry(hidden, "Destination folder")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid(row=7, column=0)
        self.group_menu = ctk.CTkOptionMenu(hidden, values=list(ENVIRONMENTAL_MENU_GROUPS))
        self.group_menu.set("All Resources")
        self.group_menu.grid(row=8, column=0)
        self.intended_use_entry = self._entry(hidden, "Optional intended use")
        self.intended_use_entry.grid(row=9, column=0)
        self.preview_status = ctk.CTkLabel(hidden, text="")
        self.preview_status.grid(row=10, column=0)
        self.preview_facts = ctk.CTkLabel(hidden, text="")
        self.preview_facts.grid(row=11, column=0)

    def _build_details_panel(self) -> None:
        panel = ctk.CTkFrame(self.right_rail, corner_radius=9, fg_color="#070b0f", border_color="#1b2b32", border_width=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(10, 14), pady=(74, 16))
        panel.grid_columnconfigure(0, weight=1)
        self.details_panel = panel
        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="26-017.00-123  *", font=self._font(20, "bold"), text_color="#f4fbfb").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="x", font=self._font(22), text_color="#a8b3b9").grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(header, text="POTENTIAL LEAD", height=22, corner_radius=5, fg_color="#063d42", text_color="#00f0e6", font=self._font(10, "bold")).grid(row=1, column=0, sticky="w", pady=(7, 9))
        ctk.CTkLabel(header, text="1021 Gilpin Ave\nWilmington, DE 19806\nNew Castle County", font=self._font(13), text_color="#d6e1e6", justify="left").grid(row=2, column=0, sticky="w")
        tabs = ctk.CTkFrame(panel, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 10))
        for col, tab in enumerate(("Overview", "Details", "Owner", "History")):
            ctk.CTkLabel(tabs, text=tab, height=34, text_color="#00e1df" if col == 0 else "#a6b0b8", font=self._font(12, "bold" if col == 0 else "normal")).grid(row=0, column=col, padx=(0, 24), sticky="w")
        ctk.CTkFrame(tabs, height=2, fg_color="#00d6d6").grid(row=1, column=0, sticky="ew")
        details = ctk.CTkFrame(panel, corner_radius=7, fg_color="#0a1014", border_color="#172830", border_width=1)
        details.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))
        details.grid_columnconfigure(1, weight=1)
        for row, (label, value) in enumerate((
            ("Parcel ID", "26-017.00-123"),
            ("Acres", "1.24"),
            ("Zoning", "C-2 (Commercial)"),
            ("Land Use", "Vacant Land"),
            ("Last Sale", "$950,000 on 06/12/2021"),
            ("Assessed Value", "$1,125,400"),
            ("Tax Map", "26-17.00-123.00"),
        )):
            ctk.CTkLabel(details, text=label, font=self._font(12), text_color="#9aa6ad").grid(row=row, column=0, sticky="w", padx=12, pady=8)
            ctk.CTkLabel(details, text=value, font=self._font(12), text_color="#e0e9ed").grid(row=row, column=1, sticky="e", padx=12, pady=8)
        self._details_section(panel, 3, "Notes", "Great redevelopment potential.\nSurrounded by new construction.\nCheck zoning variance history.", "+ Add Note")
        self._details_section(panel, 4, "Tags", "Redevelopment     High Potential", "+ Add Tag")
        self._details_section(panel, 5, "Documents", "Deed_2021.pdf        248 KB\nSurvey_2021.pdf      1.2 MB\nZoning_Letter.pdf    532 KB", "View All")
        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=14, pady=(4, 14))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Add to List                         v", height=44, corner_radius=7, fg_color="#0096a3", hover_color="#00aeba", text_color="#f1ffff", font=self._font(14, "bold")).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.package_button = ctk.CTkButton(footer, text="Generate Report", height=42, corner_radius=7, fg_color="#061116", hover_color="#0b2027", border_color="#006e79", border_width=1, text_color="#00d6d6", font=self._font(14, "bold"), command=self._create_package, state="disabled")
        self.package_button.grid(row=1, column=0, sticky="ew")

    def _details_section(self, parent, row: int, title: str, body: str, action: str) -> None:
        section = ctk.CTkFrame(parent, corner_radius=7, fg_color="#080f13", border_color="#101d24", border_width=1)
        section.grid(row=row, column=0, sticky="ew", padx=14, pady=(0, 10))
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text=title, font=self._font(14, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        ctk.CTkLabel(section, text=action, font=self._font(12, "bold"), text_color="#00d6d6").grid(row=0, column=1, sticky="e", padx=12, pady=(12, 6))
        ctk.CTkLabel(section, text=body, font=self._font(12), text_color="#cbd5da", justify="left").grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12))

    def _toggle_layer_manager(self) -> None:
        self.layer_manager_visible = not self.layer_manager_visible
        if self.layer_manager_visible:
            self.layer_manager.grid()
            self.layer_toggle_button.configure(text="Hide")
            self.layers_restore_button.place_forget()
            self.main_content.grid_rowconfigure(0, weight=3, minsize=450)
            self.main_content.grid_rowconfigure(1, weight=2, minsize=330)
        else:
            self.layer_manager.grid_remove()
            self.layer_toggle_button.configure(text="Show")
            self.main_content.grid_rowconfigure(0, weight=1, minsize=0)
            self.main_content.grid_rowconfigure(1, weight=0, minsize=0)
            self.layers_restore_button.place(relx=1, x=-78, y=14, anchor="ne")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not hasattr(self, "map_canvas"):
            return
        canvas = self.map_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#050a0c", outline="")
        for x in range(-80, width + 120, 124):
            for y in range(-50, height + 100, 82):
                shade = 28 + ((x * 5 + y * 3) % 32)
                canvas.create_rectangle(x, y, x + 72, y + 34, fill=f"#{shade:02x}{shade:02x}{max(shade - 5, 0):02x}", outline="#313a3a")
        for offset in (-120, 160, 440, 720, 1000, 1280):
            canvas.create_polygon(offset, -80, offset + 56, -80, offset + width * 0.15 + 120, height + 80, offset + width * 0.15 + 56, height + 80, fill="#242c2b", outline="")
        for y in (height * 0.18, height * 0.48, height * 0.78):
            canvas.create_polygon(-80, y, width + 80, y + 58, width + 80, y + 98, -80, y + 40, fill="#222928", outline="")
        parcel = (width * 0.47, height * 0.28, width * 0.59, height * 0.22, width * 0.69, height * 0.72, width * 0.54, height * 0.83, width * 0.43, height * 0.36)
        canvas.create_polygon(parcel, fill="", outline="#006b72", width=7)
        canvas.create_polygon(parcel, fill="#003f40", outline="#00d6d6", width=3)
        canvas.create_polygon(parcel, fill="#008b8b", outline="", stipple="gray50")
        pin_x, pin_y = width * 0.57, height * 0.50
        pin_r = max(16, min(width, height) * 0.035)
        canvas.create_oval(pin_x - pin_r, pin_y - pin_r, pin_x + pin_r, pin_y + pin_r, fill="#00cbd4", outline="")
        canvas.create_polygon(pin_x - pin_r * 0.55, pin_y + pin_r * 0.45, pin_x + pin_r * 0.55, pin_y + pin_r * 0.45, pin_x, pin_y + pin_r * 2.1, fill="#00cbd4", outline="")
        canvas.create_rectangle(0, 0, width, height, fill="#000000", outline="", stipple="gray75")

    def _reset_visuals(self) -> None:
        self.zoning_snapshot.configure(text="Running development options...")
        self.zoning_activity.grid()
        self.zoning_activity.start()
        for child in self.zoning_rows.winfo_children():
            child.destroy()
        for child in self.resource_rows.winfo_children():
            child.destroy()
        for var in self.preview_layer_vars.values():
            var.set(False)
        for child in self.layer_controls.winfo_children():
            child.configure(state="disabled")
        self._clear_log()
        self._refresh_preview()

    def _sync_run_button_state(self, running: bool | None = None) -> None:
        is_running = self.running_jobs > 0 if running is None else running
        new_search_pending = is_running and self._current_research_key() != self.active_research_key
        self.run_button.configure(text="+  New Search" if new_search_pending or not is_running else "x  Cancel Search", fg_color="#101820" if new_search_pending or not is_running else "#32191c")


class FunctionalPropSpectorApp(PropSpectorApp):
    """Functional premium shell with a live-sized GIS viewport and stable controls."""

    def __init__(self) -> None:
        ctk.set_widget_scaling(0.5)
        ctk.set_window_scaling(1.0)
        super().__init__()

    def _build_ui(self) -> None:
        ctk.set_widget_scaling(0.5)
        ctk.set_window_scaling(1.0)
        self.configure(fg_color="#020609")
        self.minsize(760, 520)
        self.left_width = 270
        self.details_width = 420
        self.layer_manager_visible = True
        self.active_workspace = "Dashboard"
        self.active_detail_tab = "Overview"
        self.map_mode = "Aerial"
        self.zoom_level = 1
        self.active_layer_group = "Environmental"
        self.saved_lists: dict[str, list[str]] = {"Redevelopment Watchlist": []}
        self.user_notes: list[str] = [
            "Great redevelopment potential.",
            "Surrounded by new construction.",
            "Check zoning variance history.",
        ]
        self.user_tags: list[tuple[str, str, str]] = [
            ("Redevelopment", "#062f3d", "#00d6d6"),
            ("High Potential", "#181d3a", "#c7b5ff"),
        ]
        self.generated_documents: list[Path] = []
        self.arcgis_visible_layers: set[str] = set(RESOURCE_STATUS_ORDER[:4])
        self.arcgis_viewer_bbox = (616645.185946933, 637885.7321867421, 618168.1540817255, 639062.5711999908)
        self.arcgis_parcel_geometry: dict | None = None
        self.arcgis_parcel_number = ""
        self.arcgis_viewer_image: Image.Image | None = None
        self.arcgis_viewer_status = "ArcGIS viewer ready"
        self.arcgis_viewer_request_id = 0
        self.arcgis_events: queue.Queue[tuple[int, Image.Image | None, tuple[float, float, float, float] | None, str]] = queue.Queue()
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.detail_tab_buttons: dict[str, ctk.CTkButton] = {}
        self.layer_widgets: list[dict[str, object]] = []
        self.demo_layers = [
            {"icon": "FH", "title": "Flood Hazard Zones (FEMA)", "sub": "1% Annual Chance Flood Hazard", "color": "#00cfe0", "on": True, "pct": 0.65},
            {"icon": "WL", "title": "Wetlands (NWI)", "sub": "National Wetlands Inventory", "color": "#20c997", "on": True, "pct": 0.70},
            {"icon": "SO", "title": "Soils (SSURGO)", "sub": "Soil Survey Geographic Database", "color": "#e3a64b", "on": True, "pct": 0.60},
            {"icon": "PA", "title": "Protected Areas", "sub": "Conservation and Protected Lands", "color": "#f4c542", "on": True, "pct": 0.50},
            {"icon": "EJ", "title": "Environmental Justice Index", "sub": "EPA EJScreen 2.0", "color": "#7aa7ff", "on": False, "pct": 0.0},
            {"icon": "WF", "title": "Wildfire Risk", "sub": "Wildfire Hazard Potential", "color": "#ff8a4c", "on": False, "pct": 0.0},
        ]

        self.grid_columnconfigure(0, minsize=155)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, minsize=8)
        self.grid_columnconfigure(3, minsize=self.details_width)
        self.grid_rowconfigure(0, weight=1)

        self.left_rail = ctk.CTkFrame(self, width=155, corner_radius=0, fg_color="#03080c")
        self.left_rail.configure(width=self.left_width, height=1)
        self.left_rail.place(x=0, y=0)
        self.left_rail.grid_propagate(False)
        self.left_rail.grid_columnconfigure(0, weight=1)
        self.left_rail.grid_rowconfigure(2, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#04090d")
        self.preview_shell.configure(width=600, height=1)
        self.preview_shell.place(x=self.left_width, y=0)
        self.preview_shell.grid_propagate(False)
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self.details_resize_handle = ctk.CTkFrame(self.preview_shell, width=8, corner_radius=0, fg_color="#071119")
        self.details_resize_handle.configure(width=8, height=1)
        self.details_resize_handle.place(x=self.left_width + 600, y=0)
        self.details_resize_handle.grid_propagate(False)
        self.details_resize_handle.bind("<ButtonPress-1>", self._start_details_resize)
        self.details_resize_handle.bind("<B1-Motion>", self._drag_details_resize)
        self.details_resize_handle.bind("<Double-Button-1>", lambda _event: self._set_details_width(420))
        self.details_resize_handle.bind("<Enter>", lambda _event: self.details_resize_handle.configure(fg_color="#0a4450"))
        self.details_resize_handle.bind("<Leave>", lambda _event: self.details_resize_handle.configure(fg_color="#071119"))

        self.right_rail = ctk.CTkFrame(self.preview_shell, width=self.details_width, corner_radius=0, fg_color="#04090d")
        self.right_rail.configure(width=self.details_width, height=1)
        self.right_rail.place(x=self.left_width + 608, y=0)
        self.right_rail.grid_propagate(False)
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

        self._build_left_rail()
        self._build_preview_area()
        self.details_resize_handle.destroy()
        self.right_rail.destroy()
        self._build_details_overlay_host()
        self._build_details_panel()
        self._build_runtime_controls()
        self.bind("<Configure>", self._on_root_configure)
        self.after_idle(self._fit_to_screen)
        for delay in (150, 500, 1000, 2000):
            self.after(delay, self._fit_to_screen)
        self.after_idle(self._refresh_preview)

    def _on_root_configure(self, event) -> None:
        if event.widget is self:
            self._layout_top_level_frames()

    def _layout_top_level_frames(self) -> None:
        if not hasattr(self, "right_rail"):
            return
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        left = min(self.left_width, max(220, int(width * 0.18)))
        handle = 8
        preview_width = max(620, width - left)
        map_width = max(self.map_viewport.winfo_width() if hasattr(self, "map_viewport") else 0, preview_width)
        map_height = max(self.map_viewport.winfo_height() if hasattr(self, "map_viewport") else 0, height)
        right = min(self.details_width, max(360, int(width * 0.26)), max(320, map_width - 520))
        center = max(360, map_width - right - handle)
        overlay_x_scale = 0.39
        overlay_height_scale = 0.48
        self.left_rail.configure(width=left, height=height)
        self.preview_shell.configure(width=preview_width, height=height)
        self.details_resize_handle.configure(width=handle, height=max(1, int(map_height * overlay_height_scale)))
        self.right_rail.configure(width=right, height=max(1, int(map_height * overlay_height_scale)))
        self.left_rail.place_configure(x=0, y=0)
        self.preview_shell.place_configure(x=left, y=0)
        self.details_resize_handle.place_configure(x=int(center * overlay_x_scale), y=0)
        self.right_rail.place_configure(x=int((center + handle) * overlay_x_scale), y=0)
        self.preview_shell.lift()
        self.left_rail.lift()
        self.details_resize_handle.lift()
        self.right_rail.lift()
        if hasattr(self, "layer_manager") and self.layer_manager_visible:
            self.layer_manager.lift()
    def _build_details_overlay_host(self) -> None:
        self.details_resize_handle = ctk.CTkFrame(self.map_viewport, width=8, corner_radius=0, fg_color="#071119")
        self.details_resize_handle.configure(width=8, height=1)
        self.details_resize_handle.place(x=600, y=0)
        self.details_resize_handle.grid_propagate(False)
        self.details_resize_handle.bind("<ButtonPress-1>", self._start_details_resize)
        self.details_resize_handle.bind("<B1-Motion>", self._drag_details_resize)
        self.details_resize_handle.bind("<Double-Button-1>", lambda _event: self._set_details_width(420))
        self.details_resize_handle.bind("<Enter>", lambda _event: self.details_resize_handle.configure(fg_color="#0a4450"))
        self.details_resize_handle.bind("<Leave>", lambda _event: self.details_resize_handle.configure(fg_color="#071119"))

        self.right_rail = ctk.CTkFrame(self.map_viewport, width=self.details_width, corner_radius=0, fg_color="#04090d")
        self.right_rail.configure(width=self.details_width, height=1)
        self.right_rail.place(x=608, y=0)
        self.right_rail.grid_propagate(False)
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

    def _maximize(self) -> None:
        self._fit_to_screen()
        self.after(350, self._ensure_fullscreen_geometry)

    def _ensure_fullscreen_geometry(self) -> None:
        self._fit_to_screen()

    def _fit_to_screen(self) -> None:
        self.update_idletasks()
        screen_w = max(self.winfo_screenwidth(), 1)
        screen_h = max(self.winfo_screenheight(), 1)
        actual_w = max(self.winfo_width(), 1)
        actual_h = max(self.winfo_height(), 1)
        scale_x = actual_w / screen_w if actual_w > screen_w else 1
        scale_y = actual_h / screen_h if actual_h > screen_h else 1
        requested_w = max(760, int(screen_w / scale_x))
        requested_h = max(520, int(screen_h / scale_y))
        self.geometry(f"{requested_w}x{requested_h}+0+0")
        self.update_idletasks()
        self._layout_top_level_frames()

    def _panel(self, parent, row: int | None = None, padx: int = 14, pady: tuple[int, int] | int = (0, 12), radius: int = 8) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(parent, corner_radius=radius, fg_color="#081017", border_color="#162831", border_width=1)
        if row is not None:
            panel.grid(row=row, column=0, sticky="ew", padx=padx, pady=pady)
        return panel

    def _premium_button(self, parent, text: str, command, height: int = 44, primary: bool = False) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            height=height,
            corner_radius=7,
            anchor="w",
            fg_color="#0095a0" if primary else "#101922",
            hover_color="#00aeba" if primary else "#162630",
            border_color="#00c8cf" if primary else "#1b2b34",
            border_width=1,
            text_color="#f4ffff" if primary else "#e2edf2",
            font=self._font(13, "bold" if primary else "normal"),
            command=command,
        )

    def _build_left_rail(self) -> None:
        header = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(28, 26))
        header.grid_columnconfigure(1, weight=1)
        logo = self._load_functional_logo(42)
        if logo is not None:
            ctk.CTkLabel(header, image=logo, text="").grid(row=0, column=0, rowspan=2, padx=(0, 12), pady=(0, 2))
            self.logo_image = logo
        else:
            ctk.CTkLabel(header, text="PS", width=42, height=42, corner_radius=10, fg_color="#062a30", border_color="#00a8b0", border_width=1, text_color="#00d8d8", font=self._font(14, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(brand, text="Prop", font=self._font(25, "bold"), text_color="#f4fbfb").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(brand, text="Spector", font=self._font(25, "bold"), text_color="#00d8d8").grid(row=0, column=1, sticky="w")
        self.status_badge = ctk.CTkLabel(header, text="Ready", height=24, corner_radius=12, fg_color="#071b1f", border_color="#16454c", border_width=1, text_color="#92f3ef", font=self._font(11, "bold"))
        self.status_badge.grid(row=1, column=1, sticky="w", pady=(4, 0))

        nav = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=16)
        nav.grid_columnconfigure(0, weight=1)
        nav_items = (
            ("D", "Dashboard"),
            ("M", "Map Explorer"),
            ("C", "Code Logic"),
            ("R", "Reports"),
            ("O", "Development Options"),
            ("G", "Demographics"),
            ("S", "Settings"),
        )
        for index, (icon, label) in enumerate(nav_items):
            button = ctk.CTkButton(
                nav,
                text=f"{icon}   {label}",
                height=48,
                corner_radius=7,
                anchor="w",
                fg_color="#08242c" if label == self.active_workspace else "transparent",
                hover_color="#112934",
                border_color="#0b606b" if label == self.active_workspace else "#03080c",
                border_width=1 if label == self.active_workspace else 0,
                text_color="#00e4e2" if label == self.active_workspace else "#c6d0d7",
                font=self._font(13, "bold" if label == self.active_workspace else "normal"),
                command=lambda name=label: self._select_workspace(name),
            )
            button.grid(row=index, column=0, sticky="ew", pady=(0, 8))
            self.nav_buttons[label] = button

        ctk.CTkFrame(self.left_rail, fg_color="transparent").grid(row=2, column=0, sticky="nsew")

        quick = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        quick.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 22))
        quick.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(quick, text="QUICK ACTIONS", font=self._font(11, "bold"), text_color="#86949d").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.run_button = self._premium_button(quick, "+  New Search", self._start_new_search)
        self.run_button.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._premium_button(quick, "Import Parcels", self._browse).grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._premium_button(quick, "Create List", self._create_list).grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self._premium_button(quick, "Generate Report", self._create_package).grid(row=4, column=0, sticky="ew")

        account = ctk.CTkFrame(self.left_rail, fg_color="#070d12", corner_radius=8, border_color="#162832", border_width=1)
        account.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 18))
        account.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(account, text="ZM", width=42, height=42, corner_radius=21, fg_color="#111b24", border_color="#283943", border_width=1, text_color="#f7ffff", font=self._font(14, "bold")).grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=12)
        ctk.CTkLabel(account, text="Zak Morris", font=self._font(13, "bold"), text_color="#eef6f8").grid(row=0, column=1, sticky="sw", pady=(12, 0))
        ctk.CTkLabel(account, text="Administrator", font=self._font(12), text_color="#9aa6ad").grid(row=1, column=1, sticky="nw", pady=(0, 12))
        ctk.CTkButton(account, text="v", width=30, height=30, corner_radius=15, fg_color="transparent", hover_color="#122630", text_color="#aeb9bf", command=lambda: self._select_workspace("Settings")).grid(row=0, column=2, rowspan=2, padx=(0, 10))

    def _load_functional_logo(self, size: int) -> ctk.CTkImage | None:
        try:
            image = Image.open(resource_path("assets", "PropspectorIcon.png"))
            return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
        except Exception:
            return None

    def _build_preview_area(self) -> None:
        top = ctk.CTkFrame(self.preview_shell, height=76, corner_radius=0, fg_color="#04090d")
        top.grid(row=0, column=0, sticky="ew", padx=(0, 12), pady=(16, 0))
        top.grid_columnconfigure(0, weight=1)

        self.search_shell = ctk.CTkFrame(top, height=54, corner_radius=9, fg_color="#090f15", border_color="#1f303a", border_width=1)
        self.search_shell.grid(row=0, column=0, sticky="w")
        self.search_shell.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.search_shell, text="Search", font=self._font(12, "bold"), text_color="#8f9da6").grid(row=0, column=0, padx=(16, 8))
        self.parcel_entry = ctk.CTkEntry(
            self.search_shell,
            width=320,
            height=42,
            border_width=0,
            fg_color="transparent",
            placeholder_text="Search by Address, Owner, Parcel ID...",
            placeholder_text_color="#7e8a92",
            text_color="#edf7f8",
            font=self._font(14),
        )
        self.parcel_entry.grid(row=0, column=1, sticky="ew")
        self.parcel_entry.bind("<KeyRelease>", lambda _event: self._sync_run_button_state())
        self.parcel_entry.bind("<Return>", lambda _event: self._run_or_cancel())
        self.parcel_entry.bind("<FocusIn>", lambda _event: self.search_shell.configure(border_color="#00cdd2"))
        self.parcel_entry.bind("<FocusOut>", lambda _event: self.search_shell.configure(border_color="#1f303a"))
        self.search_shell.bind("<Button-1>", lambda _event: self.parcel_entry.focus_set())
        self.bind_all("<Control-k>", lambda _event: self._focus_search())
        ctk.CTkButton(self.search_shell, text="Search", width=76, height=32, corner_radius=6, fg_color="#073d44", hover_color="#0c4f57", text_color="#eaffff", font=self._font(12, "bold"), command=self._run_or_cancel).grid(row=0, column=2, padx=(8, 4))
        ctk.CTkLabel(self.search_shell, text="Ctrl K", width=58, height=28, corner_radius=6, fg_color="#0f171c", border_color="#1b2a31", border_width=1, text_color="#c3cbd0", font=self._font(12, "bold")).grid(row=0, column=3, padx=(0, 10))

        tools = ctk.CTkFrame(top, fg_color="transparent")
        tools.grid(row=0, column=1, sticky="e")
        for col, (label, command) in enumerate((
            ("Moon", self._toggle_theme),
            ("Bell 3", lambda: self._select_workspace("Reports")),
            ("?", self._show_help),
            ("ZM", lambda: self._select_workspace("Settings")),
            ("v", lambda: self._select_workspace("Settings")),
        )):
            ctk.CTkButton(
                tools,
                text=label,
                width=48,
                height=42,
                corner_radius=21,
                fg_color="#111922" if label == "ZM" else "transparent",
                hover_color="#12242c",
                text_color="#e4edf0",
                font=self._font(11 if len(label) > 2 else 14, "bold" if label == "ZM" else "normal"),
                command=command,
            ).grid(row=0, column=col, padx=(6, 0))

        self.map_viewport = ctk.CTkFrame(self.preview_shell, corner_radius=9, fg_color="#050a0e", border_color="#18323b", border_width=1)
        self.map_viewport.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=(4, 16))
        self.map_viewport.grid_columnconfigure(0, weight=1)
        self.map_viewport.grid_rowconfigure(0, weight=1)

        self.map_canvas = ctk.CTkCanvas(self.map_viewport, bg="#05090c", highlightthickness=0, bd=0)
        self.map_canvas.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.map_canvas.bind("<Configure>", self._on_map_canvas_configure)
        self._build_map_chrome()
        self._build_layer_manager_overlay()

    def _build_map_chrome(self) -> None:
        self.map_mode_buttons: dict[str, ctk.CTkButton] = {}
        mode_switch = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#16343d", border_width=1)
        mode_switch.place(x=18, y=16)
        for col, mode in enumerate(("Aerial", "Satellite")):
            button = ctk.CTkButton(
                mode_switch,
                text=mode,
                width=78,
                height=38,
                corner_radius=6,
                fg_color="#007a86" if mode == self.map_mode else "transparent",
                hover_color="#0f2b34",
                text_color="#f0ffff" if mode == self.map_mode else "#aeb9bf",
                font=self._font(13, "bold" if mode == self.map_mode else "normal"),
                command=lambda name=mode: self._set_map_mode(name),
            )
            button.grid(row=0, column=col, padx=(0 if col == 0 else 2, 0), pady=2)
            self.map_mode_buttons[mode] = button

        controls = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#1a2d34", border_width=1)
        controls.place(relx=1, x=-18, y=16, anchor="ne")
        control_specs = (
            ("+", self._zoom_in),
            ("-", self._zoom_out),
            ("Layers", self._toggle_layer_manager),
            ("Filter", lambda: self._mock_action("Filter controls placeholder opened.")),
            ("Locate", lambda: self._mock_action("Map recentered on selected parcel.")),
        )
        for idx, (label, command) in enumerate(control_specs):
            ctk.CTkButton(
                controls,
                text=label,
                width=58,
                height=40,
                corner_radius=0,
                fg_color="transparent",
                hover_color="#102934",
                text_color="#e6eef1",
                font=self._font(11 if len(label) > 1 else 18, "bold" if len(label) > 1 else "normal"),
                command=command,
            ).grid(row=idx, column=0)

        self.map_legend = ctk.CTkFrame(self.map_viewport, corner_radius=7, fg_color="#071015", border_color="#20343b", border_width=1)
        self.map_legend.place(x=18, y=86)
        ctk.CTkLabel(self.map_legend, text="PARCEL STATUS", font=self._font(11, "bold"), text_color="#f3f7f8").grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 8))
        for row, (dot, label, value) in enumerate((("#00d6d6", "Selected", "1"), ("#25d2bb", "Potential Lead", "87"), ("#ffc642", "Watchlist", "12"), ("#6e7a85", "Other", "4,882")), start=1):
            ctk.CTkLabel(self.map_legend, text="o", text_color=dot, font=self._font(13, "bold")).grid(row=row, column=0, sticky="w", padx=(12, 6), pady=(0, 7))
            ctk.CTkLabel(self.map_legend, text=label, text_color="#bdc8ce", font=self._font(12)).grid(row=row, column=1, sticky="w", pady=(0, 7))
            ctk.CTkLabel(self.map_legend, text=value, text_color="#ffffff", font=self._font(12, "bold")).grid(row=row, column=2, sticky="e", padx=(18, 12), pady=(0, 7))

        self.layers_restore_button = ctk.CTkButton(
            self.map_viewport,
            text="Layer Manager",
            width=132,
            height=38,
            corner_radius=7,
            fg_color="#071015",
            hover_color="#102934",
            border_color="#1a2d34",
            border_width=1,
            text_color="#00d6d6",
            font=self._font(12, "bold"),
            command=self._toggle_layer_manager,
        )

    def _build_layer_manager_overlay(self) -> None:
        self.layer_manager = ctk.CTkFrame(self.preview_shell, height=230, corner_radius=9, fg_color="#070d12", border_color="#1e363f", border_width=1)
        self.layer_manager.place(relx=0.43, rely=1.0, anchor="s", relwidth=0.58, y=-120)
        self.layer_manager.lift()
        self.layer_manager.grid_propagate(False)
        self.layer_manager.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Layer Manager", font=self._font(17, "bold"), text_color="#f2f7f8").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="Live GIS-ready viewport", font=self._font(11), text_color="#7f8d95").grid(row=1, column=0, sticky="w", pady=(1, 0))
        self.layer_toggle_button = ctk.CTkButton(header, text="Hide", width=70, height=30, corner_radius=6, fg_color="#0c171d", hover_color="#102934", text_color="#c8d2d8", font=self._font(12, "bold"), command=self._toggle_layer_manager)
        self.layer_toggle_button.grid(row=0, column=1, rowspan=2, sticky="e")

        tabs = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.layer_group_buttons: dict[str, ctk.CTkButton] = {}
        for col, tab in enumerate(("Environmental", "Physical", "Zoning & Planning", "Infrastructure", "Boundaries", "Risk")):
            button = ctk.CTkButton(
                tabs,
                text=tab,
                height=30,
                corner_radius=5,
                fg_color="#08242c" if tab == self.active_layer_group else "transparent",
                hover_color="#102630",
                text_color="#00dedb" if tab == self.active_layer_group else "#a7b0b7",
                font=self._font(12, "bold" if tab == self.active_layer_group else "normal"),
                command=lambda name=tab: self._select_layer_group(name),
            )
            button.grid(row=0, column=col, padx=(0, 8), sticky="w")
            self.layer_group_buttons[tab] = button

        rows = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 12))
        rows.grid_columnconfigure(0, weight=1)
        self.layer_rows_frame = rows
        for index, layer in enumerate(self.demo_layers):
            self._functional_layer_row(rows, index, layer)

    def _select_layer_group(self, name: str) -> None:
        self.active_layer_group = name
        for label, button in self.layer_group_buttons.items():
            active = label == name
            button.configure(
                fg_color="#08242c" if active else "transparent",
                text_color="#00dedb" if active else "#a7b0b7",
                font=self._font(12, "bold" if active else "normal"),
            )
        self._sync_backend_layer_rows()
        self._log(f"{name} layers selected.")

    def _focus_search(self) -> None:
        if hasattr(self, "parcel_entry"):
            self.parcel_entry.focus_set()
            try:
                self.parcel_entry.icursor("end")
            except Exception:
                pass

    def _start_new_search(self) -> None:
        if self.running_jobs > 0:
            self._run_or_cancel()
            return
        parcel = self.parcel_entry.get().strip() if hasattr(self, "parcel_entry") else ""
        if parcel and not self.ready_for_package:
            self._run_or_cancel()
            return
        if parcel and self.ready_for_package:
            self.parcel_entry.delete(0, "end")
        self._focus_search()
        if hasattr(self, "search_shell"):
            self.search_shell.configure(border_color="#00cdd2")
        if hasattr(self, "status_badge"):
            self.status_badge.configure(text="Search", fg_color="#071b1f", text_color="#92f3ef")
        self._log("New search ready. Type an address, owner, or parcel ID, then press Search.")

    def _on_map_canvas_configure(self, event) -> None:
        self._refresh_preview()
        if self.preview_bundle is not None or not hasattr(self, "arcgis_viewer_image"):
            return
        image = self.arcgis_viewer_image
        if image is None:
            return
        if abs(int(event.width) - image.width) < 120 and abs(int(event.height) - image.height) < 120:
            return
        pending = getattr(self, "_map_resize_after_id", None)
        if pending is not None:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._map_resize_after_id = self.after(450, self._request_arcgis_viewer_refresh)

    def _request_arcgis_viewer_refresh(self) -> None:
        if not hasattr(self, "map_canvas"):
            return
        self.arcgis_viewer_request_id += 1
        request_id = self.arcgis_viewer_request_id
        width = max(640, int(self.map_canvas.winfo_width() or PREVIEW_WIDTH))
        height = max(420, int(self.map_canvas.winfo_height() or PREVIEW_HEIGHT))
        bbox = self._fit_bbox_to_viewport(tuple(float(value) for value in self.arcgis_viewer_bbox), width, height)
        self.arcgis_viewer_bbox = bbox
        export_width, export_height = self._arcgis_export_size(width, height)
        layer_names = tuple(self.arcgis_visible_layers)
        self.arcgis_viewer_status = "Loading ArcGIS imagery..."
        if hasattr(self, "preview_status"):
            self.preview_status.configure(text=self.arcgis_viewer_status)
        threading.Thread(target=self._arcgis_viewer_worker, args=(request_id, bbox, export_width, export_height, layer_names), daemon=True).start()
        self._refresh_preview()

    def _fit_bbox_to_viewport(self, bbox: tuple[float, float, float, float], width: int, height: int) -> tuple[float, float, float, float]:
        xmin, ymin, xmax, ymax = bbox
        box_width = max(xmax - xmin, 1.0)
        box_height = max(ymax - ymin, 1.0)
        target_ratio = max(width, 1) / max(height, 1)
        current_ratio = box_width / box_height
        if current_ratio < target_ratio:
            extra = (box_height * target_ratio - box_width) / 2
            xmin -= extra
            xmax += extra
        else:
            extra = (box_width / target_ratio - box_height) / 2
            ymin -= extra
            ymax += extra
        return xmin, ymin, xmax, ymax

    def _arcgis_export_size(self, width: int, height: int) -> tuple[int, int]:
        width = max(640, int(width))
        height = max(420, int(height))
        scale = min(1.0, 1400 / width, 980 / height)
        return max(640, int(width * scale)), max(420, int(height * scale))

    def _arcgis_viewer_worker(self, request_id: int, bbox: tuple[float, float, float, float], width: int, height: int, layer_names: tuple[str, ...] = ()) -> None:
        try:
            image = self._arcgis_export_image(IMAGERY_2025_MAPSERVER_URL, bbox, width, height, transparent=False)
            if layer_names:
                self.arcgis_events.put((request_id, image.copy(), bbox, "ArcGIS imagery loaded; loading selected layers..."))
            for service_url, layer_ids in self._arcgis_layers_by_service(layer_names).items():
                overlay = self._arcgis_export_image(service_url, bbox, width, height, transparent=True, layer_ids=layer_ids)
                image.alpha_composite(overlay)
            message = f"ArcGIS imagery loaded with {len(layer_names)} selected layer(s)" if layer_names else "ArcGIS imagery loaded"
            self.arcgis_events.put((request_id, image, bbox, message))
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("ArcGIS viewer refresh failed")
            self.arcgis_events.put((request_id, None, None, f"ArcGIS viewer failed: {exc}"))

    def _arcgis_export_image(
        self,
        service_url: str,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
        transparent: bool,
        layer_ids: tuple[int, ...] = (),
    ) -> Image.Image:
        params = {
            "f": "image",
            "bbox": ",".join(f"{value:.3f}" for value in bbox),
            "bboxSR": MAP_SPATIAL_REFERENCE,
            "imageSR": MAP_SPATIAL_REFERENCE,
            "size": f"{width},{height}",
            "format": "png32",
            "transparent": "true" if transparent else "false",
            "dpi": str(PREVIEW_DPI),
        }
        if layer_ids:
            params["layers"] = "show:" + ",".join(str(layer_id) for layer_id in layer_ids)
        url = f"{service_url.rstrip('/')}/export?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with urllib.request.urlopen(request, timeout=35) as response:
            return Image.open(io.BytesIO(response.read())).convert("RGBA")

    def _arcgis_layers_by_service(self, layer_names: tuple[str, ...]) -> dict[str, tuple[int, ...]]:
        grouped: dict[str, list[int]] = {}
        for name in layer_names:
            source = ENVIRONMENTAL_LAYER_SOURCES.get(name)
            if source is None:
                continue
            grouped.setdefault(source.mapserver_url, []).append(source.layer_id)
        return {url: tuple(dict.fromkeys(ids)) for url, ids in grouped.items()}

    def _drain_arcgis_events(self) -> None:
        while True:
            try:
                request_id, image, bbox, message = self.arcgis_events.get_nowait()
            except queue.Empty:
                break
            if request_id != self.arcgis_viewer_request_id:
                continue
            if image is not None and bbox is not None:
                self.arcgis_viewer_image = image
                self.arcgis_viewer_bbox = bbox
                self.arcgis_viewer_status = message
                if self.preview_bundle is None:
                    self._refresh_preview()
            else:
                self.arcgis_viewer_status = message
            if hasattr(self, "preview_status"):
                self.preview_status.configure(text=self.arcgis_viewer_status)
            if hasattr(self, "action_feedback") and self.action_feedback.winfo_exists():
                self.action_feedback.configure(text=self.arcgis_viewer_status)
        self.after(250, self._drain_arcgis_events)

    def _render_arcgis_viewer(self) -> None:
        canvas = self.map_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")
        if self.arcgis_viewer_image is None:
            canvas.create_rectangle(0, 0, width, height, fill="#050a0c", outline="")
            canvas.create_text(width / 2, height / 2, text=self.arcgis_viewer_status, fill="#8fa4aa", font=(self.font_family, 16, "bold"))
            self._lift_map_chrome()
            return
        image = self.arcgis_viewer_image.convert("RGB")
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        self.map_canvas_photo = ImageTk.PhotoImage(image)
        canvas.create_image(0, 0, image=self.map_canvas_photo, anchor="nw")
        self._draw_arcgis_parcel_highlight(canvas, width, height)
        self._lift_map_chrome()

    def _draw_arcgis_parcel_highlight(self, canvas, width: int, height: int) -> None:
        geometry = getattr(self, "arcgis_parcel_geometry", None)
        if not geometry:
            return
        all_points: list[tuple[float, float]] = []
        for ring in geometry.get("rings", []):
            points = [self._map_point_to_canvas(point, width, height) for point in ring]
            if len(points) < 2:
                continue
            flat = [coordinate for point in points for coordinate in point]
            canvas.create_polygon(*flat, fill="#00d6d6", stipple="gray50", outline="")
            canvas.create_line(*flat, fill="#001011", width=8, smooth=True, joinstyle="round")
            canvas.create_line(*flat, fill="#00e7e1", width=3, smooth=True, joinstyle="round")
            all_points.extend(points)
        if not all_points:
            return
        center_x = sum(point[0] for point in all_points) / len(all_points)
        center_y = sum(point[1] for point in all_points) / len(all_points)
        canvas.create_oval(center_x - 10, center_y - 10, center_x + 10, center_y + 10, fill="#00d6d6", outline="#021012", width=3)

    def _map_point_to_canvas(self, point: list[float], width: int, height: int) -> tuple[float, float]:
        xmin, ymin, xmax, ymax = self.arcgis_viewer_bbox
        x = (float(point[0]) - xmin) / max(xmax - xmin, 1.0) * width
        y = height - ((float(point[1]) - ymin) / max(ymax - ymin, 1.0) * height)
        return x, y

    def _zoom_arcgis_bbox(self, factor: float) -> None:
        xmin, ymin, xmax, ymax = self.arcgis_viewer_bbox
        center_x = (xmin + xmax) / 2
        center_y = (ymin + ymax) / 2
        half_width = (xmax - xmin) * factor / 2
        half_height = (ymax - ymin) * factor / 2
        self.arcgis_viewer_bbox = (center_x - half_width, center_y - half_height, center_x + half_width, center_y + half_height)
        self.preview_bundle = None
        self._request_arcgis_viewer_refresh()

    def _locate_selected_parcel(self) -> None:
        parcel = self.parcel_entry.get().strip() or "1021 Gilpin Ave"
        folder = self.folder_entry.get().strip() or str(Path.home() / "Documents")
        group = self.group_menu.get()
        width = max(640, int(self.map_canvas.winfo_width() or PREVIEW_WIDTH))
        height = max(420, int(self.map_canvas.winfo_height() or PREVIEW_HEIGHT))
        export_width, export_height = self._arcgis_export_size(width, height)
        layer_names = tuple(self.arcgis_visible_layers)
        self._log(f"Locating {parcel} in ArcGIS...")
        threading.Thread(target=self._locate_arcgis_worker, args=(parcel, folder, group, width, height, export_width, export_height, layer_names), daemon=True).start()

    def _locate_arcgis_worker(self, parcel: str, folder: str, group: str, viewport_width: int, viewport_height: int, export_width: int, export_height: int, layer_names: tuple[str, ...]) -> None:
        try:
            runner = EnvironmentalWidgetRunner(parcel, Path(folder), lambda message: self._emit(self.run_id, "log", f"ArcGIS: {message}"), self.stop_event, environmental_group=group)
            geometry = runner._fetch_parcel_geometry()
            bbox = runner._print_bbox(geometry.extent, viewport_width, viewport_height, context_ratio=PREVIEW_CONTEXT_RATIO, min_context_feet=PREVIEW_MIN_CONTEXT_FEET)
            bbox = self._fit_bbox_to_viewport(bbox, viewport_width, viewport_height)
            self.arcgis_viewer_bbox = bbox
            self.arcgis_parcel_geometry = geometry.geometry
            self.arcgis_parcel_number = geometry.parcel_number
            self.arcgis_viewer_request_id += 1
            request_id = self.arcgis_viewer_request_id
            self.arcgis_viewer_status = f"Located {geometry.parcel_number}; loading ArcGIS imagery..."
            self.arcgis_events.put((request_id, None, None, self.arcgis_viewer_status))
            self._arcgis_viewer_worker(request_id, bbox, export_width, export_height, layer_names)
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("ArcGIS locate failed")
            self.arcgis_events.put((self.arcgis_viewer_request_id, None, None, f"Locate failed: {exc}"))
            self._request_arcgis_viewer_refresh()

    def _functional_layer_row(self, parent, index: int, layer: dict[str, object]) -> None:
        active = bool(layer["on"])
        color = str(layer["color"])
        row = ctk.CTkFrame(parent, height=32, corner_radius=7, fg_color="#101922" if active else "#0b1117", border_color="#1e363f" if active else "#14242c", border_width=1)
        row.grid(row=index, column=0, sticky="ew", pady=(0, 6))
        row.grid_propagate(False)
        row.grid_columnconfigure(2, weight=1)
        accent = ctk.CTkFrame(row, width=3, corner_radius=2, fg_color=color if active else "#26343c")
        accent.grid(row=0, column=0, rowspan=2, sticky="nsw", pady=7)
        icon = ctk.CTkLabel(row, text=str(layer["icon"]), width=34, height=28, corner_radius=6, fg_color="#09232a" if active else "#111a21", text_color=color if active else "#8c99a2", font=self._font(11, "bold"))
        icon.grid(row=0, column=1, rowspan=2, padx=(10, 10))
        ctk.CTkLabel(row, text=str(layer["title"]), font=self._font(13, "bold"), text_color="#eef5f7").grid(row=0, column=2, sticky="sw", pady=(5, 0))
        ctk.CTkLabel(row, text=str(layer["sub"]), font=self._font(10), text_color="#8f9ca4").grid(row=1, column=2, sticky="nw", pady=(0, 5))
        toggle = ctk.CTkButton(row, text="On" if active else "Off", width=46, height=26, corner_radius=13, fg_color="#073d44" if active else "#121b21", hover_color="#0c4f57" if active else "#1b2830", text_color="#00d6d6" if active else "#78848c", font=self._font(11, "bold"), command=lambda i=index: self._toggle_demo_layer(i))
        toggle.grid(row=0, column=3, rowspan=2, padx=(10, 10))
        progress = ctk.CTkProgressBar(row, width=150, height=5, progress_color=color if active else "#56616a", fg_color="#263039")
        progress.set(float(layer["pct"]))
        progress.grid(row=0, column=4, rowspan=2, padx=(0, 10))
        percent = ctk.CTkLabel(row, text=f"{int(float(layer['pct']) * 100)}%", width=42, font=self._font(12), text_color="#b9c4ca")
        percent.grid(row=0, column=5, rowspan=2, padx=(0, 12))
        self.layer_widgets.append({"row": row, "accent": accent, "icon": icon, "toggle": toggle, "progress": progress, "percent": percent})

    def _build_details_panel(self) -> None:
        self.details_panel = ctk.CTkFrame(self.right_rail, corner_radius=9, fg_color="#070b10", border_color="#1b2b32", border_width=1)
        self.details_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 14), pady=(74, 16))
        self.details_panel.grid_columnconfigure(0, weight=1)
        self.details_panel.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self.details_panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)
        self.detail_title_label = ctk.CTkLabel(header, text="26-017.00-123  *", font=self._font(20, "bold"), text_color="#f4fbfb")
        self.detail_title_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="x", width=34, height=34, corner_radius=17, fg_color="transparent", hover_color="#17242c", text_color="#a8b3b9", font=self._font(18), command=lambda: self._mock_action("Details panel remains pinned for this workspace.")).grid(row=0, column=1, sticky="e")
        self.detail_status_label = ctk.CTkLabel(header, text="POTENTIAL LEAD", height=22, corner_radius=5, fg_color="#063d42", text_color="#00f0e6", font=self._font(10, "bold"))
        self.detail_status_label.grid(row=1, column=0, sticky="w", pady=(5, 8))
        self.detail_address_label = ctk.CTkLabel(header, text="1021 Gilpin Ave\nWilmington, DE 19806\nNew Castle County", font=self._font(13), text_color="#d6e1e6", justify="left")
        self.detail_address_label.grid(row=2, column=0, sticky="w")

        tabs = ctk.CTkFrame(self.details_panel, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 8))
        for col, tab in enumerate(("Overview", "Details", "Owner", "History")):
            button = ctk.CTkButton(
                tabs,
                text=tab,
                width=78,
                height=34,
                corner_radius=4,
                fg_color="#08242c" if tab == self.active_detail_tab else "transparent",
                hover_color="#102630",
                text_color="#00e1df" if tab == self.active_detail_tab else "#a6b0b8",
                font=self._font(12, "bold" if tab == self.active_detail_tab else "normal"),
                command=lambda name=tab: self._select_detail_tab(name),
            )
            button.grid(row=0, column=col, padx=(0, 5), sticky="w")
            self.detail_tab_buttons[tab] = button

        self.detail_content = ctk.CTkFrame(self.details_panel, fg_color="transparent")
        self.detail_content.grid(row=2, column=0, sticky="nsew", padx=14)
        self.detail_content.grid_columnconfigure(0, weight=1)
        self._render_detail_tab()

        footer = ctk.CTkFrame(self.details_panel, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 14))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Add to List                         v", height=44, corner_radius=7, fg_color="#0096a3", hover_color="#00aeba", text_color="#f1ffff", font=self._font(14, "bold"), command=self._add_to_list).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.package_button = ctk.CTkButton(footer, text="Generate Report", height=42, corner_radius=7, fg_color="#061116", hover_color="#0b2027", border_color="#006e79", border_width=1, text_color="#00d6d6", font=self._font(14, "bold"), command=self._create_package)
        self.package_button.grid(row=1, column=0, sticky="ew")

    def _render_detail_tab(self) -> None:
        for child in self.detail_content.winfo_children():
            child.destroy()
        if self.active_detail_tab == "Overview":
            self._render_overview_tab()
        elif self.active_detail_tab == "Details":
            self._render_text_tab("Development Brief", "Lorem ipsum zoning narrative, utility notes, entitlement risks, and nearby comparable projects are staged here until the live parcel service is connected.")
        elif self.active_detail_tab == "Owner":
            self._render_text_tab("Owner Profile", "Gilpin Holdings LLC\nMailing address, contact notes, related parcels, and outreach history placeholders are available for review.")
        else:
            self._render_text_tab("Parcel History", "2021 sale recorded at $950,000.\n2023 preliminary redevelopment conversation.\n2026 watchlist and lead scoring placeholder.")

    def _render_overview_tab(self) -> None:
        details = ctk.CTkFrame(self.detail_content, corner_radius=7, fg_color="#0a1014", border_color="#172830", border_width=1)
        details.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        details.grid_columnconfigure(1, weight=1)
        for row, (label, value) in enumerate((
            ("Parcel ID", "26-017.00-123"),
            ("Acres", "1.24"),
            ("Zoning", "C-2 (Commercial)"),
            ("Land Use", "Vacant Land"),
            ("Last Sale", "$950,000 on 06/12/2021"),
            ("Assessed Value", "$1,125,400"),
            ("Tax Map", "26-17.00-123.00"),
        )):
            ctk.CTkLabel(details, text=label, font=self._font(12), text_color="#9aa6ad").grid(row=row, column=0, sticky="w", padx=12, pady=6)
            ctk.CTkLabel(details, text=value, font=self._font(12), text_color="#e0e9ed").grid(row=row, column=1, sticky="e", padx=12, pady=6)
        self._details_section(self.detail_content, 1, "Notes", "Great redevelopment potential.\nSurrounded by new construction.\nCheck zoning variance history.", "+ Add Note", self._add_note)
        self._tags_section(self.detail_content, 2)
        self._documents_section(self.detail_content, 3)
        self.action_feedback = ctk.CTkLabel(self.detail_content, text="All controls are wired to placeholder actions.", font=self._font(11), text_color="#82919a")
        self.action_feedback.grid(row=4, column=0, sticky="w", pady=(0, 2))

    def _render_text_tab(self, title: str, body: str) -> None:
        card = ctk.CTkFrame(self.detail_content, corner_radius=7, fg_color="#0a1014", border_color="#172830", border_width=1)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=self._font(15, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))
        ctk.CTkLabel(card, text=body, font=self._font(12), text_color="#cbd5da", justify="left", wraplength=max(280, self.details_width - 80)).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 14))

    def _details_section(self, parent, row: int, title: str, body: str, action: str, command) -> None:
        section = ctk.CTkFrame(parent, corner_radius=7, fg_color="#080f13", border_color="#101d24", border_width=1)
        section.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text=title, font=self._font(14, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 5))
        ctk.CTkButton(section, text=action, width=88, height=28, corner_radius=5, fg_color="transparent", hover_color="#102630", text_color="#00d6d6", font=self._font(12, "bold"), command=command).grid(row=0, column=1, sticky="e", padx=10, pady=(8, 3))
        self.notes_label = ctk.CTkLabel(section, text=body, font=self._font(12), text_color="#cbd5da", justify="left")
        self.notes_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))

    def _tags_section(self, parent, row: int) -> None:
        section = ctk.CTkFrame(parent, corner_radius=7, fg_color="#080f13", border_color="#101d24", border_width=1)
        section.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text="Tags", font=self._font(14, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 7))
        ctk.CTkButton(section, text="+ Add Tag", width=82, height=28, corner_radius=5, fg_color="transparent", hover_color="#102630", text_color="#00d6d6", font=self._font(12, "bold"), command=self._add_tag).grid(row=0, column=1, sticky="e", padx=10, pady=(8, 3))
        chips = ctk.CTkFrame(section, fg_color="transparent")
        chips.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))
        self.tags_frame = chips
        self._tag_chip("Redevelopment", "#062f3d", "#00d6d6").grid(row=0, column=0, padx=(0, 6))
        self._tag_chip("High Potential", "#181d3a", "#c7b5ff").grid(row=0, column=1, padx=(0, 6))

    def _tag_chip(self, text: str, bg: str, fg: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(self.tags_frame, text=f"{text}  x", height=26, corner_radius=5, fg_color=bg, text_color=fg, font=self._font(11))

    def _documents_section(self, parent, row: int) -> None:
        section = ctk.CTkFrame(parent, corner_radius=7, fg_color="#080f13", border_color="#101d24", border_width=1)
        section.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text="Documents", font=self._font(14, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 7))
        ctk.CTkButton(section, text="View All", width=70, height=28, corner_radius=5, fg_color="transparent", hover_color="#102630", text_color="#00d6d6", font=self._font(12, "bold"), command=lambda: self._mock_action("Document library placeholder opened.")).grid(row=0, column=2, sticky="e", padx=10, pady=(8, 3))
        for idx, (name, size) in enumerate((("Deed_2021.pdf", "248 KB"), ("Survey_2021.pdf", "1.2 MB"), ("Zoning_Letter.pdf", "532 KB")), start=1):
            ctk.CTkButton(section, text=name, height=26, corner_radius=5, anchor="w", fg_color="transparent", hover_color="#101b22", text_color="#b9c5cb", font=self._font(12), command=lambda doc=name: self._mock_action(f"{doc} placeholder opened.")).grid(row=idx, column=0, sticky="ew", padx=10, pady=(0, 5))
            ctk.CTkLabel(section, text=size, font=self._font(11), text_color="#87939b").grid(row=idx, column=1, sticky="e", padx=8, pady=(0, 5))
            ctk.CTkButton(section, text="v", width=28, height=24, corner_radius=5, fg_color="transparent", hover_color="#102630", text_color="#8f9aa2", command=lambda doc=name: self._mock_action(f"{doc} download placeholder queued.")).grid(row=idx, column=2, sticky="e", padx=(0, 10), pady=(0, 5))

    def _build_runtime_controls(self) -> None:
        hidden = ctk.CTkFrame(self, fg_color="transparent")
        hidden.grid(row=99, column=0)
        hidden.grid_remove()
        self.layer_controls = ctk.CTkFrame(hidden, fg_color="transparent")
        self.layer_controls.grid(row=0, column=0)
        for index, name in enumerate(RESOURCE_STATUS_ORDER):
            var = ctk.BooleanVar(value=False)
            self.preview_layer_vars[name] = var
            ctk.CTkCheckBox(self.layer_controls, text=name, variable=var, command=self._refresh_preview, state="disabled").grid(row=index, column=0)
        self.resource_rows = ctk.CTkFrame(hidden, fg_color="transparent")
        self.resource_rows.grid(row=1, column=0)
        self.zoning_snapshot = ctk.CTkLabel(hidden, text="Development options ready.")
        self.zoning_snapshot.grid(row=2, column=0)
        self.zoning_activity = ctk.CTkProgressBar(hidden, mode="indeterminate")
        self.zoning_activity.grid(row=3, column=0)
        self.zoning_activity.grid_remove()
        self.zoning_rows = ctk.CTkFrame(hidden, fg_color="transparent")
        self.zoning_rows.grid(row=4, column=0)
        self.log_box = ctk.CTkTextbox(hidden)
        self.log_box.grid(row=5, column=0)
        self.log_box.configure(state="disabled")
        self.folder_entry = self._entry(hidden, "Destination folder")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid(row=6, column=0)
        self.group_menu = ctk.CTkOptionMenu(hidden, values=list(ENVIRONMENTAL_MENU_GROUPS))
        self.group_menu.set("All Resources")
        self.group_menu.grid(row=7, column=0)
        self.intended_use_entry = self._entry(hidden, "Optional intended use")
        self.intended_use_entry.grid(row=8, column=0)
        self.preview_status = ctk.CTkLabel(hidden, text="Ready")
        self.preview_status.grid(row=9, column=0)
        self.preview_facts = ctk.CTkLabel(hidden, text="")
        self.preview_facts.grid(row=10, column=0)

    def _entry(self, parent, placeholder: str) -> ctk.CTkEntry:
        return ctk.CTkEntry(parent, placeholder_text=placeholder, height=38, corner_radius=7, fg_color="#05090d", border_color="#263a42", text_color="#edf6f7", placeholder_text_color="#68757c", font=self._font(14))

    def _select_workspace(self, name: str) -> None:
        self.active_workspace = name
        for label, button in self.nav_buttons.items():
            active = label == name
            button.configure(
                fg_color="#08242c" if active else "transparent",
                border_color="#0b606b" if active else "#03080c",
                border_width=1 if active else 0,
                text_color="#00e4e2" if active else "#c6d0d7",
                font=self._font(13, "bold" if active else "normal"),
            )
        self.status_badge.configure(text=name[:10])
        self._mock_action(f"{name} workspace loaded with placeholder controls.")

    def _select_detail_tab(self, name: str) -> None:
        self.active_detail_tab = name
        for label, button in self.detail_tab_buttons.items():
            active = label == name
            button.configure(
                fg_color="#08242c" if active else "transparent",
                text_color="#00e1df" if active else "#a6b0b8",
                font=self._font(12, "bold" if active else "normal"),
            )
        self._render_detail_tab()

    def _set_map_mode(self, name: str) -> None:
        self.map_mode = name
        for label, button in self.map_mode_buttons.items():
            active = label == name
            button.configure(fg_color="#007a86" if active else "transparent", text_color="#f0ffff" if active else "#aeb9bf", font=self._font(13, "bold" if active else "normal"))
        self._refresh_preview()
        self._mock_action(f"{name} map mode selected.")

    def _toggle_layer_manager(self) -> None:
        self.layer_manager_visible = not self.layer_manager_visible
        if self.layer_manager_visible:
            self.layer_manager.place(relx=0.43, rely=1.0, anchor="s", relwidth=0.58, y=-120)
            self.layer_manager.lift()
            self.layer_toggle_button.configure(text="Hide")
            self.layers_restore_button.place_forget()
        else:
            self.layer_manager.place_forget()
            self.layers_restore_button.place(relx=1.0, rely=1.0, x=-18, y=-18, anchor="se")
        self._refresh_preview()

    def _toggle_demo_layer(self, index: int) -> None:
        layer = self.demo_layers[index]
        layer["on"] = not bool(layer["on"])
        active = bool(layer["on"])
        color = str(layer["color"])
        widgets = self.layer_widgets[index]
        widgets["row"].configure(fg_color="#101922" if active else "#0b1117", border_color="#1e363f" if active else "#14242c")
        widgets["accent"].configure(fg_color=color if active else "#26343c")
        widgets["icon"].configure(fg_color="#09232a" if active else "#111a21", text_color=color if active else "#8c99a2")
        widgets["toggle"].configure(text="On" if active else "Off", fg_color="#073d44" if active else "#121b21", hover_color="#0c4f57" if active else "#1b2830", text_color="#00d6d6" if active else "#78848c")
        self._refresh_preview()
        self._mock_action(f"{layer['title']} turned {'on' if active else 'off'}.")

    def _zoom_in(self) -> None:
        self.zoom_level = min(4, self.zoom_level + 1)
        self._refresh_preview()
        self._mock_action(f"Map zoom set to {self.zoom_level}.")

    def _zoom_out(self) -> None:
        self.zoom_level = max(1, self.zoom_level - 1)
        self._refresh_preview()
        self._mock_action(f"Map zoom set to {self.zoom_level}.")

    def _start_details_resize(self, event) -> None:
        self._resize_start_x = event.x_root
        self._resize_start_width = self.details_width
        self.details_resize_handle.configure(fg_color="#00b9c2")

    def _drag_details_resize(self, event) -> None:
        self._set_details_width(self._resize_start_width + self._resize_start_x - event.x_root)

    def _set_details_width(self, width: int) -> None:
        self.details_width = max(360, min(720, int(width)))
        self.right_rail.configure(width=self.details_width)
        self._layout_top_level_frames()

    def _mock_action(self, message: str) -> None:
        if hasattr(self, "action_feedback") and self.action_feedback.winfo_exists():
            self.action_feedback.configure(text=message)
        self._log(message)

    def _add_note(self) -> None:
        self.notes_label.configure(text="Great redevelopment potential.\nSurrounded by new construction.\nCheck zoning variance history.\nLorem ipsum note added for diligence review.")
        self._mock_action("Note added to the placeholder parcel record.")

    def _add_tag(self) -> None:
        if hasattr(self, "tags_frame") and self.tags_frame.winfo_exists() and not hasattr(self, "_added_due_diligence_tag"):
            self._added_due_diligence_tag = True
            self._tag_chip("Due Diligence", "#2c2410", "#ffd36e").grid(row=0, column=2, padx=(0, 6))
        self._mock_action("Tag added to the placeholder parcel record.")

    def _add_to_list(self) -> None:
        self._mock_action("Parcel added to Redevelopment Watchlist.")

    def _create_package(self) -> None:
        if self.ready_for_package and self.folder_entry.get().strip():
            try:
                super()._create_package()
                return
            except Exception as exc:
                self._log(f"Report generation needs review: {exc}")
        self._mock_action("Report draft prepared with placeholder parcel content.")

    def _set_running(self, running: bool, jobs: int | None = None) -> None:
        if jobs is not None:
            self.running_jobs = jobs
        self._sync_run_button_state(running)
        self.package_button.configure(state="normal", fg_color="#061116", text_color="#00d6d6")
        self.status_badge.configure(
            text="Running" if running else "Review" if self.had_error else "Ready",
            fg_color="#0f1d18" if running else "#2d2415" if self.had_error else "#071b1f",
            text_color="#94c6d8" if running else "#d0a96d" if self.had_error else "#92f3ef",
        )
        if running:
            self.zoning_activity.grid()
            self.zoning_activity.start()
        else:
            self.zoning_activity.stop()
            self.zoning_activity.grid_remove()

    def _sync_run_button_state(self, running: bool | None = None) -> None:
        if not hasattr(self, "run_button"):
            return
        is_running = self.running_jobs > 0 if running is None else running
        new_search_pending = False
        if hasattr(self, "parcel_entry") and hasattr(self, "group_menu") and hasattr(self, "intended_use_entry"):
            new_search_pending = is_running and self._current_research_key() != self.active_research_key
        self.run_button.configure(
            text="+  New Search" if new_search_pending or not is_running else "x  Cancel Search",
            fg_color="#101922" if new_search_pending or not is_running else "#35191d",
            hover_color="#162630" if new_search_pending or not is_running else "#4a2329",
            text_color="#e2edf2",
        )

    def _log(self, message: str) -> None:
        if hasattr(self, "log_box"):
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        if hasattr(self, "preview_status"):
            self.preview_status.configure(text=message)

    def _clear_log(self) -> None:
        if hasattr(self, "log_box"):
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.configure(state="disabled")

    def _reset_visuals(self) -> None:
        self.zoning_snapshot.configure(text="Running development options...")
        self.zoning_activity.grid()
        self.zoning_activity.start()
        for child in self.zoning_rows.winfo_children():
            child.destroy()
        for child in self.resource_rows.winfo_children():
            child.destroy()
        for var in self.preview_layer_vars.values():
            var.set(False)
        for child in self.layer_controls.winfo_children():
            child.configure(state="disabled")
        self._clear_log()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not hasattr(self, "map_canvas"):
            return
        canvas = self.map_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")
        base = "#050a0c" if self.map_mode == "Aerial" else "#060b12"
        canvas.create_rectangle(0, 0, width, height, fill=base, outline="")

        zoom_shift = (self.zoom_level - 1) * 18
        for x in range(-120 - zoom_shift, int(width) + 160, 124):
            for y in range(-80 - zoom_shift, int(height) + 120, 82):
                shade = 30 + ((x * 5 + y * 3) % 34)
                roof = f"#{shade:02x}{shade:02x}{max(shade - 6, 0):02x}"
                canvas.create_rectangle(x, y, x + 72, y + 34, fill=roof, outline="#343e3f")
                if (x + y) % 3 == 0:
                    canvas.create_rectangle(x + 8, y + 6, x + 64, y + 28, fill="", outline="#4b5555")

        for offset in (-180, 120, 420, 720, 1020, 1320):
            canvas.create_polygon(offset, -90, offset + 58, -90, offset + width * 0.14 + 140, height + 90, offset + width * 0.14 + 72, height + 90, fill="#232c2c", outline="")
            canvas.create_line(offset + 28, -80, offset + width * 0.14 + 106, height + 80, fill="#65716f", width=1)
        for y in (height * 0.18, height * 0.48, height * 0.77):
            canvas.create_polygon(-90, y, width + 90, y + 58, width + 90, y + 98, -90, y + 40, fill="#202827", outline="")
            canvas.create_line(-80, y + 19, width + 80, y + 77, fill="#5b6562", width=1)

        if any(bool(layer["on"]) for layer in self.demo_layers):
            for idx, layer in enumerate(self.demo_layers):
                if bool(layer["on"]):
                    color = str(layer["color"])
                    y = height * (0.24 + idx * 0.07)
                    canvas.create_line(width * 0.16, y, width * 0.88, y + height * 0.08, fill=color, width=2, stipple="gray50")

        parcel = (
            width * 0.48, height * 0.27,
            width * 0.60, height * 0.22,
            width * 0.69, height * 0.70,
            width * 0.55, height * 0.82,
            width * 0.43, height * 0.36,
        )
        canvas.create_polygon(parcel, fill="", outline="#005b64", width=8)
        canvas.create_polygon(parcel, fill="#004346", outline="#00d6d6", width=3)
        canvas.create_polygon(parcel, fill="#008b8b", outline="", stipple="gray50")

        pin_x, pin_y = width * 0.57, height * 0.49
        pin_r = max(15, min(width, height) * 0.03)
        canvas.create_oval(pin_x - pin_r * 1.2, pin_y - pin_r * 1.2, pin_x + pin_r * 1.2, pin_y + pin_r * 1.2, fill="#003c43", outline="")
        canvas.create_oval(pin_x - pin_r, pin_y - pin_r, pin_x + pin_r, pin_y + pin_r, fill="#00cbd4", outline="")
        canvas.create_polygon(pin_x - pin_r * 0.55, pin_y + pin_r * 0.45, pin_x + pin_r * 0.55, pin_y + pin_r * 0.45, pin_x, pin_y + pin_r * 2.0, fill="#00cbd4", outline="")
        canvas.create_oval(pin_x - 5, pin_y - 5, pin_x + 5, pin_y + 5, fill="#042026", outline="")
        canvas.create_rectangle(0, 0, width, height, fill="#000000", outline="", stipple="gray75")
        if self.layer_manager_visible:
            self._draw_canvas_layer_manager(canvas, width, height)
        if hasattr(self, "layer_manager") and self.layer_manager_visible:
            self.layer_manager.lift()
        if hasattr(self, "map_legend"):
            self.map_legend.lift()
        if hasattr(self, "details_resize_handle"):
            self.details_resize_handle.lift()
        if hasattr(self, "right_rail"):
            self.right_rail.lift()

    def _draw_canvas_layer_manager(self, canvas, width: int, height: int) -> None:
        panel_width = min(width * 0.62, 1280)
        x0 = max(28, width * 0.08)
        x1 = x0 + panel_width
        y1 = max(420, height - 220)
        y0 = max(220, y1 - 360)
        canvas.create_rectangle(x0 + 8, y0 + 10, x1 + 8, y1 + 10, fill="#010406", outline="", stipple="gray50")
        canvas.create_rectangle(x0, y0, x1, y1, fill="#071017", outline="#1e363f", width=2)
        canvas.create_text(x0 + 28, y0 + 30, text="Layer Manager", fill="#f2f7f8", anchor="w", font=(self.font_family, 15, "bold"))
        canvas.create_text(x1 - 68, y0 + 30, text="Hide", fill="#9fb8bf", anchor="center", font=(self.font_family, 11, "bold"))
        tabs = ("Environmental", "Physical", "Zoning & Planning", "Infrastructure", "Boundaries", "Risk")
        tx = x0 + 28
        for index, tab in enumerate(tabs):
            fill = "#00dedb" if index == 0 else "#8f9ca4"
            canvas.create_text(tx, y0 + 68, text=tab, fill=fill, anchor="w", font=(self.font_family, 10, "bold" if index == 0 else "normal"))
            tx += 145 if index != 2 else 175
        row_y = y0 + 98
        for index, layer in enumerate(self.demo_layers):
            active = bool(layer["on"])
            color = str(layer["color"]) if active else "#53616a"
            row_top = row_y + index * 40
            canvas.create_rectangle(x0 + 18, row_top, x1 - 18, row_top + 30, fill="#101922" if active else "#0b1117", outline="#1e363f" if active else "#14242c")
            canvas.create_rectangle(x0 + 18, row_top, x0 + 22, row_top + 30, fill=color, outline="")
            canvas.create_text(x0 + 40, row_top + 15, text=str(layer["icon"]), fill=color, anchor="w", font=(self.font_family, 9, "bold"))
            canvas.create_text(x0 + 86, row_top + 9, text=str(layer["title"]), fill="#eef5f7", anchor="w", font=(self.font_family, 10, "bold"))
            canvas.create_text(x0 + 86, row_top + 23, text=str(layer["sub"]), fill="#8f9ca4", anchor="w", font=(self.font_family, 8, "normal"))
            canvas.create_text(x1 - 260, row_top + 15, text="On" if active else "Off", fill="#00d6d6" if active else "#78848c", anchor="center", font=(self.font_family, 9, "bold"))
            bar_x0 = x1 - 210
            bar_x1 = x1 - 80
            canvas.create_line(bar_x0, row_top + 15, bar_x1, row_top + 15, fill="#263039", width=3)
            canvas.create_line(bar_x0, row_top + 15, bar_x0 + (bar_x1 - bar_x0) * float(layer["pct"]), row_top + 15, fill=color, width=3)
            canvas.create_text(x1 - 38, row_top + 15, text=f"{int(float(layer['pct']) * 100)}%", fill="#b9c4ca", anchor="e", font=(self.font_family, 9, "normal"))


class DockedPropSpectorApp(FunctionalPropSpectorApp):
    """Stable docked shell for the premium PropSpector dashboard."""

    def __init__(self) -> None:
        ctk.set_window_scaling(1.0)
        ctk.set_widget_scaling(1.0)
        PropSpectorApp.__init__(self)

    def _build_ui(self) -> None:
        self._sync_window_geometry_scaling()
        ctk.set_widget_scaling(1.0)
        self.configure(fg_color="#020609")
        self.minsize(1120, 720)
        self.left_width = 252
        self.details_width = 390
        self.layer_manager_visible = True
        self.active_workspace = "Dashboard"
        self.active_detail_tab = "Overview"
        self.map_mode = "Aerial"
        self.zoom_level = 1
        self.active_layer_group = "Environmental"
        self.saved_lists: dict[str, list[str]] = {"Redevelopment Watchlist": []}
        self.user_notes: list[str] = [
            "Great redevelopment potential.",
            "Surrounded by new construction.",
            "Check zoning variance history.",
        ]
        self.user_tags: list[tuple[str, str, str]] = [
            ("Redevelopment", "#062f3d", "#00d6d6"),
            ("High Potential", "#181d3a", "#c7b5ff"),
        ]
        self.generated_documents: list[Path] = []
        self.arcgis_visible_layers: set[str] = set(RESOURCE_STATUS_ORDER[:4])
        self.arcgis_viewer_bbox = (616645.185946933, 637885.7321867421, 618168.1540817255, 639062.5711999908)
        self.arcgis_parcel_geometry: dict | None = None
        self.arcgis_parcel_number = ""
        self.arcgis_viewer_image: Image.Image | None = None
        self.arcgis_viewer_status = "ArcGIS viewer ready"
        self.arcgis_viewer_request_id = 0
        self.arcgis_events: queue.Queue[tuple[int, Image.Image | None, tuple[float, float, float, float] | None, str]] = queue.Queue()
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.detail_tab_buttons: dict[str, ctk.CTkButton] = {}
        self.layer_widgets: list[dict[str, object]] = []
        self.demo_layers = [
            {"icon": "FH", "title": "Flood Hazard Zones (FEMA)", "sub": "1% Annual Chance Flood Hazard", "color": "#00cfe0", "on": True, "pct": 0.65},
            {"icon": "WL", "title": "Wetlands (NWI)", "sub": "National Wetlands Inventory", "color": "#20c997", "on": True, "pct": 0.70},
            {"icon": "SO", "title": "Soils (SSURGO)", "sub": "Soil Survey Geographic Database", "color": "#e3a64b", "on": True, "pct": 0.60},
            {"icon": "PA", "title": "Protected Areas", "sub": "Conservation & Protected Lands", "color": "#f4c542", "on": True, "pct": 0.50},
            {"icon": "EJ", "title": "Environmental Justice Index", "sub": "EPA EJScreen 2.0", "color": "#7aa7ff", "on": False, "pct": 0.0},
            {"icon": "WF", "title": "Wildfire Risk", "sub": "Wildfire Hazard Potential", "color": "#ff8a4c", "on": False, "pct": 0.0},
        ]

        self.grid_columnconfigure(0, minsize=self.left_width, weight=0)
        self.grid_columnconfigure(1, minsize=480, weight=1)
        self.grid_columnconfigure(2, minsize=8, weight=0)
        self.grid_columnconfigure(3, minsize=self.details_width, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self.left_rail = ctk.CTkFrame(self, width=self.left_width, corner_radius=0, fg_color="#03080c")
        self.left_rail.grid(row=0, column=0, sticky="nsew")
        self.left_rail.grid_propagate(False)
        self.left_rail.grid_columnconfigure(0, weight=1)
        self.left_rail.grid_rowconfigure(2, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#04090d")
        self.preview_shell.grid(row=0, column=1, sticky="nsew")
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self.details_resize_handle = ctk.CTkFrame(self, width=8, corner_radius=0, fg_color="#071119")
        self.details_resize_handle.grid(row=0, column=2, sticky="ns")
        self.details_resize_handle.grid_propagate(False)
        self.details_resize_handle.bind("<ButtonPress-1>", self._start_details_resize)
        self.details_resize_handle.bind("<B1-Motion>", self._drag_details_resize)
        self.details_resize_handle.bind("<Double-Button-1>", lambda _event: self._set_details_width(390))
        self.details_resize_handle.bind("<Enter>", lambda _event: self.details_resize_handle.configure(fg_color="#0a4450"))
        self.details_resize_handle.bind("<Leave>", lambda _event: self.details_resize_handle.configure(fg_color="#071119"))

        self.right_rail = ctk.CTkFrame(self, width=self.details_width, corner_radius=0, fg_color="#04090d")
        self.right_rail.grid(row=0, column=3, sticky="nsew")
        self.right_rail.grid_propagate(False)
        self.right_rail.grid_columnconfigure(0, weight=1)
        self.right_rail.grid_rowconfigure(0, weight=1)

        self._build_left_rail()
        self._build_preview_area()
        self._build_details_panel()
        self._build_runtime_controls()
        self._sync_backend_layer_rows()
        self.after_idle(self._refresh_preview)
        self.after(150, self._drain_arcgis_events)
        self.after(350, self._locate_selected_parcel)

    def _start(self) -> None:
        parcel = self.parcel_entry.get().strip() if hasattr(self, "parcel_entry") else ""
        super()._start()
        if parcel and self.running_jobs > 0:
            self._locate_selected_parcel()

    def _maximize(self) -> None:
        self.update_idletasks()
        self._set_raw_window_geometry(self._work_area_geometry())
        self.after(350, self._ensure_fullscreen_geometry)

    def _ensure_fullscreen_geometry(self) -> None:
        self._set_raw_window_geometry(self._work_area_geometry())

    def _sync_window_geometry_scaling(self) -> None:
        ctk.set_window_scaling(1.0)

    def _set_raw_window_geometry(self, geometry: str) -> None:
        try:
            self.tk.call("wm", "geometry", self._w, geometry)
        except Exception:
            self.geometry(geometry)

    def _work_area_geometry(self) -> str:
        if sys.platform.startswith("win"):
            try:
                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                rect = RECT()
                ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
                width = max(1120, rect.right - rect.left)
                height = max(720, rect.bottom - rect.top)
                return f"{width}x{height}+{rect.left}+{rect.top}"
            except Exception:
                pass
        try:
            screen_width = max(1120, self.winfo_screenwidth())
            screen_height = max(720, self.winfo_screenheight())
            return f"{screen_width}x{screen_height}+0+0"
        except Exception:
            return "1280x800+40+40"

    def _layout_top_level_frames(self) -> None:
        return

    def _build_map_chrome(self) -> None:
        self.map_mode_buttons: dict[str, ctk.CTkButton] = {}
        mode_switch = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#16343d", border_width=1)
        mode_switch.place(x=18, y=16)
        for col, mode in enumerate(("Aerial", "Satellite")):
            button = ctk.CTkButton(
                mode_switch,
                text=mode,
                width=78,
                height=38,
                corner_radius=6,
                fg_color="#007a86" if mode == self.map_mode else "transparent",
                hover_color="#0f2b34",
                text_color="#f0ffff" if mode == self.map_mode else "#aeb9bf",
                font=self._font(13, "bold" if mode == self.map_mode else "normal"),
                command=lambda name=mode: self._set_map_mode(name),
            )
            button.grid(row=0, column=col, padx=(0 if col == 0 else 2, 0), pady=2)
            self.map_mode_buttons[mode] = button

        controls = ctk.CTkFrame(self.map_viewport, fg_color="#071015", corner_radius=7, border_color="#1a2d34", border_width=1)
        controls.place(relx=1, x=-18, y=16, anchor="ne")
        control_specs = (
            ("+", self._zoom_in),
            ("-", self._zoom_out),
            ("Layers", self._toggle_layer_manager),
            ("Filter", lambda: self._select_workspace("Map Explorer")),
            ("Locate", self._locate_selected_parcel),
        )
        for idx, (label, command) in enumerate(control_specs):
            ctk.CTkButton(
                controls,
                text=label,
                width=58,
                height=40,
                corner_radius=0,
                fg_color="transparent",
                hover_color="#102934",
                text_color="#e6eef1",
                font=self._font(11 if len(label) > 1 else 18, "bold" if len(label) > 1 else "normal"),
                command=command,
            ).grid(row=idx, column=0)

        self.map_legend = ctk.CTkFrame(self.map_viewport, corner_radius=7, fg_color="#071015", border_color="#20343b", border_width=1)
        self.map_legend.place(x=18, y=86)
        ctk.CTkLabel(self.map_legend, text="PARCEL STATUS", font=self._font(11, "bold"), text_color="#f3f7f8").grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 8))
        for row, (dot, label, value) in enumerate((("#00d6d6", "Selected", "1"), ("#25d2bb", "Potential Lead", "Live"), ("#ffc642", "Watchlist", "0"), ("#6e7a85", "Backend", "Ready")), start=1):
            ctk.CTkLabel(self.map_legend, text="o", text_color=dot, font=self._font(13, "bold")).grid(row=row, column=0, sticky="w", padx=(12, 6), pady=(0, 7))
            ctk.CTkLabel(self.map_legend, text=label, text_color="#bdc8ce", font=self._font(12)).grid(row=row, column=1, sticky="w", pady=(0, 7))
            ctk.CTkLabel(self.map_legend, text=value, text_color="#ffffff", font=self._font(12, "bold")).grid(row=row, column=2, sticky="e", padx=(18, 12), pady=(0, 7))

        self.layers_restore_button = ctk.CTkButton(
            self.map_viewport,
            text="Layer Manager",
            width=132,
            height=38,
            corner_radius=7,
            fg_color="#071015",
            hover_color="#102934",
            border_color="#1a2d34",
            border_width=1,
            text_color="#00d6d6",
            font=self._font(12, "bold"),
            command=self._toggle_layer_manager,
        )

    def _build_layer_manager_overlay(self) -> None:
        self.layer_manager = ctk.CTkFrame(self.map_viewport, height=360, corner_radius=9, fg_color="#070d12", border_color="#1e363f", border_width=1)
        self.layer_manager.place(relx=0.5, rely=1.0, anchor="s", relwidth=0.92, y=-16)
        self.layer_manager.lift()
        self.layer_manager.grid_propagate(False)
        self.layer_manager.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Layer Manager", font=self._font(17, "bold"), text_color="#f2f7f8").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="Live GIS-ready viewport", font=self._font(11), text_color="#7f8d95").grid(row=1, column=0, sticky="w", pady=(1, 0))
        self.layer_toggle_button = ctk.CTkButton(header, text="Hide", width=70, height=30, corner_radius=6, fg_color="#0c171d", hover_color="#102934", text_color="#c8d2d8", font=self._font(12, "bold"), command=self._toggle_layer_manager)
        self.layer_toggle_button.grid(row=0, column=1, rowspan=2, sticky="e")

        tabs = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        tabs.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.layer_group_buttons: dict[str, ctk.CTkButton] = {}
        for col, tab in enumerate(("Environmental", "Physical", "Zoning & Planning", "Infrastructure", "Boundaries", "Risk")):
            button = ctk.CTkButton(
                tabs,
                text=tab,
                height=30,
                corner_radius=5,
                fg_color="#08242c" if tab == self.active_layer_group else "transparent",
                hover_color="#102630",
                text_color="#00dedb" if tab == self.active_layer_group else "#a7b0b7",
                font=self._font(12, "bold" if tab == self.active_layer_group else "normal"),
                command=lambda name=tab: self._select_layer_group(name),
            )
            button.grid(row=0, column=col, padx=(0, 8), sticky="w")
            self.layer_group_buttons[tab] = button

        rows = ctk.CTkFrame(self.layer_manager, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 12))
        rows.grid_columnconfigure(0, weight=1)
        self.layer_rows_frame = rows
        for index, layer in enumerate(self.demo_layers):
            self._functional_layer_row(rows, index, layer)

    def _functional_layer_row(self, parent, index: int, layer: dict[str, object]) -> None:
        active = bool(layer["on"])
        color = str(layer["color"])
        row = ctk.CTkFrame(parent, height=42, corner_radius=7, fg_color="#101922" if active else "#0b1117", border_color="#1e363f" if active else "#14242c", border_width=1)
        row.grid(row=index, column=0, sticky="ew", pady=(0, 7))
        row.grid_propagate(False)

        accent = ctk.CTkFrame(row, width=3, height=28, corner_radius=2, fg_color=color if active else "#26343c")
        accent.place(x=0, y=7)
        icon = ctk.CTkLabel(row, text=str(layer["icon"]), width=38, height=30, corner_radius=6, fg_color="#09232a" if active else "#111a21", text_color=color if active else "#8c99a2", font=self._font(11, "bold"))
        icon.place(x=12, y=6)
        title = ctk.CTkLabel(row, text=str(layer["title"]), font=self._font(13, "bold"), text_color="#eef5f7", anchor="w")
        title.place(x=64, y=4)
        subtitle = ctk.CTkLabel(row, text=str(layer["sub"]), font=self._font(10), text_color="#8f9ca4", anchor="w")
        subtitle.place(x=64, y=23)

        resource_name = str(layer.get("resource_name", ""))
        toggle_command = (lambda name=resource_name, i=index: self._toggle_backend_layer(name, i)) if resource_name else (lambda i=index: self._toggle_demo_layer(i))
        toggle = ctk.CTkButton(row, text="On" if active else "Off", width=48, height=28, corner_radius=14, fg_color="#073d44" if active else "#121b21", hover_color="#0c4f57" if active else "#1b2830", text_color="#00d6d6" if active else "#78848c", font=self._font(11, "bold"), command=toggle_command)
        toggle.place(relx=1.0, x=-300, y=7, anchor="ne")
        progress = ctk.CTkProgressBar(row, width=150, height=5, progress_color=color if active else "#56616a", fg_color="#263039")
        progress.set(float(layer["pct"]))
        progress.place(relx=1.0, x=-110, rely=0.5, anchor="e")
        percent = ctk.CTkLabel(row, text=f"{int(float(layer['pct']) * 100)}%", width=42, font=self._font(12), text_color="#b9c4ca")
        percent.place(relx=1.0, x=-14, rely=0.5, anchor="e")
        self.layer_widgets.append({"row": row, "accent": accent, "icon": icon, "toggle": toggle, "progress": progress, "percent": percent, "resource_name": resource_name, "pct": float(layer["pct"]), "color": color})

    def _apply_preview(self, preview: PreviewBundle) -> None:
        self.preview_bundle = preview
        for name, var in self.preview_layer_vars.items():
            var.set(name in preview.default_visible_layers)
        for child in self.layer_controls.winfo_children():
            child.configure(state="normal")
        self.preview_status.configure(text="Live GIS preview ready" if preview.layer_images else "Aerial ready; loading resources")
        self.preview_facts.configure(text=self._preview_facts_text(preview))
        self._update_detail_header_from_preview(preview)
        self._sync_backend_layer_rows()
        if self.active_detail_tab == "Overview":
            self._render_detail_tab()
        self._refresh_preview()

    def _apply_resources(self, statuses: tuple[ResourcePresence, ...]) -> None:
        PropSpectorApp._apply_resources(self, statuses)
        self._sync_backend_layer_rows()
        if self.active_detail_tab == "Overview":
            self._render_detail_tab()

    def _apply_zoning(self, result: FeasibilityResult) -> None:
        PropSpectorApp._apply_zoning(self, result)
        if self.active_detail_tab == "Overview":
            self._render_detail_tab()

    def _update_detail_header_from_preview(self, preview: PreviewBundle) -> None:
        facts = preview.parcel_facts
        parcel = facts.get("Parcel") or facts.get("Parcel ID") or self.parcel_entry.get().strip() or "Selected Parcel"
        address = facts.get("Address") or "Address not returned"
        owner = facts.get("Owner") or ""
        zoning = ", ".join(preview.zoning_districts) if preview.zoning_districts else facts.get("Zoning", "")
        if hasattr(self, "detail_title_label"):
            self.detail_title_label.configure(text=f"{parcel}  *")
        if hasattr(self, "detail_status_label"):
            self.detail_status_label.configure(text="LIVE BACKEND", fg_color="#063d42", text_color="#00f0e6")
        if hasattr(self, "detail_address_label"):
            lines = [address]
            if owner:
                lines.append(owner)
            if zoning:
                lines.append(f"Zoning: {zoning}")
            self.detail_address_label.configure(text="\n".join(lines[:3]))

    def _sync_backend_layer_rows(self) -> None:
        if not hasattr(self, "layer_rows_frame"):
            return
        for child in self.layer_rows_frame.winfo_children():
            child.destroy()
        self.layer_widgets.clear()

        models = self._backend_layer_models()
        for index, layer in enumerate(models[:6]):
            self._functional_layer_row(self.layer_rows_frame, index, layer)

    def _backend_layer_models(self) -> list[dict[str, object]]:
        if self.active_layer_group != "Environmental":
            group_layers = {
                "Physical": (
                    ("TO", "Topography", "ArcGIS physical layers will render here", "#7aa7ff"),
                    ("SO", "Soils", "Available through environmental soil services", "#e3a64b"),
                    ("HY", "Hydrology", "Waterbody and drainage overlays", "#00cfe0"),
                ),
                "Zoning & Planning": (
                    ("ZD", "Zoning Districts", "Populated by the zoning backend after research", "#c7b5ff"),
                    ("MU", "Municipality", "Municipal boundary context", "#7aa7ff"),
                    ("LU", "Land Use", "Land-use layer route ready", "#20c997"),
                ),
                "Infrastructure": (
                    ("RD", "Road Frontage", "Road overlay from ArcGIS query", "#d8d8d8"),
                    ("UT", "Utilities", "Utility route ready for service connection", "#00cfe0"),
                    ("TR", "Transit", "Transit layer route ready", "#f4c542"),
                ),
                "Boundaries": (
                    ("PL", "Parcel Boundary", "Parcel geometry from ArcGIS parcel service", "#00cfe0"),
                    ("CT", "County Boundary", "County context route ready", "#20c997"),
                    ("NB", "Neighborhood", "Neighborhood route ready", "#f4c542"),
                ),
                "Risk": (
                    ("FH", "Flood Risk", "FEMA floodplain backend layer", "#00cfe0"),
                    ("EJ", "Environmental Justice", "Risk route ready", "#7aa7ff"),
                    ("WR", "WRPA", "Water resource protection area layers", "#20c997"),
                ),
            }
            return [
                {"icon": icon, "title": title, "sub": subtitle, "color": color, "on": False, "pct": 0.0, "resource_name": ""}
                for icon, title, subtitle, color in group_layers.get(self.active_layer_group, ())
            ]

        statuses = self.resource_status_by_name
        preview = self.preview_bundle
        names = list(RESOURCE_STATUS_ORDER)

        def sort_key(name: str) -> tuple[int, int, int, int]:
            status = statuses.get(name)
            active = bool(self.preview_layer_vars.get(name) and self.preview_layer_vars[name].get()) if preview is not None else name in self.arcgis_visible_layers
            present = status is not None and status.status == "Present"
            has_layer = preview is not None and name in preview.layer_images
            return (0 if active else 1, 0 if present else 1, 0 if has_layer else 1, names.index(name))

        available = [name for name in names if name in statuses or (preview is not None and name in preview.layer_images)]
        if not available:
            available = names[:6]
        available.sort(key=sort_key)

        models: list[dict[str, object]] = []
        palette = ("#00cfe0", "#20c997", "#e3a64b", "#f4c542", "#7aa7ff", "#ff8a4c")
        for index, name in enumerate(available):
            status = statuses.get(name)
            active = bool(self.preview_layer_vars.get(name) and self.preview_layer_vars[name].get()) if preview is not None else name in self.arcgis_visible_layers
            present = status is not None and status.status == "Present"
            sub = self._backend_layer_subtitle(status, preview is not None and name in preview.layer_images)
            pct = 0.85 if active else 0.0
            if present and not active:
                pct = 0.25
            models.append(
                {
                    "icon": self._backend_layer_icon(name),
                    "title": self._backend_layer_title(name),
                    "sub": sub,
                    "color": palette[index % len(palette)],
                    "on": active,
                    "pct": pct,
                    "resource_name": name,
                }
            )
        return models

    def _backend_layer_subtitle(self, status: ResourcePresence | None, has_layer: bool) -> str:
        if status is None:
            return "Layer image ready" if has_layer else "Waiting for resource status"
        metric = self._resource_metric_text(status)
        if status.status == "Present":
            return f"Present - {metric}"
        if status.error:
            return f"{status.status} - {status.error[:48]}"
        return status.status

    def _backend_layer_title(self, name: str) -> str:
        replacements = {
            "FEMA 100-year Floodplain (1 PCT Annual Chance)": "FEMA 100-year Floodplain",
            "FEMA 500-year Floodplain (0.2 PCT Annual Chance)": "FEMA 500-year Floodplain",
            "Erosion Prone Soils/Slopes": "Erosion Prone Soils",
        }
        return replacements.get(name, name)

    def _backend_layer_icon(self, name: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", name)
        if not words:
            return "LY"
        if len(words) == 1:
            return words[0][:2].upper()
        return "".join(word[0] for word in words[:2]).upper()

    def _toggle_backend_layer(self, name: str, index: int) -> None:
        var = self.preview_layer_vars.get(name)
        if self.preview_bundle is None or var is None:
            if name in self.arcgis_visible_layers:
                self.arcgis_visible_layers.remove(name)
                active = False
            else:
                self.arcgis_visible_layers.add(name)
                active = True
            self._update_layer_widget_state(index, active)
            self._request_arcgis_viewer_refresh()
            self._log(f"{self._backend_layer_title(name)} {'shown' if active else 'hidden'} on the ArcGIS map.")
            return
        var.set(not bool(var.get()))
        active = bool(var.get())
        self._update_layer_widget_state(index, active)
        self._refresh_preview()
        self._mock_action(f"{self._backend_layer_title(name)} {'shown' if active else 'hidden'} on the live preview.")

    def _update_layer_widget_state(self, index: int, active: bool) -> None:
        if not 0 <= index < len(self.layer_widgets):
            return
        widgets = self.layer_widgets[index]
        color = str(widgets.get("color", "#00cfe0"))
        pct = float(widgets.get("pct", 0.85))
        widgets["row"].configure(fg_color="#101922" if active else "#0b1117", border_color="#1e363f" if active else "#14242c")
        widgets["accent"].configure(fg_color=color if active else "#26343c")
        widgets["icon"].configure(fg_color="#09232a" if active else "#111a21", text_color=color if active else "#8c99a2")
        widgets["toggle"].configure(text="On" if active else "Off", fg_color="#073d44" if active else "#121b21", hover_color="#0c4f57" if active else "#1b2830", text_color="#00d6d6" if active else "#78848c")
        widgets["progress"].configure(progress_color=color if active else "#56616a")
        widgets["progress"].set(pct if active else 0.0)
        widgets["percent"].configure(text=f"{int(pct * 100)}%" if active else "0%")

    def _select_workspace(self, name: str) -> None:
        self.active_workspace = name
        for label, button in self.nav_buttons.items():
            active = label == name
            button.configure(
                fg_color="#08242c" if active else "transparent",
                border_color="#0b606b" if active else "#03080c",
                border_width=1 if active else 0,
                text_color="#00e4e2" if active else "#c6d0d7",
                font=self._font(13, "bold" if active else "normal"),
            )
        self.status_badge.configure(text=name[:10])
        if name == "Map Explorer":
            if not self.layer_manager_visible:
                self._toggle_layer_manager()
            self.active_detail_tab = "Overview"
        elif name in {"Code Logic", "Development Options"}:
            self.active_detail_tab = "Details"
        elif name == "Reports":
            self.active_detail_tab = "History"
        self._render_detail_tab()
        self._log(f"{name} workspace opened.")

    def _select_detail_tab(self, name: str) -> None:
        self.active_detail_tab = name
        for label, button in self.detail_tab_buttons.items():
            active = label == name
            button.configure(
                fg_color="#08242c" if active else "transparent",
                text_color="#00e1df" if active else "#a6b0b8",
                font=self._font(12, "bold" if active else "normal"),
            )
        self._render_detail_tab()

    def _render_detail_tab(self) -> None:
        if not hasattr(self, "detail_content"):
            return
        for child in self.detail_content.winfo_children():
            child.destroy()
        if self.active_workspace == "Reports":
            self._render_reports_route()
            return
        if self.active_workspace in {"Code Logic", "Development Options"}:
            self._render_development_route()
            return
        if self.active_workspace == "Demographics":
            self._render_route_card("Demographics", "Demographic service route is ready. Connect the preferred demographic provider to populate population, income, household, and growth metrics.")
            return
        if self.active_workspace == "Settings":
            self._render_settings_route()
            return
        if self.active_detail_tab == "Overview":
            self._render_overview_tab()
        elif self.active_detail_tab == "Details":
            self._render_development_route()
        elif self.active_detail_tab == "Owner":
            self._render_owner_route()
        else:
            self._render_reports_route()

    def _render_route_card(self, title: str, body: str) -> None:
        card = ctk.CTkFrame(self.detail_content, corner_radius=7, fg_color="#0a1014", border_color="#172830", border_width=1)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=self._font(15, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))
        ctk.CTkLabel(card, text=body, font=self._font(12), text_color="#cbd5da", justify="left", wraplength=max(280, self.details_width - 80)).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 14))

    def _render_development_route(self) -> None:
        if self.zoning_result is None:
            self._render_route_card("Development Options", "Run research to populate zoning districts, by-right options, yield estimates, and code-review notes from the existing zoning backend.")
            return
        best = self._best_recommendation(self.zoning_result)
        headline = self._yield_breakdown(self.zoning_result, best) if best else self.zoning_result.summary
        zoning = ", ".join(district.code for district in self.zoning_result.zoning_districts) or "-"
        self._render_route_card("Development Options", f"{headline}\nZoning: {zoning}\nMunicipality: {self.zoning_result.municipality}")

    def _render_owner_route(self) -> None:
        facts = self.preview_bundle.parcel_facts if self.preview_bundle is not None else {}
        owner = facts.get("Owner") or "Owner will appear after research completes."
        address = facts.get("Address") or "-"
        parcel = facts.get("Parcel") or self.parcel_entry.get().strip() or "-"
        self._render_route_card("Owner Profile", f"Owner: {owner}\nParcel: {parcel}\nAddress: {address}\nList membership: {self._list_membership_text(parcel)}")

    def _render_reports_route(self) -> None:
        section = ctk.CTkFrame(self.detail_content, corner_radius=7, fg_color="#0a1014", border_color="#172830", border_width=1)
        section.grid(row=0, column=0, sticky="ew")
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text="Reports", font=self._font(15, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))
        status = "Ready to generate after research" if not self.ready_for_package else "Research preview ready. Generate Report will build the PDF package."
        ctk.CTkLabel(section, text=status, font=self._font(12), text_color="#cbd5da", justify="left", wraplength=max(280, self.details_width - 80)).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))
        docs = self.generated_documents
        if not docs:
            ctk.CTkLabel(section, text="No generated documents yet.", font=self._font(12), text_color="#8f9ca4").grid(row=2, column=0, sticky="w", padx=14, pady=(0, 14))
            return
        for index, path in enumerate(docs, start=2):
            ctk.CTkButton(section, text=path.name, height=30, corner_radius=5, anchor="w", fg_color="#101922", hover_color="#172832", text_color="#dbe8ec", font=self._font(12), command=lambda item=path: self._open_document(item)).grid(row=index, column=0, sticky="ew", padx=14, pady=(0, 8))

    def _render_settings_route(self) -> None:
        group = self.group_menu.get() if hasattr(self, "group_menu") else "All Resources"
        destination = self.folder_entry.get().strip() if hasattr(self, "folder_entry") else ""
        intended = self.intended_use_entry.get().strip() if hasattr(self, "intended_use_entry") else ""
        self._render_route_card("Settings", f"Destination: {destination or 'Default Documents folder'}\nEnvironmental group: {group}\nIntended use: {intended or '-'}\nClassic fallback: set PROPSPECTOR_CLASSIC_GUI=1 before launch.")

    def _list_membership_text(self, parcel: str) -> str:
        memberships = [name for name, parcels in self.saved_lists.items() if parcel in parcels]
        return ", ".join(memberships) if memberships else "Not listed"

    def _render_overview_tab(self) -> None:
        facts = self.preview_bundle.parcel_facts if self.preview_bundle is not None else {}
        zoning = ", ".join(self.preview_bundle.zoning_districts) if self.preview_bundle is not None and self.preview_bundle.zoning_districts else "-"
        present_count = sum(1 for status in self.resource_status_by_name.values() if status.status == "Present")
        best = self._best_recommendation(self.zoning_result) if self.zoning_result is not None else None
        development = self._yield_breakdown(self.zoning_result, best) if self.zoning_result is not None and best is not None else "Awaiting research"

        details = ctk.CTkFrame(self.detail_content, corner_radius=7, fg_color="#0a1014", border_color="#172830", border_width=1)
        details.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        details.grid_columnconfigure(1, weight=1)
        rows = (
            ("Parcel", facts.get("Parcel") or self.parcel_entry.get().strip() or "Awaiting search"),
            ("Address", facts.get("Address") or "Awaiting backend preview"),
            ("Owner", facts.get("Owner") or "-"),
            ("Zoning", zoning),
            ("Mapped Resources", f"{present_count} present" if self.resource_status_by_name else "Awaiting backend scan"),
            ("Development", development),
        )
        for row, (label, value) in enumerate(rows):
            ctk.CTkLabel(details, text=label, font=self._font(12), text_color="#9aa6ad").grid(row=row, column=0, sticky="w", padx=12, pady=6)
            ctk.CTkLabel(details, text=value, font=self._font(12), text_color="#e0e9ed", wraplength=max(220, self.details_width - 160), justify="right").grid(row=row, column=1, sticky="e", padx=12, pady=6)
        self._details_section(self.detail_content, 1, "Backend Activity", self.preview_status.cget("text") if hasattr(self, "preview_status") else "Ready", "+ Add Note", self._add_note)
        self._tags_section(self.detail_content, 2)
        self._documents_section(self.detail_content, 3)
        self.action_feedback = ctk.CTkLabel(self.detail_content, text="Visible controls are connected to the existing PropSpector backend.", font=self._font(11), text_color="#82919a")
        self.action_feedback.grid(row=4, column=0, sticky="w", pady=(0, 2))

    def _set_map_mode(self, name: str) -> None:
        self.map_mode = name
        for label, button in self.map_mode_buttons.items():
            active = label == name
            button.configure(fg_color="#007a86" if active else "transparent", text_color="#f0ffff" if active else "#aeb9bf", font=self._font(13, "bold" if active else "normal"))
        if self.preview_bundle is None:
            self._request_arcgis_viewer_refresh()
        else:
            self._refresh_preview()
        self._log(f"{name} map mode selected.")

    def _zoom_in(self) -> None:
        self.zoom_level = min(8, self.zoom_level + 1)
        self._zoom_arcgis_bbox(0.72)
        self._log(f"ArcGIS zoom level {self.zoom_level}.")

    def _zoom_out(self) -> None:
        self.zoom_level = max(1, self.zoom_level - 1)
        self._zoom_arcgis_bbox(1.38)
        self._log(f"ArcGIS zoom level {self.zoom_level}.")

    def _toggle_layer_manager(self) -> None:
        self.layer_manager_visible = not self.layer_manager_visible
        if self.layer_manager_visible:
            self.layer_manager.place(relx=0.5, rely=1.0, anchor="s", relwidth=0.92, y=-16)
            self.layer_manager.lift()
            self.layer_toggle_button.configure(text="Hide")
            self.layers_restore_button.place_forget()
        else:
            self.layer_manager.place_forget()
            self.layers_restore_button.place(relx=1.0, rely=1.0, x=-18, y=-18, anchor="se")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if self.preview_bundle is None:
            self._render_arcgis_viewer()
            return
        if not hasattr(self, "map_canvas"):
            return
        canvas = self.map_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")

        image = self._compose_backend_preview_image().convert("RGB")
        ratio = max(width / image.width, height / image.height)
        scaled_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
        image = image.resize(scaled_size, Image.Resampling.LANCZOS)
        left = max(0, (image.width - width) // 2)
        top = max(0, (image.height - height) // 2)
        image = image.crop((left, top, left + width, top + height))
        self.map_canvas_photo = ImageTk.PhotoImage(image)
        canvas.create_image(0, 0, image=self.map_canvas_photo, anchor="nw")
        self._lift_map_chrome()

    def _compose_backend_preview_image(self) -> Image.Image:
        assert self.preview_bundle is not None
        canvas = self.preview_bundle.base_image.copy()
        for name in RESOURCE_STATUS_ORDER:
            var = self.preview_layer_vars.get(name)
            if var is not None and var.get():
                layer = self.preview_bundle.layer_images.get(name)
                if layer is not None:
                    canvas.alpha_composite(layer)
        canvas.alpha_composite(self.preview_bundle.parcel_outline_image)
        canvas.alpha_composite(self.preview_bundle.road_overlay_image)
        return canvas

    def _lift_map_chrome(self) -> None:
        if hasattr(self, "layer_manager") and self.layer_manager_visible:
            self.layer_manager.lift()
        if hasattr(self, "map_legend"):
            self.map_legend.lift()
        if hasattr(self, "layers_restore_button") and not self.layer_manager_visible:
            self.layers_restore_button.lift()

    def _draw_canvas_layer_manager(self, canvas, width: int, height: int) -> None:
        return

    def _set_details_width(self, width: int) -> None:
        self.details_width = max(340, min(680, int(width)))
        self.grid_columnconfigure(3, minsize=self.details_width)
        if hasattr(self, "right_rail"):
            self.right_rail.configure(width=self.details_width)
        if hasattr(self, "details_panel"):
            self.details_panel.update_idletasks()

    def _tags_section(self, parent, row: int) -> None:
        section = ctk.CTkFrame(parent, corner_radius=7, fg_color="#080f13", border_color="#101d24", border_width=1)
        section.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text="Tags", font=self._font(14, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 7))
        ctk.CTkButton(section, text="+ Add Tag", width=82, height=28, corner_radius=5, fg_color="transparent", hover_color="#102630", text_color="#00d6d6", font=self._font(12, "bold"), command=self._add_tag).grid(row=0, column=1, sticky="e", padx=10, pady=(8, 3))
        chips = ctk.CTkFrame(section, fg_color="transparent")
        chips.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))
        self.tags_frame = chips
        for index, (text, bg, fg) in enumerate(self.user_tags):
            ctk.CTkLabel(chips, text=f"{text}  x", height=26, corner_radius=5, fg_color=bg, text_color=fg, font=self._font(11)).grid(row=0, column=index, padx=(0, 6))

    def _documents_section(self, parent, row: int) -> None:
        section = ctk.CTkFrame(parent, corner_radius=7, fg_color="#080f13", border_color="#101d24", border_width=1)
        section.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(section, text="Documents", font=self._font(14, "bold"), text_color="#f1f6f8").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 7))
        ctk.CTkButton(section, text="View All", width=70, height=28, corner_radius=5, fg_color="transparent", hover_color="#102630", text_color="#00d6d6", font=self._font(12, "bold"), command=lambda: self._select_workspace("Reports")).grid(row=0, column=2, sticky="e", padx=10, pady=(8, 3))
        if not self.generated_documents:
            ctk.CTkLabel(section, text="Generated reports will appear here.", font=self._font(12), text_color="#87939b").grid(row=1, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 10))
            return
        for idx, path in enumerate(self.generated_documents[:3], start=1):
            size = f"{path.stat().st_size / 1024:,.0f} KB" if path.exists() else "-"
            ctk.CTkButton(section, text=path.name, height=26, corner_radius=5, anchor="w", fg_color="transparent", hover_color="#101b22", text_color="#b9c5cb", font=self._font(12), command=lambda item=path: self._open_document(item)).grid(row=idx, column=0, sticky="ew", padx=10, pady=(0, 5))
            ctk.CTkLabel(section, text=size, font=self._font(11), text_color="#87939b").grid(row=idx, column=1, sticky="e", padx=8, pady=(0, 5))
            ctk.CTkButton(section, text="Open", width=44, height=24, corner_radius=5, fg_color="transparent", hover_color="#102630", text_color="#8f9aa2", command=lambda item=path: self._open_document(item)).grid(row=idx, column=2, sticky="e", padx=(0, 10), pady=(0, 5))

    def _add_note(self) -> None:
        note = f"Follow-up note {len(self.user_notes) + 1}: review after backend refresh."
        self.user_notes.append(note)
        if hasattr(self, "notes_label") and self.notes_label.winfo_exists():
            self.notes_label.configure(text="\n".join(self.user_notes[-4:]))
        self._log("Note added to this parcel workspace.")

    def _add_tag(self) -> None:
        if not any(tag[0] == "Backend Verified" for tag in self.user_tags):
            self.user_tags.append(("Backend Verified", "#102c24", "#7df2c4"))
        self._render_detail_tab()
        self._log("Tag added to this parcel workspace.")

    def _add_to_list(self) -> None:
        parcel = ""
        if self.preview_bundle is not None:
            parcel = self.preview_bundle.parcel_facts.get("Parcel", "")
        parcel = parcel or self.parcel_entry.get().strip() or "Current parcel"
        parcels = self.saved_lists.setdefault("Redevelopment Watchlist", [])
        if parcel not in parcels:
            parcels.append(parcel)
            self._log(f"{parcel} added to Redevelopment Watchlist.")
        else:
            self._log(f"{parcel} is already in Redevelopment Watchlist.")
        self._render_detail_tab()

    def _create_list(self) -> None:
        name = f"Parcel List {len(self.saved_lists) + 1}"
        self.saved_lists.setdefault(name, [])
        self._select_workspace("Reports")
        self._log(f"{name} created.")

    def _toggle_theme(self) -> None:
        current = ctk.get_appearance_mode().lower()
        next_mode = "light" if current == "dark" else "dark"
        ctk.set_appearance_mode(next_mode)
        self._log(f"{next_mode.title()} mode selected.")

    def _show_help(self) -> None:
        self._select_workspace("Settings")
        self._log("Help: enter an address or parcel, run research, then review layers and generate a report.")

    def _create_package(self) -> None:
        if self.ready_for_package and self.folder_entry.get().strip():
            PropSpectorApp._create_package(self)
            return
        if not self.parcel_entry.get().strip():
            self._log("Enter a parcel number or address before generating a report.")
        elif not self.ready_for_package:
            self._log("Run research first. Generate Report becomes active after the backend preview is ready.")
        else:
            self._log("Choose a destination folder before generating a report.")

    def _open_document(self, path: Path) -> None:
        if not path.exists():
            self._log(f"Document not found: {path.name}")
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            self._log(f"Opened {path.name}.")
        except Exception as exc:
            self._log(f"Could not open {path.name}: {exc}")

    def _set_running(self, running: bool, jobs: int | None = None) -> None:
        FunctionalPropSpectorApp._set_running(self, running, jobs)
        if hasattr(self, "package_button"):
            self.package_button.configure(
                state="normal",
                fg_color="#061116" if self.ready_for_package else "#0c171d",
                text_color="#00d6d6" if self.ready_for_package else "#6d8188",
            )

    def _drain_events(self) -> None:
        while True:
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            if len(item) == 3:
                event_run_id, event, payload = item
                if event_run_id != self.run_id:
                    continue
            else:
                event, payload = item
            if event == "log":
                self._log(str(payload))
                self.last_activity_message = str(payload)
            elif event == "resources":
                self._apply_resources(payload)  # type: ignore[arg-type]
            elif event == "preview" and isinstance(payload, PreviewBundle):
                self._apply_preview(payload)
            elif event == "env_done" and isinstance(payload, PreviewResult):
                self._apply_resources(payload.resource_statuses)
                self._apply_preview(payload.preview)
                self.ready_for_package = True
                self.package_button.configure(state="normal", fg_color="#061116", text_color="#00d6d6")
            elif event == "zoning" and isinstance(payload, FeasibilityResult):
                self._apply_zoning(payload)
            elif event == "package_done":
                paths = payload if isinstance(payload, tuple) else ()
                self.generated_documents = [Path(path) for path in paths]
                self._log(f"Created {len(paths)} environmental PDF file(s).")
                if self.active_workspace == "Reports" or self.active_detail_tab == "History":
                    self._render_detail_tab()
            elif event == "error":
                self._log(str(payload))
                self.had_error = True
                if str(payload).startswith("Zoning feasibility failed:"):
                    self._apply_zoning_failure(str(payload))
                    self.job_statuses["zoning"] = "Failed"
                elif str(payload).startswith("Environmental preview failed:"):
                    self.job_statuses["environmental"] = "Failed"
                self.status_badge.configure(text="Review", fg_color="#2d2415", text_color="#d0a96d")
            elif event == "job_done":
                job = str(payload)
                if self.job_statuses.get(job) == "Running":
                    self.job_statuses[job] = "Done"
                self.running_jobs = max(0, self.running_jobs - 1)
                if self.running_jobs == 0:
                    self._set_running(False)
        self.after(150, self._drain_events)

    def _log(self, message: str) -> None:
        FunctionalPropSpectorApp._log(self, message)
        if hasattr(self, "action_feedback") and self.action_feedback.winfo_exists():
            self.action_feedback.configure(text=message[:140])


def main() -> None:
    enable_high_dpi()
    app_class = PropSpectorApp if os.environ.get("PROPSPECTOR_CLASSIC_GUI") == "1" else DockedPropSpectorApp
    app = app_class()
    app.mainloop()
