"""Tkinter GUI. Paste an ARP table (or open a file), get a sortable vendor table."""

from __future__ import annotations

import ipaddress
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .core import Result, resolve, to_csv, to_table
from .oui import VendorLookup, default_cache_dir, update_database

COLUMNS = (("ip", "IP Address", 130), ("mac", "MAC Address", 150),
           ("vendor", "Vendor", 300), ("notes", "Notes", 200))


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=10)
        self.root = root
        self.results: list[Result] = []
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.online = tk.BooleanVar(value=False)
        self.include_special = tk.BooleanVar(value=False)
        self.status = tk.StringVar()
        self.lookup = VendorLookup()
        self._sort_state: dict[str, bool] = {}

        root.title(f"ARP Vendor Lookup v{__version__}")
        root.minsize(760, 560)
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self._build()
        self._refresh_db_status()
        self.after(100, self._poll_events)

    # -- layout -------------------------------------------------------------
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="Paste ARP table output (Windows, Linux, macOS, Cisco, Palo Alto, Fortinet, Juniper):"
                  ).grid(row=0, column=0, sticky="w")
        self.input = ScrolledText(self, height=10, wrap=tk.NONE, font=("Courier", 10))
        self.input.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
        self.rowconfigure(1, weight=1)

        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")
        self.lookup_btn = ttk.Button(bar, text="Look Up Vendors", command=self.run_lookup)
        self.lookup_btn.pack(side="left")
        ttk.Button(bar, text="Open File...", command=self.open_file).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="left")
        ttk.Checkbutton(bar, text="Online fallback", variable=self.online).pack(side="left", padx=(16, 4))
        ttk.Checkbutton(bar, text="Show broadcast/multicast", variable=self.include_special).pack(side="left")
        self.update_btn = ttk.Button(bar, text="Update OUI DB", command=self.run_update)
        self.update_btn.pack(side="right")

        table_frame = ttk.Frame(self)
        table_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 4))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.rowconfigure(3, weight=2)
        self.tree = ttk.Treeview(table_frame, columns=[c[0] for c in COLUMNS], show="headings", height=12)
        for key, label, width in COLUMNS:
            self.tree.heading(key, text=label, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor="w", stretch=key == "vendor")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        bottom = ttk.Frame(self)
        bottom.grid(row=4, column=0, sticky="ew")
        self.progress = ttk.Progressbar(bottom, mode="determinate", length=160)
        self.progress.pack(side="left")
        ttk.Label(bottom, textvariable=self.status).pack(side="left", padx=8)
        ttk.Button(bottom, text="Export CSV...", command=self.export_csv).pack(side="right")
        ttk.Button(bottom, text="Copy Table", command=self.copy_table).pack(side="right", padx=4)

    # -- actions ------------------------------------------------------------
    def run_lookup(self) -> None:
        if self.busy:
            return
        text = self.input.get("1.0", tk.END)
        if not text.strip():
            self.status.set("Paste an ARP table first.")
            return
        if not self.lookup.has_database and not self.online.get():
            if messagebox.askyesno(
                "No offline database",
                "The offline OUI database hasn't been downloaded yet.\n\n"
                "Download it now from IEEE (about 6 MB, one time)?",
            ):
                self.run_update(then_lookup=True)
            else:
                self.status.set("Tip: enable 'Online fallback' or update the OUI DB.")
            return
        self.lookup.online = self.online.get()
        self._set_busy(True, "Looking up vendors...")
        include = self.include_special.get()

        def work():
            try:
                res = resolve(text, self.lookup, include_special=include,
                              progress=lambda i, n: self.events.put(("progress", i, n)))
                self.events.put(("results", res))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def run_update(self, then_lookup: bool = False) -> None:
        if self.busy:
            return
        self._set_busy(True, "Downloading IEEE OUI registries...")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def work():
            try:
                update_database(progress=lambda m: self.events.put(("status", m)))
                self.events.put(("db_updated", then_lookup))
            except Exception as exc:
                self.events.put(("error", f"Update failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def open_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt *.log *.csv"), ("All files", "*.*")])
        if path:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self.input.delete("1.0", tk.END)
                self.input.insert("1.0", fh.read())

    def clear(self) -> None:
        self.input.delete("1.0", tk.END)
        self.tree.delete(*self.tree.get_children())
        self.results = []
        self.progress["value"] = 0
        self._refresh_db_status()

    def export_csv(self) -> None:
        if not self.results:
            self.status.set("Nothing to export yet.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="arp_vendors.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(to_csv(self._visible_results()))
            self.status.set(f"Saved {len(self.results)} rows to {path}")

    def copy_table(self) -> None:
        if not self.results:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(to_table(self._visible_results()))
        self.status.set("Table copied to clipboard.")

    def sort_by(self, key: str) -> None:
        reverse = self._sort_state.get(key, False)
        if key == "ip":
            keyfunc = lambda r: ipaddress.IPv4Address(r.ip)
        else:
            keyfunc = lambda r: getattr(r, key).lower()
        self.results.sort(key=keyfunc, reverse=reverse)
        self._sort_state[key] = not reverse
        self._fill_table()

    # -- helpers ------------------------------------------------------------
    def _visible_results(self) -> list[Result]:
        return list(self.results)

    def _fill_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for r in self.results:
            self.tree.insert("", tk.END, values=(r.ip, r.mac, r.vendor, r.notes))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.lookup_btn.configure(state=state)
        self.update_btn.configure(state=state)
        if message:
            self.status.set(message)

    def _refresh_db_status(self) -> None:
        if self.lookup.has_database:
            self.status.set(f"Offline DB ready: {self.lookup.size:,} vendor prefixes")
        else:
            self.status.set(f"No offline DB yet - click 'Update OUI DB' ({default_cache_dir()})")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, i, n = event
                    self.progress.configure(mode="determinate", maximum=max(n, 1))
                    self.progress["value"] = i
                    self.status.set(f"Resolved {i} of {n}")
                elif kind == "results":
                    self.results = event[1]
                    self._fill_table()
                    self._set_busy(False, f"Done - {len(self.results)} entries.")
                    if not self.results:
                        self.status.set("No IP/MAC pairs found. Check the pasted text.")
                elif kind == "status":
                    self.status.set(event[1])
                elif kind == "db_updated":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.lookup.load()
                    self._set_busy(False)
                    self._refresh_db_status()
                    if event[1]:
                        self.run_lookup()
                elif kind == "error":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self._set_busy(False, event[1])
                    messagebox.showerror("Error", event[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
