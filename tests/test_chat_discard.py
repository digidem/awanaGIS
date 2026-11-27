"""Regression tests for failed transcript-row cleanup."""

from importlib import import_module
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
ChatDock = import_module(f"{ROOT.name}.gui.chat_dock").ChatDock


class FakeLayout:
    def __init__(self, indexes, take_error=None):
        self.indexes = iter(indexes)
        self.take_error = take_error
        self.taken = []

    def indexOf(self, _widget):
        value = next(self.indexes)
        if isinstance(value, Exception):
            raise value
        return value

    def takeAt(self, index):
        if self.take_error is not None:
            raise self.take_error
        self.taken.append(index)
        return object()


class FakeWidget:
    def __init__(self, hide_error=None, delete_error=None):
        self.hide_error = hide_error
        self.delete_error = delete_error
        self.hidden = False
        self.detached = False
        self.deleted = False

    def hide(self):
        if self.hide_error is not None:
            raise self.hide_error
        self.hidden = True

    def setParent(self, _parent):
        self.detached = True

    def deleteLater(self):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True


class ChatDiscardTests(unittest.TestCase):
    def test_deleted_layout_lookup_skips_delete_later(self):
        widget = FakeWidget()
        layout = FakeLayout([RuntimeError("deleted"), RuntimeError("deleted")])
        dock = SimpleNamespace(transcript_layout=layout)

        ChatDock._discard(dock, [widget])

        self.assertTrue(widget.hidden)
        self.assertTrue(widget.detached)
        self.assertFalse(widget.deleted)
        self.assertEqual(layout.taken, [])

    def test_detached_live_widget_is_deleted(self):
        widget = FakeWidget()
        layout = FakeLayout([-1, -1])
        dock = SimpleNamespace(transcript_layout=layout)

        ChatDock._discard(dock, [widget])

        self.assertTrue(widget.hidden)
        self.assertTrue(widget.detached)
        self.assertTrue(widget.deleted)

    def test_layout_refusal_still_hides_and_detaches(self):
        widget = FakeWidget()
        layout = FakeLayout([0, 0], take_error=RuntimeError("refused"))
        dock = SimpleNamespace(transcript_layout=layout)

        ChatDock._discard(dock, [widget])

        self.assertTrue(widget.hidden)
        self.assertTrue(widget.detached)
        self.assertFalse(widget.deleted)

    def test_deleted_widget_does_not_stop_sibling_cleanup(self):
        deleted = FakeWidget(hide_error=RuntimeError("deleted"))
        sibling = FakeWidget()
        layout = FakeLayout([-1, -1, -1])
        dock = SimpleNamespace(transcript_layout=layout)

        ChatDock._discard(dock, [deleted, sibling])

        self.assertTrue(sibling.hidden)
        self.assertTrue(sibling.detached)
        self.assertTrue(sibling.deleted)

    def test_delete_later_error_does_not_stop_sibling_cleanup(self):
        deleted = FakeWidget(delete_error=RuntimeError("deleted"))
        sibling = FakeWidget()
        layout = FakeLayout([-1, -1, -1, -1])
        dock = SimpleNamespace(transcript_layout=layout)

        ChatDock._discard(dock, [deleted, sibling])

        self.assertTrue(sibling.hidden)
        self.assertTrue(sibling.detached)
        self.assertTrue(sibling.deleted)

    def test_unexpected_layout_error_propagates(self):
        widget = FakeWidget()
        layout = FakeLayout([ValueError("unexpected")])
        dock = SimpleNamespace(transcript_layout=layout)

        with self.assertRaisesRegex(ValueError, "unexpected"):
            ChatDock._discard(dock, [widget])


if __name__ == "__main__":
    unittest.main()
