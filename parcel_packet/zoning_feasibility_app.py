from __future__ import annotations

import logging
import queue
import re
import threading
from pathlib import Path
from tkinter import filedialog
import tkinter.font as tkfont

import customtkinter as ctk

from .fonts import load_bundled_fonts
from .logging_utils import configure_logging
from .settings import AppSettings, load_settings, save_settings
from .zoning_feasibility_runner import (
    APARTMENT_UNIT_SIZE_MIX,
    COUNTY_CODE_HOME,
    MIXED_USE_COMMERCIAL_GFA_SHARE,
    MIXED_USE_PROGRAM_GFA_UTILIZATION,
    MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY,
    VALUE_SCREEN_METHOD_LINES,
    VALUE_SCREEN_SOURCE_LINES,
    FeasibilityResult,
    YieldRecommendation,
    ZoningFeasibilityRunner,
)


APP_NAME = "Zoning Feasibility Checker"


class ZoningFeasibilityApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        configure_logging()
        load_bundled_fonts()
        ctk.set_appearance_mode("dark")

        self.font_family = self._pick_font_family()
        self.settings = load_settings()
        self.events: queue.Queue[tuple[str, str | FeasibilityResult | Path]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.current_result: FeasibilityResult | None = None

        self.title(APP_NAME)
        self.geometry("1120x780+64+64")
        self.minsize(960, 680)
        self.configure(fg_color="#070a0d")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self.after(150, self._drain_events)

    def _font(self, size: int, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family=self.font_family, size=size, weight=weight)

    def _pick_font_family(self) -> str:
        available = set(tkfont.families(self))
        for family in ("Nunito Sans Normal", "Nunito Sans", "NunitoSans", "Segoe UI Variable Text", "Segoe UI"):
            if family in available:
                return family
        return "TkDefaultFont"

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkFrame(self, height=38, corner_radius=0, fg_color="#2d5675").grid(row=0, column=0, sticky="ew")

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=24, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=APP_NAME, font=self._font(30, "bold"), text_color="#f2f5f3").grid(row=0, column=0, sticky="w")
        self.status_badge = ctk.CTkLabel(
            header,
            text="Ready",
            width=96,
            height=32,
            corner_radius=8,
            fg_color="#0d1518",
            text_color="#94c6d8",
            font=self._font(13, "bold"),
        )
        self.status_badge.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            header,
            text=(
                "Query NCC GIS zoning, identify municipality, and generate conservative by-right yield recommendations. "
                "Enter an address, one parcel, or multiple adjoining parcels for an assembled-site screen."
            ),
            text_color="#8d999b",
            font=self._font(14),
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        form = self._panel(row=2)
        form.grid_columnconfigure(1, weight=1)
        label_style = {"font": self._font(15, "bold"), "text_color": "#d0d8d4"}

        ctk.CTkLabel(form, text="Parcel(s) or address", **label_style).grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(16, 6))
        self.parcel_entry = self._entry(form, "1021 Gilpin Ave or 1105400001, 1105400002")
        self.parcel_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=(16, 6))

        ctk.CTkLabel(form, text="Report folder", **label_style).grid(row=1, column=0, sticky="w", padx=(16, 8), pady=(6, 16))
        self.folder_entry = self._entry(form, "")
        self.folder_entry.insert(0, self.settings.last_destination)
        self.folder_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=(6, 8))
        self.browse_button = ctk.CTkButton(
            form,
            text="Browse",
            width=94,
            height=38,
            corner_radius=8,
            fg_color="#2d5675",
            hover_color="#386b91",
            text_color="#f2f7f8",
            font=self._font(14, "bold"),
            command=self._browse,
        )
        self.browse_button.grid(row=1, column=3, sticky="ew", padx=(0, 16), pady=(6, 8))

        ctk.CTkLabel(form, text="Use screening", **label_style).grid(row=2, column=0, sticky="w", padx=(16, 8), pady=(8, 16))
        self.use_mode = ctk.StringVar(value="Automatic broad screening")
        self.use_mode_menu = ctk.CTkOptionMenu(
            form,
            values=("Automatic broad screening", "Advanced intended use"),
            variable=self.use_mode,
            height=38,
            corner_radius=8,
            fg_color="#0b1518",
            button_color="#2d5675",
            button_hover_color="#386b91",
            dropdown_fg_color="#0b0f0e",
            dropdown_hover_color="#19313a",
            text_color="#edf3ef",
            font=self._font(14),
            command=lambda _value: self._toggle_advanced_use(),
        )
        self.use_mode_menu.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(8, 16))
        self.intended_use_entry = self._entry(form, "hospital, cigarette outlet, data center...")
        self.intended_use_entry.grid(row=2, column=2, columnspan=2, sticky="ew", padx=(0, 16), pady=(8, 16))
        self.intended_use_entry.configure(state="disabled", placeholder_text_color="#46534f")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 12))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        result_shell = self._panel(parent=body, row=0, column=0, padx=(0, 8), pady=0)
        result_shell.grid_rowconfigure(1, weight=1)
        result_shell.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(result_shell, text="Feasibility Result", font=self._font(18, "bold"), text_color="#e7eeea").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 6)
        )
        self.result_frame = ctk.CTkScrollableFrame(
            result_shell,
            corner_radius=10,
            fg_color="#070a0d",
            border_color="#203844",
            border_width=1,
        )
        self.result_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.result_frame.grid_columnconfigure(0, weight=1)
        self._write_result("Enter a parcel number or address, then run the check to generate a conservative yield matrix.")

        source_shell = self._panel(parent=body, row=0, column=1, padx=(8, 0), pady=0)
        source_shell.grid_rowconfigure(1, weight=1)
        source_shell.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(source_shell, text="Feasibility Snapshot", font=self._font(18, "bold"), text_color="#e7eeea").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 6)
        )
        self.sources_text = ctk.CTkTextbox(
            source_shell,
            corner_radius=10,
            fg_color="#070a0d",
            border_color="#203844",
            border_width=1,
            text_color="#aebbb8",
            font=self._font(13),
            wrap="word",
        )
        self.sources_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.sources_text.insert("end", "Key feasibility points will appear after a check.")
        self.sources_text.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 16))
        footer.grid_columnconfigure(0, weight=1)
        self.run_button = ctk.CTkButton(
            footer,
            text="Run Zoning Check",
            width=190,
            height=44,
            corner_radius=8,
            fg_color="#2d5675",
            hover_color="#386b91",
            text_color="#f3faf6",
            font=self._font(15, "bold"),
            command=self._start,
        )
        self.run_button.grid(row=0, column=1, padx=(10, 0))
        self.save_button = ctk.CTkButton(
            footer,
            text="Save Report",
            width=140,
            height=44,
            corner_radius=8,
            fg_color="#1b2a2f",
            hover_color="#2d4350",
            text_color="#8d9b95",
            font=self._font(15, "bold"),
            command=self._save_report,
            state="disabled",
        )
        self.save_button.grid(row=0, column=2, padx=(12, 0))

    def _panel(self, row: int, column: int = 0, parent=None, padx=24, pady=(0, 10)) -> ctk.CTkFrame:
        parent = parent or self
        shell = ctk.CTkFrame(parent, corner_radius=16, fg_color="#0b0f0e", border_color="#1f3a45", border_width=1)
        shell.grid(row=row, column=column, sticky="nsew", padx=padx, pady=pady)
        return shell

    def _entry(self, parent, placeholder: str) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            height=38,
            corner_radius=8,
            fg_color="#070a0d",
            border_color="#30454b",
            text_color="#edf3ef",
            placeholder_text_color="#68756f",
            font=self._font(14),
        )

    def _browse(self) -> None:
        initial = self.folder_entry.get().strip() or str(Path.home() / "Documents")
        folder = filedialog.askdirectory(initialdir=initial)
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

    def _start(self) -> None:
        parcel = self.parcel_entry.get().strip()
        if not parcel:
            self._write_result("Enter a parcel number or address first.")
            return
        folder = self.folder_entry.get().strip()
        if folder:
            self.settings = AppSettings(last_destination=folder, project_prefix="")
            save_settings(self.settings)

        self.current_result = None
        self.save_button.configure(state="disabled", fg_color="#1b2a2f", text_color="#8d9b95")
        self._set_running(True)
        self._write_result("Running zoning feasibility check...")
        self._write_sources("")

        runner = ZoningFeasibilityRunner(
            parcel_number=parcel,
            intended_use=self._advanced_use_text(),
            progress=self._progress,
        )
        self.worker = threading.Thread(target=self._worker, args=(runner,), daemon=True)
        self.worker.start()

    def _worker(self, runner: ZoningFeasibilityRunner) -> None:
        try:
            self.events.put(("done", runner.analyze()))
        except Exception as exc:
            logging.getLogger("parcel_packet").exception("Zoning feasibility check failed")
            self.events.put(("error", str(exc)))

    def _save_report(self) -> None:
        if self.current_result is None:
            return
        folder = self.folder_entry.get().strip()
        if not folder:
            self._write_result("Choose a report folder before saving.")
            return
        runner = ZoningFeasibilityRunner(self.parcel_entry.get())
        try:
            path = runner.write_report(self.current_result, Path(folder))
        except Exception as exc:
            self._write_result(f"Could not save report: {exc}")
            return
        self.status_badge.configure(text="Saved", fg_color="#0d1b16", text_color="#91c7a9")
        self._write_sources(self._snapshot_display(self.current_result) + f"\n\nSaved report:\n{path}")

    def _progress(self, message: str) -> None:
        self.events.put(("progress", message))

    def _advanced_use_text(self) -> str:
        if self.use_mode.get() != "Advanced intended use":
            return ""
        return self.intended_use_entry.get().strip()

    def _toggle_advanced_use(self) -> None:
        enabled = self.use_mode.get() == "Advanced intended use"
        self.intended_use_entry.configure(
            state="normal" if enabled else "disabled",
            border_color="#3f735a" if enabled else "#30454b",
            placeholder_text_color="#70817c" if enabled else "#46534f",
        )

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self.status_badge.configure(text=str(payload), fg_color="#0d1518", text_color="#94c6d8")
                elif event == "done" and isinstance(payload, FeasibilityResult):
                    self.current_result = payload
                    self._set_running(False)
                    self._apply_result(payload)
                elif event == "error":
                    self._set_running(False)
                    self.status_badge.configure(text="Error", fg_color="#38252a", text_color="#d6aaa8")
                    self._write_result(f"Check failed:\n{payload}")
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _apply_result(self, result: FeasibilityResult) -> None:
        color = "#153325" if result.status == "Yield Screening Complete" else "#2d2415"
        text_color = "#91d3ac" if result.status == "Yield Screening Complete" else "#d0bc78"
        self.status_badge.configure(text=result.status[:18], fg_color=color, text_color=text_color)
        self.save_button.configure(state="normal", fg_color="#2d5675", text_color="#f3faf6")
        self._render_result(result)
        self._write_sources(self._snapshot_display(result))

    def _render_result(self, result: FeasibilityResult) -> None:
        self._clear_result()
        zoning = ", ".join(
            f"{district.code} - {district.description}" if district.description else district.code
            for district in result.zoning_districts
        ) or "-"
        self._section_label("Development Options")
        self._opportunity_list(result)
        parcel_rows = [
            ("Parcel", result.parcel.parcel_number),
            ("Address", result.parcel.address or "-"),
            ("Owner", result.parcel.owner or "-"),
            ("Municipality", result.municipality),
            ("Zoning", zoning),
        ]
        if self._is_public_owner(result.parcel.owner):
            parcel_rows.append(("Private development", "Public/quasi-public land; private redevelopment is not likely without acquisition, disposition, partnership, or public approval."))
        self._key_value_grid(
            "Parcel Snapshot",
            tuple(parcel_rows),
        )
        self._compact_notes(result)
        ctk.CTkLabel(
            self.result_frame,
            text="Planning note: This is a preliminary screening tool, not a legal zoning determination.",
            text_color="#7f8c88",
            font=self._font(12, "bold"),
            justify="left",
            wraplength=680,
        ).grid(row=self._next_result_row(), column=0, sticky="ew", padx=14, pady=(8, 14))

    def _opportunity_list(self, result: FeasibilityResult) -> None:
        if not result.recommendations:
            ctk.CTkLabel(
                self.result_frame,
                text="No development options were generated.",
                text_color="#aebbb8",
                font=self._font(13),
                anchor="w",
            ).grid(row=self._next_result_row(), column=0, sticky="ew", padx=14, pady=(0, 10))
            return
        for index, recommendation in enumerate(result.recommendations, start=1):
            self._opportunity_row(result, recommendation, index)

    def _opportunity_row(self, result: FeasibilityResult, recommendation: YieldRecommendation, index: int) -> None:
        shell = ctk.CTkFrame(
            self.result_frame,
            corner_radius=12,
            fg_color=self._opportunity_bg(recommendation),
            border_color=self._opportunity_border(recommendation),
            border_width=1,
        )
        shell.grid(row=self._next_result_row(), column=0, sticky="ew", padx=10, pady=(0, 8))
        shell.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 8))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text=f"{index}",
            width=34,
            height=34,
            corner_radius=10,
            fg_color=self._status_color(recommendation.status),
            text_color="#07100d",
            font=self._font(14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        ctk.CTkLabel(
            header,
            text=self._opportunity_line(result, recommendation),
            text_color="#ecf4ef",
            font=self._font(14, "bold"),
            anchor="w",
            justify="left",
            wraplength=690,
        ).grid(row=0, column=1, sticky="ew")

        details = ctk.CTkFrame(shell, corner_radius=10, fg_color="#07100f", border_color="#18343b", border_width=1)
        details.grid_columnconfigure(0, weight=1)
        detail_text = "\n".join(self._opportunity_detail_lines(result, recommendation))
        ctk.CTkLabel(
            details,
            text=detail_text,
            text_color="#aebbb8",
            font=self._font(12),
            anchor="w",
            justify="left",
            wraplength=760,
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        details.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        details.grid_remove()

        state = {"open": False}

        def toggle() -> None:
            state["open"] = not state["open"]
            if state["open"]:
                details.grid()
                expand_button.configure(text="^")
            else:
                details.grid_remove()
                expand_button.configure(text="v")

        expand_button = ctk.CTkButton(
            header,
            text="v",
            width=32,
            height=30,
            corner_radius=10,
            fg_color="#152326",
            hover_color="#20383f",
            text_color="#c6d8d1",
            font=self._font(16, "bold"),
            command=toggle,
        )
        expand_button.grid(row=0, column=2, sticky="e", padx=(10, 0))
        header.bind("<Button-1>", lambda _event: toggle())

    def _opportunity_line(self, result: FeasibilityResult, recommendation: YieldRecommendation) -> str:
        return (
            f"{self._display_option_name(recommendation)} | "
            f"{self._yield_breakdown(result, recommendation)} | "
            f"{self._market_range_text(recommendation)}"
        )

    def _yield_breakdown(self, result: FeasibilityResult, recommendation: YieldRecommendation) -> str:
        if recommendation.conservative_yield is None:
            return "Review required"
        option = recommendation.development_option.lower()
        if "mixed use" in option:
            if recommendation.program_scenario:
                scenario = recommendation.program_scenario
                return f"{scenario.modeled_units or 0:,} units within +/-{(scenario.envelope_gfa or 0):,} sf GFA envelope"
            commercial_gfa, units = self._mixed_use_split(recommendation)
            return f"{units:,} units within mixed-use GFA program; {commercial_gfa:,} sf commercial component"
        return self._yield_metric_text(result, recommendation)

    def _display_option_name(self, recommendation: YieldRecommendation) -> str:
        option = recommendation.development_option
        clean = option.lower()
        if clean == "mixed use development":
            return "Mixed Use"
        if clean == "commercial apartments":
            return "Apartments"
        if clean == "other / custom use":
            return "Civic / Utility / Solar / Other"
        return option

    def _opportunity_detail_lines(self, result: FeasibilityResult, recommendation: YieldRecommendation) -> tuple[str, ...]:
        gross_label = "Theoretical envelope" if recommendation.program_scenario else "Theoretical screen"
        gross_value = (
            f"{recommendation.program_scenario.envelope_gfa or 0:,} sf GFA"
            if recommendation.program_scenario
            else ("-" if recommendation.gross_area_yield is None else f"{recommendation.gross_area_yield:,}")
        )
        lines = [
            f"Development option: {recommendation.development_option}",
            f"Status: {recommendation.status}",
            f"Recommended scenario: {self._yield_breakdown(result, recommendation)}",
            f"{gross_label}: {gross_value}",
        ]
        if "mixed use" in recommendation.development_option.lower():
            scenario = recommendation.program_scenario
            if scenario:
                lines.extend(
                    (
                        f"Buildable envelope: +/-{(scenario.envelope_gfa or 0):,} sf GFA.",
                        f"Residential screen: {scenario.modeled_units or 0:,} units within the GFA envelope.",
                        f"Code allocation: +/-{(scenario.total_program_gfa or 0):,} sf total GFA; +/-{(scenario.residential_gfa or 0):,} sf residential; +/-{(scenario.commercial_gfa or 0):,} sf commercial.",
                        "Planning-level zoning screen; verify against recorded plans, approvals, site constraints, and final engineering.",
                    )
                )

            else:
                outdoor_units = self._mixed_use_units_from_note(recommendation.note)
                site_units = self._mixed_use_site_units_from_note(recommendation.note)
                if outdoor_units or site_units:
                    commercial_gfa, ranked_units = self._mixed_use_split(recommendation)
                    lines.append(
                        f"Mixed-use split: {ranked_units:,} apartments modeled within the mixed-use GFA program, with {commercial_gfa:,} sf commercial GFA. "
                        f"The apartment count is capped by residential GFA, outdoor-area support"
                        f"{f' ({outdoor_units:,} units)' if outdoor_units else ''}, and site support"
                        f"{f' ({site_units:,} units)' if site_units else ''}."
                    )
        if recommendation.development_option == "Other / custom use":
            lines.append(
                "Plain-English examples: school/civic/institutional-style facilities, community-serving uses, utilities, renewable/solar facilities, or other permitted nonresidential uses that are not better represented by office, retail, industrial, or residential categories."
            )
        if recommendation.limiting_factors:
            lines.append(f"Primary limits: {', '.join(recommendation.limiting_factors)}.")
        if recommendation.note:
            lines.append(recommendation.note)
        return tuple(lines)

    def _compact_notes(self, result: FeasibilityResult) -> None:
        notes = [line for line in self._footnote_lines(result) if line]
        if not notes:
            return
        self._section_label("Small Print")
        ctk.CTkLabel(
            self.result_frame,
            text="\n".join(notes[:8]),
            text_color="#8f9c98",
            font=self._font(11),
            justify="left",
            wraplength=780,
        ).grid(row=self._next_result_row(), column=0, sticky="ew", padx=14, pady=(0, 8))

    def _opportunity_bg(self, recommendation: YieldRecommendation) -> str:
        if recommendation.status == "By Right":
            return "#0b1713"
        if "Review" in recommendation.status or "Interpretation" in recommendation.status:
            return "#17140c"
        if recommendation.status == "Not By Right":
            return "#170d0d"
        return "#0b1113"

    def _opportunity_border(self, recommendation: YieldRecommendation) -> str:
        if recommendation.status == "By Right":
            return "#315f4a"
        if "Review" in recommendation.status or "Interpretation" in recommendation.status:
            return "#6a5a2a"
        if recommendation.status == "Not By Right":
            return "#663636"
        return "#244955"

    def _status_color(self, status: str) -> str:
        if status == "By Right":
            return "#91c7a9"
        if "Review" in status or "Interpretation" in status:
            return "#d3ba72"
        if status == "Not By Right":
            return "#d99a96"
        return "#94c6d8"

    def _key_value_grid(self, title: str, rows: tuple[tuple[str, str], ...]) -> None:
        self._section_label(title)
        shell = ctk.CTkFrame(self.result_frame, corner_radius=10, fg_color="#09100f", border_width=1, border_color="#18343b")
        shell.grid(row=self._next_result_row(), column=0, sticky="ew", padx=10, pady=(0, 10))
        shell.grid_columnconfigure(1, weight=1)
        for index, (label, value) in enumerate(rows):
            ctk.CTkLabel(shell, text=label, font=self._font(12, "bold"), text_color="#78a492", anchor="w").grid(
                row=index, column=0, sticky="w", padx=(12, 14), pady=(8 if index == 0 else 4, 8 if index == len(rows) - 1 else 4)
            )
            ctk.CTkLabel(shell, text=value, font=self._font(13), text_color="#d5dfdb", anchor="w", justify="left", wraplength=560).grid(
                row=index, column=1, sticky="ew", padx=(0, 12), pady=(8 if index == 0 else 4, 8 if index == len(rows) - 1 else 4)
            )

    def _section_label(self, text: str) -> None:
        ctk.CTkLabel(self.result_frame, text=text, font=self._font(16, "bold"), text_color="#e7eeea", anchor="w").grid(
            row=self._next_result_row(), column=0, sticky="ew", padx=10, pady=(12, 6)
        )

    def _clear_result(self) -> None:
        for child in self.result_frame.winfo_children():
            child.destroy()
        self._result_row = 0

    def _next_result_row(self) -> int:
        row = getattr(self, "_result_row", 0)
        self._result_row = row + 1
        return row

    def _yield_metric_text(self, result: FeasibilityResult, recommendation: YieldRecommendation | None) -> str:
        if not recommendation or recommendation.conservative_yield is None:
            return "-"
        unit = self._yield_unit(result, recommendation)
        return f"{recommendation.conservative_yield:,} {unit}"

    def _yield_unit(self, result: FeasibilityResult, recommendation: YieldRecommendation) -> str:
        option = recommendation.development_option.lower()
        lot_options = ("single-family", "two-family", "townhouse", "semi-detached")
        if any(label in option for label in lot_options):
            return "Lots"
        if "solar" in option:
            return "sf site area"
        if "apartment" in option or "manufactured" in option or "mobile" in option or "home" in option:
            return "units"
        if self._is_gfa_recommendation(recommendation):
            return "sf GFA"
        if result.capacity_matrix and result.capacity_matrix.capacity_type == "nonresidential":
            return "sf GFA"
        return "Lots"

    def _is_gfa_recommendation(self, recommendation: YieldRecommendation) -> bool:
        option = recommendation.development_option.lower()
        return any(
            label in option
            for label in (
                "office",
                "retail",
                "commercial",
                "industrial",
                "mixed use",
                "custom",
                "other",
                "institutional",
                "civic",
                "utility",
                "solar",
            )
        )

    def _best_recommendation(self, result: FeasibilityResult) -> YieldRecommendation | None:
        if not result.recommendations:
            return None
        return max(result.recommendations, key=self._recommendation_rank_key)

    def _recommendation_rank_key(self, item: YieldRecommendation) -> tuple[float, int, int]:
        status_rank = {
            "By Right": 60,
            "Limited Use Review": 50,
            "Special Use Review": 40,
            "Interpretation Required": 30,
            "Review Required": 20,
            "Dimensional Variance Likely": 10,
            "Not By Right": 0,
        }.get(item.status, 0)
        midpoint = ((item.market_value_low or 0) + (item.market_value_high or 0)) / 2
        return midpoint, status_rank, item.conservative_yield or 0

    def _footnote_lines(self, result: FeasibilityResult) -> tuple[str, ...]:
        lines = [
            "* Resource acreage is overlap-adjusted. Higher protection ratios claim acreage before lower-ratio resources.",
        ]
        lines.extend(line.removeprefix("Warning: ") for line in result.details if line.startswith("Warning: "))
        for index, item in enumerate(result.recommendations, start=1):
            if item.status == "Not By Right" and not item.conservative_yield:
                continue
            if item.note:
                lines.append(f"[{index}] {item.note}")
            if item.limiting_factors:
                lines.append(f"[{index}] Limiting factors: {', '.join(item.limiting_factors)}.")
        return tuple(dict.fromkeys(lines))

    def _snapshot_display(self, result: FeasibilityResult) -> str:
        best = self._best_recommendation(result)
        zoning = ", ".join(district.code for district in result.zoning_districts) or "-"
        answer_label, answer_value = self._snapshot_answer(result, best)
        lines = [answer_label, answer_value, ""]
        if best:
            lines.extend(
                [
                    "Top ranked option",
                    best.development_option,
                    "",
                ]
            )
            if self._market_range_text(best) != "-":
                lines.extend(["Value screen", self._market_range_text(best), ""])
        lines.extend(
            [
                "Parcel",
                result.parcel.parcel_number,
                "",
                "Zoning / jurisdiction",
                f"{zoning} / {result.municipality}",
            ]
        )
        if self._is_public_owner(result.parcel.owner):
            lines.extend(
                [
                    "",
                    "Public ownership",
                    f"Owner appears public/quasi-public: {result.parcel.owner}. Private development is not likely unless the property is acquired, disposed, leased, partnered, or otherwise made available by the public owner.",
                ]
            )
        environmental = self._snapshot_environmental_lines(result)
        if environmental:
            lines.extend(["", "Environmental constraints", *environmental])
        if result.capacity_matrix:
            lines.extend(["", *self._snapshot_capacity_lines(result)])
        if best and best.limiting_factors:
            lines.extend(["", "Primary constraint", self._plain_limit(best.limiting_factors[0])])
            if len(best.limiting_factors) > 1:
                lines.extend(["Other constraints", ", ".join(self._plain_limit(factor) for factor in best.limiting_factors[1:3])])
        limited = self._limited_use_lines(result)
        if limited:
            lines.extend(["", "Limited-use potential", *limited])
        caveats = self._snapshot_caveats(result, best)
        if caveats:
            lines.extend(["", "Watch items", *caveats])
        lines.extend(["", "Value logic", *self._snapshot_value_logic_lines()])
        lines.extend(["", "Code source", COUNTY_CODE_HOME if result.municipality == "Unincorporated New Castle County" else (result.sources[0] if result.sources else "-")])
        return "\n".join(lines)

    def _snapshot_environmental_lines(self, result: FeasibilityResult) -> tuple[str, ...]:
        present = [
            resource
            for resource in result.protected_resources
            if resource.measured_acres > 0.005
        ]
        if not present:
            return ("No mapped protected resources found on the parcel.",)
        lines: list[str] = []
        for resource in sorted(present, key=lambda item: item.protected_acres, reverse=True):
            label = self._resource_snapshot_name(resource.name)
            measured = f"{resource.measured_acres:.2f} ac"
            protected = f"{resource.protected_acres:.2f} ac protected" if resource.protected_acres else "review area"
            lines.append(f"{label}: {measured}; {protected}")
        return tuple(lines[:8])

    def _resource_snapshot_name(self, name: str) -> str:
        clean = name.replace(" (see section 10.320)", "")
        clean = clean.replace(", assumed Tier 3", "")
        return clean

    def _snapshot_value_logic_lines(self) -> tuple[str, ...]:
        return (
            VALUE_SCREEN_METHOD_LINES[0],
            VALUE_SCREEN_METHOD_LINES[1],
            VALUE_SCREEN_METHOD_LINES[2],
            VALUE_SCREEN_METHOD_LINES[3],
            VALUE_SCREEN_METHOD_LINES[4],
            VALUE_SCREEN_METHOD_LINES[5],
            "Sources: " + " | ".join(VALUE_SCREEN_SOURCE_LINES),
        )

    def _snapshot_answer(self, result: FeasibilityResult, best: YieldRecommendation | None) -> tuple[str, str]:
        if not best or best.conservative_yield is None:
            return ("Feasibility answer", result.summary)
        if best.program_scenario:
            scenario = best.program_scenario
            return ("Residential scenario", f"{scenario.modeled_units or 0:,} units within +/-{(scenario.envelope_gfa or 0):,} sf GFA envelope | {self._market_range_text(best)}")
        if best.market_value_low is not None and best.market_value_high is not None:
            return ("Highest-value screen", f"{self._yield_metric_text(result, best)} | {self._market_range_text(best)}")
        if result.capacity_matrix and result.capacity_matrix.capacity_type == "nonresidential":
            return ("By-right GFA", self._yield_metric_text(result, best))
        label = "By-right lots" if "apartment" not in best.development_option.lower() else "By-right units"
        return (label, self._yield_metric_text(result, best))

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

    def _mixed_use_units_from_note(self, note: str) -> int:
        match = re.search(r"residential unit support ([\d,]+)", note)
        if not match:
            return 0
        return int(match.group(1).replace(",", ""))

    def _mixed_use_site_units_from_note(self, note: str) -> int:
        match = re.search(r"site support ([\d,]+)", note)
        if not match:
            return 0
        return int(match.group(1).replace(",", ""))

    def _mixed_use_split(self, recommendation: YieldRecommendation) -> tuple[int, int]:
        if recommendation.program_scenario:
            return recommendation.program_scenario.commercial_gfa or 0, recommendation.program_scenario.modeled_units or 0
        outdoor_supported_units = self._mixed_use_units_from_note(recommendation.note)
        site_supported_units = self._mixed_use_site_units_from_note(recommendation.note)
        allowed_gfa = recommendation.conservative_yield or 0
        program_gfa = int(allowed_gfa * MIXED_USE_PROGRAM_GFA_UTILIZATION)
        commercial_gfa = int(program_gfa * MIXED_USE_COMMERCIAL_GFA_SHARE)
        residential_gfa = max(0, program_gfa - commercial_gfa)
        average_net_area = sum(share * area for _bedroom, share, area in APARTMENT_UNIT_SIZE_MIX)
        average_gross_area = average_net_area / MIXED_USE_RESIDENTIAL_GROSS_EFFICIENCY
        gfa_supported_units = int(residential_gfa / average_gross_area) if average_gross_area else 0
        candidates = [gfa_supported_units]
        if outdoor_supported_units:
            candidates.append(outdoor_supported_units)
        if site_supported_units:
            candidates.append(site_supported_units)
        units = min(candidates)
        return commercial_gfa, units

    def _limited_use_lines(self, result: FeasibilityResult) -> tuple[str, ...]:
        lines: list[str] = []
        for item in result.recommendations:
            if item.status not in {"Limited Use Review", "Special Use Review"}:
                continue
            if item.conservative_yield is None:
                lines.append(f"{item.development_option}: review required")
            elif item.development_option == "Commercial apartments":
                lines.append(f"{item.development_option}: {self._yield_metric_text(result, item)} outdoor-area screen")
            else:
                lines.append(f"{item.development_option}: {self._yield_metric_text(result, item)}")
        return tuple(lines[:4])

    def _snapshot_capacity_lines(self, result: FeasibilityResult) -> tuple[str, ...]:
        matrix = result.capacity_matrix
        if matrix is None:
            return ()
        if matrix.capacity_type == "nonresidential":
            return (
                "Buildable area",
                f"{matrix.net_buildable_site_area_ac:,.2f} ac after protected resources/landscape",
                "Applied FAR",
                f"Gross {matrix.max_gross_far:.2f} / net {matrix.max_net_far:.2f}",
            )
        return (
            "Buildable area",
            f"{matrix.net_buildable_site_area_ac:,.2f} ac after open space/protected resources",
            "Density check",
            f"Gross cap {matrix.district_density_yield:,.1f}; site cap {matrix.site_specific_density_yield:,.1f}",
        )

    def _snapshot_caveats(self, result: FeasibilityResult, best: YieldRecommendation | None) -> tuple[str, ...]:
        caveats: list[str] = []
        if best and best.note:
            caveats.append(best.note)
        caveats.extend(line.removeprefix("Warning: ") for line in result.details if line.startswith("Warning: "))
        return tuple(dict.fromkeys(caveats[:3]))

    def _plain_limit(self, value: str) -> str:
        return value[:1].upper() + value[1:] if value else value

    def _is_public_owner(self, owner: str) -> bool:
        clean = owner.upper()
        public_terms = (
            "STATE OF",
            "COUNTY",
            "CITY OF",
            "TOWN OF",
            "SCHOOL DISTRICT",
            "BOARD OF EDUCATION",
            "DEPARTMENT",
            "AUTHORITY",
            "UNIVERSITY OF",
        )
        return any(term in clean for term in public_terms)

    def _write_result(self, text: str) -> None:
        self._clear_result()
        ctk.CTkLabel(
            self.result_frame,
            text=text,
            text_color="#cdd8d5",
            font=self._font(14),
            justify="left",
            wraplength=700,
        ).grid(row=self._next_result_row(), column=0, sticky="ew", padx=16, pady=16)

    def _write_sources(self, text: str) -> None:
        self.sources_text.configure(state="normal")
        self.sources_text.delete("1.0", "end")
        self.sources_text.insert("end", text or "Key feasibility points will appear after a check.")
        self.sources_text.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        self.browse_button.configure(state=state)
        self.status_badge.configure(
            text="Running" if running else "Ready",
            fg_color="#0d1518" if running else "#0d1512",
            text_color="#94c6d8" if running else "#91c7a9",
        )

    def _on_close(self) -> None:
        self.destroy()


def main() -> None:
    app = ZoningFeasibilityApp()
    app.mainloop()


if __name__ == "__main__":
    main()
