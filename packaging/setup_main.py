"""Budgetier-Windows.exe: one file that installs or updates Budgetier for this PC.

    Budgetier-Windows.exe            shows the install window
    Budgetier-Windows.exe --silent   installs with no window; exit code 0 means success
    Budgetier-Windows.exe --update   what the app runs to update itself: waits for it to
                                     close, keeps your shortcuts, then opens it again
        --dir FOLDER  --no-desktop  --no-start-menu

Windows asks for admin rights when it starts, because the program goes in Program Files
and is registered for the whole PC. Only the program folder is replaced. Your data lives
in %LOCALAPPDATA%\\Budgetier and is never touched, so updating can't lose your history.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Budgetier"
NO_WINDOW = subprocess.CREATE_NO_WINDOW
CLOSE_WAIT = 30  # seconds for the app to finish closing after it starts an update
PROGRAM_FILES = {"budgetier.exe", "uninstall.exe", "uninstall.ps1", "_internal"}  # lowercase
log = logging.getLogger("budgetier.setup")


def start_log() -> None:
    """Setup has no console, so this is what explains a problem after the fact."""
    path = Path(os.environ.get("TEMP", ".")) / "BudgetierSetup.log"
    logging.basicConfig(filename=path, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("started: %s", " ".join(sys.argv))


class SetupError(Exception):
    """A problem to show the person, in words they can act on."""


@dataclass
class Options:
    target: Path
    desktop: bool = True
    start_menu: bool = True


def resource(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / name


def read_version() -> str:
    """From the VERSION file: bundled in the installer, at the project root otherwise."""
    folder = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return (folder / "VERSION").read_text(encoding="utf-8-sig").strip()  # Notepad may add a BOM


VERSION = read_version()


def default_target() -> Path:
    return Path(os.environ.get("ProgramW6432") or os.environ["ProgramFiles"]) / "Budgetier"


def app_is_running() -> bool:
    found = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Budgetier.exe", "/NH"],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
    return "Budgetier.exe" in found.stdout


def _installed_value(name: str) -> str | None:
    """HKCU covers installs made by versions before 1.2, which were per user."""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, UNINSTALL_KEY) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            continue
    return None


def installed_version() -> str | None:
    return _installed_value("DisplayVersion")


def installed_location() -> Path | None:
    location = _installed_value("InstallLocation")
    return Path(location) if location else None


def resolve_target(chosen: str | Path) -> Path:
    """Where to install, made safe. Installing replaces the whole folder, so a folder
    that isn't already Budgetier's gets a Budgetier folder of its own inside it."""
    text = str(chosen).strip().strip('"')
    if not text:
        raise SetupError("Choose a folder to install in.")
    path = Path(os.path.expandvars(text))
    if not path.is_absolute():
        raise SetupError("Choose a full folder path, like C:\\Apps.")
    if path.name.lower() != "budgetier":
        path = path / "Budgetier"
    if path.exists() and any(p.name.lower() not in PROGRAM_FILES for p in path.iterdir()):
        raise SetupError(f"{path} already has other files in it. Choose a different folder.")
    return path


def check_writable(target: Path) -> None:
    # A real write, not tempfile: on Windows it retries forever in a folder it can't use.
    probe_from = next((p for p in (target, *target.parents) if p.exists()), None)
    try:
        if probe_from is None:
            raise OSError
        probe = probe_from / f".budgetier-setup-{os.getpid()}"
        probe.touch()
        probe.unlink()
    except OSError as e:
        raise SetupError(f"Budgetier can't write to {probe_from or target}. "
                         "Choose a different folder.") from e


def unpack(payload: Path, target: Path, progress=lambda share: None) -> None:
    """Unpack beside the old copy and swap at the end, so a failure at any point
    leaves whatever was installed still working."""
    fresh = target.with_name(target.name + ".new")
    old = target.with_name(target.name + ".old")
    shutil.rmtree(fresh, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(payload) as archive:
            names = archive.infolist()
            for n, item in enumerate(names, 1):
                archive.extract(item, fresh)
                progress(n / len(names))
        if not (fresh / "Budgetier.exe").exists():
            raise SetupError("This installer is damaged. Build or download it again.")
        if target.exists():
            target.rename(old)
        try:
            fresh.rename(target)
        except OSError:
            if old.exists():
                old.rename(target)
            raise
    except zipfile.BadZipFile as e:
        raise SetupError("This installer is damaged. Build or download it again.") from e
    finally:
        shutil.rmtree(fresh, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


def remove_moved_install(previous: Path | None, target: Path) -> None:
    """After installing somewhere new, clear the old copy, but only if it's really ours."""
    if previous and previous != target and (previous / "Budgetier.exe").exists():
        log.info("removing old copy at %s", previous)
        shutil.rmtree(previous, onexc=lambda _f, path, e: log.warning("couldn't remove %s: %s", path, e))


def _shell_folders() -> tuple[Path, Path, Path, Path]:
    """The all-users desktop and Start menu, then this user's, where 1.1 put shortcuts."""
    names = ("CommonDesktopDirectory", "CommonPrograms", "Desktop", "Programs")
    script = "; ".join(f"[Environment]::GetFolderPath('{n}')" for n in names)
    found = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           check=True, capture_output=True, text=True, creationflags=NO_WINDOW)
    common_desktop, common_programs, desktop, programs = found.stdout.split("\n")[:4]
    return (Path(common_desktop.strip()), Path(common_programs.strip()),
            Path(desktop.strip()), Path(programs.strip()))


def shortcut_state() -> tuple[bool, bool]:
    """Which shortcuts exist now, so an update keeps the choices you already made."""
    if not installed_version():
        return True, True
    try:
        common_desktop, common_programs, desktop, programs = _shell_folders()
    except (OSError, subprocess.CalledProcessError):
        return True, True
    return ((common_desktop / "Budgetier.lnk").exists() or (desktop / "Budgetier.lnk").exists(),
            (common_programs / "Budgetier.lnk").exists() or (programs / "Budgetier.lnk").exists())


def set_shortcuts(target: Path, desktop: bool, start_menu: bool) -> None:
    desktop_dir, programs_dir, user_desktop, user_programs = _shell_folders()
    for folder in (user_desktop, user_programs):
        (folder / "Budgetier.lnk").unlink(missing_ok=True)
    wanted = []
    for folder, keep in ((desktop_dir, desktop), (programs_dir, start_menu)):
        link = folder / "Budgetier.lnk"
        if keep:
            wanted.append(str(link))
        else:
            link.unlink(missing_ok=True)
    if not wanted:
        return
    script = """
$s = New-Object -ComObject WScript.Shell
foreach ($path in $env:BUDGETIER_LINKS -split '\\|') {
    $link = $s.CreateShortcut($path)
    $link.TargetPath = Join-Path $env:BUDGETIER_TARGET 'Budgetier.exe'
    $link.WorkingDirectory = $env:BUDGETIER_TARGET
    $link.Description = 'Budgetier'
    $link.Save()
}"""
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                   capture_output=True, creationflags=NO_WINDOW,
                   env={**os.environ, "BUDGETIER_TARGET": str(target), "BUDGETIER_LINKS": "|".join(wanted)})


def register(target: Path) -> None:
    """List the app in Windows' Installed Apps, with its uninstaller."""
    size_kb = sum(p.stat().st_size for p in target.rglob("*") if p.is_file()) // 1024
    remover = target / "uninstall.exe"
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY) as key:
        for name, value in (("DisplayName", "Budgetier"), ("DisplayVersion", VERSION),
                            ("Publisher", "Budgetier"), ("InstallLocation", str(target)),
                            ("DisplayIcon", str(target / "Budgetier.exe")),
                            ("InstallDate", date.today().strftime("%Y%m%d")),
                            ("UninstallString", f'"{remover}"'),
                            ("QuietUninstallString", f'"{remover}" --silent')):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in (("EstimatedSize", size_kb), ("NoModify", 1), ("NoRepair", 1)):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def user_install_location() -> Path | None:
    """Where a version before 1.2 installed for this user, if one is still registered."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return Path(winreg.QueryValueEx(key, "InstallLocation")[0])
    except OSError:
        return None


def forget_user_registration() -> None:
    """Versions before 1.2 registered in HKCU; two entries would show the app twice."""
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        log.info("removed the per-user entry")
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("couldn't remove the per-user entry: %s", e)


def install(options: Options, progress=lambda share: None) -> Path:
    if app_is_running():
        raise SetupError("Budgetier is open. Close it, then try again.")
    target = resolve_target(options.target)
    check_writable(target)
    previous, user_copy = installed_location(), user_install_location()
    log.info("target %s, previous %s, per-user copy %s", target, previous, user_copy)
    try:
        unpack(resource("payload.zip"), target, progress)
        remove_moved_install(previous, target)
        remove_moved_install(user_copy, target)
        set_shortcuts(target, options.desktop, options.start_menu)
        register(target)
        forget_user_registration()
    except (OSError, subprocess.CalledProcessError) as e:
        log.exception("install failed")
        raise SetupError(f"Couldn't finish installing: {e}") from e
    log.info("installed %s", VERSION)
    return target


def uninstall(folder: Path) -> None:
    """Remove the program, its shortcuts and its Installed Apps entry. Your data stays."""
    if not (folder / "Budgetier.exe").exists():
        raise SetupError(f"{folder} isn't a Budgetier install, so nothing was removed.")
    if app_is_running():
        raise SetupError("Budgetier is open. Close it, then try again.")
    log.info("uninstalling %s", folder)
    for shell_folder in _shell_folders():
        (shell_folder / "Budgetier.lnk").unlink(missing_ok=True)
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            winreg.DeleteKey(hive, UNINSTALL_KEY)
        except OSError:
            pass
    remove_program(folder)
    # This program is running from the folder and can't delete itself, so a short-lived
    # command does it. A packaged exe is two processes, and both hold the file open.
    finish_removal(folder, [os.getpid(), os.getppid()])


def remove_program(folder: Path) -> None:
    """Everything except the uninstaller, now, so the app is really gone when we say so."""
    for path in folder.iterdir():
        if path.name.lower() == "uninstall.exe":
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def finish_removal(folder: Path, waiting_for: list[int]) -> subprocess.Popen:
    quoted = str(folder).replace("'", "''")
    ids = ",".join(str(i) for i in waiting_for)
    script = (f"Wait-Process -Id {ids} -ErrorAction SilentlyContinue; "
              f"Remove-Item -LiteralPath '{quoted}' -Recurse -Force")
    return subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            cwd=os.environ.get("SystemRoot"), creationflags=NO_WINDOW)  # DETACHED_PROCESS
    # would make PowerShell exit successfully without doing anything.


def launch(target: Path) -> None:
    # This installer runs as admin. Starting the app through Explorer runs it as the
    # signed-in user instead, so it opens that person's data rather than an admin's.
    subprocess.Popen(["explorer.exe", str(target / "Budgetier.exe")])


def payload_size_mb() -> int:
    with zipfile.ZipFile(resource("payload.zip")) as archive:
        return round(sum(i.file_size for i in archive.infolist()) / 1_048_576)


def window() -> int:
    import tkinter as tk
    from tkinter import filedialog, ttk

    pine, panel, line, paper, gold, soft = "#101a17", "#18231f", "#26312d", "#f4f1e8", "#d6b06a", "#a9b5ae"
    body = ("Segoe UI", 10)
    root = tk.Tk()
    root.title("Budgetier Setup")
    root.configure(bg=pine)
    root.resizable(False, False)
    width, height = 580, 500
    root.geometry(f"{width}x{height}+{(root.winfo_screenwidth() - width) // 2}+{(root.winfo_screenheight() - height) // 2}")
    try:
        root.iconbitmap(resource("Budgetier.ico"))
    except tk.TclError:
        pass

    existing = installed_version()
    action = "Reinstall" if existing == VERSION else "Update" if existing else "Install"
    has_desktop, has_start = shortcut_state()

    heading = tk.StringVar(value={"Install": "Install Budgetier", "Reinstall": "Reinstall Budgetier"}
                           .get(action, "Update Budgetier"))
    message = tk.StringVar(value="Turns your bank and card exports into one clear picture of your money. "
                                 "Everything stays on this computer.")
    tk.Label(root, textvariable=heading, bg=pine, fg=paper, font=("Segoe UI Variable Display", 22, "bold"),
             anchor="w").pack(fill="x", padx=32, pady=(26, 4))
    tk.Label(root, textvariable=message, bg=pine, fg=soft, font=body, anchor="nw", justify="left",
             wraplength=512).pack(fill="x", padx=32)

    facts = tk.Frame(root, bg=panel, highlightthickness=1, highlightbackground=line)
    for label, value in (("Version", VERSION + (f"  (replaces {existing})" if existing and existing != VERSION else "")),
                         ("Disk space", f"About {payload_size_mb()} MB"),
                         ("Installs for", "Everyone on this PC. Each person's data stays private")):
        row = tk.Frame(facts, bg=panel)
        row.pack(fill="x", padx=14, pady=2)
        tk.Label(row, text=label, bg=panel, fg=soft, font=body, width=12, anchor="w").pack(side="left")
        tk.Label(row, text=value, bg=panel, fg=paper, font=body, anchor="w").pack(side="left")

    options = tk.Frame(root, bg=pine)
    location = tk.StringVar(value=str(installed_location() or default_target()))
    desktop = tk.BooleanVar(value=has_desktop)
    start_menu = tk.BooleanVar(value=has_start)
    tk.Label(options, text="Install location", bg=pine, fg=paper, font=(body[0], 10, "bold"), anchor="w").pack(fill="x")
    pick = tk.Frame(options, bg=pine)
    pick.pack(fill="x", pady=(3, 10))
    field = tk.Entry(pick, textvariable=location, bg=panel, fg=paper, insertbackground=paper, relief="flat",
                     font=body, highlightthickness=1, highlightbackground=line, highlightcolor=gold)
    field.pack(side="left", fill="x", expand=True, ipady=6)

    def browse() -> None:
        chosen = filedialog.askdirectory(parent=root, title="Choose where to install Budgetier")
        if chosen:
            path = Path(chosen)
            location.set(str(path if path.name.lower() == "budgetier" else path / "Budgetier"))

    tk.Button(pick, text="Browse", command=browse, relief="flat", bd=0, cursor="hand2", font=body, padx=14,
              bg=line, fg=paper, activebackground="#33403b", activeforeground=paper).pack(side="left", padx=(8, 0), ipady=3)

    tk.Label(options, text="Shortcuts", bg=pine, fg=paper, font=(body[0], 10, "bold"), anchor="w").pack(fill="x")
    for text, variable in (("Add to the Start menu", start_menu), ("Add to the desktop", desktop)):
        tk.Checkbutton(options, text=text, variable=variable, bg=pine, fg=paper, selectcolor=panel, font=body,
                       activebackground=pine, activeforeground=paper, anchor="w", bd=0, highlightthickness=0,
                       cursor="hand2").pack(fill="x", pady=1)
    tk.Label(options, text="Your accounts and transactions are stored separately in your user folder, "
                           "so installing, updating or uninstalling never changes them.",
             bg=pine, fg=soft, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=512).pack(fill="x", pady=(10, 0))

    facts.pack(fill="x", padx=32, pady=(14, 14), ipady=5)
    options.pack(fill="x", padx=32)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Gold.Horizontal.TProgressbar", troughcolor=line, background=gold,
                    bordercolor=pine, lightcolor=gold, darkcolor=gold)
    share = tk.DoubleVar()
    bar = ttk.Progressbar(root, variable=share, maximum=1.0, style="Gold.Horizontal.TProgressbar")

    buttons = tk.Frame(root, bg=pine)
    buttons.pack(side="bottom", fill="x", padx=32, pady=(0, 24))

    def button(text, command, main=False):
        return tk.Button(buttons, text=text, command=command, relief="flat", bd=0, cursor="hand2",
                         font=("Segoe UI", 10, "bold" if main else "normal"), padx=18, pady=7,
                         bg=gold if main else line, fg=pine if main else paper,
                         activebackground="#e2c07e" if main else "#33403b",
                         activeforeground=pine if main else paper)

    main_button = button(action, lambda: start(), main=True)
    side_button = button("Cancel", root.destroy)
    main_button.pack(side="right")
    side_button.pack(side="right", padx=(0, 8))
    root.bind("<Return>", lambda event: main_button.invoke())
    installed: dict[str, Path] = {}

    def finished(target: Path) -> None:
        installed["target"] = target
        bar.pack_forget()
        facts.pack_forget()
        heading.set("Budgetier is ready")
        places = [name for name, on in (("the Start menu", start_menu.get()), ("your desktop", desktop.get())) if on]
        where = f"Find it in {' and '.join(places)}." if places else f"It's installed in {target}."
        message.set(f"Version {VERSION} is installed. {where}\n\nWhen it opens, Budgetier walks you through adding "
                    "your first bank files and shows which banks work.")
        side_button.config(text="Close", state="normal", command=root.destroy)
        main_button.config(text="Open Budgetier", state="normal", command=open_app)

    def failed(text: str) -> None:
        bar.pack_forget()
        options.pack(fill="x", padx=32)
        heading.set("That didn't work")
        message.set(text)
        main_button.config(text="Try again", state="normal")
        side_button.config(state="normal")

    def open_app() -> None:
        launch(installed["target"])
        root.destroy()

    def start() -> None:
        main_button.config(state="disabled")
        side_button.config(state="disabled")
        options.pack_forget()
        heading.set("Installing...")
        message.set(f"Copying files to {location.get()}")
        share.set(0)
        bar.pack(fill="x", padx=32, pady=(4, 0))
        chosen = Options(Path(location.get()), desktop.get(), start_menu.get())

        def work() -> None:
            try:
                target = install(chosen, lambda s: root.after(0, share.set, s))
            except SetupError as e:
                root.after(0, failed, str(e))
            else:
                root.after(0, finished, target)

        threading.Thread(target=work, daemon=True).start()

    root.mainloop()
    return 0


def update() -> int:
    """The app is closing itself, so give it a moment. Whatever happens, it opens again:
    a failed update leaves the installed copy in use, and the person should know why."""
    deadline = time.monotonic() + CLOSE_WAIT
    while app_is_running() and time.monotonic() < deadline:
        time.sleep(.5)
    target, code = installed_location() or default_target(), 0
    try:
        target = install(Options(target, *shortcut_state()))
    except SetupError as e:
        log.error("update failed: %s", e)
        ctypes.windll.user32.MessageBoxW(None, f"Budgetier couldn't update. {e}", "Budgetier", 0x10)
        code = 1
    if (target / "Budgetier.exe").exists():
        launch(target)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--dir")
    parser.add_argument("--no-desktop", action="store_true")
    parser.add_argument("--no-start-menu", action="store_true")
    args, _ = parser.parse_known_args()
    start_log()
    if args.update:
        return update()
    if not args.silent:
        return window()
    try:
        install(Options(Path(args.dir) if args.dir else installed_location() or default_target(),
                        not args.no_desktop, not args.no_start_menu))
    except SetupError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
