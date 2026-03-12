import configparser
import sys
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QWheelEvent
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


class CompareMode(Enum):
    SIDE_BY_SIDE = "Side by Side"
    SLIDER = "Slider"


class ImageCompareCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.image_a: QImage | None = None
        self.image_b: QImage | None = None
        self._zoom_min = 1.0
        self._zoom_max = 8.0
        self._zoom_step = 1.1
        self._lens_size = 160
        self._lens_zoom_factor = 4.0

        self._reset_view_state()
        self.setMouseTracking(True)

    def _reset_view_state(self) -> None:
        self.mode = CompareMode.SIDE_BY_SIDE
        self.slider_ratio = 0.5
        self._dragging_slider = False
        self._slider_zoom = 1.0
        self._slider_pan = QPointF(0.0, 0.0)
        self._side_zoom = 1.0
        self._side_center_norm = QPointF(0.5, 0.5)
        self._hold_zoom_active = False
        self._hold_norm_pos = None

    def _clear_interaction_state(self) -> None:
        self._dragging_slider = False
        self._hold_zoom_active = False
        self._hold_norm_pos = None

    def set_images(
        self,
        image_a: QImage | None,
        image_b: QImage | None,
        *,
        reset_view: bool = True,
    ) -> None:
        self.image_a = image_a
        self.image_b = image_b
        if reset_view:
            self._reset_view_state()
        else:
            self._clear_interaction_state()
        self.update()

    def set_mode(self, mode: CompareMode) -> None:
        if self._dragging_slider:
            self._end_slider_drag()
        self.mode = mode
        self._dragging_slider = False
        self._hold_zoom_active = False
        self._hold_norm_pos = None
        self.update()

    def set_lens_size(self, size: int) -> None:
        self._lens_size = max(60, min(400, size))
        self.update()

    def set_lens_zoom(self, zoom: float) -> None:
        self._lens_zoom_factor = max(1.0, min(10.0, zoom))
        self.update()

    def _view_area(self) -> QRectF:
        padding = 20.0
        return QRectF(self.rect()).adjusted(padding, padding, -padding, -padding)

    def _side_panes(self) -> tuple[QRectF, QRectF]:
        area = self._view_area()
        gap = 8.0
        pane_w = (area.width() - gap) / 2.0
        left = QRectF(area.x(), area.y(), pane_w, area.height())
        right = QRectF(area.x() + pane_w + gap, area.y(), pane_w, area.height())
        return left, right

    def _side_base_scale(self, image: QImage, pane: QRectF) -> float:
        if image.isNull() or pane.width() <= 0 or pane.height() <= 0:
            return 1.0
        return min(pane.width() / image.width(), pane.height() / image.height())

    def _pane_render_state(
        self,
        image: QImage,
        pane: QRectF,
        *,
        zoom: float | None = None,
        center_norm: QPointF | None = None,
    ) -> tuple[QRectF, QRectF]:
        if image.isNull() or pane.width() <= 0 or pane.height() <= 0:
            return QRectF(), QRectF()

        scale = self._side_base_scale(image, pane)
        active_zoom = self._side_zoom if zoom is None else zoom
        center = self._side_center_norm if center_norm is None else center_norm

        vis_w = min(float(image.width()), pane.width() / (scale * active_zoom))
        vis_h = min(float(image.height()), pane.height() / (scale * active_zoom))

        center_x = center.x() * max(0.0, image.width() - 1.0)
        center_y = center.y() * max(0.0, image.height() - 1.0)

        src_x = max(0.0, min(center_x - (vis_w / 2.0), image.width() - vis_w))
        src_y = max(0.0, min(center_y - (vis_h / 2.0), image.height() - vis_h))
        src_rect = QRectF(src_x, src_y, vis_w, vis_h)

        dst_w = vis_w * scale * active_zoom
        dst_h = vis_h * scale * active_zoom
        dst_x = pane.x() + (pane.width() - dst_w) / 2.0
        dst_y = pane.y() + (pane.height() - dst_h) / 2.0
        dst_rect = QRectF(dst_x, dst_y, dst_w, dst_h)
        return src_rect, dst_rect

    def _normalized_from_side_position(
        self,
        pos: QPointF,
        src_a: QRectF,
        dst_a: QRectF,
        src_b: QRectF,
        dst_b: QRectF,
    ) -> tuple[float, float] | None:
        if dst_a.contains(pos):
            src_rect, dst_rect, image = src_a, dst_a, self.image_a
        elif dst_b.contains(pos):
            src_rect, dst_rect, image = src_b, dst_b, self.image_b
        else:
            return None

        if image is None or dst_rect.width() <= 0 or dst_rect.height() <= 0:
            return None

        px = src_rect.x() + (
            (pos.x() - dst_rect.x()) * (src_rect.width() / dst_rect.width())
        )
        py = src_rect.y() + (
            (pos.y() - dst_rect.y()) * (src_rect.height() / dst_rect.height())
        )

        nx = px / max(1.0, image.width() - 1.0)
        ny = py / max(1.0, image.height() - 1.0)
        return (max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny)))

    def _normalized_in_render_state(
        self,
        pos: QPointF,
        image: QImage,
        src_rect: QRectF,
        dst_rect: QRectF,
    ) -> tuple[float, float] | None:
        if image.isNull() or dst_rect.width() <= 0 or dst_rect.height() <= 0:
            return None

        px = src_rect.x() + (
            (pos.x() - dst_rect.x()) * (src_rect.width() / dst_rect.width())
        )
        py = src_rect.y() + (
            (pos.y() - dst_rect.y()) * (src_rect.height() / dst_rect.height())
        )
        return (
            max(0.0, min(1.0, px / max(1.0, image.width() - 1.0))),
            max(0.0, min(1.0, py / max(1.0, image.height() - 1.0))),
        )

    def _normalized_from_side_cursor(self, pos: QPointF) -> tuple[float, float] | None:
        if self.image_a is None or self.image_b is None:
            return None

        left_pane, right_pane = self._side_panes()
        src_a, dst_a = self._pane_render_state(self.image_a, left_pane)
        src_b, dst_b = self._pane_render_state(self.image_b, right_pane)
        return self._normalized_from_side_position(pos, src_a, dst_a, src_b, dst_b)

    def _side_cursor_zoom_center(self, pos: QPointF, new_zoom: float) -> QPointF | None:
        left_pane, right_pane = self._side_panes()
        panes = ((self.image_a, left_pane), (self.image_b, right_pane))
        for image, pane in panes:
            if image is None:
                continue
            current_src, current_dst = self._pane_render_state(image, pane)
            if not current_dst.contains(pos):
                continue

            norm = self._normalized_in_render_state(pos, image, current_src, current_dst)
            if norm is None:
                return None

            next_src, next_dst = self._pane_render_state(
                image,
                pane,
                zoom=new_zoom,
                center_norm=self._side_center_norm,
            )
            if next_dst.isNull():
                return None

            rel_x = (pos.x() - next_dst.x()) / next_dst.width()
            rel_y = (pos.y() - next_dst.y()) / next_dst.height()
            src_px = norm[0] * max(0.0, image.width() - 1.0)
            src_py = norm[1] * max(0.0, image.height() - 1.0)
            center_x = src_px - ((rel_x - 0.5) * next_src.width())
            center_y = src_py - ((rel_y - 0.5) * next_src.height())
            max_x = max(0.0, image.width() - next_src.width())
            max_y = max(0.0, image.height() - next_src.height())
            clamped_x = max(0.0, min(center_x - (next_src.width() / 2.0), max_x))
            clamped_y = max(0.0, min(center_y - (next_src.height() / 2.0), max_y))
            return QPointF(
                (clamped_x + (next_src.width() / 2.0)) / max(1.0, image.width() - 1.0),
                (clamped_y + (next_src.height() / 2.0)) / max(1.0, image.height() - 1.0),
            )
        return None

    def _draw_placeholder(self, painter: QPainter, text: str) -> None:
        painter.setPen(QColor("#d8dee9"))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_side_by_side(self, painter: QPainter) -> None:
        left_pane, right_pane = self._side_panes()
        if self.image_a is not None:
            src_a, dst_a = self._pane_render_state(self.image_a, left_pane)
            painter.drawImage(dst_a, self.image_a, src_a)
        if self.image_b is not None:
            src_b, dst_b = self._pane_render_state(self.image_b, right_pane)
            painter.drawImage(dst_b, self.image_b, src_b)

        pane_pen = QPen(QColor("#7f8ea3"))
        pane_pen.setWidth(1)
        painter.setPen(pane_pen)
        painter.drawRect(left_pane)
        painter.drawRect(right_pane)

        divider_x = left_pane.right() + 4.0
        divider_pen = QPen(QColor("#f2f2f2"))
        divider_pen.setWidth(2)
        painter.setPen(divider_pen)
        painter.drawLine(
            QPointF(divider_x, left_pane.top()),
            QPointF(divider_x, left_pane.bottom()),
        )

        if (
            self.image_a is not None
            and self.image_b is not None
            and self._hold_zoom_active
            and self._hold_norm_pos is not None
        ):
            self._draw_hold_lens(
                painter, self.image_a, src_a, dst_a, left_pane, self._hold_norm_pos
            )
            self._draw_hold_lens(
                painter, self.image_b, src_b, dst_b, right_pane, self._hold_norm_pos
            )

    def _draw_hold_lens(
        self,
        painter: QPainter,
        image: QImage,
        src_rect: QRectF,
        dst_rect: QRectF,
        pane_rect: QRectF,
        norm_pos: tuple[float, float],
    ) -> None:
        if src_rect.isNull() or dst_rect.isNull():
            return

        nx, ny = norm_pos
        src_px = nx * max(0.0, image.width() - 1.0)
        src_py = ny * max(0.0, image.height() - 1.0)

        dst_px = dst_rect.x() + (
            (src_px - src_rect.x()) * (dst_rect.width() / src_rect.width())
        )
        dst_py = dst_rect.y() + (
            (src_py - src_rect.y()) * (dst_rect.height() / src_rect.height())
        )

        lens_rect = QRectF(
            dst_px - self._lens_size / 2.0,
            dst_py - self._lens_size / 2.0,
            float(self._lens_size),
            float(self._lens_size),
        ).intersected(pane_rect)
        if lens_rect.isNull():
            return

        px_per_screen_x = src_rect.width() / max(1.0, dst_rect.width())
        px_per_screen_y = src_rect.height() / max(1.0, dst_rect.height())

        src_w = min(
            image.width(),
            (lens_rect.width() * px_per_screen_x) / self._lens_zoom_factor,
        )
        src_h = min(
            image.height(),
            (lens_rect.height() * px_per_screen_y) / self._lens_zoom_factor,
        )
        src_x = max(0.0, min(src_px - (src_w / 2.0), image.width() - src_w))
        src_y = max(0.0, min(src_py - (src_h / 2.0), image.height() - src_h))
        lens_src = QRectF(src_x, src_y, src_w, src_h)

        painter.save()
        painter.setClipRect(pane_rect)
        painter.drawImage(lens_rect, image, lens_src)
        painter.restore()

        lens_pen = QPen(QColor("#ffffff"))
        lens_pen.setWidth(2)
        painter.setPen(lens_pen)
        painter.drawRect(lens_rect)

    def _slider_base_size(self) -> tuple[float, float]:
        if self.image_a is not None and not self.image_a.isNull():
            return float(self.image_a.width()), float(self.image_a.height())
        if self.image_b is not None and not self.image_b.isNull():
            return float(self.image_b.width()), float(self.image_b.height())
        return 0.0, 0.0

    def _clamp_slider_pan(self, area: QRectF, target_w: float, target_h: float) -> None:
        max_pan_x = max(0.0, (target_w - area.width()) / 2.0)
        max_pan_y = max(0.0, (target_h - area.height()) / 2.0)
        pan_x = min(max(self._slider_pan.x(), -max_pan_x), max_pan_x)
        pan_y = min(max(self._slider_pan.y(), -max_pan_y), max_pan_y)
        self._slider_pan = QPointF(pan_x, pan_y)

    def _slider_target_rect(self) -> QRectF:
        area = self._view_area()
        base_w, base_h = self._slider_base_size()
        if base_w <= 0 or base_h <= 0:
            return QRectF()

        target_w = base_w * self._slider_zoom
        target_h = base_h * self._slider_zoom
        self._clamp_slider_pan(area, target_w, target_h)

        center_x = area.center().x() + self._slider_pan.x()
        center_y = area.center().y() + self._slider_pan.y()
        return QRectF(
            center_x - target_w / 2.0,
            center_y - target_h / 2.0,
            target_w,
            target_h,
        )

    def _slider_x(self, area: QRectF) -> float:
        return area.x() + (area.width() * self.slider_ratio)

    def _set_slider_from_x(self, x: float, area: QRectF) -> None:
        if area.width() <= 0:
            return
        clamped = max(area.left(), min(x, area.right()))
        self.slider_ratio = (clamped - area.x()) / area.width()
        self.slider_ratio = max(0.0, min(1.0, self.slider_ratio))
        self.update()

    def _is_slider_hit(self, pos: QPointF, area: QRectF) -> bool:
        if area.isNull():
            return False
        slider_x = self._slider_x(area)
        handle_rect = QRectF(slider_x - 10.0, area.y(), 20.0, area.height())
        return handle_rect.contains(pos)

    def _end_slider_drag(self) -> None:
        if not self._dragging_slider:
            return
        self._dragging_slider = False
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def _draw_slider(self, painter: QPainter) -> None:
        area = self._view_area()
        target = self._slider_target_rect()
        if target.isNull() or area.isNull():
            return

        painter.save()
        painter.setClipRect(area)

        slider_x = self._slider_x(area)
        left_clip_rect = QRectF(
            area.x(), area.y(), max(0.0, slider_x - area.x()), area.height()
        )
        right_clip_rect = QRectF(
            slider_x, area.y(), max(0.0, area.right() - slider_x), area.height()
        )

        if self.image_b is not None and right_clip_rect.width() > 0:
            painter.save()
            painter.setClipRect(right_clip_rect)
            painter.drawImage(target, self.image_b)
            painter.restore()

        if self.image_a is not None and left_clip_rect.width() > 0:
            painter.save()
            painter.setClipRect(left_clip_rect)
            painter.drawImage(target, self.image_a)
            painter.restore()

        line_pen = QPen(QColor("#ffffff"))
        line_pen.setWidth(2)
        painter.setPen(line_pen)
        painter.drawLine(
            QPointF(slider_x, area.top()), QPointF(slider_x, area.bottom())
        )

        handle_rect = QRectF(slider_x - 7.0, area.center().y() - 20.0, 14.0, 40.0)
        painter.fillRect(handle_rect, QColor("#ffffff"))
        painter.setPen(QColor("#1f232a"))
        painter.drawRect(handle_rect)
        painter.restore()

        border_pen = QPen(QColor("#7f8ea3"))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.drawRect(area)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1f232a"))

        if not self.image_a and not self.image_b:
            self._draw_placeholder(
                painter, "Load Image A and Image B to start comparison."
            )
            return

        if self.mode == CompareMode.SIDE_BY_SIDE:
            self._draw_side_by_side(painter)
        else:
            self._draw_slider(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self.image_a is None or self.image_b is None:
            return

        if self.mode == CompareMode.SIDE_BY_SIDE:
            if event.button() == Qt.MouseButton.LeftButton:
                left_pane, right_pane = self._side_panes()
                src_a, dst_a = self._pane_render_state(self.image_a, left_pane)
                src_b, dst_b = self._pane_render_state(self.image_b, right_pane)
                norm = self._normalized_from_side_position(
                    pos, src_a, dst_a, src_b, dst_b
                )
                if norm is not None:
                    self._hold_zoom_active = True
                    self._hold_norm_pos = norm
                    self.update()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        area = self._view_area()
        if self._is_slider_hit(pos, area) or area.contains(pos):
            self._dragging_slider = True
            if QWidget.mouseGrabber() is None:
                self.grabMouse()
            self._set_slider_from_x(pos.x(), area)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self.image_a is None or self.image_b is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if self.mode == CompareMode.SIDE_BY_SIDE:
            left_pane, right_pane = self._side_panes()
            src_a, dst_a = self._pane_render_state(self.image_a, left_pane)
            src_b, dst_b = self._pane_render_state(self.image_b, right_pane)
            norm = self._normalized_from_side_position(pos, src_a, dst_a, src_b, dst_b)
            self.setCursor(
                Qt.CursorShape.CrossCursor
                if norm is not None
                else Qt.CursorShape.ArrowCursor
            )
            if self._hold_zoom_active and norm is not None:
                self._hold_norm_pos = norm
                self.update()
            return

        area = self._view_area()
        if self._is_slider_hit(pos, area):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif area.contains(pos):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if self._dragging_slider:
            self._set_slider_from_x(pos.x(), area)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        del event
        if self._hold_zoom_active:
            self._hold_zoom_active = False
            self._hold_norm_pos = None
        self._end_slider_drag()
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._end_slider_drag()
        super().hideEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._end_slider_drag()
        super().focusOutEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self.image_a is None or self.image_b is None:
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        steps = delta / 120.0
        modifiers = event.modifiers()
        pan_step = 40.0 * steps

        if self.mode == CompareMode.SIDE_BY_SIDE:
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                if steps > 0:
                    proposed_zoom = self._side_zoom * (self._zoom_step**steps)
                else:
                    proposed_zoom = self._side_zoom / (self._zoom_step ** abs(steps))
                new_zoom = max(self._zoom_min, min(self._zoom_max, proposed_zoom))
                if abs(new_zoom - self._side_zoom) < 1e-6:
                    return

                new_center = self._side_cursor_zoom_center(event.position(), new_zoom)
                self._side_zoom = new_zoom
                if new_center is not None:
                    self._side_center_norm = new_center
                self.update()
                return

            base_w = float(max(self.image_a.width(), self.image_b.width(), 1))
            base_h = float(max(self.image_a.height(), self.image_b.height(), 1))

            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                nx = self._side_center_norm.x() - (pan_step / base_w)
                ny = self._side_center_norm.y()
            else:
                nx = self._side_center_norm.x()
                ny = self._side_center_norm.y() - (pan_step / base_h)

            self._side_center_norm = QPointF(
                max(0.0, min(1.0, nx)),
                max(0.0, min(1.0, ny)),
            )
            self.update()
            return

        area = self._view_area()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            old_target = self._slider_target_rect()
            if old_target.isNull():
                return

            px = event.position().x()
            py = event.position().y()
            rel_x = (px - old_target.x()) / old_target.width()
            rel_y = (py - old_target.y()) / old_target.height()

            if steps > 0:
                proposed_zoom = self._slider_zoom * (self._zoom_step**steps)
            else:
                proposed_zoom = self._slider_zoom / (self._zoom_step ** abs(steps))
            new_zoom = max(self._zoom_min, min(self._zoom_max, proposed_zoom))
            if abs(new_zoom - self._slider_zoom) < 1e-6:
                return

            self._slider_zoom = new_zoom
            base_w, base_h = self._slider_base_size()
            target_w = base_w * self._slider_zoom
            target_h = base_h * self._slider_zoom

            new_left = px - (rel_x * target_w)
            new_top = py - (rel_y * target_h)
            new_center_x = new_left + (target_w / 2.0)
            new_center_y = new_top + (target_h / 2.0)
            self._slider_pan = QPointF(
                new_center_x - area.center().x(),
                new_center_y - area.center().y(),
            )
            self._clamp_slider_pan(area, target_w, target_h)
            self.update()
            return

        target = self._slider_target_rect()
        overflow_x = max(0.0, target.width() - area.width())
        overflow_y = max(0.0, target.height() - area.height())

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            if overflow_x > 0:
                self._slider_pan = QPointF(
                    self._slider_pan.x() + pan_step, self._slider_pan.y()
                )
        else:
            if overflow_y > 0:
                self._slider_pan = QPointF(
                    self._slider_pan.x(), self._slider_pan.y() + pan_step
                )

        self._clamp_slider_pan(area, target.width(), target.height())
        self.update()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Image Comparator")
        self.resize(1280, 720)

        self.config_path = Path(__file__).resolve().parent / "config.ini"
        self.last_folder = self._load_last_folder()

        self.image_a: QImage | None = None
        self.image_b: QImage | None = None

        self.canvas = ImageCompareCanvas()
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

        clear_workspace_btn = QPushButton("Clear Workspace")
        clear_workspace_btn.clicked.connect(self._clear_workspace)

        mode_side_btn = QPushButton("Side by Side")
        mode_side_btn.clicked.connect(
            lambda: self.canvas.set_mode(CompareMode.SIDE_BY_SIDE)
        )

        mode_slider_btn = QPushButton("Slider")
        mode_slider_btn.clicked.connect(
            lambda: self.canvas.set_mode(CompareMode.SLIDER)
        )

        lens_zoom_label = QLabel("Lens Zoom")
        lens_zoom_input = QDoubleSpinBox()
        lens_zoom_input.setDecimals(1)
        lens_zoom_input.setRange(1.0, 10.0)
        lens_zoom_input.setSingleStep(0.2)
        lens_zoom_input.setValue(4.0)
        lens_zoom_input.valueChanged.connect(self.canvas.set_lens_zoom)
        self.lens_zoom_input = lens_zoom_input

        lens_size_label = QLabel("Lens Size")
        lens_size_input = QSpinBox()
        lens_size_input.setRange(60, 400)
        lens_size_input.setSingleStep(10)
        lens_size_input.setValue(160)
        lens_size_input.valueChanged.connect(self.canvas.set_lens_size)
        self.lens_size_input = lens_size_input

        controls = QHBoxLayout()
        controls.addWidget(load_a_btn)
        controls.addWidget(unload_a_btn)
        controls.addWidget(self.label_a, stretch=1)
        controls.addSpacing(8)
        controls.addWidget(load_b_btn)
        controls.addWidget(unload_b_btn)
        controls.addWidget(self.label_b, stretch=1)
        controls.addSpacing(12)
        controls.addWidget(clear_workspace_btn)
        controls.addSpacing(12)
        controls.addWidget(mode_side_btn)
        controls.addWidget(mode_slider_btn)
        controls.addSpacing(12)
        controls.addWidget(lens_zoom_label)
        controls.addWidget(lens_zoom_input)
        controls.addWidget(lens_size_label)
        controls.addWidget(lens_size_input)

        root = QVBoxLayout()
        root.addLayout(controls)
        root.addWidget(self.canvas, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)
        QApplication.instance().installEventFilter(self)

        self._save_last_folder(self.last_folder)

    def _load_last_folder(self) -> Path:
        default_dir = Path(__file__).resolve().parent
        parser = configparser.ConfigParser()
        try:
            if self.config_path.exists():
                parser.read(self.config_path)
                raw = parser.get("app", "last_folder", fallback=str(default_dir))
            else:
                raw = str(default_dir)
        except (configparser.Error, OSError):
            raw = str(default_dir)

        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (default_dir / path).resolve()
        if not path.exists() or not path.is_dir():
            return default_dir
        return path

    def _save_last_folder(self, folder: Path) -> None:
        parser = configparser.ConfigParser()
        parser["app"] = {"last_folder": str(folder)}
        try:
            with self.config_path.open("w", encoding="utf-8") as f:
                parser.write(f)
        except OSError:
            pass

    def _load_image(self, target: str) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select image",
            str(self.last_folder),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
        )
        if not file_path:
            return

        image = QImage(file_path)
        if image.isNull():
            QMessageBox.critical(
                self,
                "Failed to load image",
                f"Could not open file:\n{file_path}",
            )
            return

        selected_path = Path(file_path)
        self.last_folder = selected_path.parent
        self._save_last_folder(self.last_folder)

        if target == "a":
            self.image_a = image
            self.label_a.setText(f"Image A: {selected_path.name}")
        else:
            self.image_b = image
            self.label_b.setText(f"Image B: {selected_path.name}")

        self.canvas.set_images(self.image_a, self.image_b)

    def _unload_image(self, target: str) -> None:
        if target == "a":
            self.image_a = None
            self.label_a.setText("Image A: Not loaded")
        else:
            self.image_b = None
            self.label_b.setText("Image B: Not loaded")

        self.canvas.set_images(self.image_a, self.image_b, reset_view=False)

    def _clear_workspace(self) -> None:
        self.image_a = None
        self.image_b = None
        self.label_a.setText("Image A: Not loaded")
        self.label_b.setText("Image B: Not loaded")
        self.canvas.set_images(None, None, reset_view=True)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.MouseButtonPress:
            return super().eventFilter(watched, event)

        focused = self.focusWidget()
        if focused in {self.lens_zoom_input, self.lens_size_input}:
            widget = QApplication.widgetAt(event.globalPosition().toPoint())
            in_zoom = widget is not None and (
                widget is self.lens_zoom_input or self.lens_zoom_input.isAncestorOf(widget)
            )
            in_size = widget is not None and (
                widget is self.lens_size_input or self.lens_size_input.isAncestorOf(widget)
            )
            if not in_zoom and not in_size:
                focused.clearFocus()
                self.centralWidget().setFocus()
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:  # noqa: N802
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
