from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter.font as tkfont

import customtkinter as ctk

from .aerial_runner import AerialMapRunner, AerialResult
from .fonts import load_bundled_fonts
from .logging_utils import configure_logging
from .settings import AppSettings, load_settings, save_settings
from .single_instance import acquire_single_instance_lock, release_single_instance_lock


class ParcelPacketApp(ctk.CTk):
    def __init__(self) -> None:
        self.lock_fd = acquire_single_instance_lock()
        if self.lock_fd is None:
            raise RuntimeError("Parcel Aerial Map is already open.")
        super().__init__()
        self.log_path = configure_logging()
        load_bundled_fonts()
        ctk.set_appearance_mode("dark")
        self.font_family = self._pick_font_family()

        self.settings = load_settings()
        self.events: queue.Queue[tuple[str, str | AerialResult]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

        self.title("Parcel Aerial Map")
        self.geometry("780x390")
        self.minsize(700, 370)
        self.configure(fg_color="#090b0f")
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
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 6))
        header.grid_columnconfigure(0, weight=1)

        eyebrow = ctk.CTkLabel(
            header,
            text="AERIAL CAPTURE",
            font=self._font(11, "bold"),
            text_color="#6f8fa7",
        )
        eyebrow.grid(row=0, column=0, sticky="w")
        title = ctk.CTkLabel(header, text="Parcel Aerial Map", font=self._font(29, "bold"), text_color="#f1f4f6")
        title.grid(row=1, column=0, sticky="w", pady=(2, 0))
        status_pill = ctk.CTkLabel(
            header,
            text="Ready",
            width=82,
            height=30,
            corner_radius=4,
            fg_color="#10161d",
            text_color="#87b8a6",
            font=self._font(12, "bold"),
        )
        status_pill.grid(row=1, column=1, sticky="e", padx=(12, 0))
        self.header_status = status_pill
        subtitle = ctk.CTkLabel(
            header,
            text="Aerial PDF capture for New Castle County parcels",
            text_color="#87909a",
            font=self._font(14),
        )
        subtitle.grid(row=2, column=0, sticky="w", pady=(1, 0))

        form = ctk.CTkFrame(self, corner_radius=6, fg_color="#11151b", border_color="#202833", border_width=1)
        form.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 8))
        form.grid_columnconfigure(0, minsize=150)
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(2, minsize=98)

        label_style = {"font": self._font(16, "bold"), "text_color": "#cbd2da"}
        ctk.CTkLabel(form, text="Parcel number", **label_style).grid(row=0, column=0, sticky="w", padx=(14, 8), pady=(10, 4))
        self.parcel_entry = ctk.CTkEntry(
            form,
            placeholder_text="07-046.40-077",
            height=40,
            corner_radius=4,
            fg_color="#090c11",
            border_color="#29323d",
            text_color="#edf2f5",
            placeholder_text_color="#64727d",
            font=self._font(16),
        )
        self.parcel_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=(10, 4))

        ctk.CTkLabel(form, text="Destination folder", **label_style).grid(row=1, column=0, sticky="w", padx=(14, 8), pady=(4, 10))
        self.folder_entry = ctk.CTkEntry(
            form,
            height=40,
            corner_radius=4,
            fg_color="#090c11",
            border_color="#29323d",
            text_color="#edf2f5",
            font=self._font(16),
        )
        self.folder_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.folder_entry.insert(0, self.settings.last_destination)
        self.browse_button = ctk.CTkButton(
            form,
            text="Browse",
            width=92,
            height=40,
            corner_radius=4,
            fg_color="#203143",
            hover_color="#2a4056",
            text_color="#dbe6ee",
            font=self._font(14, "bold"),
            command=self._browse,
        )
        self.browse_button.grid(row=1, column=2, sticky="ew", padx=(0, 14), pady=(4, 10))

        progress_panel = ctk.CTkFrame(self, corner_radius=6, fg_color="#10141a", border_color="#202833", border_width=1)
        progress_panel.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        progress_panel.grid_columnconfigure(0, weight=1)
        progress_panel.grid_rowconfigure(1, weight=1)
        status_row = ctk.CTkFrame(progress_panel, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        status_row.grid_columnconfigure(1, weight=1)
        accent_dot = ctk.CTkLabel(status_row, text="", width=9, height=9, corner_radius=4, fg_color="#4f806f")
        accent_dot.grid(row=0, column=0, sticky="w", padx=(0, 9))
        self.status_label = ctk.CTkLabel(status_row, text="Ready", anchor="w", font=self._font(16, "bold"), text_color="#e7edf0")
        self.status_label.grid(row=0, column=1, sticky="ew")
        self.log_box = ctk.CTkTextbox(
            progress_panel,
            height=96,
            corner_radius=4,
            fg_color="#090c11",
            border_color="#1d2530",
            border_width=1,
            font=self._font(14),
            text_color="#b8c3cb",
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        self.log_box.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 14))
        footer.grid_columnconfigure(0, weight=1)
        self.run_button = ctk.CTkButton(
            footer,
            text="Save Aerial PDF",
            width=168,
            height=44,
            corner_radius=4,
            fg_color="#456f88",
            hover_color="#527f9c",
            text_color="#eef7f8",
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
            fg_color="#171d25",
            hover_color="#222b35",
            text_color="#aeb7bf",
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
            important_pause_seconds=3,
            settle_pause_seconds=3,
            assisted_layers=False,
        )
        save_settings(self.settings)
        self.stop_event.clear()
        self._set_running(True)
        self._clear_log()
        self._log("Starting aerial map capture")

        runner = AerialMapRunner(
            parcel_number=parcel,
            destination=Path(folder),
            progress=self._progress,
            stop_event=self.stop_event,
            pause_seconds=3,
            browser_channel=self.settings.browser_channel,
        )
        self.worker = threading.Thread(target=self._run_worker, args=(runner,), daemon=True)
        self.worker.start()

    def _run_worker(self, runner: AerialMapRunner) -> None:
        try:
            result = runner.run()
            self.events.put(("done", result))
        except Exception as exc:
            import logging

            logging.getLogger("parcel_packet").exception("Aerial capture failed")
            self.events.put(("error", str(exc)))

    def _progress(self, message: str) -> None:
        self.events.put(("progress", message))

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self.status_label.configure(text=str(payload))
                    self.header_status.configure(text="Running", fg_color="#111d28", text_color="#8ab6cf")
                    self._log(str(payload))
                elif event == "done":
                    result = payload if isinstance(payload, AerialResult) else None
                    self.status_label.configure(text="Finished: aerial PDF saved")
                    self.header_status.configure(text="Saved", fg_color="#101b18", text_color="#8dc5b0")
                    if result:
                        self._log(f"Saved PDF: {result.pdf_path}")
                        self._log(f"Debug folder: {result.debug_folder}")
                    self._set_running(False)
                    messagebox.showinfo("Aerial PDF complete", "Saved the aerial map PDF.")
                elif event == "error":
                    self.status_label.configure(text="Needs attention")
                    self.header_status.configure(text="Error", fg_color="#38252a", text_color="#d6aaa8")
                    self._log(f"Error: {payload}")
                    self._set_running(False)
                    messagebox.showerror("Packet stopped", str(payload))
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
        if running:
            self.header_status.configure(text="Running", fg_color="#111d28", text_color="#8ab6cf")
        else:
            self.header_status.configure(text="Ready", fg_color="#10161d", text_color="#87b8a6")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _log(self, message: str) -> None:
        import logging

        logging.getLogger("parcel_packet").info(message)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


def main() -> None:
    try:
        app = ParcelPacketApp()
    except RuntimeError as exc:
        messagebox.showwarning("Already open", str(exc))
        return
    try:
        app.mainloop()
    finally:
        release_single_instance_lock(getattr(app, "lock_fd", None))


if __name__ == "__main__":
    main()
