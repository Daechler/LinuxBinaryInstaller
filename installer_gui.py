import os
import sys
import shutil
import stat
from dataclasses import dataclass
import shlex

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def expanduser(path: str) -> str:
    return os.path.expanduser(path)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def sanitize_filename(name: str) -> str:
    base = os.path.splitext(os.path.basename(name))[0]
    safe = []
    for ch in base:
        if ch.isalnum() or ch in ("-", "_", "."):
            safe.append(ch)
        elif ch in (" ", "/", "\\"):
            safe.append("-")
    s = "".join(safe).strip("-._")
    return s or "app"


def make_executable(path: str) -> None:
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_file(path: str, content: str, mode: int = 0o644) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, mode)


def read_desktop_fields(path: str) -> dict:
    fields = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    fields[k.strip()] = v.strip()
    except Exception:
        pass
    return fields


def build_desktop_content(
    name: str,
    exec_path: str,
    icon_path: str | None,
    terminal: bool = False,
    categories: str = "Utility;",
    try_exec: str | None = None,
) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Exec={exec_path}",
        *( [f"TryExec={try_exec}"] if try_exec else [] ),
        f"Terminal={'true' if terminal else 'false'}",
        "StartupNotify=true",
        f"Categories={categories}",
    ]
    if icon_path:
        lines.append(f"Icon={icon_path}")
    return "\n".join(lines) + "\n"


def quote_if_needed(path: str) -> str:
    if not path:
        return path
    if any(ch.isspace() for ch in path):
        return f'"{path}"'
    return path


def rebuild_exec_with_target(existing_exec: str | None, target_exec: str) -> str:
    """Deprecated for general use; left for compatibility.
    Prefer compute_exec_with_placeholders().
    """
    target_exec = target_exec.strip()
    if not existing_exec:
        return target_exec
    try:
        parts = shlex.split(existing_exec, posix=True)
        if not parts:
            return target_exec
        args = parts[1:]
        if args:
            return " ".join([target_exec] + args)
        return target_exec
    except Exception:
        return target_exec


def _read_shebang_tokens(path: str) -> list[str] | None:
    try:
        with open(path, "rb") as f:
            first = f.readline(256)
        if not first.startswith(b"#!"):
            return None
        line = first[2:].strip().decode("utf-8", errors="ignore")
        if not line:
            return None
        return shlex.split(line)
    except Exception:
        return None


def _ext_interpreter(ext: str) -> list[str] | None:
    ext = ext.lower()
    if ext in (".py", ".py3", ".pyw"):
        return ["python3"]
    if ext in (".sh", ".bash"):
        return ["bash"]
    if ext in (".zsh",):
        return ["zsh"]
    return None


def _is_executable(path: str) -> bool:
    try:
        return os.access(path, os.X_OK)
    except Exception:
        return False


def compute_exec_command(target_path: str) -> tuple[str, str | None]:
    """Given a target file, return (Exec string, TryExec program).

    - Honors shebang when present: Exec = "<shebang...> <file>"
    - Falls back to common interpreters by extension for scripts
    - Uses the file directly when executable (incl. AppImage)
    - TryExec is set to the first command in Exec when applicable
    """
    shebang = _read_shebang_tokens(target_path)
    if shebang:
        cmd = " ".join(shebang + [quote_if_needed(target_path)])
        return cmd, (shebang[0] if shebang else None)

    ext = os.path.splitext(target_path)[1]
    interp = _ext_interpreter(ext)
    if interp:
        cmd = " ".join(interp + [quote_if_needed(target_path)])
        return cmd, interp[0]

    # AppImage or generic executable
    if ext.lower() == ".appimage" or _is_executable(target_path):
        return quote_if_needed(target_path), target_path

    # Last resort: attempt to make it executable and run directly
    try:
        make_executable(target_path)
        if _is_executable(target_path):
            return quote_if_needed(target_path), target_path
    except Exception:
        pass

    # Fallback to running with sh
    cmd = "sh " + quote_if_needed(target_path)
    return cmd, "sh"


def _extract_placeholders(existing_exec: str | None) -> list[str]:
    if not existing_exec:
        return []
    try:
        parts = shlex.split(existing_exec, posix=True)
    except Exception:
        parts = existing_exec.split()
    placeholders = []
    for p in parts:
        if "%" in p:
            placeholders.append(p)
    # Deduplicate while preserving order
    seen = set()
    uniq: list[str] = []
    for p in placeholders:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def build_desktop_from_existing(fields: dict, exec_cmd: str, try_exec: str | None, icon_path: str | None, override_terminal: bool | None) -> str:
    out: dict[str, str] = {}
    # Minimal, safe set of fields to avoid brittle entries
    out["Type"] = "Application"
    out["Name"] = fields.get("Name") or os.path.basename(exec_cmd.split()[0])
    # Preserve placeholders from existing Exec, append to our computed command
    placeholders = _extract_placeholders(fields.get("Exec"))
    full_exec = " ".join([exec_cmd] + placeholders) if placeholders else exec_cmd
    out["Exec"] = full_exec
    if try_exec:
        out["TryExec"] = try_exec

    # Terminal: use explicit override when given; otherwise default to false
    if override_terminal is None:
        term_val = fields.get("Terminal", "false")
        out["Terminal"] = "true" if str(term_val).lower() == "true" else "false"
    else:
        out["Terminal"] = "true" if override_terminal else "false"

    # Icon: only use user-provided path; do not inherit arbitrary Icon values
    if icon_path:
        out["Icon"] = icon_path

    # Additional safe fields to preserve when present
    if fields.get("Comment"):
        out["Comment"] = fields.get("Comment")
    if fields.get("GenericName"):
        out["GenericName"] = fields.get("GenericName")
    if fields.get("Keywords"):
        out["Keywords"] = fields.get("Keywords")
    if fields.get("StartupWMClass"):
        out["StartupWMClass"] = fields.get("StartupWMClass")

    # Safe defaults, with gentle preservation when present
    out["StartupNotify"] = fields.get("StartupNotify", "true") or "true"
    out["Categories"] = fields.get("Categories") or "Utility;"

    # Serialize in a stable order
    lines = ["[Desktop Entry]"]
    for k in (
        "Type",
        "Name",
        "GenericName",
        "Comment",
        "Exec",
        "TryExec",
        "Icon",
        "Terminal",
        "StartupNotify",
        "Categories",
        "Keywords",
        "StartupWMClass",
    ):
        if k in out and out[k] is not None:
            lines.append(f"{k}={out[k]}")
    return "\n".join(lines) + "\n"


@dataclass
class InstallPlan:
    binary_src: str
    desktop_src: str | None
    icon_src: str | None
    program_name: str
    create_menu: bool
    create_desktop: bool
    run_in_terminal: bool


class InstallerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Linux Binary Installer")
        self.setMinimumWidth(640)
        self.setWindowIcon(QIcon.fromTheme("system-software-install"))

        central = QWidget()
        layout = QVBoxLayout(central)

        layout.addWidget(self._build_select_group())
        layout.addWidget(self._build_options_group())

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.install_btn = QPushButton("Install")
        self.install_btn.clicked.connect(self.on_install)
        btn_row.addWidget(self.install_btn)
        layout.addLayout(btn_row)

        self.setCentralWidget(central)

    def _build_select_group(self) -> QGroupBox:
        grp = QGroupBox("Select Files")
        grid = QGridLayout(grp)

        # Binary selector
        grid.addWidget(QLabel("Binary file"), 0, 0)
        self.binary_edit = QLineEdit()
        self.binary_edit.setPlaceholderText("/path/to/program, AppImage, or script")
        self.binary_edit.textChanged.connect(self._maybe_autofill_name)
        grid.addWidget(self.binary_edit, 0, 1)
        btn_bin = QPushButton("Browse…")
        btn_bin.clicked.connect(self._pick_binary)
        grid.addWidget(btn_bin, 0, 2)

        # Desktop file (optional)
        grid.addWidget(QLabel("Desktop file (optional)"), 1, 0)
        self.desktop_edit = QLineEdit()
        self.desktop_edit.setPlaceholderText("/path/to/app.desktop (optional)")
        self.desktop_edit.textChanged.connect(self._maybe_prefill_from_desktop)
        grid.addWidget(self.desktop_edit, 1, 1)
        btn_desktop = QPushButton("Browse…")
        btn_desktop.clicked.connect(self._pick_desktop)
        grid.addWidget(btn_desktop, 1, 2)

        # Program name
        grid.addWidget(QLabel("Program name"), 2, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name used for binary and shortcuts")
        grid.addWidget(self.name_edit, 2, 1, 1, 2)

        # Icon (optional)
        grid.addWidget(QLabel("Icon (optional)"), 3, 0)
        self.icon_edit = QLineEdit()
        self.icon_edit.setPlaceholderText("/path/to/icon.png/svg/xpm (optional)")
        grid.addWidget(self.icon_edit, 3, 1)
        btn_icon = QPushButton("Browse…")
        btn_icon.clicked.connect(self._pick_icon)
        grid.addWidget(btn_icon, 3, 2)

        return grp

    def _build_options_group(self) -> QGroupBox:
        grp = QGroupBox("Options")
        v = QVBoxLayout(grp)
        self.chk_menu = QCheckBox("Create Start Menu entry (~/.local/share/applications)")
        self.chk_menu.setChecked(True)
        self.chk_desktop = QCheckBox("Create Desktop shortcut (~/%s)" % os.path.join("Desktop"))
        self.chk_terminal = QCheckBox("Run in terminal")
        v.addWidget(self.chk_menu)
        v.addWidget(self.chk_desktop)
        v.addWidget(self.chk_terminal)
        return grp

    # File pickers
    def _pick_binary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Binary", os.path.expanduser("~"))
        if path:
            self.binary_edit.setText(path)

    def _pick_desktop(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select .desktop file", os.path.expanduser("~"), "Desktop Files (*.desktop)")
        if path:
            self.desktop_edit.setText(path)

    def _pick_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select icon",
            os.path.expanduser("~"),
            "Images (*.png *.svg *.xpm *.ico *.jpg *.jpeg)"
        )
        if path:
            self.icon_edit.setText(path)

    # Autofill helpers
    def _maybe_autofill_name(self) -> None:
        if not self.name_edit.text().strip():
            text = self.binary_edit.text().strip()
            if text:
                self.name_edit.setText(sanitize_filename(os.path.basename(text)))

    def _maybe_prefill_from_desktop(self) -> None:
        dpath = self.desktop_edit.text().strip()
        if not dpath or not os.path.isfile(dpath):
            return
        fields = read_desktop_fields(dpath)
        if not self.name_edit.text().strip():
            name = fields.get("Name")
            if name:
                self.name_edit.setText(sanitize_filename(name))
        if not self.icon_edit.text().strip():
            icon = fields.get("Icon")
            if icon and os.path.isabs(icon) and os.path.exists(icon):
                self.icon_edit.setText(icon)

    # Install logic
    def on_install(self) -> None:
        plan = self._gather_plan()
        if not plan:
            return
        try:
            self._perform_install(plan)
        except Exception as e:
            QMessageBox.critical(self, "Install failed", f"An error occurred:\n{e}")
            return
        QMessageBox.information(self, "Success", "Installation complete.")

    def _gather_plan(self) -> InstallPlan | None:
        binary_src = self.binary_edit.text().strip()
        if not binary_src:
            QMessageBox.warning(self, "Missing binary", "Please select a binary to install.")
            return None
        if not os.path.isfile(binary_src):
            QMessageBox.warning(self, "Invalid binary", "Binary path does not exist.")
            return None

        desktop_src = self.desktop_edit.text().strip() or None
        if desktop_src and not os.path.isfile(desktop_src):
            QMessageBox.warning(self, "Invalid desktop file", ".desktop path does not exist.")
            return None

        name = self.name_edit.text().strip() or sanitize_filename(binary_src)
        name = sanitize_filename(name)
        if not name:
            QMessageBox.warning(self, "Invalid name", "Please enter a valid program name.")
            return None

        icon_src = self.icon_edit.text().strip() or None
        if icon_src and not os.path.isfile(icon_src):
            QMessageBox.warning(self, "Invalid icon", "Icon path does not exist.")
            return None

        create_menu = self.chk_menu.isChecked()
        create_desktop = self.chk_desktop.isChecked()
        run_in_terminal = self.chk_terminal.isChecked()

        if not create_menu and not create_desktop and not desktop_src:
            # If no .desktop provided and user doesn't want entries, still ok. We just install the binary.
            pass

        return InstallPlan(
            binary_src=binary_src,
            desktop_src=desktop_src,
            icon_src=icon_src,
            program_name=name,
            create_menu=create_menu,
            create_desktop=create_desktop,
            run_in_terminal=run_in_terminal,
        )

    def _perform_install(self, plan: InstallPlan) -> None:
        home = os.path.expanduser("~")
        apps_dir = os.path.join(home, ".local", "share", "applications")
        desktop_dir = os.path.join(home, "Desktop")

        ensure_dir(apps_dir)
        if plan.create_desktop:
            ensure_dir(desktop_dir)

        # Use the exact paths the user selected
        # Exec/TryExec should reference the chosen binary path
        chosen_bin = plan.binary_src

        # Compute the best Exec command and TryExec for the selected file
        exec_cmd, try_exec = compute_exec_command(chosen_bin)

        # Best effort: ensure selected file is executable when appropriate (e.g., AppImage)
        try:
            if os.path.splitext(chosen_bin)[1].lower() == ".appimage" and not _is_executable(chosen_bin):
                make_executable(chosen_bin)
        except Exception:
            pass

        # Icon: prefer the explicitly selected icon path; otherwise preserve any from provided desktop file
        icon_target_path = plan.icon_src if plan.icon_src else None

        # Desktop entry handling
        desktop_content = None
        if plan.desktop_src:
            fields = read_desktop_fields(plan.desktop_src)
            desktop_content = build_desktop_from_existing(
                fields=fields,
                exec_cmd=exec_cmd,
                try_exec=try_exec,
                icon_path=icon_target_path,
                override_terminal=plan.run_in_terminal,
            )
        else:
            desktop_content = build_desktop_content(
                name=plan.program_name,
                exec_path=exec_cmd,
                icon_path=icon_target_path,
                terminal=plan.run_in_terminal,
                categories="Utility;",
                try_exec=try_exec,
            )

        # Write entries where requested
        if plan.create_menu or plan.desktop_src:
            # Even if not creating menu explicitly, if user supplied a desktop file, place it in applications.
            apps_file = os.path.join(apps_dir, f"{plan.program_name}.desktop")
            write_file(apps_file, desktop_content, mode=0o644)

        if plan.create_desktop:
            desk_file = os.path.join(desktop_dir, f"{plan.program_name}.desktop")
            write_file(desk_file, desktop_content, mode=0o755)  # executable for desktop launchers


def main() -> int:
    app = QApplication(sys.argv)
    win = InstallerWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
