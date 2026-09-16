import os
import sys
import queue
import time
import traceback
import cv2
from PyQt5.QtCore import Qt, QDateTime, QSize, QTimer, QRect, QPoint
from PyQt5.QtGui import QImage, QPixmap, QIcon, QPainter, QPen, QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
                             QFileDialog, QPushButton, QComboBox, QScrollArea)

DEBUG = os.environ.get('USB_CAM_DEBUG', '0') == '1'

def debug_log(msg):
    if DEBUG:
        sys.stderr.write(f"[DEBUG {time.time():.3f}] {msg}\n")
        sys.stderr.flush()


class CameraPicture(QLabel):
    EDGE_MARGIN = 35

    def __init__(self, camera_widget):
        super().__init__()
        debug_log("CameraPicture.__init__ start")
        self.camera_widget = camera_widget
        self.setAlignment(Qt.AlignCenter)
        self.setFrameShape(QFrame.Box)
        self.setMinimumSize(320, 240)

        self.rect_img = None
        self._stored_rect = None
        self.select_mode_active = False
        self.recording_locked = False

        self.drag_type = None
        self.drag_start_pos = None
        self.drag_start_rect = None

        self.display_rect = None
        self.original_size = None
        self.fps_text = "FPS: 0.0"

        self.setMouseTracking(True)
        debug_log("CameraPicture.__init__ done")

    # ---------- 坐标转换 ----------
    def widget_to_image(self, widget_pos):
        debug_log(f"widget_to_image called with pos=({widget_pos.x()},{widget_pos.y()})")
        if not self.display_rect or not self.original_size:
            debug_log("widget_to_image: display_rect or original_size is None")
            return None
        if self.display_rect.width() == 0 or self.original_size[0] == 0:
            debug_log("widget_to_image: width or original width is 0")
            return None
        if not self.display_rect.contains(widget_pos):
            debug_log("widget_to_image: pos not in display_rect")
            return None
        rel_x = (widget_pos.x() - self.display_rect.x()) / self.display_rect.width()
        rel_y = (widget_pos.y() - self.display_rect.y()) / self.display_rect.height()
        img_x = int(rel_x * self.original_size[0])
        img_y = int(rel_y * self.original_size[1])
        img_x = max(0, min(img_x, self.original_size[0] - 1))
        img_y = max(0, min(img_y, self.original_size[1] - 1))
        result = QPoint(img_x, img_y)
        debug_log(f"widget_to_image result: ({img_x},{img_y})")
        return result

    def image_to_widget(self, img_point):
        debug_log(f"image_to_widget called with ({img_point.x()},{img_point.y()})")
        if not self.display_rect or not self.original_size:
            debug_log("image_to_widget: display_rect or original_size None")
            return None
        if self.original_size[0] == 0 or self.original_size[1] == 0:
            debug_log("image_to_widget: original size zero")
            return None
        rel_x = img_point.x() / self.original_size[0]
        rel_y = img_point.y() / self.original_size[1]
        wx = self.display_rect.x() + int(rel_x * self.display_rect.width())
        wy = self.display_rect.y() + int(rel_y * self.display_rect.height())
        result = QPoint(wx, wy)
        debug_log(f"image_to_widget result: ({wx},{wy})")
        return result

    def image_rect_to_widget(self, img_rect):
        debug_log("image_rect_to_widget called")
        if not img_rect or not img_rect.isValid():
            debug_log("image_rect_to_widget: invalid img_rect")
            return None
        if not self.display_rect or not self.original_size:
            debug_log("image_rect_to_widget: display_rect or original_size None")
            return None
        if self.original_size[0] == 0 or self.original_size[1] == 0:
            debug_log("image_rect_to_widget: original size zero")
            return None
        tl = self.image_to_widget(img_rect.topLeft())
        br = self.image_to_widget(img_rect.bottomRight())
        if tl is None or br is None:
            debug_log("image_rect_to_widget: tl or br is None")
            return None
        result = QRect(tl, br)
        debug_log(f"image_rect_to_widget result: {result}")
        return result

    # ---------- 矩形操作 ----------
    def create_default_rect(self):
        debug_log("create_default_rect start")
        if not self.original_size:
            debug_log("create_default_rect: original_size None")
            return
        w, h = self.original_size
        rect_w = max(4, (w // 3) // 4 * 4)
        rect_h = max(4, (h // 3) // 4 * 4)
        x = (w - rect_w) // 2
        y = (h - rect_h) // 2
        self.rect_img = QRect(x, y, rect_w, rect_h)
        debug_log(f"create_default_rect: created {self.rect_img}")

    def has_selection(self):
        return self.rect_img is not None and not self.rect_img.isNull() and self.rect_img.isValid()

    def get_image_rect(self):
        if self.has_selection():
            return QRect(self.rect_img)
        return None

    def set_image_rect(self, rect):
        if rect and rect.isValid():
            self.rect_img = QRect(rect)
            self.update()

    def clear_selection(self):
        self.rect_img = None
        self._stored_rect = None
        self.update()

    def clear_stored_rect(self):
        self._stored_rect = None
        self.rect_img = None
        self.update()

    # ---------- 模式控制 ----------
    def set_select_mode(self, active):
        debug_log(f"set_select_mode active={active}")
        if self.recording_locked:
            debug_log("set_select_mode: recording locked, ignoring")
            return
        self.select_mode_active = active
        if active:
            if self._stored_rect is not None and self._stored_rect.isValid():
                self.rect_img = QRect(self._stored_rect)
                debug_log(f"set_select_mode: restored stored rect {self.rect_img}")
            else:
                self.create_default_rect()
            self.camera_widget.pause_video(True)
            self.setCursor(Qt.ArrowCursor)
        else:
            if self.has_selection():
                self._stored_rect = QRect(self.rect_img)
                debug_log(f"set_select_mode: stored rect {self._stored_rect}")
            else:
                self._stored_rect = None
            self.rect_img = None
            self.camera_widget.pause_video(False)
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_recording_locked(self, locked):
        debug_log(f"set_recording_locked locked={locked}")
        self.recording_locked = locked
        if locked:
            self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        self.update()

    # ---------- 检测鼠标命中 ----------
    def detect_hit(self, img_pos):
        debug_log(f"detect_hit called with img_pos=({img_pos.x()},{img_pos.y()})")
        if not self.has_selection():
            debug_log("detect_hit: no selection")
            return None, None
        rect = self.rect_img
        debug_log(f"detect_hit: rect={rect}")
        if rect.width() < 20 or rect.height() < 20:
            debug_log("detect_hit: rect too small, treat as move")
            return 'move', None

        margin = self.EDGE_MARGIN
        x, y = img_pos.x(), img_pos.y()
        left = rect.left()
        right = rect.right()
        top = rect.top()
        bottom = rect.bottom()

        inside = (left <= x <= right and top <= y <= bottom)
        if not inside:
            debug_log("detect_hit: not inside")
            return None, None

        on_left = (x - left) < margin
        on_right = (right - x) < margin
        on_top = (y - top) < margin
        on_bottom = (bottom - y) < margin
        debug_log(f"detect_hit: on_left={on_left}, on_right={on_right}, on_top={on_top}, on_bottom={on_bottom}")

        if on_left and on_top:
            result = ('resize', 'tl')
        elif on_right and on_top:
            result = ('resize', 'tr')
        elif on_left and on_bottom:
            result = ('resize', 'bl')
        elif on_right and on_bottom:
            result = ('resize', 'br')
        elif on_left:
            result = ('resize', 'left')
        elif on_right:
            result = ('resize', 'right')
        elif on_top:
            result = ('resize', 'top')
        elif on_bottom:
            result = ('resize', 'bottom')
        else:
            result = ('move', None)
        debug_log(f"detect_hit result: {result}")
        return result

    # ---------- 鼠标事件 ----------
    def mousePressEvent(self, event):
        debug_log(f"mousePressEvent button={event.button()}, pos=({event.pos().x()},{event.pos().y()})")
        if event.button() != Qt.LeftButton:
            return
        if self.recording_locked or not self.select_mode_active:
            debug_log("mousePressEvent: ignored (locked or inactive)")
            return

        img_pos = self.widget_to_image(event.pos())
        if img_pos is None:
            debug_log("mousePressEvent: img_pos is None")
            return

        hit_type, direction = self.detect_hit(img_pos)
        if hit_type is None:
            debug_log("mousePressEvent: no hit")
            return

        self.drag_start_pos = img_pos
        self.drag_start_rect = QRect(self.rect_img) if self.has_selection() else None

        if hit_type == 'move':
            self.drag_type = 'move'
            self.setCursor(Qt.ClosedHandCursor)
        elif hit_type == 'resize':
            self.drag_type = 'resize_' + direction
            cursor_map = {
                'left': Qt.SizeHorCursor,
                'right': Qt.SizeHorCursor,
                'top': Qt.SizeVerCursor,
                'bottom': Qt.SizeVerCursor,
                'tl': Qt.SizeFDiagCursor,
                'br': Qt.SizeFDiagCursor,
                'tr': Qt.SizeBDiagCursor,
                'bl': Qt.SizeBDiagCursor,
            }
            self.setCursor(cursor_map.get(direction, Qt.ArrowCursor))
        debug_log(f"mousePressEvent: drag_type={self.drag_type}")

    def mouseMoveEvent(self, event):
        # 未拖拽时，实时更新光标
        if self.drag_type is None:
            if not self.recording_locked and self.select_mode_active and self.has_selection():
                img_pos = self.widget_to_image(event.pos())
                if img_pos:
                    hit_type, direction = self.detect_hit(img_pos)
                    if hit_type == 'move':
                        self.setCursor(Qt.OpenHandCursor)
                    elif hit_type == 'resize':
                        cursor_map = {
                            'left': Qt.SizeHorCursor,
                            'right': Qt.SizeHorCursor,
                            'top': Qt.SizeVerCursor,
                            'bottom': Qt.SizeVerCursor,
                            'tl': Qt.SizeFDiagCursor,
                            'br': Qt.SizeFDiagCursor,
                            'tr': Qt.SizeBDiagCursor,
                            'bl': Qt.SizeBDiagCursor,
                        }
                        self.setCursor(cursor_map.get(direction, Qt.ArrowCursor))
                    else:
                        self.setCursor(Qt.ArrowCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return

        # ---------- 拖拽逻辑 ----------
        img_pos = self.widget_to_image(event.pos())
        if img_pos is None:
            return

        if not self.drag_start_rect or not self.drag_start_rect.isValid():
            return

        dx = img_pos.x() - self.drag_start_pos.x()
        dy = img_pos.y() - self.drag_start_pos.y()
        new_rect = QRect(self.drag_start_rect)

        if self.drag_type == 'move':
            new_rect.moveTopLeft(new_rect.topLeft() + QPoint(dx, dy))
            if new_rect.left() < 0:
                new_rect.moveLeft(0)
            if new_rect.top() < 0:
                new_rect.moveTop(0)
            if new_rect.right() > self.original_size[0] - 1:
                new_rect.moveRight(self.original_size[0] - 1)
            if new_rect.bottom() > self.original_size[1] - 1:
                new_rect.moveBottom(self.original_size[1] - 1)
        else:
            direction = self.drag_type.split('_')[1] if '_' in self.drag_type else ''
            left, top, right, bottom = new_rect.left(), new_rect.top(), new_rect.right(), new_rect.bottom()
            # 使用首字母匹配，支持 'tl', 'tr', 'bl', 'br' 以及 'left', 'right', 'top', 'bottom'
            if 'l' in direction:
                left = min(right - 4, left + dx)
            if 'r' in direction:
                right = max(left + 4, right + dx)
            if 't' in direction:
                top = min(bottom - 4, top + dy)
            if 'b' in direction:
                bottom = max(top + 4, bottom + dy)
            if left > right:
                left, right = right, left
            if top > bottom:
                top, bottom = bottom, top
            if right - left < 4:
                diff = 4 - (right - left)
                if 'l' in direction:
                    left = max(0, left - diff)
                else:
                    right = min(self.original_size[0] - 1, right + diff)
            if bottom - top < 4:
                diff = 4 - (bottom - top)
                if 't' in direction:
                    top = max(0, top - diff)
                else:
                    bottom = min(self.original_size[1] - 1, bottom + diff)
            left = max(0, min(left, self.original_size[0] - 4))
            top = max(0, min(top, self.original_size[1] - 4))
            right = max(left + 4, min(right, self.original_size[0] - 1))
            bottom = max(top + 4, min(bottom, self.original_size[1] - 1))
            w = (right - left + 1) // 4 * 4
            h = (bottom - top + 1) // 4 * 4
            if w < 4: w = 4
            if h < 4: h = 4
            right = left + w - 1
            bottom = top + h - 1
            if right >= self.original_size[0]:
                left = self.original_size[0] - w
                right = self.original_size[0] - 1
            if bottom >= self.original_size[1]:
                top = self.original_size[1] - h
                bottom = self.original_size[1] - 1
            new_rect = QRect(left, top, w, h)

        if new_rect != self.rect_img:
            debug_log(f"mouseMoveEvent: updating rect to {new_rect}")
            self.rect_img = new_rect
            self.update()

    def mouseReleaseEvent(self, event):
        debug_log("mouseReleaseEvent")
        if event.button() == Qt.LeftButton:
            if self.drag_type:
                self.drag_type = None
                self.drag_start_rect = None
                self.setCursor(Qt.ArrowCursor)
                self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        debug_log("paintEvent start")
        try:
            super().paintEvent(event)
            painter = QPainter(self)

            if self.has_selection() and self.display_rect:
                widget_rect = self.image_rect_to_widget(self.rect_img)
                if widget_rect and widget_rect.isValid():
                    if not self.rect().contains(widget_rect):
                        widget_rect = widget_rect.intersected(self.rect())
                    if widget_rect.isValid():
                        if self.recording_locked:
                            pen = QPen(Qt.red, 1, Qt.DashLine)
                        else:
                            pen = QPen(Qt.red, 1, Qt.SolidLine)
                        painter.setPen(pen)
                        painter.drawRect(widget_rect)
                        center = widget_rect.center()
                        cross_size = 10
                        painter.setPen(QPen(Qt.red, 2))
                        painter.drawLine(center.x() - cross_size, center.y(),
                                         center.x() + cross_size, center.y())
                        painter.drawLine(center.x(), center.y() - cross_size,
                                         center.x(), center.y() + cross_size)

            if self.fps_text:
                painter.setPen(QPen(Qt.green, 2))
                painter.drawText(10, 30, self.fps_text)

            painter.end()
        except Exception as e:
            debug_log(f"paintEvent exception: {e}\n{traceback.format_exc()}")
        debug_log("paintEvent end")

    # ---------- 显示帧 ----------
    def display_frame(self, frame, fps=None):
        debug_log("display_frame start")
        try:
            self.original_size = (frame.shape[1], frame.shape[0])
            if fps is not None:
                self.fps_text = f"FPS: {fps:.1f}"
            image = QImage(frame, frame.shape[1], frame.shape[0],
                           frame.strides[0], QImage.Format_RGB888)
            pix = QPixmap.fromImage(image)

            if self.camera_widget.zoom_mode == 0:
                viewport_size = self.camera_widget.scroll_area.viewport().size()
                scaled = pix.scaled(viewport_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.setPixmap(scaled)
                self.setFixedSize(scaled.size())
            else:
                self.setPixmap(pix)
                self.setFixedSize(pix.size())

            if self.pixmap():
                p = self.pixmap()
                p_sz = p.size()
                w_sz = self.size()
                x = (w_sz.width() - p_sz.width()) // 2
                y = (w_sz.height() - p_sz.height()) // 2
                self.display_rect = QRect(x, y, p_sz.width(), p_sz.height())
                debug_log(f"display_frame: display_rect={self.display_rect}")

            self.update()
        except Exception as e:
            debug_log(f"display_frame exception: {e}\n{traceback.format_exc()}")
        debug_log("display_frame end")
