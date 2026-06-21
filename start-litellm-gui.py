"""PySide6 GUI for LiteLLM Configurator — pick OpenRouter models, manage profiles, launch."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from litellm_utils import (
    CONFIG_DIR, ROLES, YAML_PATH,
    find_litellm, generate_yaml, health_check, kill_process_on_port,
    update_claude_md,
)

SCRIPTS_DIR = Path.home() / ".claude" / "scripts"
PROFILES_DIR = CONFIG_DIR / "profiles"
CLAUDE_MD_PATH = CONFIG_DIR / "CLAUDE.md"

DEFAULT_MODELS = {
    "advisor": "~anthropic/claude-opus-latest",
    "agent": "deepseek/deepseek-v4-flash",
    "subagent": "deepseek/deepseek-v4-flash",
}

PRESETS: list[dict] = [
    {
        "name": "★ Uncompromising",
        "models": {
            "advisor": "anthropic/claude-opus-4.8",
            "agent": "anthropic/claude-opus-4.8-fast",
            "subagent": "google/gemini-3.5-flash",
        },
        "port": 4001,
        "project_dir": "",
        "est_cost": "$16.50/1M in",
    },
    {
        "name": "★ Sweet Spot",
        "models": {
            "advisor": "anthropic/claude-opus-4.8",
            "agent": "~anthropic/claude-sonnet-latest",
            "subagent": "deepseek/deepseek-v4-flash",
        },
        "port": 4001,
        "project_dir": "",
        "est_cost": "$8.09/1M in",
    },
    {
        "name": "★ Cost-Conscious",
        "models": {
            "advisor": "~anthropic/claude-sonnet-latest",
            "agent": "deepseek/deepseek-v4-pro",
            "subagent": "deepseek/deepseek-v4-flash",
        },
        "port": 4001,
        "project_dir": "",
        "est_cost": "$3.53/1M in",
    },
    {
        "name": "★ Speed Demon",
        "models": {
            "advisor": "~anthropic/claude-sonnet-latest",
            "agent": "google/gemini-3.5-flash",
            "subagent": "deepseek/deepseek-v4-flash",
        },
        "port": 4001,
        "project_dir": "",
        "est_cost": "$4.59/1M in",
    },
    {
        "name": "★ Solo Dev",
        "models": {
            "advisor": "qwen/qwen3.7-max",
            "agent": "qwen/qwen3.7-plus",
            "subagent": "deepseek/deepseek-v4-flash",
        },
        "port": 4001,
        "project_dir": "",
        "est_cost": "$1.66/1M in",
    },
]

PALETTE = {
    "bg": "#0f1419",
    "panel": "#171e25",
    "panel_2": "#202a33",
    "panel_3": "#27343f",
    "line": "#384956",
    "text": "#e9f0f5",
    "muted": "#9dacb7",
    "accent": "#41d6c3",
    "accent_2": "#7aa7ff",
    "good": "#80df96",
    "warn": "#ffc86b",
    "bad": "#ff7676",
}

try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
    from PySide6.QtGui import QFont, QFontDatabase, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QFrame,
        QPlainTextEdit,
        QSizePolicy,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    msg = "PySide6 is required. Install with: pip install PySide6"
    print(msg, file=sys.stderr)
    sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────

def _stylesheet() -> str:
    b = PALETTE
    return f"""
        QMainWindow {{ background-color: {b['bg']}; }}
        QWidget {{ background-color: {b['bg']}; color: {b['text']}; font-family: 'Segoe UI', 'Consolas', sans-serif; font-size: 13px; }}
        QWidget#side-panel {{ background-color: {b['panel_2']}; border-right: 1px solid {b['line']}; }}
        QLabel {{ background: transparent; }}
        QLabel#heading {{ font-size: 18px; font-weight: 600; color: {b['text']}; padding: 4px 0; }}
        QLabel#role-label {{ font-size: 14px; font-weight: 600; color: {b['accent']}; padding: 0; background: transparent; }}
        QLabel#model-display {{ font-size: 13px; color: {b['text']}; padding: 6px 10px; background-color: {b['panel_2']}; border: 1px solid {b['line']}; border-radius: 6px; }}
        QLabel#status {{ font-size: 12px; color: {b['muted']}; padding: 2px 0; background: transparent; }}
        QLabel#good {{ color: {b['good']}; background: transparent; }}
        QLabel#bad {{ color: {b['bad']}; background: transparent; }}
        QLabel#warn {{ color: {b['warn']}; background: transparent; }}
        QLabel#accent {{ color: {b['accent']}; background: transparent; }}
        QLabel#cost-label {{ font-size: 13px; color: {b['accent_2']}; padding: 4px 0; background: transparent; }}

        QLineEdit {{ background-color: {b['panel_2']}; color: {b['text']}; border: 1px solid {b['line']}; border-radius: 6px; padding: 6px 10px; font-size: 13px; }}
        QLineEdit:focus {{ border: 1px solid {b['accent']}; }}

        QPushButton {{ background-color: {b['panel_3']}; color: {b['text']}; border: 1px solid {b['line']}; border-radius: 6px; padding: 8px 20px; font-size: 13px; font-weight: 500; }}
        QPushButton:hover {{ background-color: {b['line']}; border-color: {b['accent']}; }}
        QPushButton:pressed {{ background-color: {b['accent']}; color: {b['bg']}; }}
        QPushButton#primary {{ background-color: {b['accent']}; color: {b['bg']}; border: none; font-weight: 600; }}
        QPushButton#primary:hover {{ background-color: #5ce0cf; }}
        QPushButton#danger {{ color: {b['bad']}; border-color: {b['bad']}; }}
        QPushButton#danger:hover {{ background-color: {b['bad']}; color: {b['bg']}; }}
        QPushButton#accent {{ background-color: {b['accent_2']}; color: {b['bg']}; border: none; font-weight: 600; }}
        QPushButton#accent:hover {{ background-color: #94baff; }}
        QPushButton:disabled {{ opacity: 0.4; }}

        QListWidget {{ background-color: {b['panel']}; border: 1px solid {b['line']}; border-radius: 6px; padding: 4px; outline: none; }}
        QListWidget::item {{ padding: 8px 10px; border-radius: 4px; }}
        QListWidget::item:selected {{ background-color: {b['panel_3']}; color: {b['accent']}; }}
        QListWidget::item:hover {{ background-color: {b['panel_2']}; }}
        QListWidget::item:disabled {{ color: {b['muted']}; font-style: italic; font-size: 12px; }}

        QPlainTextEdit {{ background-color: {b['panel']}; color: {b['muted']}; border: 1px solid {b['line']}; border-radius: 6px; padding: 8px; font-family: 'Consolas', monospace; font-size: 12px; }}
        QFrame#card {{ background-color: {b['panel']}; border: 1px solid {b['line']}; border-radius: 8px; padding: 12px; }}
        QFrame#card-accent {{ background-color: {b['panel']}; border: 1px solid {b['accent']}; border-radius: 8px; padding: 12px; }}
        QFrame#profile-card {{ background-color: {b['panel_2']}; border: 1px solid {b['line']}; border-radius: 8px; padding: 8px; }}

        /* ── Scrollbars ─────────────────────── */
        QScrollBar:vertical {{
            background: {b['panel']};
            width: 8px;
            margin: 0;
            border: none;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {b['line']};
            min-height: 30px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {b['muted']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0; border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}

        QScrollBar:horizontal {{
            background: {b['panel']};
            height: 8px;
            margin: 0;
            border: none;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {b['line']};
            min-width: 30px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {b['muted']};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0; border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}
    """


def fetch_models_blocking() -> list[dict]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set.")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    models = data.get("data", [])
    models.sort(key=lambda m: m.get("id", ""))
    return models


def find_model_by_id(models: list[dict], model_id: str) -> dict | None:
    for m in models:
        if m.get("id") == model_id:
            return m
    return None


def _model_supports_vision(model: dict) -> bool:
    modality = model.get("architecture", {}).get("modality", "")
    return "image" in modality.lower()


def profile_path(name: str) -> Path:
    return PROFILES_DIR / f"{name}.json"


def list_profiles() -> list[tuple[str, dict]]:
    if not PROFILES_DIR.exists():
        return []
    result = []
    for f in sorted(PROFILES_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        # ignore non-profile jsons that might have been placed there
        if "models" not in data:
            continue
        result.append((data.get("name", f.stem), data))
    return result


def save_profile(name: str, port: int, models: dict, project_dir: str = "") -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = profile_path(name)
    data = {
        "name": name,
        "port": port,
        "project_dir": project_dir,
        "models": models,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def delete_profile(name: str) -> None:
    path = profile_path(name)
    if path.exists():
        path.unlink()


def open_terminal_with_env(models: dict, port: int, project_dir: str = "") -> None:
    """Open a new terminal window with the proxy env vars set and claude command ready."""
    base_url = f"http://localhost:{port}"

    cd_host = f'cd "{project_dir}"; ' if project_dir else ""
    cd_ps = f'Set-Location "{project_dir}"; ' if project_dir else ""

    # All box lines: inner width = 74, total = 76 (║ + 74 chars + ║)
    B = "══════════════════════════════════════════════════════════════════════════"
    role_lines = []
    for role_key, alias, label in ROLES:
        mid = models.get(role_key, "?")
        mid_display = (mid[:35] + "..") if len(mid) > 37 else mid
        role_lines.append(f"║  {label:10s}  {alias:<18s} →  {mid_display:<37s} ║")
    role_block_ps = "".join(f'Write-Host "{line}"; ' for line in role_lines)
    role_block_bash = "".join(f'echo "{line}"; ' for line in role_lines)

    if platform.system() == "Windows":
        ps_project_line = (f'Write-Host "║  Project: {project_dir:<62} ║"; ') if project_dir else ""
        ps_command = (
            f'{cd_ps}'
            f'$env:ANTHROPIC_BASE_URL="{base_url}"; '
            f'$env:ANTHROPIC_API_KEY="sk-local-fake"; '
            f'Write-Host ""; '
            f'Write-Host "╔{B}╗"; '
            f'Write-Host "║               LiteLLM Proxy — Active Models                              ║"; '
            f'Write-Host "╠{B}╣"; '
            f'Write-Host "║  Port: {port:<65} ║"; '
            f'{ps_project_line}'
            f'{role_block_ps}'
            f'Write-Host "╠{B}╣"; '
            f'Write-Host "║  Proxy running in background — env vars are set.                         ║"; '
            f'Write-Host "╚{B}╝"; '
            f'Write-Host ""; '
            f'Write-Host "Press Enter to launch Claude Code, or type: claude"; '
            f'Read-Host; '
            f'claude'
        )
        subprocess.Popen(
            ["start", "powershell", "-NoExit", "-Command", ps_command],
            shell=True,
        )
    else:
        bash_project_line = (f'echo "║  Project: {project_dir:<62} ║"; ') if project_dir else ""
        bash_script = (
            f'{cd_host}'
            f'export ANTHROPIC_BASE_URL="{base_url}"; '
            f'export ANTHROPIC_API_KEY="sk-local-fake"; '
            f'echo ""; '
            f'echo "╔{B}╗"; '
            f'echo "║               LiteLLM Proxy — Active Models                              ║"; '
            f'echo "╠{B}╣"; '
            f'echo "║  Port: {port:<65} ║"; '
            f'{bash_project_line}'
            f'{role_block_bash}'
            f'echo "╠{B}╣"; '
            f'echo "║  Proxy running in background — env vars are set.                         ║"; '
            f'echo "╚{B}╝"; '
            f'echo ""; '
            f'read -p "Press Enter to launch Claude Code... "; '
            f'claude'
        )
        if platform.system() == "Darwin":
            escaped = bash_script.replace('"', '\\"')
            subprocess.Popen(
                ["osascript", "-e",
                 f'tell application "Terminal" to do script "{escaped}"'],
                shell=False,
            )
        else:
            for term_cmd in [
                ["x-terminal-emulator", "-e", "bash", "-c", bash_script],
                ["gnome-terminal", "--", "bash", "-c", bash_script],
                ["xfce4-terminal", "-e", f"bash -c {bash_script!r}"],
                ["konsole", "-e", "bash", "-c", bash_script],
                ["xterm", "-e", "bash", "-c", bash_script],
            ]:
                try:
                    subprocess.Popen(term_cmd, shell=False)
                    break
                except FileNotFoundError:
                    continue


# ── Model Selector Widget ─────────────────────────────────────────────

class ModelSearchWidget(QFrame):
    """A search + list widget for picking one model for a role."""

    model_selected = Signal(str)  # emits model_id

    def __init__(self, role_label: str, claude_alias: str, models: list[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._all_models = models
        self._role_label = role_label
        self._claude_alias = claude_alias
        self._selected_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header row: role label + alias
        header = QHBoxLayout()
        role_lbl = QLabel(role_label)
        role_lbl.setObjectName("role-label")
        alias_lbl = QLabel(f"(as {claude_alias})")
        alias_lbl.setObjectName("status")
        header.addWidget(role_lbl)
        header.addWidget(alias_lbl)
        header.addStretch()
        layout.addLayout(header)

        # Search bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search models by name or ID…")
        self.search_input.textChanged.connect(self._filter_models)
        layout.addWidget(self.search_input)

        # Model list
        self.model_list = QListWidget()
        self.model_list.setMinimumHeight(80)
        self.model_list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self.model_list, stretch=1)

        # Selected display
        self.selected_display = QLabel("No model selected")
        self.selected_display.setObjectName("model-display")
        layout.addWidget(self.selected_display)

        self.vision_warn = QLabel("  No image support — Claude Code may send screenshots to this role")
        self.vision_warn.setObjectName("bad")
        self.vision_warn.setVisible(False)
        layout.addWidget(self.vision_warn)

        self.latency_label = QLabel("Latency: —")
        self.latency_label.setObjectName("status")
        self.latency_label.setVisible(False)
        layout.addWidget(self.latency_label)

        self._refresh_list()

    def set_models(self, models: list[dict]) -> None:
        self._all_models = models
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.model_list.blockSignals(True)
        self.model_list.clear()

        query = self.search_input.text().strip().lower() if self.search_input.text() else ""
        if query:
            filtered = [
                m for m in self._all_models
                if query in m.get("id", "").lower() or query in m.get("name", "").lower()
            ]
        else:
            filtered = list(self._all_models)

        for m in filtered:
            mid = m.get("id", "?")
            name = m.get("name", "")
            ctx = m.get("context_length", 0)
            ctx_k = f"{ctx // 1000}K" if ctx else "?"
            pricing = m.get("pricing", {})
            p_in = float(pricing.get("prompt", 0) or 0)
            p_out = float(pricing.get("completion", 0) or 0)

            vision_tag = "[img]" if _model_supports_vision(m) else "     "
            p_in_m = p_in * 1_000_000
            p_out_m = p_out * 1_000_000
            display = f"{vision_tag}  {mid}  [{ctx_k}]  ${p_in_m:.2f}/${p_out_m:.2f} per 1M"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, mid)
            self.model_list.addItem(item)

        # Re-select previous selection
        if self._selected_id:
            for i in range(self.model_list.count()):
                if self.model_list.item(i).data(Qt.UserRole) == self._selected_id:
                    self.model_list.setCurrentRow(i)
                    break

        self.model_list.blockSignals(False)

    def _filter_models(self) -> None:
        self._refresh_list()

    def _on_selection_changed(self, current, previous) -> None:
        if current is None:
            return
        mid = current.data(Qt.UserRole)
        self._selected_id = mid
        self.selected_display.setText(mid)
        m = find_model_by_id(self._all_models, mid)
        self.vision_warn.setVisible(m is not None and not _model_supports_vision(m))
        self.model_selected.emit(mid)

    def set_selected(self, model_id: str) -> None:
        self._selected_id = model_id
        self.selected_display.setText(model_id or "No model selected")
        m = find_model_by_id(self._all_models, model_id)
        self.vision_warn.setVisible(m is not None and not _model_supports_vision(m))
        for i in range(self.model_list.count()):
            if self.model_list.item(i).data(Qt.UserRole) == model_id:
                self.model_list.setCurrentRow(i)
                break

    def selected_model(self) -> str | None:
        return self._selected_id

    def supports_vision(self) -> bool:
        if not self._selected_id:
            return True
        m = find_model_by_id(self._all_models, self._selected_id)
        return _model_supports_vision(m) if m else True

    def set_latency(self, ms: float | None, error: str | None = None) -> None:
        self.latency_label.setVisible(ms is not None or error is not None)
        if error:
            self.latency_label.setText("Latency: error")
            obj = "bad"
        elif ms is None:
            self.latency_label.setText("Latency: —")
            obj = "status"
        elif ms < 3000:
            self.latency_label.setText(f"Latency: {ms:.0f} ms")
            obj = "good"
        elif ms < 8000:
            self.latency_label.setText(f"Latency: {ms:.0f} ms")
            obj = "warn"
        else:
            self.latency_label.setText(f"Latency: {ms:.0f} ms")
            obj = "bad"
        self.latency_label.setObjectName(obj)
        self.latency_label.style().unpolish(self.latency_label)
        self.latency_label.style().polish(self.latency_label)


# ── Main Window ───────────────────────────────────────────────────────

class ModelLoader(QObject):
    """Worker object that emits a signal when models are fetched (thread-safe)."""
    finished = Signal(list)  # list of model dicts
    error = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            models = fetch_models_blocking()
            self.finished.emit(models)
        except Exception as exc:
            self.error.emit(str(exc))


class ProxyChecker(QObject):
    """Worker that checks if a proxy is already running on the given port."""
    found = Signal()
    not_found = Signal()

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self._port = port

    @Slot()
    def run(self) -> None:
        if health_check(self._port, timeout=2):
            self.found.emit()
        else:
            self.not_found.emit()


class ProxyKiller(QObject):
    """Worker that kills the proxy on the given port off the GUI thread."""
    done = Signal()

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self._port = port

    @Slot()
    def run(self) -> None:
        kill_process_on_port(self._port)
        self.done.emit()


class ProxyLauncher(QObject):
    """Worker object that starts LiteLLM and emits ready/failed signals."""
    ready = Signal(int)  # PID
    failed = Signal(str)

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self._port = port

    @Slot()
    def run(self) -> None:
        log_path = Path(tempfile.gettempdir()) / "litellm-gui.log"
        pid_path = Path(tempfile.gettempdir()) / "litellm-gui.pid"
        try:
            litellm_cmd = find_litellm() or "litellm"
            with open(log_path, "w") as log_fh:
                proc = subprocess.Popen(
                    [litellm_cmd, "--config", str(YAML_PATH), "--port", str(self._port)],
                    env={**os.environ, "PYTHONIOENCODING": "utf-8",
                         "PYTHONUTF8": "1", "SSLKEYLOGFILE": ""},
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            pid_path.write_text(str(proc.pid))

            if health_check(self._port):
                self.ready.emit(proc.pid)
            else:
                last = log_path.read_text().splitlines()[-5:] if log_path.exists() else []
                err_text = "\n".join(last) if last else "(no log output)"
                self.failed.emit(err_text)
        except Exception as exc:
            self.failed.emit(str(exc))


class LatencyTester(QObject):
    """Worker that sends a minimal request to each role and measures round-trip time."""
    result = Signal(str, float)  # role_key, ms
    error = Signal(str, str)     # role_key, error message

    def __init__(self, port: int, role_key: str, alias: str, parent=None):
        super().__init__(parent)
        self._port = port
        self._role_key = role_key
        self._model = alias if alias != "claude-*" else "claude-ping-test"

    @Slot()
    def run(self) -> None:
        payload = json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://localhost:{self._port}/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer sk-local-fake",
            },
        )
        try:
            start = time.perf_counter()
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.result.emit(self._role_key, elapsed_ms)
        except Exception as exc:
            body = ""
            if hasattr(exc, "read"):
                try:
                    body = exc.read().decode("utf-8", errors="replace")[:400]
                except Exception:
                    pass
            msg = str(exc) + (f" — {body}" if body else "")
            self.error.emit(self._role_key, msg)


class LiteLLMGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self._models: list[dict] = []
        self._profiles: list[tuple[str, dict]] = []
        self._profile_item_is_preset: dict[int, bool] = {}
        self._litellm_pid: int | None = None
        self._proxy_running = False
        self._port = 4001
        self._project_dir: str = ""
        self._current_models: dict[str, str] = dict(DEFAULT_MODELS)

        self._setup_ui()
        self._apply_stylesheet()
        self._populate_profiles()
        self._start_loading_models()
        # Check if a proxy is already running on the default port
        QTimer.singleShot(100, self._check_existing_proxy)

    # ── UI Setup ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setWindowTitle("LiteLLM Configurator")
        self.setMinimumSize(1080, 720)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left Panel: Profiles ──
        left_panel = QWidget()
        left_panel.setFixedWidth(220)
        left_panel.setObjectName("side-panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 16, 12, 16)
        left_layout.setSpacing(8)

        heading = QLabel("Profiles")
        heading.setObjectName("heading")
        left_layout.addWidget(heading)

        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_list, stretch=1)

        save_btn = QPushButton("Save Current")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_profile_dialog)
        left_layout.addWidget(save_btn)

        delete_btn = QPushButton("Delete Profile")
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self._delete_profile)
        left_layout.addWidget(delete_btn)

        root.addWidget(left_panel)

        # ── Right Panel Content ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 16, 20, 16)
        right_layout.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("LiteLLM Model Selector")
        title.setObjectName("heading")
        header_row.addWidget(title)
        header_row.addStretch()

        self.status_indicator = QLabel("●  Disconnected")
        self.status_indicator.setObjectName("bad")
        header_row.addWidget(self.status_indicator)

        self.refresh_btn = QPushButton("⟳ Reload Models")
        self.refresh_btn.setObjectName("accent")
        self.refresh_btn.setFixedWidth(130)
        self.refresh_btn.clicked.connect(self._start_loading_models)
        header_row.addWidget(self.refresh_btn)

        right_layout.addLayout(header_row)

        # Port row
        port_row = QHBoxLayout()
        port_lbl = QLabel("Port:")
        port_lbl.setObjectName("status")
        port_row.addWidget(port_lbl)
        self.port_input = QLineEdit(str(self._port))
        self.port_input.setFixedWidth(80)
        self.port_input.textChanged.connect(self._on_port_changed)
        port_row.addWidget(self.port_input)
        port_row.addStretch()
        right_layout.addLayout(port_row)

        # Project directory row
        proj_row = QHBoxLayout()
        proj_lbl = QLabel("Project Dir:")
        proj_lbl.setObjectName("status")
        proj_row.addWidget(proj_lbl)
        self.project_dir_input = QLineEdit()
        self.project_dir_input.setPlaceholderText("Optional — cd to this dir in the new terminal")
        self.project_dir_input.textChanged.connect(self._on_project_dir_changed)
        proj_row.addWidget(self.project_dir_input, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_project_dir)
        proj_row.addWidget(browse_btn)
        right_layout.addLayout(proj_row)

        # ── Role selector cards ──
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.advisor_widget = ModelSearchWidget("Advisor", "claude-opus-4-7", [])
        self.advisor_widget.model_selected.connect(lambda mid: self._on_model_changed("advisor", mid))
        cards_layout.addWidget(self.advisor_widget)

        self.agent_widget = ModelSearchWidget("Agent", "claude-sonnet-4-6", [])
        self.agent_widget.model_selected.connect(lambda mid: self._on_model_changed("agent", mid))
        cards_layout.addWidget(self.agent_widget)

        self.subagent_widget = ModelSearchWidget("Subagent", "claude-*", [])
        self.subagent_widget.model_selected.connect(lambda mid: self._on_model_changed("subagent", mid))
        cards_layout.addWidget(self.subagent_widget)

        right_layout.addLayout(cards_layout, stretch=1)

        # ── Cost Summary Bar ──
        cost_frame = QFrame()
        cost_frame.setObjectName("card")
        cost_layout = QHBoxLayout(cost_frame)
        cost_layout.setContentsMargins(14, 8, 14, 8)
        self.cost_label = QLabel("Cost: select models to calculate")
        self.cost_label.setObjectName("cost-label")
        cost_layout.addWidget(self.cost_label)
        cost_layout.addStretch()
        right_layout.addWidget(cost_frame)

        # ── Log / Status area ──
        status_lbl = QLabel("Proxy Log")
        status_lbl.setObjectName("role-label")
        right_layout.addWidget(status_lbl)

        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumBlockCount(500)
        self.log_area.setMinimumHeight(100)
        right_layout.addWidget(self.log_area)

        # ── Action buttons ──
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.launch_btn = QPushButton("Launch Proxy")
        self.launch_btn.setObjectName("primary")
        self.launch_btn.clicked.connect(self._launch_proxy)
        action_row.addWidget(self.launch_btn)

        self.kill_btn = QPushButton("Kill Proxy")
        self.kill_btn.setObjectName("danger")
        self.kill_btn.setEnabled(False)
        self.kill_btn.clicked.connect(self._kill_proxy)
        action_row.addWidget(self.kill_btn)

        self.open_terminal_btn = QPushButton("Open Terminal")
        self.open_terminal_btn.setObjectName("accent")
        self.open_terminal_btn.setEnabled(False)
        self.open_terminal_btn.clicked.connect(self._open_terminal)
        action_row.addWidget(self.open_terminal_btn)

        self.latency_btn = QPushButton("Test Latency")
        self.latency_btn.setEnabled(False)
        self.latency_btn.clicked.connect(self._test_latency)
        action_row.addWidget(self.latency_btn)

        action_row.addStretch()
        right_layout.addLayout(action_row)

        root.addWidget(right, stretch=1)

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(_stylesheet())

    # ── Model Loading ─────────────────────────────────────────────────

    def _start_loading_models(self) -> None:
        if getattr(self, "_fetching", False):
            return
        self._log("Fetching models from OpenRouter...")
        self._fetching = True
        self.refresh_btn.setEnabled(False)
        self._show_loading_state(True)

        self._loader = ModelLoader()
        self._loader_thread = threading.Thread(target=self._loader.run, daemon=True)
        self._loader.finished.connect(self._on_models_loaded)
        self._loader.error.connect(self._on_model_error)
        self._loader_thread.start()

    def _show_loading_state(self, loading: bool) -> None:
        for w in [self.advisor_widget, self.agent_widget, self.subagent_widget]:
            w.search_input.setEnabled(not loading)
            w.search_input.setPlaceholderText(
                "Loading models…" if loading else "Search models by name or ID…"
            )
            w.model_list.setEnabled(not loading)
            if loading:
                w.model_list.clear()
                placeholder = QListWidgetItem("Fetching models from OpenRouter…")
                placeholder.setFlags(Qt.NoItemFlags)
                w.model_list.addItem(placeholder)

    def _on_model_error(self, err: str) -> None:
        self._fetching = False
        self.refresh_btn.setEnabled(True)
        self._show_loading_state(False)
        self._log(f"ERROR: {err}")
        self._log("Set OPENROUTER_API_KEY as a system env var and restart.")

    def _on_models_loaded(self, models: list[dict]) -> None:
        self._models = models
        self._fetching = False
        self.refresh_btn.setEnabled(True)
        self._show_loading_state(False)
        self._log(f"Loaded {len(self._models)} models from OpenRouter.")

        # Populate all three widgets
        self.advisor_widget.set_models(self._models)
        self.agent_widget.set_models(self._models)
        self.subagent_widget.set_models(self._models)

        # Set default selections
        self.advisor_widget.set_selected(DEFAULT_MODELS.get("advisor", ""))
        self.agent_widget.set_selected(DEFAULT_MODELS.get("agent", ""))
        self.subagent_widget.set_selected(DEFAULT_MODELS.get("subagent", ""))
        self._update_cost_display()

    def _on_model_changed(self, role_key: str, model_id: str) -> None:
        self._current_models[role_key] = model_id
        self._update_cost_display()

    # ── Cost Calculator ──────────────────────────────────────────────────

    def _lookup_cost(self, model_id: str) -> tuple[str, float | None]:
        m = find_model_by_id(self._models, model_id)
        if m is None:
            return ("—", None)
        p_in = float(m.get("pricing", {}).get("prompt", 0) or 0)
        p_in_m = p_in * 1_000_000
        return (f"${p_in_m:.2f}/1M", p_in_m)

    def _update_cost_display(self) -> None:
        if not self._models:
            self.cost_label.setText("Cost: select models to calculate")
            return
        parts = []
        total = 0.0
        for role_key, widget in [
            ("Advisor", self.advisor_widget),
            ("Agent", self.agent_widget),
            ("Subagent", self.subagent_widget),
        ]:
            mid = widget.selected_model()
            cost_str, cost_val = self._lookup_cost(mid)
            parts.append(f"{role_key}: {cost_str}")
            if cost_val is not None:
                total += cost_val
        total_str = f"${total:.2f}/1M" if total > 0 else "?"
        self.cost_label.setText(
            "  |  ".join(parts) + f"  —  Total: {total_str} input tokens"
        )

    # ── Profile Management ────────────────────────────────────────────

    def _populate_profiles(self) -> None:
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        self._profile_item_is_preset = {}

        row = 0
        # Built-in presets
        for preset in PRESETS:
            item = QListWidgetItem(preset["name"])
            item.setData(Qt.UserRole, preset["name"])
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            self.profile_list.addItem(item)
            self._profile_item_is_preset[row] = True
            row += 1

        # Separator
        sep_item = QListWidgetItem("── Saved ──")
        sep_item.setFlags(Qt.NoItemFlags)
        sep_item.setForeground(self.palette().color(self.palette().ColorRole.WindowText).darker(180))
        sep_item.setData(Qt.UserRole, "__separator__")
        self.profile_list.addItem(sep_item)
        self._profile_item_is_preset[row] = False  # not used but tracked
        row += 1

        # User-saved profiles
        self._profiles = list_profiles()
        for name, data in self._profiles:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.profile_list.addItem(item)
            self._profile_item_is_preset[row] = False
            row += 1

        self.profile_list.blockSignals(False)

    def _on_profile_selected(self, current, previous) -> None:
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if name == "__separator__":
            return

        row = self.profile_list.row(current)
        if self._profile_item_is_preset.get(row, False):
            for preset in PRESETS:
                if preset["name"] == name:
                    self._load_profile_data(preset)
                    break
            return

        for pname, data in self._profiles:
            if pname == name:
                self._load_profile_data(data)
                break

    def _load_profile_data(self, data: dict) -> None:
        models = data.get("models", {})
        port = data.get("port", 4001)
        project_dir = data.get("project_dir", "")
        self._port = port
        self._project_dir = project_dir
        self.port_input.setText(str(port))
        self.project_dir_input.setText(project_dir)
        self._current_models = dict(models)

        self.advisor_widget.set_selected(models.get("advisor", ""))
        self.agent_widget.set_selected(models.get("agent", ""))
        self.subagent_widget.set_selected(models.get("subagent", ""))

        self._log(f"Loaded profile '{data.get('name', '?')}'")
        self._update_cost_display()
        if self._proxy_running:
            self._log("  ⚠  Proxy is still running with the old config — kill and relaunch to apply changes.")
            self._log("  ⚠  Any open terminals need to be reopened to pick up the new settings.")
        # Recheck proxy on the profile's port
        QTimer.singleShot(200, self._check_existing_proxy)

    def _save_profile_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
        if ok and name.strip():
            models = {
                "advisor": self.advisor_widget.selected_model() or "",
                "agent": self.agent_widget.selected_model() or "",
                "subagent": self.subagent_widget.selected_model() or "",
            }
            save_profile(name.strip(), self._port, models, self._project_dir)
            self._populate_profiles()
            self._log(f"Saved profile '{name.strip()}'")

    def _delete_profile(self) -> None:
        current = self.profile_list.currentItem()
        if current is None:
            return
        name = current.data(Qt.UserRole)
        if name == "__separator__":
            return
        row = self.profile_list.row(current)
        if self._profile_item_is_preset.get(row, False):
            QMessageBox.information(self, "Built-in Preset",
                                    "This is a built-in preset and cannot be deleted.\n"
                                    "Save a new profile with your own models instead.")
            return
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            delete_profile(name)
            self._populate_profiles()
            self._log(f"Deleted profile '{name}'")

    # ── Port ──────────────────────────────────────────────────────────

    def _on_port_changed(self, text: str) -> None:
        try:
            self._port = int(text.strip())
        except ValueError:
            pass

    # ── Project Dir ────────────────────────────────────────────────────

    def _on_project_dir_changed(self, text: str) -> None:
        self._project_dir = text.strip()

    def _browse_project_dir(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select Project Directory")
        if dir_path:
            self.project_dir_input.setText(dir_path)

    # ── Detect existing proxy ──────────────────────────────────────────

    def _check_existing_proxy(self) -> None:
        """Check if a LiteLLM proxy is already running on the current port (off-thread)."""
        port = self._port
        self._checker = ProxyChecker(port)
        self._checker_thread = threading.Thread(target=self._checker.run, daemon=True)
        self._checker.found.connect(self._on_proxy_detected)
        self._checker_thread.start()

    def _on_proxy_detected(self) -> None:
        self._proxy_running = True
        self.status_indicator.setText("●  Connected (detected)")
        self.status_indicator.setObjectName("good")
        self.status_indicator.style().unpolish(self.status_indicator)
        self.status_indicator.style().polish(self.status_indicator)
        self.launch_btn.setEnabled(False)
        self.kill_btn.setEnabled(True)
        self.open_terminal_btn.setEnabled(True)
        self.latency_btn.setEnabled(True)
        self._log(f"Detected existing proxy on port {self._port}.")
        self._log("  (Kill it or launch a new one on a different port.)")

    # ── Proxy Launch / Kill ───────────────────────────────────────────

    def _log(self, msg: str) -> None:
        self.log_area.appendPlainText(msg)

    def _launch_proxy(self) -> None:
        if self._proxy_running:
            self._log("Proxy is already running. Kill it first.")
            return

        if not find_litellm():
            self._log("ERROR: litellm not found. Install with: pip install litellm")
            return

        # Gather current selections
        models = {
            "advisor": self.advisor_widget.selected_model() or "",
            "agent": self.agent_widget.selected_model() or "",
            "subagent": self.subagent_widget.selected_model() or "",
        }

        if not models["advisor"] or not models["agent"]:
            self._log("ERROR: Select models for at least Advisor and Agent.")
            return

        vision_support = {
            "advisor": self.advisor_widget.supports_vision(),
            "agent": self.agent_widget.supports_vision(),
            "subagent": self.subagent_widget.supports_vision(),
        }
        self._log("Generating LiteLLM config...")
        generate_yaml(models, vision_support=vision_support)
        self._log(f"  Wrote {YAML_PATH}")

        # Check if port is taken
        if health_check(self._port, timeout=1):
            self._log(f"Port {self._port} is in use. Kill existing process first.")
            return

        self._log(f"Starting LiteLLM on port {self._port}...")
        self.launch_btn.setEnabled(False)

        # Use signal-based worker
        self._launch_worker = ProxyLauncher(self._port)
        self._launch_worker_thread = threading.Thread(target=self._launch_worker.run, daemon=True)
        self._launch_worker.ready.connect(self._on_proxy_ready)
        self._launch_worker.failed.connect(self._on_proxy_failed)
        self._launch_worker_thread.start()

    def _on_proxy_ready(self, pid: int) -> None:
        self._litellm_pid = pid
        self._proxy_running = True
        self.status_indicator.setText("●  Connected")
        self.status_indicator.setObjectName("good")
        self.status_indicator.style().unpolish(self.status_indicator)
        self.status_indicator.style().polish(self.status_indicator)
        self.launch_btn.setEnabled(False)
        self.kill_btn.setEnabled(True)
        self.open_terminal_btn.setEnabled(True)
        self.latency_btn.setEnabled(True)
        self._log(f"LiteLLM is running on port {self._port} (PID {self._litellm_pid}).")
        # Update CLAUDE.md routing table
        self._update_claude_md()

    def _on_proxy_failed(self, err_text: str) -> None:
        self.launch_btn.setEnabled(True)
        self._log(f"Proxy failed to start:\n{err_text}")

    def _kill_proxy(self) -> None:
        self._log(f"Killing proxy on port {self._port}...")
        self.kill_btn.setEnabled(False)
        self._killer = ProxyKiller(self._port)
        self._killer_thread = threading.Thread(target=self._killer.run, daemon=True)
        self._killer.done.connect(self._on_proxy_killed)
        self._killer_thread.start()

    def _on_proxy_killed(self) -> None:
        self._proxy_running = False
        self.status_indicator.setText("●  Disconnected")
        self.status_indicator.setObjectName("bad")
        self.status_indicator.style().unpolish(self.status_indicator)
        self.status_indicator.style().polish(self.status_indicator)
        self.launch_btn.setEnabled(True)
        self.kill_btn.setEnabled(False)
        self.open_terminal_btn.setEnabled(False)
        self.latency_btn.setEnabled(False)
        for w in [self.advisor_widget, self.agent_widget, self.subagent_widget]:
            w.set_latency(None)
        self._log("Proxy stopped.")

    def _open_terminal(self) -> None:
        models = {
            "advisor": self.advisor_widget.selected_model() or "",
            "agent": self.agent_widget.selected_model() or "",
            "subagent": self.subagent_widget.selected_model() or "",
        }
        project_dir = self._project_dir
        self._log("Opening terminal with proxy env vars set...")
        open_terminal_with_env(models, self._port, project_dir)

    def _test_latency(self) -> None:
        self.latency_btn.setEnabled(False)
        self._pending_latency = len(ROLES)
        for w in [self.advisor_widget, self.agent_widget, self.subagent_widget]:
            w.latency_label.setText("Latency: testing…")
            w.latency_label.setObjectName("status")
            w.latency_label.style().unpolish(w.latency_label)
            w.latency_label.style().polish(w.latency_label)
        self._log("Testing latency for each role...")
        self._latency_workers = []
        for role_key, alias, _ in ROLES:
            worker = LatencyTester(self._port, role_key, alias)
            thread = threading.Thread(target=worker.run, daemon=True)
            worker.result.connect(self._on_latency_result)
            worker.error.connect(self._on_latency_error)
            self._latency_workers.append(worker)
            thread.start()

    def _on_latency_result(self, role_key: str, ms: float) -> None:
        widget_map = {
            "advisor": self.advisor_widget,
            "agent": self.agent_widget,
            "subagent": self.subagent_widget,
        }
        widget_map[role_key].set_latency(ms)
        self._log(f"  {role_key}: {ms:.0f} ms")
        self._pending_latency -= 1
        if self._pending_latency <= 0:
            self.latency_btn.setEnabled(True)

    def _on_latency_error(self, role_key: str, err: str) -> None:
        widget_map = {
            "advisor": self.advisor_widget,
            "agent": self.agent_widget,
            "subagent": self.subagent_widget,
        }
        widget_map[role_key].set_latency(None, error=err)
        self._log(f"  {role_key}: error — {err[:500]}")
        self._pending_latency -= 1
        if self._pending_latency <= 0:
            self.latency_btn.setEnabled(True)
            self._log("  Latency errors can put models into cooldown — kill and relaunch the proxy to reset.")

    def _update_claude_md(self) -> None:
        models = {
            "advisor": self.advisor_widget.selected_model() or "",
            "agent": self.agent_widget.selected_model() or "",
            "subagent": self.subagent_widget.selected_model() or "",
        }
        result = update_claude_md(models, self._port)
        if result is None:
            self._log("  [warn] cloud-doc.py not found; update CLAUDE.md routing table manually.")
        elif result is True:
            self._log("  Updated CLAUDE.md routing table.")
        else:
            self._log(f"  [warn] Failed to update CLAUDE.md: {result[:200]}")


# ── Entry ─────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = LiteLLMGui()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
