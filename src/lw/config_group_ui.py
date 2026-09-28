"""[lw] Render folded config groups like the outer task card header.

The framework has no group widget, so groups used to show a Yes/No switch. The
header below keeps the same ``switch_button.checkedChanged`` contract the config
card uses for ``sub_configs`` visibility, but looks and behaves like the task
card: whole row clickable, rotating arrow, collapsed whenever the card is built.
"""

from functools import wraps

from PySide6.QtCore import Qt, Signal
from qfluentwidgets.components.settings.expand_setting_card import ExpandButton

from ok.ui.qt.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget
from src.lw.config_group import is_config_group


class _GroupExpandButton(ExpandButton):
    """Task-card arrow button exposing the switch API the config card listens to."""

    checkedChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        # The base handler derives the state from the running rotation angle.
        self.clicked.disconnect()
        self.clicked.connect(self.toggle)

    def isChecked(self):
        return self._checked

    def toggle(self):
        self.setChecked(not self._checked)

    def setChecked(self, checked, animate=True):
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        if animate:
            self.setExpand(checked)
        else:
            self.rotateAni.stop()
            self.setAngle(180 if checked else 0)
        self.checkedChanged.emit(checked)


class LabelAndConfigGroup(ConfigLabelAndWidget):
    def __init__(self, config_desc, config, key: str):
        super().__init__(config_desc, config, key)
        # Same as the outer card: every freshly built card starts collapsed.
        if self.config.get(self.key):
            self.config[self.key] = False
        self.switch_button = _GroupExpandButton(self)
        self.switch_button.checkedChanged.connect(self.update_config)
        self.add_widget(self.switch_button, stretch=0)
        self.setCursor(Qt.PointingHandCursor)

    def update_value(self):
        self.switch_button.setChecked(bool(self.config.get(self.key)), animate=self.isVisible())

    def enterEvent(self, e):
        self.switch_button.setHover(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.switch_button.setHover(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.switch_button.setPressed(True)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.switch_button.setPressed(False)
            if self.rect().contains(e.position().toPoint()):
                self.switch_button.toggle()
        super().mouseReleaseEvent(e)


def install_config_group_widgets():
    """Route folded groups in Qt config cards to ``LabelAndConfigGroup``."""
    from ok.ui.qt.tasks import ConfigCard as config_card_module

    original = config_card_module.config_widget
    if getattr(original, "_lw_config_group", False):
        return

    @wraps(original)
    def config_widget(config_type, config_desc, config, key, value, task):
        the_type = config_type.get(key) if config_type is not None else None
        if is_config_group(the_type):
            return LabelAndConfigGroup(config_desc, config, key)
        return original(config_type, config_desc, config, key, value, task)

    config_widget._lw_config_group = True
    config_card_module.config_widget = config_widget
