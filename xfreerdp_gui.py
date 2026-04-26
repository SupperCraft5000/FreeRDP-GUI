#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

APP_NAME = "FreeRDP GUI"
CONFIG_DIR = Path.home() / ".config" / "xfreerdp-gui"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "server": "",
    "username": "",
    "domain": "",
    "clipboard": True,
    "sound": True,
    "dynamic_resolution": True,
    "fullscreen": False,
    "cert_ignore": True,
}


def load_config():
    data = DEFAULTS.copy()
    try:
        if CONFIG_FILE.exists():
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update({k: loaded.get(k, v) for k, v in DEFAULTS.items()})
    except Exception:
        pass
    return data


def save_config(values):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")


def has_graphical_session():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def cli_error(message):
    print(message, file=sys.stderr)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("640x500")
        self.minsize(560, 420)
        self.grid_columnconfigure(0, weight=1)
        self.config_data = load_config()
        self.proc = None
        self._build_style()
        self._build_ui()
        self._load_values()
        self.update_preview()

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Noto Sans", 15, "bold"))
        style.configure("Hint.TLabel", foreground="#555")

    def _build_ui(self):
        outer = ttk.Frame(self, padding=16)
        outer.grid(sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)

        ttk.Label(outer, text="FreeRDP GUI", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="Einfache Oberfläche für xfreerdp3 mit Host, Benutzer, Passwort und den wichtigsten Optionen.",
            style="Hint.TLabel",
            wraplength=600,
        ).grid(row=1, column=0, sticky="w", pady=(4, 16))

        form = ttk.LabelFrame(outer, text="Verbindung", padding=12)
        form.grid(row=2, column=0, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        self.server_var = tk.StringVar()
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        self.domain_var = tk.StringVar()
        self.clipboard_var = tk.BooleanVar()
        self.sound_var = tk.BooleanVar()
        self.dynamic_var = tk.BooleanVar()
        self.fullscreen_var = tk.BooleanVar()
        self.cert_ignore_var = tk.BooleanVar()

        fields = [
            ("Hostname / IP", self.server_var),
            ("Benutzername", self.user_var),
            ("Passwort", self.pass_var),
            ("Domäne (optional)", self.domain_var),
        ]
        for idx, (label, var) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=idx, column=0, sticky="w", pady=6, padx=(0, 12))
            show = "*" if label == "Passwort" else ""
            entry = ttk.Entry(form, textvariable=var, show=show)
            entry.grid(row=idx, column=1, sticky="ew", pady=6)

        opts = ttk.LabelFrame(outer, text="Optionen", padding=12)
        opts.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        opts.grid_columnconfigure(0, weight=1)
        opts.grid_columnconfigure(1, weight=1)

        ttk.Checkbutton(opts, text="Zwischenablage aktivieren", variable=self.clipboard_var, command=self.update_preview).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Ton weiterleiten", variable=self.sound_var, command=self.update_preview).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Dynamische Auflösung", variable=self.dynamic_var, command=self.update_preview).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Vollbild beim Start", variable=self.fullscreen_var, command=self.update_preview).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Zertifikat ignorieren", variable=self.cert_ignore_var, command=self.update_preview).grid(row=2, column=0, sticky="w", pady=4)

        note = ttk.Label(
            outer,
            text="Hinweis: Vollbild kann in FreeRDP später mit Strg+Alt+Enter umgeschaltet werden.",
            style="Hint.TLabel",
            wraplength=600,
        )
        note.grid(row=4, column=0, sticky="w", pady=(12, 12))

        preview_box = ttk.LabelFrame(outer, text="Befehlsvorschau", padding=12)
        preview_box.grid(row=5, column=0, sticky="nsew")
        outer.grid_rowconfigure(5, weight=1)
        preview_box.grid_columnconfigure(0, weight=1)
        preview_box.grid_rowconfigure(0, weight=1)

        self.preview = tk.Text(preview_box, height=6, wrap="word")
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview.configure(state="disabled")

        button_bar = ttk.Frame(outer)
        button_bar.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        button_bar.grid_columnconfigure(0, weight=1)

        ttk.Button(button_bar, text="Speichern", command=self.store_only).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(button_bar, text="Verbinden", command=self.connect).grid(row=0, column=2)

        self.status_var = tk.StringVar(value="Bereit")
        ttk.Label(outer, textvariable=self.status_var, style="Hint.TLabel").grid(row=7, column=0, sticky="w", pady=(12, 0))

        for var in [self.server_var, self.user_var, self.pass_var, self.domain_var]:
            var.trace_add("write", lambda *_: self.update_preview())

    def _load_values(self):
        self.server_var.set(self.config_data.get("server", ""))
        self.user_var.set(self.config_data.get("username", ""))
        self.domain_var.set(self.config_data.get("domain", ""))
        self.clipboard_var.set(bool(self.config_data.get("clipboard", True)))
        self.sound_var.set(bool(self.config_data.get("sound", True)))
        self.dynamic_var.set(bool(self.config_data.get("dynamic_resolution", True)))
        self.fullscreen_var.set(bool(self.config_data.get("fullscreen", False)))
        self.cert_ignore_var.set(bool(self.config_data.get("cert_ignore", True)))

    def current_settings(self):
        return {
            "server": self.server_var.get().strip(),
            "username": self.user_var.get().strip(),
            "domain": self.domain_var.get().strip(),
            "clipboard": self.clipboard_var.get(),
            "sound": self.sound_var.get(),
            "dynamic_resolution": self.dynamic_var.get(),
            "fullscreen": self.fullscreen_var.get(),
            "cert_ignore": self.cert_ignore_var.get(),
        }

    def build_command(self, mask_password=False):
        server = self.server_var.get().strip()
        username = self.user_var.get().strip()
        password = self.pass_var.get()
        domain = self.domain_var.get().strip()

        cmd = ["xfreerdp3"]
        if server:
            cmd.append(f"/v:{server}")
        if username:
            cmd.append(f"/u:{username}")
        if password:
            cmd.append(f"/p:{'********' if mask_password else password}")
        if domain:
            cmd.append(f"/d:{domain}")
        if self.fullscreen_var.get():
            cmd.append("/f")
        if self.sound_var.get():
            cmd.append("/sound")
        if self.dynamic_var.get():
            cmd.append("+dynamic-resolution")
        if self.clipboard_var.get():
            cmd.append("+clipboard")
        if self.cert_ignore_var.get():
            cmd.append("/cert:ignore")
        return cmd

    def update_preview(self):
        cmd = " ".join(self.build_command(mask_password=True))
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", cmd)
        self.preview.configure(state="disabled")

    def store_only(self):
        save_config(self.current_settings())
        self.status_var.set(f"Gespeichert in {CONFIG_FILE}")

    def connect(self):
        if shutil.which("xfreerdp3") is None:
            messagebox.showerror("xfreerdp3 fehlt", "xfreerdp3 wurde nicht gefunden. Bitte installiere zuerst das FreeRDP-Paket.")
            return

        if not self.server_var.get().strip():
            messagebox.showwarning("Fehlender Host", "Bitte Hostname oder IP eintragen.")
            return

        if not self.user_var.get().strip():
            messagebox.showwarning("Fehlender Benutzer", "Bitte Benutzername eintragen.")
            return

        save_config(self.current_settings())
        cmd = self.build_command(mask_password=False)
        try:
            self.proc = subprocess.Popen(cmd)
            self.status_var.set("Verbindung gestartet")
        except Exception as exc:
            messagebox.showerror("Start fehlgeschlagen", str(exc))


def main():
    if not has_graphical_session():
        cli_error(
            "Keine grafische Sitzung erkannt. Starte das Programm bitte direkt aus KDE/Plasma, dem Anwendungsmenü oder einem Terminal innerhalb deiner Desktop-Sitzung.\n"
            "Hintergrund: Für Tkinter muss DISPLAY oder WAYLAND_DISPLAY gesetzt sein."
        )
        sys.exit(1)

    try:
        App().mainloop()
    except tk.TclError as exc:
        cli_error(
            "Die GUI konnte nicht gestartet werden. Wahrscheinlich fehlt der Zugriff auf die grafische Sitzung.\n"
            f"Originalfehler: {exc}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
