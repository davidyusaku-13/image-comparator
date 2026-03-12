import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from image_comparator import CompareMode, MainWindow


def app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def sample_image(width: int = 2000, height: int = 1000) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    return image


def filled_image(color: str, width: int = 200, height: int = 100) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


def wheel_event(position: QPointF, delta_y: int, modifiers: Qt.KeyboardModifier) -> QWheelEvent:
    return QWheelEvent(
        position,
        position,
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


class ImageComparatorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = app()

    def setUp(self) -> None:
        self.window = MainWindow()
        self.window.resize(1280, 720)
        self.window.show()
        self.window.canvas.resize(1200, 640)
        self.window.image_a = sample_image()
        self.window.image_b = sample_image()
        self.window.canvas.set_images(self.window.image_a, self.window.image_b)
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()

    def test_unload_image_a_clears_only_first_image(self) -> None:
        self.window._unload_image("a")

        self.assertIsNone(self.window.image_a)
        self.assertIsNotNone(self.window.image_b)
        self.assertEqual(self.window.label_a.text(), "Image A: Not loaded")
        self.assertIsNone(self.window.canvas.image_a)
        self.assertIsNotNone(self.window.canvas.image_b)

    def test_clear_workspace_resets_images_and_view_state(self) -> None:
        self.window.canvas.set_mode(CompareMode.SLIDER)
        self.window.canvas.slider_ratio = 0.2
        self.window.canvas._slider_zoom = 2.0
        self.window.canvas._slider_pan = QPointF(25.0, -30.0)
        self.window.canvas._side_zoom = 3.0
        self.window.canvas._side_center_norm = QPointF(0.3, 0.4)
        self.window.canvas._hold_zoom_active = True
        self.window.canvas._hold_norm_pos = (0.1, 0.2)

        self.window._clear_workspace()

        self.assertIsNone(self.window.image_a)
        self.assertIsNone(self.window.image_b)
        self.assertEqual(self.window.canvas.mode, CompareMode.SIDE_BY_SIDE)
        self.assertEqual(self.window.canvas.slider_ratio, 0.5)
        self.assertEqual(self.window.canvas._slider_zoom, 1.0)
        self.assertEqual(self.window.canvas._slider_pan, QPointF(0.0, 0.0))
        self.assertEqual(self.window.canvas._side_zoom, 1.0)
        self.assertEqual(self.window.canvas._side_center_norm, QPointF(0.5, 0.5))
        self.assertFalse(self.window.canvas._hold_zoom_active)
        self.assertIsNone(self.window.canvas._hold_norm_pos)

    def test_ctrl_wheel_zooms_side_by_side_mode(self) -> None:
        self.window.canvas.set_mode(CompareMode.SIDE_BY_SIDE)
        self.window.canvas.resize(1200, 640)

        event = wheel_event(
            QPointF(300.0, 200.0),
            120,
            Qt.KeyboardModifier.ControlModifier,
        )

        self.window.canvas.wheelEvent(event)

        self.assertGreater(self.window.canvas._side_zoom, 1.0)

    def test_side_by_side_renders_image_a_when_image_b_missing(self) -> None:
        self.window.canvas.set_mode(CompareMode.SIDE_BY_SIDE)
        self.window.canvas.set_images(filled_image("#ff0000"), None)

        rendered = self.window.canvas.grab().toImage()

        self.assertEqual(rendered.pixelColor(300, 320), QColor("#ff0000"))
        self.assertEqual(rendered.pixelColor(900, 320), QColor("#1f232a"))

    def test_side_by_side_renders_image_b_when_image_a_missing(self) -> None:
        self.window.canvas.set_mode(CompareMode.SIDE_BY_SIDE)
        self.window.canvas.set_images(None, filled_image("#00ff00"))

        rendered = self.window.canvas.grab().toImage()

        self.assertEqual(rendered.pixelColor(300, 320), QColor("#1f232a"))
        self.assertEqual(rendered.pixelColor(900, 320), QColor("#00ff00"))

    def test_slider_renders_left_half_when_only_image_a_loaded(self) -> None:
        self.window.canvas.set_mode(CompareMode.SLIDER)
        self.window.canvas.set_images(filled_image("#ff0000"), None)

        rendered = self.window.canvas.grab().toImage()

        self.assertEqual(rendered.pixelColor(300, 320), QColor("#ff0000"))
        self.assertEqual(rendered.pixelColor(900, 320), QColor("#1f232a"))

    def test_slider_renders_right_half_when_only_image_b_loaded(self) -> None:
        self.window.canvas.set_mode(CompareMode.SLIDER)
        self.window.canvas.set_images(None, filled_image("#00ff00"))

        rendered = self.window.canvas.grab().toImage()

        self.assertEqual(rendered.pixelColor(300, 320), QColor("#1f232a"))
        self.assertEqual(rendered.pixelColor(900, 320), QColor("#00ff00"))

    def test_clicking_canvas_clears_spinbox_focus(self) -> None:
        self.window.lens_zoom_input.setFocus()
        self.assertTrue(self.window.lens_zoom_input.hasFocus())

        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(20.0, 20.0),
            QPointF(20.0, 20.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        original_widget_at = QApplication.widgetAt
        QApplication.widgetAt = staticmethod(lambda _point: self.window.canvas)
        try:
            self.window.eventFilter(self.window.canvas, event)
        finally:
            QApplication.widgetAt = original_widget_at

        self.assertFalse(self.window.lens_zoom_input.hasFocus())

    def test_default_window_size_is_1280_by_720(self) -> None:
        fresh_window = MainWindow()
        try:
            self.assertEqual(fresh_window.size().width(), 1280)
            self.assertEqual(fresh_window.size().height(), 720)
        finally:
            fresh_window.close()

    def test_window_uses_non_null_icon_from_assets(self) -> None:
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"

        self.assertTrue(icon_path.exists())
        self.assertFalse(self.window.windowIcon().isNull())


if __name__ == "__main__":
    unittest.main()
