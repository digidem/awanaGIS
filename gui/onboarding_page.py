"""Provider setup screen shown in the chat dock until an AI backend is connected."""

import os
from html import escape

from qgis.PyQt.QtCore import QCoreApplication, QTimer, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_mod
from ..backends import providers
from ..core.onboarding import provider_needs_key
from .backend_feedback import display_backend_feedback
from .settings_dialog import _BgTask, _LIVE_TASKS
from .theme import (
    DOCK_ACCENT as _ACCENT,
    DOCK_SUCCESS as _SUCCESS,
    DOCK_DANGER as _DANGER,
    DOCK_ACCENT_HOV as _ACCENT_HOV,
    DOCK_ACCENT_TEXT as _ACCENT_TEXT,
    DOCK_BORDER as _BORDER,
    DOCK_CANVAS as _CANVAS,
    DOCK_SURFACE as _SURFACE,
    DOCK_SURFACE_2 as _SURFACE_2,
    DOCK_TEXT as _TEXT,
    DOCK_TEXT_2 as _TEXT_2,
    DOCK_TEXT_3 as _TEXT_3,
    fs,
    ui_font,
)

TINFOIL_ID = "tinfoil"
TINFOIL_KEY_URL = "https://tinfoil.sh"
_DEBOUNCE_MS = 600


class OnboardingPage(QWidget):
    """Explicit provider setup: provider, URL, token, auto-tested model list."""

    configured = pyqtSignal()

    def __init__(self, config, open_settings, parent=None, debounce_ms=_DEBOUNCE_MS):
        super().__init__(parent)
        self._config = config
        self._open_settings = open_settings
        self._generation = 0
        self._tested = False
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._run_test)
        self.reload()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self.setStyleSheet(f"background-color: {_CANVAS};")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background-color: {_CANVAS}; }}")
        outer.addWidget(scroll)
        body = QWidget()
        body.setStyleSheet(f"background-color: {_CANVAS};")
        col = QVBoxLayout(body)
        col.setContentsMargins(20, 24, 20, 20)
        col.setSpacing(8)
        scroll.setWidget(body)

        title = QLabel(QCoreApplication.translate("OnboardingPage", "Connect an AI provider to start"))
        title.setObjectName("OnboardingTitle")
        title.setWordWrap(True)
        title.setFont(ui_font(17))
        title.setStyleSheet(f"color: {_TEXT}; background: transparent; font-size: {fs(17)}px; font-weight: 600;")
        col.addWidget(title)

        intro = QLabel(QCoreApplication.translate("OnboardingPage", "Tinfoil is the default provider because it runs models in secure enclaves, so your prompts stay private. Paste your API key below to connect. You can pick another provider at any time."))
        intro.setObjectName("OnboardingIntro")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {_TEXT_2}; background: transparent; font-size: {fs(12)}px;")
        col.addWidget(intro)
        col.addSpacing(8)

        self.provider_combo = QComboBox()
        for p in providers.all_providers():
            self.provider_combo.addItem(p["label"], p["id"])
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(QCoreApplication.translate("OnboardingPage", "Provider API base URL"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(QCoreApplication.translate("OnboardingPage", "Paste your API key here"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        for field in (self.provider_combo, self.base_url_edit, self.key_edit, self.model_combo):
            field.setStyleSheet(
                f"QComboBox, QLineEdit {{ background: {_SURFACE}; color: {_TEXT}; border: 1px solid {_BORDER}; "
                f"border-radius: 6px; padding: 6px 8px; font-size: {fs(12)}px; }}"
            )

        col.addWidget(self._field_label(QCoreApplication.translate("OnboardingPage", "Provider"), self.provider_combo))
        col.addWidget(self.provider_combo)
        col.addWidget(self._field_label(QCoreApplication.translate("OnboardingPage", "Base URL"), self.base_url_edit))
        col.addWidget(self.base_url_edit)
        col.addWidget(self._field_label(QCoreApplication.translate("OnboardingPage", "API key"), self.key_edit))
        col.addWidget(self.key_edit)

        self.key_link = QLabel()
        self.key_link.setObjectName("OnboardingKeyLink")
        self.key_link.setTextFormat(Qt.TextFormat.RichText)
        self.key_link.setOpenExternalLinks(True)
        self.key_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.key_link.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.key_link.setStyleSheet(f"background: transparent; font-size: {fs(12)}px;")
        link_text = QCoreApplication.translate("OnboardingPage", "Get a Tinfoil API key")
        self.key_link.setText(f'<a href="{TINFOIL_KEY_URL}" style="color: {_ACCENT};">{escape(link_text)}</a>')
        col.addWidget(self.key_link)

        self.status = QLabel("")
        self.status.setObjectName("OnboardingStatus")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        col.addWidget(self.status)

        col.addWidget(self._field_label(QCoreApplication.translate("OnboardingPage", "Model"), self.model_combo))
        col.addWidget(self.model_combo)
        col.addSpacing(8)

        self.start_btn = QPushButton(QCoreApplication.translate("OnboardingPage", "Start chatting"))
        self.start_btn.setObjectName("OnboardingStart")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setMinimumHeight(max(32, fs(12) + 18))
        self.start_btn.setStyleSheet(f"""
            QPushButton {{ background: {_ACCENT}; color: {_ACCENT_TEXT}; border: none;
                border-radius: 8px; font-size: {fs(13)}px; font-weight: 600; padding: 0 16px; }}
            QPushButton:hover {{ background: {_ACCENT_HOV}; }}
            QPushButton:disabled {{ background: {_SURFACE_2}; color: {_TEXT_3}; }}
        """)
        self.start_btn.setEnabled(False)
        col.addWidget(self.start_btn)

        self.more_btn = QPushButton(QCoreApplication.translate("OnboardingPage", "More options (CLI agents, custom endpoint)…"))
        self.more_btn.setObjectName("OnboardingMore")
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.setFlat(True)
        self.more_btn.setStyleSheet(
            f"QPushButton {{ color: {_TEXT_2}; background: transparent; border: none; "
            f"font-size: {fs(12)}px; text-align: left; padding: 6px 0; }}"
            f"QPushButton:hover {{ color: {_TEXT}; }}"
        )
        col.addWidget(self.more_btn)
        col.addStretch(1)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.base_url_edit.textChanged.connect(self._on_input_changed)
        self.key_edit.textChanged.connect(self._on_input_changed)
        self.model_combo.editTextChanged.connect(self._update_start_enabled)
        self.start_btn.clicked.connect(self._start)
        self.more_btn.clicked.connect(lambda: self._open_settings())

    @staticmethod
    def _field_label(text, buddy):
        lbl = QLabel(text)
        lbl.setBuddy(buddy)
        buddy.setAccessibleName(text)
        lbl.setStyleSheet(f"color: {_TEXT_3}; background: transparent; font-size: {fs(11)}px;")
        return lbl

    # ------------------------------------------------------------------ #
    def reload(self):
        """Prefill the form from saved settings (provider defaults when unset)."""
        pid = self._config.get("provider")
        saved = self._config.get("connection_mode") == config_mod.MODE_API_KEY and providers.get_provider(pid) is not None
        if not saved:
            pid = TINFOIL_ID
        self._timer_stop()
        for w in (self.provider_combo, self.base_url_edit, self.key_edit):
            w.blockSignals(True)
        idx = self.provider_combo.findData(pid)
        self.provider_combo.setCurrentIndex(max(0, idx))
        provider = providers.get_provider(self.provider_combo.currentData()) or {}
        override = (self._config.get("api_base_url") or "").strip() if saved else ""
        self.base_url_edit.setText(override or provider.get("base_url", ""))
        self.key_edit.setText((self._config.get("api_key") or "").strip() if saved else "")
        for w in (self.provider_combo, self.base_url_edit, self.key_edit):
            w.blockSignals(False)
        self._after_provider_set()
        self._reset_test()
        self._maybe_schedule()

    def _timer_stop(self):
        if hasattr(self, "_timer"):
            self._timer.stop()

    def _provider(self):
        return providers.get_provider(self.provider_combo.currentData()) or {}

    def _after_provider_set(self):
        provider = self._provider()
        env = provider.get("key_env", "")
        self.key_link.setVisible(provider.get("id") == TINFOIL_ID)
        self.key_edit.setPlaceholderText(
            QCoreApplication.translate("OnboardingPage", "Paste your key (or set {variable})").format(variable=env) if env else QCoreApplication.translate("OnboardingPage", "No key needed for local servers")
        )

    def _on_provider_changed(self, _index):
        # A key typed for one provider must never be sent to another, so the
        # key is cleared and no test runs until the user edits URL or key.
        provider = self._provider()
        for w in (self.base_url_edit, self.key_edit):
            w.blockSignals(True)
        self.base_url_edit.setText(provider.get("base_url", ""))
        self.key_edit.clear()
        for w in (self.base_url_edit, self.key_edit):
            w.blockSignals(False)
        self._timer.stop()
        self._after_provider_set()
        self._reset_test()
        self._update_idle_status()

    def shutdown(self):
        """Stop the debounce timer and ignore any test still in flight."""
        self._timer.stop()
        self._generation += 1

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _effective_key(self):
        """Typed key, else the provider's environment variable (if set)."""
        key = self.key_edit.text().strip()
        env = self._provider().get("key_env", "")
        if not key and env:
            key = (os.environ.get(env, "") or "").strip()
        return key

    def _on_input_changed(self, _text):
        self._reset_test()
        self._maybe_schedule()

    def _reset_test(self):
        self._generation += 1
        self._tested = False
        self.model_combo.clear()
        self._set_status("", _TEXT_3)
        self._update_start_enabled()

    def _can_test(self):
        if not self.base_url_edit.text().strip():
            return False
        return bool(self._effective_key()) or not provider_needs_key(self._provider())

    def _maybe_schedule(self):
        if self._can_test():
            self._set_status(QCoreApplication.translate("OnboardingPage", "Checking connection…"), _TEXT_3)
            self._timer.start()
        else:
            self._timer.stop()
            self._update_idle_status()

    def _update_idle_status(self):
        if not self.base_url_edit.text().strip():
            self._set_status(QCoreApplication.translate("OnboardingPage", "Enter the provider base URL."), _TEXT_3)
        elif self._can_test():
            self._set_status("", _TEXT_3)
        else:
            self._set_status(QCoreApplication.translate("OnboardingPage", "Enter your API key to connect."), _TEXT_3)

    def _set_status(self, text, color):
        self.status.setText(text)
        self.status.setAccessibleDescription(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent; font-size: {fs(12)}px;")

    def _update_start_enabled(self, *_):
        self.start_btn.setEnabled(self._tested and bool(self.model_combo.currentText().strip()))

    # ------------------------------------------------------------------ #
    def _run_test(self):
        """Test the connection off the UI thread and fill the model list."""
        if not self._can_test():
            return
        generation = self._generation
        provider = self._provider()
        fmt = provider.get("format", "openai")
        base_url = self.base_url_edit.text().strip()
        key = self._effective_key()
        pid = provider.get("id", "")

        def fetch():
            return providers.fetch_models(fmt, base_url, key, pid)

        task = _BgTask(fetch)
        _LIVE_TASKS.add(task)

        def finish(result, err):
            _LIVE_TASKS.discard(task)
            task.wait()  # done is emitted at the end of run(); returns at once
            task.deleteLater()
            try:
                if generation != self._generation:
                    return  # inputs changed while this test ran
                models, fetch_err = result if result else ([], "")
                self._on_result(pid, list(models or []), err or fetch_err or "")
            except RuntimeError:
                pass  # page was destroyed while the task ran  # nosec B110

        task.done.connect(finish)
        task.start()

    def _on_result(self, pid, models, err):
        if err:
            self._tested = False
            self._set_status(QCoreApplication.translate("OnboardingPage", "Failed — {error}").format(error=display_backend_feedback(err)), _DANGER)
            self._update_start_enabled()
            return
        self._tested = True
        current = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setCurrentText(providers.pick_default_model(pid, models, current))
        self.model_combo.blockSignals(False)
        count = len(models)
        if not count:
            text = QCoreApplication.translate("OnboardingPage", "Connected · no models listed — type a model name below")
        elif count == 1:
            text = QCoreApplication.translate("OnboardingPage", "Connected · 1 model available")
        else:
            text = QCoreApplication.translate("OnboardingPage", "Connected · {count} models available").format(count=count)
        self._set_status(text, _SUCCESS)
        self._update_start_enabled()

    # ------------------------------------------------------------------ #
    def _start(self):
        provider = self._provider()
        model = self.model_combo.currentText().strip()
        if not self._tested or not model:
            return
        base_url = self.base_url_edit.text().strip()
        self._config.set("connection_mode", config_mod.MODE_API_KEY)
        self._config.set("provider", provider.get("id", ""))
        self._config.set("api_key", self.key_edit.text().strip())
        self._config.set("api_base_url", "" if base_url == provider.get("base_url", "") else base_url)
        self._config.set("model", model)
        self.configured.emit()
