import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from main import CompareMode, MainWindow, load_app_icon, resolve_app_base_path
from image_comparator_app.config import SessionState, load_session_state, save_session_state

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.ini"


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


def wheel_event(
    position: QPointF,
    delta_y: int,
    modifiers: Qt.KeyboardModifier,
) -> QWheelEvent:
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
        self.original_config = (
            CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None
        )
        CONFIG_PATH.write_text(
            f"[app]\nlast_folder = {REPO_ROOT}\ncompare_mode = SIDE_BY_SIDE\n",
            encoding="utf-8",
        )

        self.window = MainWindow()
        self.window.resize(1280, 720)
        self.window.show()
        self.window.canvas.resize(1200, 640)
        self.window.image_a = sample_image()
        self.window.image_b = sample_image()
        self.window.image_a_path = REPO_ROOT / "a.png"
        self.window.image_b_path = REPO_ROOT / "b.png"
        self.window.canvas.set_images(self.window.image_a, self.window.image_b)
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        if self.original_config is None:
            CONFIG_PATH.unlink(missing_ok=True)
        else:
            CONFIG_PATH.write_text(self.original_config, encoding="utf-8")

    def _save_temp_image(self, color: str) -> Path:
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        image = filled_image(color, width=64, height=64)
        image.save(path)
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        return Path(path)

    def test_unload_image_a_clears_only_first_image(self) -> None:
        self.window._unload_image("a")

        self.assertIsNone(self.window.image_a)
        self.assertIsNotNone(self.window.image_b)
        self.assertEqual(self.window.label_a.text(), "Image A: Not loaded")
        self.assertIsNone(self.window.canvas.image_a)
        self.assertIsNotNone(self.window.canvas.image_b)

    def test_clear_workspace_preserves_mode_and_resets_view_state(self) -> None:
        self.window.canvas.set_mode(CompareMode.OVERLAY)
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
        self.assertEqual(self.window.canvas.mode, CompareMode.OVERLAY)
        self.assertEqual(self.window.canvas.slider_ratio, 0.5)
        self.assertEqual(self.window.canvas._slider_zoom, 1.0)
        self.assertEqual(self.window.canvas._slider_pan, QPointF(0.0, 0.0))
        self.assertEqual(self.window.canvas._side_zoom, 1.0)
        self.assertEqual(self.window.canvas._side_center_norm, QPointF(0.5, 0.5))
        self.assertFalse(self.window.canvas._hold_zoom_active)
        self.assertIsNone(self.window.canvas._hold_norm_pos)

    def test_reset_view_preserves_mode_and_resets_transient_state(self) -> None:
        self.window.canvas.set_mode(CompareMode.SLIDER)
        self.window.canvas.slider_ratio = 0.15
        self.window.canvas._slider_zoom = 3.0
        self.window.canvas._slider_pan = QPointF(35.0, -45.0)

        self.window._reset_view()

        self.assertEqual(self.window.canvas.mode, CompareMode.SLIDER)
        self.assertEqual(self.window.canvas.slider_ratio, 0.5)
        self.assertEqual(self.window.canvas._slider_zoom, 1.0)
        self.assertEqual(self.window.canvas._slider_pan, QPointF(0.0, 0.0))

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

    def test_overlay_renders_blended_output(self) -> None:
        self.window.canvas.set_mode(CompareMode.OVERLAY)
        self.window.overlay_opacity_input.setValue(0.5)
        self.window.canvas.set_images(
            filled_image("#ff0000", width=400, height=300),
            filled_image("#0000ff", width=400, height=300),
        )
        self.app.processEvents()

        rendered = self.window.canvas.grab().toImage()
        center = rendered.pixelColor(rendered.width() // 2, rendered.height() // 2)

        self.assertGreater(center.red(), 110)
        self.assertGreater(center.blue(), 110)
        self.assertLess(center.green(), 20)

    def test_clicking_canvas_clears_spinbox_focus(self) -> None:
        self.window.overlay_opacity_input.setFocus()
        self.assertTrue(self.window.overlay_opacity_input.hasFocus())

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

        self.assertFalse(self.window.overlay_opacity_input.hasFocus())

    def test_default_window_size_is_1280_by_720(self) -> None:
        fresh_window = MainWindow()
        try:
            self.assertEqual(fresh_window.size().width(), 1280)
            self.assertEqual(fresh_window.size().height(), 720)
        finally:
            fresh_window.close()

    def test_window_uses_non_null_icon_from_assets(self) -> None:
        icon_path = REPO_ROOT / "assets" / "icon.ico"

        self.assertTrue(icon_path.exists())
        self.assertFalse(self.window.windowIcon().isNull())

    def test_resolve_app_base_path_uses_pyinstaller_bundle_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_meipass = getattr(sys, "_MEIPASS", None)
            sys._MEIPASS = temp_dir
            try:
                self.assertEqual(resolve_app_base_path(), Path(temp_dir))
            finally:
                if original_meipass is None:
                    delattr(sys, "_MEIPASS")
                else:
                    sys._MEIPASS = original_meipass

    def test_load_app_icon_uses_pyinstaller_bundle_path(self) -> None:
        source_icon = REPO_ROOT / "assets" / "icon.ico"
        self.assertTrue(source_icon.exists())

        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_assets = Path(temp_dir) / "assets"
            bundle_assets.mkdir()
            image = QImage(str(source_icon))
            image.save(str(bundle_assets / "icon.ico"))

            original_meipass = getattr(sys, "_MEIPASS", None)
            sys._MEIPASS = temp_dir
            try:
                self.assertFalse(load_app_icon().isNull())
            finally:
                if original_meipass is None:
                    delattr(sys, "_MEIPASS")
                else:
                    sys._MEIPASS = original_meipass

    def test_assign_drop_targets_prefers_empty_slot(self) -> None:
        path = Path("/tmp/example.png")
        self.window.image_a = None
        self.window.image_b = sample_image()

        assignments = self.window._assign_drop_targets([path])

        self.assertEqual(assignments, [("a", path)])

    def test_assign_drop_targets_uses_b_when_a_is_filled(self) -> None:
        path = Path("/tmp/example.png")
        self.window.image_a = sample_image()
        self.window.image_b = None

        assignments = self.window._assign_drop_targets([path])

        self.assertEqual(assignments, [("b", path)])

    def test_handle_dropped_paths_loads_two_images_in_order(self) -> None:
        image_a_path = self._save_temp_image("#ff0000")
        image_b_path = self._save_temp_image("#0000ff")

        self.window._clear_workspace()
        loaded = self.window._handle_dropped_paths([image_a_path, image_b_path])

        self.assertEqual(loaded, 2)
        self.assertEqual(self.window.label_a.text(), f"Image A: {image_a_path.name}")
        self.assertEqual(self.window.label_b.text(), f"Image B: {image_b_path.name}")
        self.assertIsNotNone(self.window.image_a)
        self.assertIsNotNone(self.window.image_b)

    def test_swap_images_exchanges_labels_and_paths(self) -> None:
        self.window.label_a.setText("Image A: first.png")
        self.window.label_b.setText("Image B: second.png")
        first_path = Path("/tmp/first.png")
        second_path = Path("/tmp/second.png")
        self.window.image_a_path = first_path
        self.window.image_b_path = second_path

        self.window._swap_images()

        self.assertEqual(self.window.image_a_path, second_path)
        self.assertEqual(self.window.image_b_path, first_path)
        self.assertEqual(self.window.label_a.text(), "Image A: second.png")
        self.assertEqual(self.window.label_b.text(), "Image B: first.png")

    def test_mode_switch_ends_slider_drag(self) -> None:
        self.window.canvas.set_mode(CompareMode.SLIDER)
        self.window.canvas._dragging_slider = True

        self.window.canvas.set_mode(CompareMode.OVERLAY)

        self.assertFalse(self.window.canvas._dragging_slider)
        self.assertEqual(self.window.canvas.mode, CompareMode.OVERLAY)

    def test_cycle_mode_action_advances_mode(self) -> None:
        action = next(action for action in self.window.actions() if action.text() == "Cycle Mode")

        action.trigger()

        self.assertEqual(self.window.canvas.mode, CompareMode.SLIDER)

    def test_load_image_path_invalid_shows_error(self) -> None:
        with patch("image_comparator_app.window.QMessageBox.critical") as critical:
            result = self.window._load_image_path(Path("/tmp/does-not-exist.png"), "a", reset_view=True)

        self.assertFalse(result)
        critical.assert_called_once()


class SessionConfigTests(unittest.TestCase):
    def test_invalid_session_values_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.ini"
            config_path.write_text(
                "[app]\n"
                "last_folder = /tmp/does-not-exist\n"
                "compare_mode = INVALID\n"
                "lens_zoom = nope\n"
                "lens_size = -10\n"
                "overlay_opacity = 8.5\n",
                encoding="utf-8",
            )

            state = load_session_state(config_path)

        self.assertEqual(state.compare_mode, "INVALID")
        self.assertEqual(state.lens_zoom, 4.0)
        self.assertEqual(state.lens_size, 60)
        self.assertEqual(state.overlay_opacity, 1.0)
        self.assertEqual(state.last_folder, REPO_ROOT)

    def test_session_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.ini"
            state = SessionState(
                last_folder=Path(temp_dir),
                geometry="abc123",
                compare_mode="OVERLAY",
                lens_zoom=5.2,
                lens_size=220,
                overlay_opacity=0.65,
            )

            save_session_state(config_path, state)
            loaded = load_session_state(config_path)

        self.assertEqual(loaded.last_folder, Path(temp_dir))
        self.assertEqual(loaded.geometry, "abc123")
        self.assertEqual(loaded.compare_mode, "OVERLAY")
        self.assertEqual(loaded.lens_zoom, 5.2)
        self.assertEqual(loaded.lens_size, 220)
        self.assertEqual(loaded.overlay_opacity, 0.65)


if __name__ == "__main__":
    unittest.main()
