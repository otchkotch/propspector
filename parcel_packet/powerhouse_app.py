from __future__ import annotations

import logging
import queue
import re
import threading
from pathlib import Path
from tkinter import filedialog
import tkinter.font as tkfont

import customtkinter as ctk
from PIL import Image

from .environmental_config import ENVIRONMENTAL_MENU_GROUPS, RESOURCE_STATUS_ORDER, ResourcePresence
from .environmental_widget_runner import EnvironmentalWidgetRunner, PreviewBundle, PreviewResult
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


APP_NAME = "Parcel Powerhouse"


class ParcelPowerhouseApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        configure_logging()
        load_bundled_fonts()
        ctk.set_appearance_mode("dark")

        self.font_family = self._pick_font_family()
        self.settings = load_settings()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.env_worker: threading.Thread | None = None
        self.zoning_worker: threading.Thread | None = None
        self.package_worker: threading.Thread | None = None
        self.running_jobs = 0

        self.preview_bundle: PreviewBundle | None = None
        self.preview_image: ctk.CTkImage | None = None
        self.preview_layer_vars: dict[str, ctk.BooleanVar] = {}
        self.resource_status_by_name: dict[str, ResourcePresence] = {}
        self.zoning_result: FeasibilityResult | None = None
        self.ready_for_package = False

        self.title(APP_NAME)
        self.geometry("1480x900+32+32")
        self.minsize(1160, 740)
        self.configure(fg_color="#05080a")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self.after(80, self._maximize)
        self.after(150, self._drain_events)

    def _font(self, size: int, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family=self.font_family, size=size, weight=weight)

    def _pick_font_family(self) -> str:
        available = set(tkfont.families(self))
        for family in ("Nunito Sans Normal", "Nunito Sans", "NunitoSans", "Avenir Next", "Avenir", "Segoe UI Variable Text", "Segoe UI"):
            if family in available:
                return family
        return "TkDefaultFont"

    def _maximize(self) -> None:
        try:
            self.state("zoomed")
        except Exception:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, minsize=430)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.left_rail = ctk.CTkScrollableFrame(self, width=430, corner_radius=0, fg_color="#070b0a")
        self.left_rail.grid(row=0, column=0, sticky="nsew")
        self.left_rail.grid_columnconfigure(0, weight=1)

        self.preview_shell = ctk.CTkFrame(self, corner_radius=0, fg_color="#030606")
        self.preview_shell.grid(row=0, column=1, sticky="nsew")
        self.preview_shell.grid_columnconfigure(0, weight=1)
        self.preview_shell.grid_rowconfigure(1, weight=1)

        self._build_left_rail()
        self._build_preview_area()

    def _build_left_rail(self) -> None:
        accent = ctk.CTkFrame(self.left_rail, height=42, corner_radius=0, fg_color="#285a48")
        accent.grid(row=0, column=0, sticky="ew")
        accent.grid_propagate(False)

        header = ctk.CTkFrame(self.left_rail, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Integrated Research", font=self._font(13, "bold"), text_color="#83bda8").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=APP_NAME, font=self._font(30, "bold"), text_color="#f2f5f3").grid(row=1, column=0, sticky="w")
        self.status_badge = ctk.CTkLabel(header, text="Ready", width=82, height=30, corner_radius=8, fg_color="#0e1814", text_color="#91c7a9", font=self._font(12, "bold"))
        self.status_badge.grid(row=1, column=1, sticky="e")
        ctk.CTkLabel(
            header,
            text="Quickly visualize mapped environmental resources and zoning feasibility in one reference workspace.",
            text_color="#8c9692",
            font=self._font(13),
            justify="left",
            wraplength=370,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))

        form = self._card(row=2)
        form.grid_columnconfigure(0, weight=1)
        self.parcel_entry = self._entry(form, "Parcel number")
        self.parcel_entry.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 7))

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
        )
        self.group_menu.set("All Resources")
        self.group_menu.grid(row=2, column=0, sticky="ew", padx=12, pady=7)

        self.intended_use_entry = self._entry(form, "Optional intended use: solar, hospital, apartments...")
        self.intended_use_entry.grid(row=3, column=0, sticky="ew", padx=12, pady=7)

        button_row = ctk.CTkFrame(form, fg_color="transparent")
        button_row.grid(row=4, column=0, sticky="ew", padx=12, pady=(7, 12))
        button_row.grid_columnconfigure((0, 1), weight=1)
        self.run_button = ctk.CTkButton(button_row, text="Run Research", height=42, corner_radius=9, fg_color="#4f8b6d", hover_color="#5a9b7a", font=self._font(14, "bold"), command=self._start)
        self.run_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.package_button = ctk.CTkButton(button_row, text="Create Maps", height=42, corner_radius=9, fg_color="#18231f", hover_color="#24362f", text_color="#8da69a", font=self._font(14, "bold"), command=self._create_package, state="disabled")
        self.package_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self._build_layer_controls(row=3)
        self._build_resource_panel(row=4)
        self._build_zoning_panel(row=5)
        self._build_log_panel(row=6)

    def _build_layer_controls(self, row: int) -> None:
        card = self._card(row=row)
        card.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Preview Layers", font=self._font(17, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="Present", width=72, height=28, corner_radius=7, fg_color="#20312b", hover_color="#2d493d", command=self._show_present_layers, font=self._font(12, "bold")).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(header, text="Clear", width=58, height=28, corner_radius=7, fg_color="#141b19", hover_color="#202a27", command=self._clear_layers, font=self._font(12, "bold")).grid(row=0, column=2, padx=(6, 0))

        self.layer_controls = ctk.CTkScrollableFrame(card, height=190, corner_radius=10, fg_color="#070a0d", border_color="#1b332b", border_width=1)
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

    def _build_resource_panel(self, row: int) -> None:
        self.resource_card = self._card(row=row)
        self.resource_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.resource_card, text="Environmental Resources", font=self._font(17, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.resource_rows = ctk.CTkFrame(self.resource_card, fg_color="transparent")
        self.resource_rows.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.resource_rows.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.resource_rows, text="Run research to populate mapped resource presence.", font=self._font(12), text_color="#728078", wraplength=360, justify="left").grid(row=0, column=0, sticky="w")

    def _build_zoning_panel(self, row: int) -> None:
        self.zoning_card = self._card(row=row)
        self.zoning_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.zoning_card, text="Zoning Feasibility", font=self._font(17, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.zoning_snapshot = ctk.CTkLabel(self.zoning_card, text="Development options will appear here.", font=self._font(12), text_color="#8f9c98", justify="left", anchor="w", wraplength=360)
        self.zoning_snapshot.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.zoning_rows = ctk.CTkFrame(self.zoning_card, fg_color="transparent")
        self.zoning_rows.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.zoning_rows.grid_columnconfigure(0, weight=1)

    def _build_log_panel(self, row: int) -> None:
        card = self._card(row=row)
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

        self.preview_frame = ctk.CTkFrame(self.preview_shell, corner_radius=0, fg_color="#020403")
        self.preview_frame.grid(row=1, column=0, sticky="nsew")
        self.preview_frame.grid_columnconfigure(0, weight=1)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_image_label = ctk.CTkLabel(self.preview_frame, text="Preview will appear here", fg_color="#030606", text_color="#6f7b76", font=self._font(18))
        self.preview_image_label.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        self.preview_image_label.bind("<Configure>", lambda _event: self._refresh_preview())

    def _card(self, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self.left_rail, corner_radius=16, fg_color="#0b100f", border_color="#1b332b", border_width=1)
        card.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 12))
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

    def _start(self) -> None:
        parcel = self.parcel_entry.get().strip()
        if not parcel:
            self._log("Enter a parcel number first.")
            return
        folder = self.folder_entry.get().strip()
        if folder:
            self.settings = AppSettings(last_destination=folder, project_prefix="")
            save_settings(self.settings)

        self.stop_event = threading.Event()
        self.preview_bundle = None
        self.zoning_result = None
        self.ready_for_package = False
        self.resource_status_by_name.clear()
        self._set_running(True, jobs=2)
        self._reset_visuals()

        self.env_worker = threading.Thread(target=self._environmental_worker, args=(parcel, Path(folder or Path.home() / "Documents"), self.group_menu.get()), daemon=True)
        self.zoning_worker = threading.Thread(target=self._zoning_worker, args=(parcel, self.intended_use_entry.get().strip()), daemon=True)
        self.env_worker.start()
        self.zoning_worker.start()

    def _environmental_worker(self, parcel: str, destination: Path, group: str) -> None:
        try:
            runner = EnvironmentalWidgetRunner(
                parcel_number=parcel,
                destination=destination,
                progress=lambda message: self.events.put(("log", f"Environmental: {message}")),
                stop_event=self.stop_event,
                environmental_group=group,
                resource_status_callback=lambda statuses: self.events.put(("resources", statuses)),
                preview_callback=lambda preview: self.events.put(("preview", preview)),
            )
            result = runner.prepare_preview()
            self.events.put(("env_done", result))
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("Powerhouse environmental research failed")
            self.events.put(("error", f"Environmental preview failed: {exc}"))
        finally:
            self.events.put(("job_done", "environmental"))

    def _zoning_worker(self, parcel: str, intended_use: str) -> None:
        try:
            runner = ZoningFeasibilityRunner(parcel, intended_use=intended_use, progress=lambda message: self.events.put(("log", f"Zoning: {message}")))
            result = runner.analyze()
            self.events.put(("zoning", result))
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("Powerhouse zoning research failed")
            self.events.put(("error", f"Zoning feasibility failed: {exc}"))
        finally:
            self.events.put(("job_done", "zoning"))

    def _create_package(self) -> None:
        parcel = self.parcel_entry.get().strip()
        folder = self.folder_entry.get().strip()
        if not parcel or not folder:
            self._log("Enter a parcel and destination folder before creating maps.")
            return
        self._set_running(True, jobs=1)
        self.package_worker = threading.Thread(target=self._package_worker, args=(parcel, Path(folder), self.group_menu.get()), daemon=True)
        self.package_worker.start()

    def _package_worker(self, parcel: str, destination: Path, group: str) -> None:
        try:
            runner = EnvironmentalWidgetRunner(parcel, destination, lambda message: self.events.put(("log", f"Maps: {message}")), self.stop_event, environmental_group=group)
            paths = runner.build_pdf_package()
            self.events.put(("package_done", paths))
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("Powerhouse map package failed")
            self.events.put(("error", f"Map package failed: {exc}"))
        finally:
            self.events.put(("job_done", "package"))

    def _drain_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                self._log(str(payload))
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
                self.status_badge.configure(text="Review", fg_color="#2d2415", text_color="#d0a96d")
            elif event == "job_done":
                self.running_jobs = max(0, self.running_jobs - 1)
                if self.running_jobs == 0:
                    self._set_running(False)
        self.after(150, self._drain_events)

    def _set_running(self, running: bool, jobs: int | None = None) -> None:
        if jobs is not None:
            self.running_jobs = jobs
        self.run_button.configure(state="disabled" if running else "normal")
        if not running and self.ready_for_package:
            self.package_button.configure(state="normal", fg_color="#2d5a47", text_color="#eef7f2")
        else:
            self.package_button.configure(state="disabled", fg_color="#18231f", text_color="#8da69a")
        self.status_badge.configure(
            text="Running" if running else "Ready",
            fg_color="#0f1d18" if running else "#0d1512",
            text_color="#94c6d8" if running else "#91c7a9",
        )

    def _reset_visuals(self) -> None:
        self.preview_image_label.configure(image=None, text="Building preview...")
        self.preview_status.configure(text="Querying GIS layers...")
        self.preview_facts.configure(text="")
        self.zoning_snapshot.configure(text="Running zoning feasibility...")
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
        self.preview_status.configure(text="Preview ready")
        self.preview_facts.configure(text=self._preview_facts_text(preview))
        self._refresh_preview()

    def _apply_resources(self, statuses: tuple[ResourcePresence, ...]) -> None:
        self.resource_status_by_name = {status.name: status for status in statuses}
        for child in self.resource_rows.winfo_children():
            child.destroy()
        present_count = sum(1 for status in statuses if status.status == "Present")
        ctk.CTkLabel(self.resource_rows, text=f"{present_count} mapped resource categories present", font=self._font(12, "bold"), text_color="#91c7a9").grid(row=0, column=0, sticky="w", pady=(0, 6))
        for index, status in enumerate(statuses, start=1):
            fg = "#3a1718" if status.status == "Present" else "#102018"
            text = f"{status.count}" if status.status == "Present" and status.count else "OK"
            chip_color = "#b95050" if status.status == "Present" else "#4f8b6d"
            row = ctk.CTkFrame(self.resource_rows, corner_radius=8, fg_color="#070a0d", border_color="#162722", border_width=1)
            row.grid(row=index, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=status.name, font=self._font(12), text_color="#d5dfdb", anchor="w").grid(row=0, column=0, sticky="ew", padx=8, pady=7)
            ctk.CTkLabel(row, text=text, width=34, height=22, corner_radius=6, fg_color=fg, text_color=chip_color, font=self._font(12, "bold")).grid(row=0, column=1, padx=(4, 8), pady=7)

    def _apply_zoning(self, result: FeasibilityResult) -> None:
        self.zoning_result = result
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

    def _zoning_card(self, result: FeasibilityResult, recommendation: YieldRecommendation, index: int) -> None:
        border = "#315f4a" if recommendation.status == "By Right" else "#6a5a2a" if "Review" in recommendation.status or "Interpretation" in recommendation.status else "#663636"
        card = ctk.CTkFrame(self.zoning_rows, corner_radius=10, fg_color="#070d0c", border_color=border, border_width=1)
        card.grid(row=index, column=0, sticky="ew", pady=4)
        card.grid_columnconfigure(0, weight=1)
        title = f"{self._display_option_name(recommendation)}"
        meta = f"{self._yield_breakdown(result, recommendation)} | {self._market_range_text(recommendation)}"
        ctk.CTkLabel(card, text=title, font=self._font(13, "bold"), text_color="#f1f6f3", anchor="w").grid(row=0, column=0, sticky="ew", padx=9, pady=(8, 1))
        ctk.CTkLabel(card, text=meta, font=self._font(12), text_color="#b8c9c1", anchor="w", wraplength=340).grid(row=1, column=0, sticky="ew", padx=9, pady=(0, 2))
        if recommendation.limiting_factors:
            ctk.CTkLabel(card, text=", ".join(recommendation.limiting_factors[:3]), font=self._font(11), text_color="#82908a", anchor="w", wraplength=340).grid(row=2, column=0, sticky="ew", padx=9, pady=(0, 8))

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
            if recommendation.program_scenario:
                scenario = recommendation.program_scenario
                return f"{scenario.modeled_units or 0:,} units within +/-{(scenario.envelope_gfa or 0):,} sf GFA envelope"
            commercial_gfa, units = self._mixed_use_split(recommendation)
            return f"{units:,} units within mixed-use GFA program; {commercial_gfa:,} sf commercial component"
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

    def _on_close(self) -> None:
        self.stop_event.set()
        self.destroy()


def main() -> None:
    app = ParcelPowerhouseApp()
    app.mainloop()
