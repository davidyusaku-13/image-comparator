import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, Qt
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .canvas import CompareMode, ImageCompareCanvas
from .config import SessionState, load_session_state, resolve_app_base_path, save_session_state

SUPPORTED_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Image Comparator")
        self.resize(1280, 720)
        self.setWindowIcon(load_app_icon())
        self.setAcceptDrops(True)

        self.config_path = resolve_app_base_path() / "config.ini"
        self.session_state = load_session_state(self.config_path)
        self.last_folder = self.session_state.last_folder

        self.image_a = None
        self.image_b = None
        self.image_a_path: Path | None = None
        self.image_b_path: Path | None = None

        self.canvas = ImageCompareCanvas()
        self.canvas.set_mode(self._resolve_compare_mode(self.session_state.compare_mode))
        self.canvas.set_overlay_opacity(self.session_state.overlay_opacity)
        self.canvas.mode_changed.connect(self._on_mode_changed)

        self.label_a = QLabel("Image A: Not loaded")
        self.label_b = QLabel("Image B: Not loaded")

        load_a_btn = QPushButton("Load Image A")
        load_a_btn.clicked.connect(lambda: self._load_image("a"))

        load_b_btn = QPushButton("Load Image B")
        load_b_btn.clicked.connect(lambda: self._load_image("b"))

        unload_a_btn = QPushButton("Unload Image A")
        unload_a_btn.clicked.connect(lambda: self._unload_image("a"))

        unload_b_btn = QPushButton("Unload Image B")
        unload_b_btn.clicked.connect(lambda: self._unload_image("b"))

        swap_btn = QPushButton("Swap Images")
        swap_btn.clicked.connect(self._swap_images)

        reset_view_btn = QPushButton("Reset View")
        reset_view_btn.clicked.connect(self._reset_view)

        clear_workspace_btn = QPushButton("Clear Workspace")
        clear_workspace_btn.clicked.connect(self._clear_workspace)

        mode_side_btn = QPushButton("Side by Side")
        mode_side_btn.clicked.connect(lambda: self._set_mode(CompareMode.SIDE_BY_SIDE))

        mode_slider_btn = QPushButton("Slider")
        mode_slider_btn.clicked.connect(lambda: self._set_mode(CompareMode.SLIDER))

        mode_overlay_btn = QPushButton("Overlay")
        mode_overlay_btn.clicked.connect(lambda: self._set_mode(CompareMode.OVERLAY))

        lens_zoom_label = QLabel("Lens Zoom")
        lens_zoom_input = QDoubleSpinBox()
        lens_zoom_input.setDecimals(1)
        lens_zoom_input.setRange(1.0, 10.0)
        lens_zoom_input.setSingleStep(0.2)
        lens_zoom_input.setValue(self.session_state.lens_zoom)
        lens_zoom_input.valueChanged.connect(self._on_lens_zoom_changed)
        self.lens_zoom_input = lens_zoom_input

        lens_size_label = QLabel("Lens Size")
        lens_size_input = QSpinBox()
        lens_size_input.setRange(60, 400)
        lens_size_input.setSingleStep(10)
        lens_size_input.setValue(self.session_state.lens_size)
        lens_size_input.valueChanged.connect(self._on_lens_size_changed)
        self.lens_size_input = lens_size_input

        overlay_label = QLabel("Overlay")
        overlay_input = QDoubleSpinBox()
        overlay_input.setDecimals(2)
        overlay_input.setRange(0.0, 1.0)
        overlay_input.setSingleStep(0.05)
        overlay_input.setValue(self.session_state.overlay_opacity)
        overlay_input.valueChanged.connect(self._on_overlay_opacity_changed)
        self.overlay_opacity_input = overlay_input

        controls = QHBoxLayout()
        controls.addWidget(load_a_btn)
        controls.addWidget(unload_a_btn)
        controls.addWidget(self.label_a, stretch=1)
        controls.addSpacing(8)
        controls.addWidget(load_b_btn)
        controls.addWidget(unload_b_btn)
        controls.addWidget(self.label_b, stretch=1)
        controls.addSpacing(12)
        controls.addWidget(swap_btn)
        controls.addWidget(reset_view_btn)
        controls.addWidget(clear_workspace_btn)
        controls.addSpacing(12)
        controls.addWidget(mode_side_btn)
        controls.addWidget(mode_slider_btn)
        controls.addWidget(mode_overlay_btn)
        controls.addSpacing(12)
        controls.addWidget(lens_zoom_label)
        controls.addWidget(lens_zoom_input)
        controls.addWidget(lens_size_label)
        controls.addWidget(lens_size_input)
        controls.addWidget(overlay_label)
        controls.addWidget(overlay_input)

        root = QVBoxLayout()
        root.addLayout(controls)
        root.addWidget(self.canvas, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)
        self._install_actions()
        QApplication.instance().installEventFilter(self)

        self.canvas.set_lens_zoom(self.lens_zoom_input.value())
        self.canvas.set_lens_size(self.lens_size_input.value())
        self._restore_geometry()
        self._update_mode_status()

    def _install_actions(self) -> None:
        self._add_action(
            "Load Image A",
            "Ctrl+Shift+A",
            lambda: self._load_image("a"),
        )
        self._add_action(
            "Load Image B",
            "Ctrl+Shift+B",
            lambda: self._load_image("b"),
        )
        self._add_action("Swap Images", "Ctrl+T", self._swap_images)
        self._add_action("Clear Workspace", "Ctrl+Shift+X", self._clear_workspace)
        self._add_action("Reset View", "Ctrl+R", self._reset_view)
        self._add_action("Cycle Mode", "Ctrl+M", self._cycle_mode)
        self._add_action("Help", QKeySequence.StandardKey.HelpContents, self._show_help)

    def _add_action(self, text: str, shortcut, handler) -> None:
        action = QAction(text, self)
        action.triggered.connect(handler)
        action.setShortcut(shortcut)
        self.addAction(action)

    def _resolve_compare_mode(self, raw_mode: str) -> CompareMode:
        try:
            return CompareMode[raw_mode]
        except KeyError:
            return CompareMode.SIDE_BY_SIDE

    def _current_session_state(self) -> SessionState:
        geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        return SessionState(
            last_folder=self.last_folder,
            geometry=geometry,
            compare_mode=self.canvas.mode.name,
            lens_zoom=self.lens_zoom_input.value(),
            lens_size=self.lens_size_input.value(),
            overlay_opacity=self.overlay_opacity_input.value(),
        )

    def _save_session_settings(self) -> None:
        save_session_state(self.config_path, self._current_session_state())

    def _restore_geometry(self) -> None:
        if self.session_state.geometry:
            geometry = QByteArray.fromBase64(self.session_state.geometry.encode("ascii"))
            restored = self.restoreGeometry(geometry)
            if restored:
                return
        self.resize(1280, 720)

    def _set_mode(self, mode: CompareMode) -> None:
        self.canvas.set_mode(mode)
        self._update_mode_status()

    def _cycle_mode(self) -> None:
        self.canvas.cycle_mode()
        self._update_mode_status()

    def _on_mode_changed(self, _mode: CompareMode) -> None:
        self._update_mode_status()
        self._save_session_settings()

    def _on_lens_zoom_changed(self, zoom: float) -> None:
        self.canvas.set_lens_zoom(zoom)
        self._save_session_settings()

    def _on_lens_size_changed(self, size: int) -> None:
        self.canvas.set_lens_size(size)
        self._save_session_settings()

    def _on_overlay_opacity_changed(self, opacity: float) -> None:
        self.canvas.set_overlay_opacity(opacity)
        self._save_session_settings()

    def _update_mode_status(self) -> None:
        mode = self.canvas.mode.value
        if self.canvas.mode == CompareMode.SIDE_BY_SIDE:
            hint = "Left-drag hold lens, Ctrl+wheel zoom, wheel pan, Shift+wheel horizontal pan."
        elif self.canvas.mode == CompareMode.SLIDER:
            hint = "Drag slider, Ctrl+wheel zoom, wheel pan, Shift+wheel horizontal pan."
        else:
            hint = "Adjust overlay opacity, Ctrl+wheel zoom, wheel pan, Shift+wheel horizontal pan."
        self.statusBar().showMessage(f"{mode} mode. {hint} Press F1 for shortcuts.")

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Image Comparator Help",
            "\n".join(
                [
                    "Mouse and Wheel",
                    "- Ctrl+Wheel: Zoom",
                    "- Wheel: Vertical pan",
                    "- Shift+Wheel: Horizontal pan",
                    "- Side by Side: Hold left click over either pane to show synchronized lens",
                    "- Slider: Drag anywhere in the view to move the split",
                    "",
                    "Keyboard Shortcuts",
                    "- Ctrl+Shift+A: Load Image A",
                    "- Ctrl+Shift+B: Load Image B",
                    "- Ctrl+T: Swap images",
                    "- Ctrl+Shift+X: Clear workspace",
                    "- Ctrl+R: Reset view",
                    "- Ctrl+M: Cycle compare mode",
                    "- F1: Open help",
                ]
            ),
        )

    def _load_image(self, target: str) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            str(self.last_folder),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
        )
        if not file_path:
            return
        self._load_image_path(Path(file_path), target, reset_view=True)

    def _load_image_path(self, selected_path: Path, target: str, *, reset_view: bool) -> bool:
        image = self._read_image(selected_path)
        if image is None:
            QMessageBox.critical(
                self,
                "Failed to load image",
                f"Could not open file:\n{selected_path}",
            )
            return False

        self.last_folder = selected_path.parent
        self._assign_image(target, image, selected_path, reset_view=reset_view)
        self._save_session_settings()
        return True

    def _read_image(self, file_path: Path) -> QImage | None:
        image = QImage(str(file_path))
        if image.isNull():
            return None
        return image

    def _assign_image(
        self,
        target: str,
        image,
        image_path: Path,
        *,
        reset_view: bool,
    ) -> None:
        if target == "a":
            self.image_a = image
            self.image_a_path = image_path
            self.label_a.setText(f"Image A: {image_path.name}")
        else:
            self.image_b = image
            self.image_b_path = image_path
            self.label_b.setText(f"Image B: {image_path.name}")

        self.canvas.set_images(self.image_a, self.image_b, reset_view=reset_view)

    def _assign_drop_targets(self, paths: list[Path]) -> list[tuple[str, Path]]:
        filtered = [path for path in paths if path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES]
        if not filtered:
            return []

        assignments: list[tuple[str, Path]] = []
        if len(filtered) >= 2:
            return [("a", filtered[0]), ("b", filtered[1])]

        target = "a"
        if self.image_a is None:
            target = "a"
        elif self.image_b is None:
            target = "b"
        else:
            target = "a"
        assignments.append((target, filtered[0]))
        return assignments

    def _handle_dropped_paths(self, paths: list[Path]) -> int:
        assignments = self._assign_drop_targets(paths)
        loaded = 0
        for index, (target, path) in enumerate(assignments):
            if self._load_image_path(path, target, reset_view=index == 0):
                loaded += 1
        return loaded

    def _unload_image(self, target: str) -> None:
        if target == "a":
            self.image_a = None
            self.image_a_path = None
            self.label_a.setText("Image A: Not loaded")
        else:
            self.image_b = None
            self.image_b_path = None
            self.label_b.setText("Image B: Not loaded")

        self.canvas.set_images(self.image_a, self.image_b, reset_view=False)
        self._save_session_settings()

    def _swap_images(self) -> None:
        self.image_a, self.image_b = self.image_b, self.image_a
        self.image_a_path, self.image_b_path = self.image_b_path, self.image_a_path
        self.label_a.setText(
            f"Image A: {self.image_a_path.name}" if self.image_a_path else "Image A: Not loaded"
        )
        self.label_b.setText(
            f"Image B: {self.image_b_path.name}" if self.image_b_path else "Image B: Not loaded"
        )
        self.canvas.set_images(self.image_a, self.image_b, reset_view=False)
        self._save_session_settings()

    def _reset_view(self) -> None:
        self.canvas.reset_view()

    def _clear_workspace(self) -> None:
        self.image_a = None
        self.image_b = None
        self.image_a_path = None
        self.image_b_path = None
        self.label_a.setText("Image A: Not loaded")
        self.label_b.setText("Image B: Not loaded")
        self.canvas.set_images(None, None, reset_view=False)
        self.canvas.reset_view()
        self._save_session_settings()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.MouseButtonPress:
            return super().eventFilter(watched, event)

        focused = self.focusWidget()
        focusable_inputs = {
            self.lens_zoom_input,
            self.lens_size_input,
            self.overlay_opacity_input,
        }
        if focused in focusable_inputs:
            widget = QApplication.widgetAt(event.globalPosition().toPoint())
            inside_input = any(
                widget is not None and (widget is input_widget or input_widget.isAncestorOf(widget))
                for input_widget in focusable_inputs
            )
            if not inside_input:
                focused.clearFocus()
                self.centralWidget().setFocus()
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            urls = [url for url in event.mimeData().urls() if url.isLocalFile()]
            paths = [Path(url.toLocalFile()) for url in urls]
            if self._assign_drop_targets(paths):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = [url for url in event.mimeData().urls() if url.isLocalFile()]
        paths = [Path(url.toLocalFile()) for url in urls]
        if self._handle_dropped_paths(paths):
            event.acceptProposedAction()
            return
        event.ignore()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_session_settings()
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)


def load_app_icon() -> QIcon:
    icon_path = resolve_app_base_path() / "assets" / "icon.ico"
    if not icon_path.is_file():
        return QIcon()

    icon = QIcon(str(icon_path))
    if icon.isNull():
        return QIcon()
    return icon


def main() -> int:
    app = QApplication(sys.argv)
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    window = MainWindow()
    window.show()
    return app.exec()
