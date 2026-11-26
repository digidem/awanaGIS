"""Widgets that keep transcript rows inside the dock and their height current."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QLabel


class WrapLabel(QLabel):
    """A word-wrapped label for text inside the chat transcript.

    A plain QLabel reports its widest word as its minimum width, so one long token can make
    a transcript row wider than the dock. It also does not call updateGeometry() when it is
    resized, although its height for width changes with its width, so nested layouts keep a
    stale height. This label reports a minimum width of zero and re-announces its geometry
    whenever its width changes.
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        size.setWidth(0)
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateGeometry()


def elide_button(button, text_width=96):
    """Shorten a button label that is wider than ``text_width``; the full text becomes its tooltip."""
    full = button.text()
    shown = button.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, text_width)
    if shown != full:
        button.setText(shown)
        button.setToolTip(full)
