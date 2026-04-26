#!/usr/bin/env python3
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

APP_NAME = "FreeRDP GUI"
CONFIG_DIR = Path.home() / ".config" / "xfreerdp-gui"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROFILES_DIR = CONFIG_DIR / "profiles"
LAUNCHERS_DIR = Path.home() / ".local" / "share" / "xfreerdp-gui" / "launchers"

DEFAULTS = {
    "server": "",
    "username": "",
    "password": "",
    "domain": "",
    "profile_name": "",
    "clipboard": True,
    "sound": True,
    "dynamic_resolution": True,
    "fullscreen": False,
    "cert_ignore": True,
    "save_password_in_profile": True,
    "save_password_in_launcher": True,
}


def load_json(path, fallback):
    data = dict(fallback)
    try:
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
    except Exception:
        pass
    return data


def save_json(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")


def has_graphical_session():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def cli_error(message):
    print(message, file=sys.stderr)


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9äöüß._ -]+", "", value)
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"[\s/]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value or "rdp-profil"


def get_desktop_dir():
    cfg = Path.home() / ".config" / "user-dirs.dirs"
    if cfg.exists():
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("XDG_DESKTOP_DIR="):
                    raw = line.split("=", 1)[1].strip().strip('"')
                    raw = raw.replace("$HOME", str(Path.home()))
                    return Path(raw).expanduser()
        except Exception:
            pass
    return Path.home() / "Desktop"


def list_profiles():
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("760x700")
        self.minsize(680, 560)
        self.grid_columnconfigure(0, weight=1)
        self.config_data = load_json(CONFIG_FILE, DEFAULTS)
        self.proc = None
        self._build_style()
        self._build_ui()
        self._load_values(self.config_data)
        self.refresh_profiles()
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
        outer.grid_rowconfigure(5, weight=1)

        ttk.Label(outer, text="FreeRDP GUI", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="GUI für xfreerdp3 mit Verbindungsprofilen und Desktop-Startern im .desktop-Stil.",
            style="Hint.TLabel",
            wraplength=720,
        ).grid(row=1, column=0, sticky="w", pady=(4, 16))

        profile_box = ttk.LabelFrame(outer, text="Profile", padding=12)
        profile_box.grid(row=2, column=0, sticky="ew")
        for c in range(4):
            profile_box.grid_columnconfigure(c, weight=1 if c == 1 else 0)

        self.profile_select_var = tk.StringVar()
        self.profile_name_var = tk.StringVar()

        ttk.Label(profile_box, text="Gespeichertes Profil").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        self.profile_combo = ttk.Combobox(profile_box, textvariable=self.profile_select_var, state="readonly")
        self.profile_combo.grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(profile_box, text="Laden", command=self.load_selected_profile).grid(row=0, column=2, padx=8, pady=6)
        ttk.Button(profile_box, text="Liste neu laden", command=self.refresh_profiles).grid(row=0, column=3, pady=6)

        ttk.Label(profile_box, text="Profilname").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(profile_box, textvariable=self.profile_name_var).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Button(profile_box, text="Profil speichern", command=self.save_profile).grid(row=1, column=2, padx=8, pady=6)
        ttk.Button(profile_box, text="Desktop-Starter anlegen", command=self.create_desktop_shortcut).grid(row=1, column=3, pady=6)

        form = ttk.LabelFrame(outer, text="Verbindung", padding=12)
        form.grid(row=3, column=0, sticky="ew", pady=(14, 0))
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
        self.save_password_profile_var = tk.BooleanVar()
        self.save_password_launcher_var = tk.BooleanVar()

        fields = [
            ("Hostname / IP", self.server_var, ""),
            ("Benutzername", self.user_var, ""),
            ("Passwort", self.pass_var, "*"),
            ("Domäne (optional)", self.domain_var, ""),
        ]
        for idx, (label, var, show) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=idx, column=0, sticky="w", pady=6, padx=(0, 12))
            ttk.Entry(form, textvariable=var, show=show).grid(row=idx, column=1, sticky="ew", pady=6)

        opts = ttk.LabelFrame(outer, text="Optionen", padding=12)
        opts.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        opts.grid_columnconfigure(0, weight=1)
        opts.grid_columnconfigure(1, weight=1)

        ttk.Checkbutton(opts, text="Zwischenablage aktivieren", variable=self.clipboard_var, command=self.update_preview).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Ton weiterleiten", variable=self.sound_var, command=self.update_preview).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Dynamische Auflösung", variable=self.dynamic_var, command=self.update_preview).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Vollbild beim Start", variable=self.fullscreen_var, command=self.update_preview).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Zertifikat ignorieren", variable=self.cert_ignore_var, command=self.update_preview).grid(row=2, column=0, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Passwort im Profil speichern", variable=self.save_password_profile_var).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="Passwort im Desktop-Starter speichern", variable=self.save_password_launcher_var).grid(row=3, column=0, sticky="w", pady=4)

        ttk.Label(
            outer,
            text="Achtung: Passwort in Profilen oder Desktop-Startern wird im Klartext gespeichert.",
            style="Hint.TLabel",
            wraplength=720,
        ).grid(row=5, column=0, sticky="nw", pady=(12, 8))

        preview_box = ttk.LabelFrame(outer, text="Befehlsvorschau", padding=12)
        preview_box.grid(row=6, column=0, sticky="nsew")
        preview_box.grid_columnconfigure(0, weight=1)
        preview_box.grid_rowconfigure(0, weight=1)
        outer.grid_rowconfigure(6, weight=1)

        self.preview = tk.Text(preview_box, height=7, wrap="word")
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview.configure(state="disabled")

        button_bar = ttk.Frame(outer)
        button_bar.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        button_bar.grid_columnconfigure(0, weight=1)
        ttk.Button(button_bar, text="Einstellungen speichern", command=self.store_main_config).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(button_bar, text="Verbinden", command=self.connect).grid(row=0, column=2)

        self.status_var = tk.StringVar(value="Bereit")
        ttk.Label(outer, textvariable=self.status_var, style="Hint.TLabel").grid(row=8, column=0, sticky="w", pady=(12, 0))

        for var in [self.server_var, self.user_var, self.pass_var, self.domain_var, self.profile_name_var]:
            var.trace_add("write", lambda *_: self.update_preview())

    def _values_dict(self):
        return {
            "server": self.server_var.get().strip(),
            "username": self.user_var.get().strip(),
            "password": self.pass_var.get(),
            "domain": self.domain_var.get().strip(),
            "profile_name": self.profile_name_var.get().strip(),
            "clipboard": self.clipboard_var.get(),
            "sound": self.sound_var.get(),
            "dynamic_resolution": self.dynamic_var.get(),
            "fullscreen": self.fullscreen_var.get(),
            "cert_ignore": self.cert_ignore_var.get(),
            "save_password_in_profile": self.save_password_profile_var.get(),
            "save_password_in_launcher": self.save_password_launcher_var.get(),
        }

    def _load_values(self, values):
        merged = dict(DEFAULTS)
        merged.update(values)
        self.server_var.set(merged.get("server", ""))
        self.user_var.set(merged.get("username", ""))
        self.pass_var.set(merged.get("password", ""))
        self.domain_var.set(merged.get("domain", ""))
        self.profile_name_var.set(merged.get("profile_name", ""))
        self.clipboard_var.set(bool(merged.get("clipboard", True)))
        self.sound_var.set(bool(merged.get("sound", True)))
        self.dynamic_var.set(bool(merged.get("dynamic_resolution", True)))
        self.fullscreen_var.set(bool(merged.get("fullscreen", False)))
        self.cert_ignore_var.set(bool(merged.get("cert_ignore", True)))
        self.save_password_profile_var.set(bool(merged.get("save_password_in_profile", True)))
        self.save_password_launcher_var.set(bool(merged.get("save_password_in_launcher", True)))

    def store_main_config(self):
        save_json(CONFIG_FILE, self._values_dict())
        self.status_var.set(f"Einstellungen gespeichert in {CONFIG_FILE}")

    def build_command(self, mask_password=False, include_password=True):
        data = self._values_dict()
        cmd = ["xfreerdp3"]
        if data["server"]:
            cmd.append(f"/v:{data['server']}")
        if data["username"]:
            cmd.append(f"/u:{data['username']}")
        if include_password and data["password"]:
            pw = "********" if mask_password else data["password"]
            cmd.append(f"/p:{pw}")
        if data["domain"]:
            cmd.append(f"/d:{data['domain']}")
        if data["fullscreen"]:
            cmd.append("/f")
        if data["sound"]:
            cmd.append("/sound")
        if data["dynamic_resolution"]:
            cmd.append("+dynamic-resolution")
        if data["clipboard"]:
            cmd.append("+clipboard")
        if data["cert_ignore"]:
            cmd.append("/cert:ignore")
        return cmd

    def update_preview(self):
        cmd = " ".join(self.build_command(mask_password=True, include_password=True))
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", cmd)
        self.preview.configure(state="disabled")

    def refresh_profiles(self):
        names = list_profiles()
        self.profile_combo["values"] = names
        if names and self.profile_select_var.get() not in names:
            self.profile_select_var.set(names[0])
        self.status_var.set(f"{len(names)} Profil(e) gefunden")

    def _profile_path(self, name):
        return PROFILES_DIR / f"{slugify(name)}.json"

    def save_profile(self):
        name = self.profile_name_var.get().strip() or self.server_var.get().strip() or "rdp-profil"
        values = self._values_dict()
        values["profile_name"] = name
        if not self.save_password_profile_var.get():
            values["password"] = ""
        path = self._profile_path(name)
        save_json(path, values)
        self.refresh_profiles()
        self.profile_select_var.set(path.stem)
        self.status_var.set(f"Profil gespeichert: {path}")

    def load_selected_profile(self):
        name = self.profile_select_var.get().strip()
        if not name:
            messagebox.showinfo("Kein Profil", "Bitte zuerst ein gespeichertes Profil auswählen.")
            return
        path = self._profile_path(name)
        if not path.exists():
            messagebox.showerror("Profil fehlt", f"Profil wurde nicht gefunden: {path}")
            return
        self._load_values(load_json(path, DEFAULTS))
        self.update_preview()
        self.status_var.set(f"Profil geladen: {path}")

    def _write_launcher_script(self, profile_name):
        include_password = self.save_password_launcher_var.get()
        cmd = self.build_command(mask_password=False, include_password=include_password)
        if not include_password:
            cmd = [arg for arg in cmd if not arg.startswith("/p:")]
        safe_name = slugify(profile_name)
        script_path = LAUNCHERS_DIR / f"{safe_name}.sh"
        quoted = " ".join(shlex.quote(arg) for arg in cmd)
        script = "#!/bin/sh\nexec " + quoted + "\n"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(0o700)
        return script_path, safe_name

    def create_desktop_shortcut(self):
        if not self.server_var.get().strip() or not self.user_var.get().strip():
            messagebox.showwarning("Fehlende Daten", "Bitte mindestens Hostname/IP und Benutzername eintragen.")
            return
        profile_name = self.profile_name_var.get().strip() or self.server_var.get().strip() or "rdp-profil"
        if self.save_password_launcher_var.get() and not self.pass_var.get():
            if not messagebox.askyesno("Ohne Passwort", "Im Starter soll ein Passwort gespeichert werden, aber das Passwortfeld ist leer. Starter trotzdem erstellen?"):
                return
        script_path, safe_name = self._write_launcher_script(profile_name)
        desktop_dir = get_desktop_dir()
        desktop_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = desktop_dir / f"{safe_name}.desktop"
        desktop_content = f"""[Desktop Entry]\nType=Application\nVersion=1.0\nName=RDP {profile_name}\nComment=Startet xfreerdp3 für {self.server_var.get().strip()}\nExec={script_path}\nIcon=preferences-system-network\nTerminal=false\nCategories=Network;RemoteAccess;\nStartupNotify=true\n"""
        desktop_file.write_text(desktop_content, encoding="utf-8")
        desktop_file.chmod(0o755)
        self.status_var.set(f"Desktop-Starter erstellt: {desktop_file}")
        messagebox.showinfo(
            "Desktop-Starter erstellt",
            f"Starter angelegt:\n{desktop_file}\n\nStartskript:\n{script_path}\n\nBei manchen Plasma-Setups musst du den Starter beim ersten Start einmal als vertrauenswürdig bestätigen.",
        )

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
        save_json(CONFIG_FILE, self._values_dict())
        try:
            self.proc = subprocess.Popen(self.build_command(mask_password=False, include_password=True))
            self.status_var.set("Verbindung gestartet")
        except Exception as exc:
            messagebox.showerror("Start fehlgeschlagen", str(exc))


def main():
    if not has_graphical_session():
        cli_error(
            "Keine grafische Sitzung erkannt. Starte das Programm bitte direkt aus KDE/Plasma, dem Anwendungsmenü oder einem Terminal innerhalb deiner Desktop-Sitzung.\n"
            "Für Tkinter muss DISPLAY oder WAYLAND_DISPLAY gesetzt sein."
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
