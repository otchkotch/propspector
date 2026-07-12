from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter.font as tkfont

import customtkinter as ctk

from .environmental_config import (
    ENVIRONMENTAL_MENU_GROUPS,
    RESOURCE_STATUS_ORDER,
    ResourcePresence,
)
from .environmental_runner import (
    EnvironmentalMapsRunner,
    EnvironmentalResult,
)
from .fonts import load_bundled_fonts
from .logging_utils import configure_logging
from .settings import AppSettings, load_settings, save_settings
from .single_instance import acquire_single_instance_lock, release_single_instance_lock


class EnvironmentalMapsApp(ctk.CTk):
    def __init__(self) -> None:
        self.lock_fd = acquire_single_instance_lock()
        if self.lock_fd is None:
            raise RuntimeError("Environmental Maps is already open.")
        super().__init__()
        self.log_path = configure_logging()
        load_bundled_fonts()
        ctk.set_appearance_mode("dark")
        self.font_family = self._pick_font_family()

        self.settings = load_settings()
        self.events: queue.Queue[
            tuple[str, str | EnvironmentalResult | tuple[ResourcePresence, ...]]
        ] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.progress_expanded = False

        self.title("Environmental Resources")
        self.geometry("860x760")
        self.minsize(780, 700)
        self.configure(fg_color="#070a0d")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
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
            "Segoe UI Variable Display",
            "Segoe UI",
        ):
            if family in available:
                return family
        return "TkDefaultFont"

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=0)
        self.grid_rowconfigure(4, weight=1)

        top_accent = ctk.CTkFrame(self, height=28, corner_radius=0, fg_color="#315f4b")
        top_accent.grid(row=0, column=0, sticky="ew")
        top_accent.grid_propagate(False)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=24, pady=(10, 8))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(header, text="Environmental Resources", font=self._font(30, "bold"), text_color="#f2f5f3")
        title.grid(row=0, column=0, sticky="w", pady=(0, 0))
        self.header_status = ctk.CTkLabel(
            header,
            text="Ready",
            width=82,
            height=30,
            corner_radius=4,
            fg_color="#101b17",
            text_color="#91c7a9",
            font=self._font(12, "bold"),
        )
        self.header_status.grid(row=0, column=1, sticky="e", padx=(12, 0))
        subtitle = ctk.CTkLabel(
            header,
            text=(
                "This app creates PDFs of the various Environmental Resources affecting a property. "
                "Input a parcel number and select which Map Groups to run. Select All Resources to run every Map Group. "
                "The app opens a web browser and creates files in the specified destination folder."
            ),
            text_color="#8c9692",
            font=self._font(13),
            justify="left",
            wraplength=650,
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

        form_shell = ctk.CTkFrame(self, corner_radius=8, fg_color="#111a17", border_color="#244236", border_width=1)
        form_shell.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 9))
        form_shell.grid_columnconfigure(0, weight=1)
        form = ctk.CTkFrame(form_shell, corner_radius=6, fg_color="#0c1110", border_color="#1c2a25", border_width=1)
        form.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        form.grid_columnconfigure(0, minsize=150)
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(2, minsize=98)

        label_style = {"font": self._font(16, "bold"), "text_color": "#d0d8d4"}
        ctk.CTkLabel(form, text="Parcel number", **label_style).grid(row=0, column=0, sticky="w", padx=(14, 8), pady=(10, 4))
        self.parcel_entry = ctk.CTkEntry(
            form,
            placeholder_text="0612700002",
            height=40,
            corner_radius=4,
            fg_color="#070a0d",
            border_color="#30453d",
            text_color="#edf3ef",
            placeholder_text_color="#68756f",
            font=self._font(16),
        )
        self.parcel_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=(10, 4))

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
        self.folder_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
        self.folder_entry.insert(0, self.settings.last_destination)
        self.browse_button = ctk.CTkButton(
            form,
            text="Browse",
            width=92,
            height=40,
            corner_radius=4,
            fg_color="#2d5a47",
            hover_color="#376d56",
            text_color="#eef7f2",
            font=self._font(14, "bold"),
            command=self._browse,
        )
        self.browse_button.grid(row=1, column=2, sticky="ew", padx=(0, 14), pady=4)

        ctk.CTkLabel(form, text="Map group", **label_style).grid(row=2, column=0, sticky="w", padx=(14, 8), pady=(4, 10))
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
        self.group_menu.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=(4, 10))

        progress_shell = ctk.CTkFrame(self, corner_radius=8, fg_color="#0b0f0e", border_color="#1b332b", border_width=1)
        progress_shell.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 9))
        progress_shell.grid_columnconfigure(0, weight=1)
        progress_shell.grid_rowconfigure(0, weight=0)
        progress_panel = ctk.CTkFrame(progress_shell, corner_radius=6, fg_color="#101614", border_color="#25352f", border_width=1)
        progress_panel.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        progress_panel.grid_columnconfigure(0, weight=1)
        progress_panel.grid_rowconfigure(1, weight=0)
        status_row = ctk.CTkFrame(progress_panel, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", padx=14, pady=8)
        status_row.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(status_row, text="", width=9, height=9, corner_radius=4, fg_color="#4f8b6d").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 9),
        )
        self.progress_toggle_button = ctk.CTkButton(
            status_row,
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
        self.progress_toggle_button.grid(row=0, column=1, sticky="w", padx=(0, 10))
        self.status_label = ctk.CTkLabel(status_row, text="Ready", anchor="w", font=self._font(16, "bold"), text_color="#e7eeea")
        self.status_label.grid(row=0, column=2, sticky="ew")
        self.log_box = ctk.CTkTextbox(
            progress_panel,
            height=78,
            corner_radius=4,
            fg_color="#070a0d",
            border_color="#223830",
            border_width=1,
            font=self._font(14),
            text_color="#b9c4bf",
        )
        self.log_box.configure(state="disabled")

        results_shell = ctk.CTkFrame(self, corner_radius=8, fg_color="#0b0f0e", border_color="#1b332b", border_width=1)
        results_shell.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 9))
        results_shell.grid_columnconfigure(0, weight=1)
        results_shell.grid_rowconfigure(0, weight=1)
        self.results_panel = ctk.CTkFrame(results_shell, corner_radius=6, fg_color="#0f1513", border_color="#25352f", border_width=1)
        self.results_panel.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.results_panel.grid_columnconfigure(0, weight=1)
        self.results_panel.grid_rowconfigure(1, weight=1)
        results_header = ctk.CTkFrame(self.results_panel, fg_color="transparent")
        results_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        results_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            results_header,
            text="Environmental Sub Categories",
            font=self._font(16, "bold"),
            text_color="#e7eeea",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            results_header,
            text="Present",
            font=self._font(13, "bold"),
            text_color="#8faaa0",
        ).grid(row=0, column=1, sticky="e", padx=(12, 44))

        self.results_frame = ctk.CTkScrollableFrame(
            self.results_panel,
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
            name_label = ctk.CTkLabel(
                self.results_frame,
                text=name,
                anchor="w",
                font=self._font(13),
                text_color="#c9d3cf",
            )
            name_label.grid(row=row_index, column=0, sticky="ew", padx=(10, 8), pady=2)
            present_label = ctk.CTkLabel(
                self.results_frame,
                text="-",
                width=58,
                height=24,
                corner_radius=4,
                fg_color="#111817",
                text_color="#6f7b76",
                font=self._font(15, "bold"),
            )
            present_label.grid(row=row_index, column=1, sticky="e", padx=(4, 8), pady=2)
            count_label = ctk.CTkLabel(
                self.results_frame,
                text="",
                width=54,
                anchor="e",
                font=self._font(12),
                text_color="#68756f",
            )
            count_label.grid(row=row_index, column=2, sticky="e", padx=(0, 10), pady=2)
            self.result_rows[name] = (name_label, present_label, count_label)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 14))
        footer.grid_columnconfigure(0, weight=1)
        self.run_button = ctk.CTkButton(
            footer,
            text="Run Research",
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
        )
        self.cancel_button.grid(row=0, column=2, padx=(12, 0))
        self.cancel_button.configure(state="disabled")

    def _browse(self) -> None:
        initial = self.folder_entry.get().strip() or str(Path.home() / "Documents")
        folder = filedialog.askdirectory(initialdir=initial)
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

    def _start(self) -> None:
        parcel = self.parcel_entry.get().strip()
        folder = self.folder_entry.get().strip()
        if not parcel:
            messagebox.showwarning("Parcel needed", "Enter a parcel number first.")
            return
        if not folder:
            messagebox.showwarning("Folder needed", "Choose a destination folder first.")
            return

        self.settings = AppSettings(
            last_destination=folder,
            project_prefix="",
            browser_channel=self.settings.browser_channel,
            important_pause_seconds=1,
            settle_pause_seconds=1,
            assisted_layers=False,
        )
        save_settings(self.settings)
        self.stop_event.clear()
        self._set_running(True)
        self._clear_log()
        self._reset_results()
        self._log("Starting environmental map capture")

        runner = EnvironmentalMapsRunner(
            parcel_number=parcel,
            destination=Path(folder),
            progress=self._progress,
            stop_event=self.stop_event,
            environmental_group=self.group_menu.get(),
            pause_seconds=1,
            browser_channel=self.settings.browser_channel,
            headless_browser=False,
            offscreen_browser=False,
            resource_status_callback=self._resource_statuses,
        )
        self.worker = threading.Thread(target=self._run_worker, args=(runner,), daemon=True)
        self.worker.start()

    def _run_worker(self, runner: EnvironmentalMapsRunner) -> None:
        try:
            result = runner.run()
            self.events.put(("done", result))
        except Exception as exc:
            import logging

            logging.getLogger("parcel_packet").exception("Environmental capture failed")
            self.events.put(("error", str(exc)))

    def _progress(self, message: str) -> None:
        self.events.put(("progress", message))

    def _resource_statuses(self, statuses: tuple[ResourcePresence, ...]) -> None:
        self.events.put(("resource_statuses", statuses))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self.status_label.configure(text=str(payload))
                    self.header_status.configure(text="Running", fg_color="#0f1d18", text_color="#91c7a9")
                    self._log(str(payload))
                elif event == "resource_statuses":
                    statuses = payload if isinstance(payload, tuple) else ()
                    self._apply_results(statuses)
                    self._log("Resource presence check complete")
                elif event == "done":
                    result = payload if isinstance(payload, EnvironmentalResult) else None
                    self.status_label.configure(text="Finished: research complete")
                    self.header_status.configure(text="Saved", fg_color="#0d1b16", text_color="#91c7a9")
                    if result:
                        self._apply_results(result.resource_statuses)
                        for pdf_path in result.environmental_pdf_paths:
                            self._log(f"Saved PDF: {pdf_path}")
                        self._log(f"Debug folder: {result.debug_folder}")
                    self._set_running(False)
                    messagebox.showinfo("Parcel research complete", "Saved the environmental map PDF files.")
                elif event == "error":
                    self.status_label.configure(text="Needs attention")
                    self.header_status.configure(text="Error", fg_color="#38252a", text_color="#d6aaa8")
                    self._log(f"Error: {payload}")
                    self._set_running(False)
                    messagebox.showerror("Capture stopped", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._drain_events)

    def _cancel(self) -> None:
        self.stop_event.set()
        self._log("Cancelling after the current browser step")

    def _on_close(self) -> None:
        self.stop_event.set()
        release_single_instance_lock(self.lock_fd)
        self.destroy()

    def _set_running(self, running: bool) -> None:
        self.run_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.browse_button.configure(state="disabled" if running else "normal")
        self.group_menu.configure(state="disabled" if running else "normal")
        if running:
            self.header_status.configure(text="Running", fg_color="#0f1d18", text_color="#91c7a9")
        else:
            self.header_status.configure(text="Ready", fg_color="#0d1512", text_color="#91c7a9")

    def _toggle_progress(self) -> None:
        self.progress_expanded = not self.progress_expanded
        if self.progress_expanded:
            self.progress_toggle_button.configure(text="Progress v")
            self.log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        else:
            self.progress_toggle_button.configure(text="Progress >")
            self.log_box.grid_remove()

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _reset_results(self) -> None:
        for _, present_label, count_label in self.result_rows.values():
            present_label.configure(text="-", fg_color="#111817", text_color="#6f7b76")
            count_label.configure(text="")

    def _apply_results(self, statuses: tuple[ResourcePresence, ...]) -> None:
        for status in statuses:
            row = self.result_rows.get(status.name)
            if row is None:
                continue
            _, present_label, count_label = row
            if status.status == "Present":
                present_label.configure(text="X", fg_color="#3b1517", text_color="#ff7474")
            elif status.status == "Absent":
                present_label.configure(text="", fg_color="#111817", text_color="#6f7b76")
            else:
                present_label.configure(text="?", fg_color="#2d2415", text_color="#d0a96d")
            if status.count is not None:
                count_label.configure(text=str(status.count))
            elif status.error:
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
    try:
        app = EnvironmentalMapsApp()
    except RuntimeError as exc:
        messagebox.showwarning("Already open", str(exc))
        return
    try:
        app.mainloop()
    finally:
        release_single_instance_lock(getattr(app, "lock_fd", None))


if __name__ == "__main__":
    main()
