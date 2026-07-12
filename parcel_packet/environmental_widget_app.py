from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from tkinter import filedialog
import tkinter.font as tkfont

import customtkinter as ctk
from PIL import Image

from .environmental_config import ENVIRONMENTAL_MENU_GROUPS, RESOURCE_STATUS_ORDER, ResourcePresence
from .fonts import load_bundled_fonts
from .logging_utils import configure_logging
from .environmental_widget_runner import EnvironmentalWidgetRunner, PreviewBundle, PreviewResult
from .settings import AppSettings, load_settings, save_settings


APP_NAME = "Environmental Widget"
TRANSPARENT_WIDGET_COLOR = "#010203"


class EnvironmentalWidgetApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        configure_logging()
        load_bundled_fonts()
        ctk.set_appearance_mode("dark")

        self.font_family = self._pick_font_family()
        self.settings = load_settings()
        self.events: queue.Queue[
            tuple[str, str | tuple[Path, ...] | PreviewResult | PreviewBundle | tuple[ResourcePresence, ...]]
        ] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.progress_expanded = False
        self.workspace_visible = False
        self.progress_percent = 0
        self.preview_bundle: PreviewBundle | None = None
        self.preview_image: ctk.CTkImage | None = None
        self.preview_layer_vars: dict[str, ctk.BooleanVar] = {}
        self.resource_status_by_name: dict[str, ResourcePresence] = {}
        self.ready_for_package = False
        self.results_window: ctk.CTkToplevel | None = None
        self.preview_window: ctk.CTkToplevel | None = None
        self.visible_result_rows: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}
        self.visible_preview_image_label: ctk.CTkLabel | None = None
        self.visible_preview_facts_label: ctk.CTkLabel | None = None
        self.visible_preview_status_label: ctk.CTkLabel | None = None
        self.visible_present_layers_button: ctk.CTkButton | None = None
        self.visible_clear_layers_button: ctk.CTkButton | None = None
        self.visible_preview_controls: list[ctk.CTkCheckBox] = []
        self._drag_offsets: dict[ctk.CTkToplevel, tuple[int, int]] = {}

        self.title(APP_NAME)
        self.geometry("760x520")
        self.minsize(700, 500)
        self.configure(fg_color="#070a0d")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self.after(50, self._position_main_window)
        self.after(150, self._drain_events)

    def _font(self, size: int, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family=self.font_family, size=size, weight=weight)

    def _pick_font_family(self) -> str:
        available = set(tkfont.families(self))
        for family in (
            "Nunito Sans Normal",
            "Nunito Sans",
            "NunitoSans",
            "Avenir Next",
            "Avenir",
            "Segoe UI Variable Text",
            "Segoe UI",
        ):
            if family in available:
                return family
        return "TkDefaultFont"

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=0)

        accent = ctk.CTkFrame(self, height=38, corner_radius=0, fg_color="#285a48")
        accent.grid(row=0, column=0, sticky="ew")
        accent.grid_propagate(False)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=24, pady=(12, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=APP_NAME,
            font=self._font(14, "bold"),
            text_color="#83bda8",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Environmental Resources",
            font=self._font(30, "bold"),
            text_color="#f2f5f3",
        ).grid(row=1, column=0, sticky="w")
        self.header_status = ctk.CTkLabel(
            header,
            text="Ready",
            width=86,
            height=30,
            corner_radius=4,
            fg_color="#0d1512",
            text_color="#91c7a9",
            font=self._font(12, "bold"),
        )
        self.header_status.grid(row=1, column=1, sticky="e", padx=(12, 0))
        ctk.CTkLabel(
            header,
            text=(
                "Create parcel environmental map PDFs directly from NCC GIS services. "
                "Input a parcel number or address, choose a Map Group, and select a destination folder. "
                "All Resources runs every Map Group and combines the parcel map packet."
            ),
            text_color="#8c9692",
            font=self._font(13),
            justify="left",
            wraplength=690,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        form = self._panel(row=2, height=160)
        form.grid_columnconfigure(0, minsize=150)
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(2, minsize=100)
        label_style = {"font": self._font(16, "bold"), "text_color": "#d0d8d4"}

        ctk.CTkLabel(form, text="Parcel or address", **label_style).grid(row=0, column=0, sticky="w", padx=(14, 8), pady=(12, 4))
        self.parcel_entry = ctk.CTkEntry(
            form,
            placeholder_text="1105400001",
            height=40,
            corner_radius=4,
            fg_color="#070a0d",
            border_color="#30453d",
            text_color="#edf3ef",
            placeholder_text_color="#68756f",
            font=self._font(16),
        )
        self.parcel_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=(12, 4))

        ctk.CTkLabel(form, text="Destination folder", **label_style).grid(row=1, column=0, sticky="w", padx=(14, 8), pady=4)
        self.folder_entry = ctk.CTkEntry(
            form,
            height=40,
            corner_radius=4,
            fg_color="#070a0d",
            border_color="#30453d",
            text_color="#edf3ef",
            font=self._font(16),
        )
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
        self.browse_button = ctk.CTkButton(
            form,
            text="Browse",
            width=94,
            height=40,
            corner_radius=4,
            fg_color="#2d5a47",
            hover_color="#376d56",
            text_color="#eef7f2",
            font=self._font(14, "bold"),
            command=self._browse,
        )
        self.browse_button.grid(row=1, column=2, sticky="ew", padx=(0, 14), pady=4)

        ctk.CTkLabel(form, text="Map group", **label_style).grid(row=2, column=0, sticky="w", padx=(14, 8), pady=(4, 12))
        self.group_menu = ctk.CTkOptionMenu(
            form,
            values=list(ENVIRONMENTAL_MENU_GROUPS),
            height=40,
            corner_radius=4,
            fg_color="#080d0c",
            button_color="#2d5a47",
            button_hover_color="#376d56",
            dropdown_fg_color="#111917",
            dropdown_hover_color="#1f382e",
            text_color="#edf3ef",
            font=self._font(16),
            dropdown_font=self._font(15),
        )
        self.group_menu.set("All Resources")
        self.group_menu.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=(4, 12))

        progress = self._panel(row=3, height=56)
        progress.grid_columnconfigure(2, weight=1)
        progress.grid_columnconfigure(3, minsize=54)
        self.progress_dot = ctk.CTkLabel(progress, text="", width=9, height=9, corner_radius=4, fg_color="#4f8b6d")
        self.progress_dot.grid(
            row=0,
            column=0,
            sticky="w",
            padx=(14, 9),
            pady=10,
        )
        self.progress_toggle_button = ctk.CTkButton(
            progress,
            text="Progress >",
            width=106,
            height=30,
            corner_radius=4,
            fg_color="#151f1c",
            hover_color="#20312b",
            text_color="#b9cfc5",
            font=self._font(13, "bold"),
            command=self._toggle_progress,
        )
        self.progress_toggle_button.grid(row=0, column=1, sticky="w", padx=(0, 10), pady=10)
        self.status_label = ctk.CTkLabel(progress, text="Ready", anchor="w", font=self._font(16, "bold"), text_color="#e7eeea")
        self.status_label.grid(row=0, column=2, sticky="ew", pady=10)
        self.progress_percent_label = ctk.CTkLabel(
            progress,
            text="0%",
            width=52,
            anchor="e",
            font=self._font(15, "bold"),
            text_color="#8faaa0",
        )
        self.progress_percent_label.grid(row=0, column=3, sticky="e", padx=(8, 14), pady=10)
        self.progress_bar = ctk.CTkProgressBar(
            progress,
            height=6,
            corner_radius=3,
            mode="determinate",
            progress_color="#4f8b6d",
            fg_color="#1a2220",
        )
        self.progress_bar.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 9))
        self.progress_bar.set(0)
        self.progress_bar.grid_remove()
        self.log_box = ctk.CTkTextbox(
            progress,
            height=86,
            corner_radius=4,
            fg_color="#070a0d",
            border_color="#223830",
            border_width=1,
            font=self._font(14),
            text_color="#b9c4bf",
        )
        self.log_box.configure(state="disabled")

        self.workspace = ctk.CTkFrame(self, fg_color="transparent")
        self.workspace.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 9))
        self.workspace.grid_columnconfigure(0, weight=1, uniform="workspace")
        self.workspace.grid_columnconfigure(1, weight=1, uniform="workspace")
        self.workspace.grid_rowconfigure(0, weight=1)

        results = self._embedded_panel(self.workspace, row=0, column=0)
        results.grid_columnconfigure(0, weight=1)
        results.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(results, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Environmental Sub Categories", font=self._font(16, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="Result", font=self._font(13, "bold"), text_color="#8faaa0").grid(row=0, column=1, sticky="e", padx=(12, 22))

        self.results_frame = ctk.CTkScrollableFrame(
            results,
            corner_radius=4,
            fg_color="#070a0d",
            border_color="#223830",
            border_width=1,
            height=300,
        )
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        self.results_frame.grid_columnconfigure(0, weight=1)
        self.result_rows: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel, ctk.CTkLabel]] = {}
        for row_index, name in enumerate(RESOURCE_STATUS_ORDER):
            name_label = ctk.CTkLabel(self.results_frame, text=name, anchor="w", font=self._font(13), text_color="#c9d3cf")
            name_label.grid(row=row_index, column=0, sticky="ew", padx=(10, 8), pady=2)
            present_label = ctk.CTkLabel(
                self.results_frame,
                text="-",
                width=82,
                height=24,
                corner_radius=4,
                fg_color="#111817",
                text_color="#6f7b76",
                font=self._font(15, "bold"),
            )
            present_label.grid(row=row_index, column=1, sticky="e", padx=(4, 8), pady=2)
            count_label = ctk.CTkLabel(self.results_frame, text="", width=54, anchor="e", font=self._font(12), text_color="#68756f")
            self.result_rows[name] = (name_label, present_label, count_label)

        preview = self._embedded_panel(self.workspace, row=0, column=1)
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(1, weight=1)
        preview_header = ctk.CTkFrame(preview, fg_color="transparent")
        preview_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        preview_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            preview_header,
            text="Live Site Preview",
            font=self._font(16, "bold"),
            text_color="#e7eeea",
        ).grid(row=0, column=0, sticky="w")
        self.preview_status_label = ctk.CTkLabel(
            preview_header,
            text="Run a parcel to build preview",
            font=self._font(12),
            text_color="#76847e",
        )
        self.preview_status_label.grid(row=0, column=1, sticky="e", padx=(12, 0))
        preview_actions = ctk.CTkFrame(preview_header, fg_color="transparent")
        preview_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.present_layers_button = ctk.CTkButton(
            preview_actions,
            text="Show Present",
            width=112,
            height=30,
            corner_radius=4,
            fg_color="#20312b",
            hover_color="#2d493d",
            text_color="#cfe4da",
            font=self._font(12, "bold"),
            command=self._show_present_preview_layers,
            state="disabled",
        )
        self.present_layers_button.grid(row=0, column=0, sticky="w")
        self.clear_layers_button = ctk.CTkButton(
            preview_actions,
            text="Clear Layers",
            width=104,
            height=30,
            corner_radius=4,
            fg_color="#151b1a",
            hover_color="#202a27",
            text_color="#aeb9b4",
            font=self._font(12, "bold"),
            command=self._clear_preview_layers,
            state="disabled",
        )
        self.clear_layers_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.preview_facts_label = ctk.CTkLabel(
            preview_header,
            text="",
            font=self._font(12),
            text_color="#b8c9c1",
            justify="left",
            anchor="w",
            wraplength=520,
        )
        self.preview_facts_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))

        preview_body = ctk.CTkFrame(preview, fg_color="transparent")
        preview_body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        preview_body.grid_columnconfigure(0, weight=1)
        preview_body.grid_columnconfigure(1, minsize=210)
        preview_body.grid_rowconfigure(0, weight=1)
        self.preview_image_label = ctk.CTkLabel(
            preview_body,
            text="Preview will appear here",
            width=500,
            height=390,
            corner_radius=4,
            fg_color="#070a0d",
            text_color="#6f7b76",
            font=self._font(14),
        )
        self.preview_image_label.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.preview_controls_frame = ctk.CTkScrollableFrame(
            preview_body,
            width=210,
            corner_radius=4,
            fg_color="#070a0d",
            border_color="#223830",
            border_width=1,
        )
        self.preview_controls_frame.grid(row=0, column=1, sticky="nsew")
        for row_index, name in enumerate(RESOURCE_STATUS_ORDER):
            var = ctk.BooleanVar(value=False)
            self.preview_layer_vars[name] = var
            checkbox = ctk.CTkCheckBox(
                self.preview_controls_frame,
                text=name,
                variable=var,
                command=self._refresh_preview,
                font=self._font(12),
                text_color="#c9d3cf",
                fg_color="#3f765c",
                hover_color="#4f9474",
                border_color="#375047",
                checkmark_color="#07100d",
                state="disabled",
            )
            checkbox.grid(row=row_index, column=0, sticky="w", padx=10, pady=4)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 14))
        footer.grid_columnconfigure(0, weight=1)
        self.run_button = ctk.CTkButton(
            footer,
            text="Run Widget",
            width=210,
            height=44,
            corner_radius=4,
            fg_color="#3f765c",
            hover_color="#4f9474",
            text_color="#f3faf6",
            font=self._font(15, "bold"),
            command=self._start,
        )
        self.run_button.grid(row=0, column=1, padx=(10, 0))
        self.package_button = ctk.CTkButton(
            footer,
            text="Create PDF Package",
            width=178,
            height=44,
            corner_radius=4,
            fg_color="#1b2a25",
            hover_color="#2d493d",
            text_color="#8d9b95",
            font=self._font(15, "bold"),
            command=self._start_package,
            state="disabled",
        )
        self.package_button.grid(row=0, column=2, padx=(12, 0))
        self.cancel_button = ctk.CTkButton(
            footer,
            text="Cancel",
            width=116,
            height=44,
            corner_radius=4,
            fg_color="#151b1a",
            hover_color="#202a27",
            text_color="#aeb9b4",
            font=self._font(15, "bold"),
            command=self._cancel,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=3, padx=(12, 0))
        self._collapse_workspace()

    def _panel(self, row: int, height: int, sticky: str = "ew") -> ctk.CTkFrame:
        shell = ctk.CTkFrame(self, corner_radius=8, fg_color="#0b0f0e", border_color="#1b332b", border_width=1)
        shell.grid(row=row, column=0, sticky=sticky, padx=24, pady=(0, 9))
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)
        panel = ctk.CTkFrame(shell, height=height, corner_radius=6, fg_color="#101614", border_color="#25352f", border_width=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        panel.grid_propagate(True)
        return panel

    def _embedded_panel(self, parent: ctk.CTkFrame, row: int, column: int) -> ctk.CTkFrame:
        shell = ctk.CTkFrame(parent, corner_radius=8, fg_color="#0b0f0e", border_color="#1b332b", border_width=1)
        shell.grid(row=row, column=column, sticky="nsew", padx=(0, 7) if column == 0 else (7, 0))
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)
        panel = ctk.CTkFrame(shell, corner_radius=6, fg_color="#101614", border_color="#25352f", border_width=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        return panel

    def _expand_workspace(self) -> None:
        self.workspace_visible = True
        self._open_detached_windows()

    def _collapse_workspace(self) -> None:
        self.workspace_visible = False
        self.workspace.grid_remove()
        self.grid_rowconfigure(4, weight=0)

    def _open_detached_windows(self) -> None:
        self._open_results_window()
        self._open_preview_window()

    def _open_results_window(self) -> None:
        if self.results_window and self.results_window.winfo_exists():
            self.results_window.lift()
            return
        self.results_window = ctk.CTkToplevel(self)
        self.results_window.title("Environmental Sub Categories")
        self._style_widget_window(self.results_window)
        self.results_window.attributes("-alpha", 0.0)
        self.results_window.protocol("WM_DELETE_WINDOW", self._close_results_window)
        self.results_window.geometry(self._quadrant_geometry("bottom-left", 500, 560))
        self.results_window.minsize(480, 300)
        self.results_window.grid_columnconfigure(0, weight=1)
        self.results_window.grid_rowconfigure(0, weight=1)
        chrome = ctk.CTkFrame(
            self.results_window,
            corner_radius=36,
            fg_color="#070a0d",
            border_color="#4b8b6d",
            border_width=2,
        )
        chrome.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        chrome.grid_columnconfigure(0, weight=1)
        chrome.grid_rowconfigure(1, weight=1)
        self._enable_window_drag(self.results_window, chrome)
        self._themed_window_header(
            chrome,
            self.results_window,
            "Environmental Checklist",
            "Resources affecting the parcel",
            self._close_results_window,
        )

        shell = ctk.CTkFrame(chrome, corner_radius=28, fg_color="#0b0f0e", border_color="#203d33", border_width=1)
        shell.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self._enable_window_drag(self.results_window, shell)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Environmental Sub Categories", font=self._font(15, "bold"), text_color="#e7eeea").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="Result", font=self._font(12, "bold"), text_color="#8faaa0").grid(row=0, column=1, sticky="e")
        frame = ctk.CTkScrollableFrame(shell, corner_radius=16, fg_color="#070a0d", border_color="#223830", border_width=1)
        frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        frame.grid_columnconfigure(0, weight=1)
        self.visible_result_rows.clear()
        for row_index, name in enumerate(RESOURCE_STATUS_ORDER):
            label = ctk.CTkLabel(frame, text=name, anchor="w", font=self._font(13), text_color="#c9d3cf")
            label.grid(row=row_index, column=0, sticky="ew", padx=(10, 8), pady=3)
            result = ctk.CTkLabel(
                frame,
                text="-",
                width=82,
                height=24,
                corner_radius=4,
                fg_color="#111817",
                text_color="#6f7b76",
                font=self._font(15, "bold"),
            )
            result.grid(row=row_index, column=1, sticky="e", padx=(4, 10), pady=3)
            self.visible_result_rows[name] = (label, result)
        self._fade_in_window(self.results_window)

    def _open_preview_window(self) -> None:
        if self.preview_window and self.preview_window.winfo_exists():
            self.preview_window.lift()
            return
        self.preview_window = ctk.CTkToplevel(self)
        self.preview_window.title("Live Site Preview")
        self._style_widget_window(self.preview_window)
        self.preview_window.attributes("-alpha", 0.0)
        self.preview_window.protocol("WM_DELETE_WINDOW", self._close_preview_window)
        self.preview_window.geometry(self._quadrant_geometry("top-right", 920, 720))
        self.preview_window.minsize(640, 560)
        self.preview_window.grid_columnconfigure(0, weight=1)
        self.preview_window.grid_rowconfigure(0, weight=1)
        chrome = ctk.CTkFrame(
            self.preview_window,
            corner_radius=36,
            fg_color="#070a0d",
            border_color="#4b8b6d",
            border_width=2,
        )
        chrome.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        chrome.grid_columnconfigure(0, weight=1)
        chrome.grid_rowconfigure(1, weight=1)
        self._enable_window_drag(self.preview_window, chrome)
        self._themed_window_header(
            chrome,
            self.preview_window,
            "Live Site Preview",
            "Aerial, parcel, roads, and environmental overlays",
            self._close_preview_window,
        )

        shell = ctk.CTkFrame(chrome, corner_radius=28, fg_color="#0b0f0e", border_color="#203d33", border_width=1)
        shell.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self._enable_window_drag(self.preview_window, shell)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(shell, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        top.grid_columnconfigure(0, weight=1)
        self.visible_preview_status_label = ctk.CTkLabel(top, text="Building preview", font=self._font(12), text_color="#76847e")
        self.visible_preview_status_label.grid(row=0, column=1, sticky="e")
        self.visible_preview_facts_label = ctk.CTkLabel(top, text="", font=self._font(12), text_color="#b8c9c1", justify="left", anchor="w", wraplength=610)
        self.visible_preview_facts_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.visible_present_layers_button = ctk.CTkButton(actions, text="Show Present", width=112, height=30, corner_radius=4, fg_color="#20312b", hover_color="#2d493d", text_color="#cfe4da", font=self._font(12, "bold"), command=self._show_present_preview_layers, state="disabled")
        self.visible_present_layers_button.grid(row=0, column=0, sticky="w")
        self.visible_clear_layers_button = ctk.CTkButton(actions, text="Clear Layers", width=104, height=30, corner_radius=4, fg_color="#151b1a", hover_color="#202a27", text_color="#aeb9b4", font=self._font(12, "bold"), command=self._clear_preview_layers, state="disabled")
        self.visible_clear_layers_button.grid(row=0, column=1, sticky="w", padx=(8, 0))

        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, minsize=220)
        body.grid_rowconfigure(0, weight=1)
        self.visible_preview_image_label = ctk.CTkLabel(body, text="Preview will appear here", width=570, height=430, corner_radius=18, fg_color="#070a0d", text_color="#6f7b76", font=self._font(14))
        self.visible_preview_image_label.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        controls = ctk.CTkScrollableFrame(body, width=220, corner_radius=18, fg_color="#070a0d", border_color="#223830", border_width=1)
        controls.grid(row=0, column=1, sticky="nsew")
        self.visible_preview_controls.clear()
        for row_index, name in enumerate(RESOURCE_STATUS_ORDER):
            checkbox = ctk.CTkCheckBox(
                controls,
                text=name,
                variable=self.preview_layer_vars[name],
                command=self._refresh_preview,
                font=self._font(12),
                text_color="#c9d3cf",
                fg_color="#3f765c",
                hover_color="#4f9474",
                border_color="#375047",
                checkmark_color="#07100d",
                state="disabled",
            )
            checkbox.grid(row=row_index, column=0, sticky="w", padx=10, pady=4)
            self.visible_preview_controls.append(checkbox)
        self._fade_in_window(self.preview_window)

    def _style_widget_window(self, window: ctk.CTkToplevel) -> None:
        window.configure(fg_color=TRANSPARENT_WIDGET_COLOR)
        window.overrideredirect(True)
        try:
            window.wm_attributes("-transparentcolor", TRANSPARENT_WIDGET_COLOR)
        except Exception:
            window.configure(fg_color="#070a0d")

    def _position_main_window(self) -> None:
        self.update_idletasks()
        self.geometry("760x520+24+24")

    def _quadrant_geometry(self, quadrant: str, preferred_width: int, preferred_height: int) -> str:
        self.update_idletasks()
        screen_width = max(1024, self.winfo_screenwidth())
        screen_height = max(720, self.winfo_screenheight())
        margin = 24
        taskbar_allowance = 64
        work_height = max(640, screen_height - taskbar_allowance)
        half_width = screen_width // 2

        if quadrant == "top-right":
            x = half_width + 12
            y = margin
            width = max(640, min(preferred_width, screen_width - x - margin))
            height = max(560, min(preferred_height, work_height - (margin * 2)))
        elif quadrant == "bottom-left":
            x = margin
            main_bottom = 24 + 520 + 16
            y = min(max(work_height // 2 + 12, main_bottom), work_height - 300)
            width = max(500, min(preferred_width, half_width - (margin * 2)))
            height = max(300, min(preferred_height, work_height - y - margin))
        else:
            x = margin
            y = margin
            width = min(preferred_width, half_width - (margin * 2))
            height = min(preferred_height, work_height - (margin * 2))
        return f"{width}x{height}+{x}+{y}"

    def _themed_window_header(
        self,
        parent,
        window: ctk.CTkToplevel,
        title: str,
        subtitle: str,
        close_command,
    ) -> None:
        header = ctk.CTkFrame(parent, corner_radius=28, fg_color="#070a0d")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkFrame(header, height=8, corner_radius=4, fg_color="#285a48").grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 10))
        title_label = ctk.CTkLabel(header, text=title, font=self._font(22, "bold"), text_color="#f2f5f3")
        title_label.grid(row=1, column=0, sticky="w", padx=(12, 0))
        close_button = ctk.CTkButton(
            header,
            text="X",
            width=34,
            height=28,
            corner_radius=6,
            fg_color="#151b1a",
            hover_color="#38252a",
            text_color="#c8d4ce",
            font=self._font(13, "bold"),
            command=close_command,
        )
        close_button.grid(row=1, column=1, sticky="e", padx=(12, 12))
        subtitle_label = ctk.CTkLabel(header, text=subtitle, font=self._font(12), text_color="#8c9692")
        subtitle_label.grid(row=2, column=0, sticky="w", padx=(12, 0), pady=(2, 12))
        self._enable_window_drag(window, header)
        self._enable_window_drag(window, title_label)
        self._enable_window_drag(window, subtitle_label)

    def _enable_window_drag(self, window: ctk.CTkToplevel, widget) -> None:
        widget.bind("<ButtonPress-1>", lambda event, target=window: self._start_window_drag(target, event))
        widget.bind("<B1-Motion>", lambda event, target=window: self._drag_window(target, event))

    def _start_window_drag(self, window: ctk.CTkToplevel, event) -> None:
        self._drag_offsets[window] = (event.x_root - window.winfo_x(), event.y_root - window.winfo_y())

    def _drag_window(self, window: ctk.CTkToplevel, event) -> None:
        offset_x, offset_y = self._drag_offsets.get(window, (0, 0))
        window.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def _fade_in_window(self, window: ctk.CTkToplevel, step: int = 0) -> None:
        if not window.winfo_exists():
            return
        alpha = min(1.0, step / 8)
        window.attributes("-alpha", alpha)
        if alpha < 1.0:
            self.after(18, lambda: self._fade_in_window(window, step + 1))

    def _close_results_window(self) -> None:
        if self.results_window and self.results_window.winfo_exists():
            self.results_window.destroy()
        self.results_window = None
        self.visible_result_rows.clear()

    def _close_preview_window(self) -> None:
        if self.preview_window and self.preview_window.winfo_exists():
            self.preview_window.destroy()
        self.preview_window = None
        self.visible_preview_image_label = None
        self.visible_preview_facts_label = None
        self.visible_preview_status_label = None
        self.visible_present_layers_button = None
        self.visible_clear_layers_button = None
        self.visible_preview_controls.clear()

    def _set_progress_running(self) -> None:
        self.progress_bar.configure(mode="determinate", progress_color="#4f8b6d")
        self.progress_dot.configure(fg_color="#4f8b6d")
        self.progress_bar.grid()
        self._set_progress_percent(max(self.progress_percent, 2))

    def _set_progress_complete(self) -> None:
        self.progress_bar.configure(mode="determinate", progress_color="#4f8b6d")
        self.progress_dot.configure(fg_color="#4f8b6d")
        self._set_progress_percent(100)

    def _set_progress_error(self) -> None:
        self.progress_bar.configure(mode="determinate", progress_color="#b88b4a")
        self.progress_dot.configure(fg_color="#b88b4a")
        self._set_progress_percent(max(self.progress_percent, 1))

    def _set_progress_percent(self, value: int) -> None:
        self.progress_percent = max(0, min(100, value))
        self.progress_percent_label.configure(text=f"{self.progress_percent}%")
        self.progress_bar.set(self.progress_percent / 100)

    def _progress_percent_for_message(self, message: str) -> int:
        if message.startswith("Finding parcel geometry"):
            return 8
        if message.startswith("Checking environmental resources"):
            return 18
        if message.startswith("Building live preview"):
            return 38
        if message.startswith("Rendering map images"):
            return 56
        if message.startswith("Rendered "):
            return min(84, max(self.progress_percent + 7, 64))
        if message.startswith("Writing combined"):
            return 96
        if message.startswith("Writing "):
            return min(94, max(self.progress_percent + 3, 86))
        return self.progress_percent

    def _browse(self) -> None:
        initial = self.folder_entry.get().strip() or str(Path.home() / "Documents")
        folder = filedialog.askdirectory(initialdir=initial)
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

    def _reset_for_new_parcel(self) -> None:
        self.ready_for_package = False
        self._close_results_window()
        self._close_preview_window()
        self._reset_results()
        self._reset_preview()
        self.package_button.configure(
            state="disabled",
            fg_color="#1b2a25",
            hover_color="#2d493d",
            text_color="#8d9b95",
        )
        self.header_status.configure(text="Ready", fg_color="#0d1512", text_color="#91c7a9")
        self.status_label.configure(text="Ready")
        self.progress_bar.grid_remove()

    def _start(self) -> None:
        parcel = self.parcel_entry.get().strip()
        folder = self.folder_entry.get().strip()
        if not parcel:
            self._show_widget_notice("Parcel needed", "Enter a parcel number or address first.", "warning")
            return
        if not folder:
            self._show_widget_notice("Folder needed", "Choose a destination folder first.", "warning")
            return

        self.settings = AppSettings(last_destination=folder, project_prefix="")
        save_settings(self.settings)
        self.stop_event.clear()
        self._reset_for_new_parcel()
        self._expand_workspace()
        self._set_progress_percent(0)
        self._set_running(True)
        self._clear_log()
        self._log("Starting Environmental Widget research")

        runner = EnvironmentalWidgetRunner(
            parcel_number=parcel,
            destination=Path(folder),
            progress=self._progress,
            stop_event=self.stop_event,
            environmental_group=self.group_menu.get(),
            resource_status_callback=self._resource_statuses,
            preview_callback=self._preview_ready,
        )
        self.worker = threading.Thread(target=self._preview_worker, args=(runner,), daemon=True)
        self.worker.start()

    def _start_package(self) -> None:
        parcel = self.parcel_entry.get().strip()
        folder = self.folder_entry.get().strip()
        if not self.ready_for_package:
            self._show_widget_notice("Preview needed", "Run the widget before creating the PDF package.", "warning")
            return
        self.stop_event.clear()
        self._set_progress_percent(52)
        self._set_running(True)
        self.package_button.configure(state="disabled")
        self._log("Starting PDF package")

        runner = EnvironmentalWidgetRunner(
            parcel_number=parcel,
            destination=Path(folder),
            progress=self._progress,
            stop_event=self.stop_event,
            environmental_group=self.group_menu.get(),
        )
        self.worker = threading.Thread(target=self._package_worker, args=(runner,), daemon=True)
        self.worker.start()

    def _preview_worker(self, runner: EnvironmentalWidgetRunner) -> None:
        try:
            result = runner.prepare_preview()
            self.events.put(("preview_done", result))
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("Environmental Widget preview failed")
            self.events.put(("error", str(exc)))

    def _package_worker(self, runner: EnvironmentalWidgetRunner) -> None:
        try:
            pdf_paths = runner.build_pdf_package()
            self.events.put(("package_done", pdf_paths))
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("Environmental Widget PDF package failed")
            self.events.put(("error", str(exc)))

    def _progress(self, message: str) -> None:
        self.events.put(("progress", message))

    def _resource_statuses(self, statuses: tuple[ResourcePresence, ...]) -> None:
        self.events.put(("resource_statuses", statuses))

    def _preview_ready(self, preview: PreviewBundle) -> None:
        self.events.put(("preview", preview))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    message = str(payload)
                    self.status_label.configure(text=message)
                    self._set_progress_percent(max(self.progress_percent, self._progress_percent_for_message(message)))
                    self.header_status.configure(text="Running", fg_color="#0f1d18", text_color="#91c7a9")
                    self._log(message)
                elif event == "resource_statuses":
                    statuses = payload if isinstance(payload, tuple) else ()
                    self._apply_results(statuses)
                    self._set_progress_percent(max(self.progress_percent, 32))
                    self._log("Resource presence check complete")
                elif event == "preview":
                    if isinstance(payload, PreviewBundle):
                        self._apply_preview(payload)
                        self._set_progress_percent(max(self.progress_percent, 52))
                        self._log("Live preview ready")
                elif event == "preview_done":
                    result = payload if isinstance(payload, PreviewResult) else None
                    if result:
                        self._apply_results(result.resource_statuses)
                        self._apply_preview(result.preview)
                    self._set_running(False)
                    self._set_progress_complete()
                    self.ready_for_package = True
                    self.package_button.configure(
                        state="normal",
                        fg_color="#3f765c",
                        hover_color="#4f9474",
                        text_color="#f3faf6",
                    )
                    self.status_label.configure(text="Preview ready: PDF package optional")
                    self.header_status.configure(text="Ready", fg_color="#0d1b16", text_color="#91c7a9")
                elif event == "package_done":
                    pdf_paths = payload if isinstance(payload, tuple) else ()
                    for pdf_path in pdf_paths:
                        self._log(f"Saved PDF: {pdf_path}")
                    self._set_running(False)
                    self._set_progress_complete()
                    self.status_label.configure(text="Finished: PDF package complete")
                    self.header_status.configure(text="Saved", fg_color="#0d1b16", text_color="#91c7a9")
                    self._show_widget_notice("PDF package complete", "Saved the environmental map PDF files.", "success")
                elif event == "error":
                    self._log(f"Error: {payload}")
                    self._set_running(False)
                    self._set_progress_error()
                    self.status_label.configure(text="Needs attention")
                    self.header_status.configure(text="Error", fg_color="#38252a", text_color="#d6aaa8")
                    self._show_widget_notice("Environmental Widget stopped", str(payload), "error")
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        self.browse_button.configure(state=state)
        self.group_menu.configure(state=state)
        if running:
            self.package_button.configure(state="disabled")
        elif self.ready_for_package:
            self.package_button.configure(state="normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        if running:
            self._set_progress_running()
            self.header_status.configure(text="Running", fg_color="#0f1d18", text_color="#91c7a9")

    def _cancel(self) -> None:
        self.stop_event.set()
        self._log("Cancelling after the current GIS request")

    def _on_close(self) -> None:
        self.stop_event.set()
        self._close_results_window()
        self._close_preview_window()
        self.destroy()

    def _toggle_progress(self) -> None:
        self.progress_expanded = not self.progress_expanded
        if self.progress_expanded:
            self.progress_toggle_button.configure(text="Progress v")
            self.log_box.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=14, pady=(0, 12))
        else:
            self.progress_toggle_button.configure(text="Progress >")
            self.log_box.grid_remove()

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _reset_results(self) -> None:
        self.resource_status_by_name.clear()
        for _, present_label, count_label in self.result_rows.values():
            present_label.configure(text="-", fg_color="#111817", text_color="#6f7b76")
            count_label.configure(text="")
        for _, result_label in self.visible_result_rows.values():
            result_label.configure(text="-", fg_color="#111817", text_color="#6f7b76")

    def _reset_preview(self) -> None:
        self.preview_bundle = None
        self.preview_image = None
        self.preview_image_label.configure(image=None, text="Building preview")
        self.preview_status_label.configure(text="Waiting for GIS layers")
        self.preview_facts_label.configure(text="")
        if self.visible_preview_image_label:
            self.visible_preview_image_label.configure(image=None, text="Building preview")
        if self.visible_preview_status_label:
            self.visible_preview_status_label.configure(text="Waiting for GIS layers")
        if self.visible_preview_facts_label:
            self.visible_preview_facts_label.configure(text="")
        for var in self.preview_layer_vars.values():
            var.set(False)
        for child in self.preview_controls_frame.winfo_children():
            child.configure(state="disabled")
        for child in self.visible_preview_controls:
            child.configure(state="disabled")
        self.present_layers_button.configure(state="disabled")
        self.clear_layers_button.configure(state="disabled")
        if self.visible_present_layers_button:
            self.visible_present_layers_button.configure(state="disabled")
        if self.visible_clear_layers_button:
            self.visible_clear_layers_button.configure(state="disabled")

    def _apply_preview(self, preview: PreviewBundle) -> None:
        self.preview_bundle = preview
        for name, var in self.preview_layer_vars.items():
            var.set(name in preview.default_visible_layers)
        for child in self.preview_controls_frame.winfo_children():
            child.configure(state="normal")
        for child in self.visible_preview_controls:
            child.configure(state="normal")
        self.present_layers_button.configure(state="normal")
        self.clear_layers_button.configure(state="normal")
        if self.visible_present_layers_button:
            self.visible_present_layers_button.configure(state="normal")
        if self.visible_clear_layers_button:
            self.visible_clear_layers_button.configure(state="normal")
        self.preview_status_label.configure(text="Preview ready")
        if self.visible_preview_status_label:
            self.visible_preview_status_label.configure(text="Preview ready")
        self.preview_facts_label.configure(text=self._preview_facts_text(preview))
        if self.visible_preview_facts_label:
            self.visible_preview_facts_label.configure(text=self._preview_facts_text(preview))
        self._refresh_preview()

    def _show_present_preview_layers(self) -> None:
        if self.preview_bundle is None:
            return
        for name, var in self.preview_layer_vars.items():
            status = self.resource_status_by_name.get(name)
            var.set(status is not None and status.status == "Present")
        self._refresh_preview()

    def _clear_preview_layers(self) -> None:
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
        image.thumbnail((500, 390), Image.Resampling.LANCZOS)
        self.preview_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.preview_image_label.configure(image=self.preview_image, text="")
        if self.visible_preview_image_label:
            visible_image = canvas.convert("RGB")
            visible_image.thumbnail((570, 430), Image.Resampling.LANCZOS)
            visible_ctk_image = ctk.CTkImage(light_image=visible_image, dark_image=visible_image, size=visible_image.size)
            self.visible_preview_image_label.configure(image=visible_ctk_image, text="")
            self.visible_preview_image_label.image = visible_ctk_image

    def _preview_facts_text(self, preview: PreviewBundle) -> str:
        facts = preview.parcel_facts
        lines = [
            f"Parcel: {facts.get('Parcel') or '-'}",
            f"Address: {facts.get('Address') or '-'}",
            f"Owner: {facts.get('Owner') or '-'}",
        ]
        if preview.zoning_districts:
            if len(preview.zoning_districts) > 1:
                lines.append("Zoning: Split Zoned: " + ", ".join(preview.zoning_districts))
            else:
                lines.append("Zoning: " + preview.zoning_districts[0])
        else:
            lines.append("Zoning: -")
        return "\n".join(lines)

    def _show_widget_notice(self, title: str, message: str, tone: str = "success") -> None:
        colors = {
            "success": ("#0d1b16", "#91c7a9"),
            "warning": ("#2d2415", "#d0a96d"),
            "error": ("#38252a", "#d6aaa8"),
        }
        bg_color, accent_color = colors.get(tone, colors["success"])
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        self._style_widget_window(dialog)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        shell = ctk.CTkFrame(dialog, corner_radius=10, fg_color="#0b0f0e", border_color="#1b332b", border_width=1)
        shell.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        shell.grid_columnconfigure(0, weight=1)
        ctk.CTkFrame(shell, height=8, corner_radius=4, fg_color=accent_color).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        panel = ctk.CTkFrame(shell, corner_radius=8, fg_color="#101614", border_color="#25352f", border_width=1)
        panel.grid(row=1, column=0, sticky="nsew", padx=2, pady=(0, 2))
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text=title, font=self._font(20, "bold"), text_color="#f2f5f3").grid(
            row=0,
            column=0,
            sticky="w",
            padx=18,
            pady=(16, 4),
        )
        ctk.CTkLabel(
            panel,
            text=message,
            font=self._font(14),
            text_color="#b8c9c1",
            justify="left",
            wraplength=380,
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))
        ctk.CTkButton(
            panel,
            text="OK",
            width=98,
            height=36,
            corner_radius=4,
            fg_color=accent_color if tone != "error" else bg_color,
            hover_color="#4f9474" if tone == "success" else "#49382b",
            text_color="#07100d" if tone == "success" else "#f2f5f3",
            font=self._font(13, "bold"),
            command=dialog.destroy,
        ).grid(row=2, column=0, sticky="e", padx=18, pady=(0, 16))

        self.update_idletasks()
        width, height = 460, 220
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_results(self, statuses: tuple[ResourcePresence, ...]) -> None:
        for status in statuses:
            self.resource_status_by_name[status.name] = status
            row = self.result_rows.get(status.name)
            if row is None:
                continue
            _, present_label, count_label = row
            if status.status == "Present":
                present_label.configure(
                    text=str(status.count if status.count is not None else "!"),
                    fg_color="#3b1517",
                    text_color="#ff7474",
                )
            elif status.status == "Absent":
                present_label.configure(text="OK", fg_color="#153325", text_color="#91d3ac")
            else:
                present_label.configure(text="?", fg_color="#2d2415", text_color="#d0a96d")
            visible_row = self.visible_result_rows.get(status.name)
            if visible_row:
                _, visible_label = visible_row
                visible_label.configure(
                    text=str(present_label.cget("text")),
                    fg_color=str(present_label.cget("fg_color")),
                    text_color=str(present_label.cget("text_color")),
                )
            if status.error:
                count_label.configure(text="Check")
            else:
                count_label.configure(text="")

    def _log(self, message: str) -> None:
        import logging

        logging.getLogger("parcel_packet").info(message)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


def main() -> None:
    app = EnvironmentalWidgetApp()
    app.mainloop()


if __name__ == "__main__":
    main()
