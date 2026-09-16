import os
import sys
import queue
import time
import traceback
import shutil
import cv2
from PyQt5.QtCore import Qt, QDateTime, QSize, QTimer, QRect, QPoint, QUrl
from PyQt5.QtGui import QImage, QPixmap, QIcon, QPainter, QPen, QColor, QDesktopServices
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
                             QFileDialog, QPushButton, QComboBox, QScrollArea,
                             QCheckBox, QSpinBox)
from camera_controller import CameraController
from file_writer import FileWriter
from i18n import tr
from camera_picture import CameraPicture, debug_log


class CameraWidget(QWidget):
    RECORD_ICON = 'rodentia-icons_media-record.svg'
    STOP_ICON = 'rodentia-icons_media-playback-stop.svg'
    CAMERA_ICON = 'mono-camera-mount.svg'
    MIN_TIMER_DELAY = 20

    def __init__(self):
        QWidget.__init__(self)
        debug_log("CameraWidget.__init__ start")
        self.main_window = None
        self.controller = CameraController()
        self.file_writer = None
        self.cam_width = 640
        self.cam_height = 480
        self.timer = None
        self.timer_delay = 40
        self.flip = None
        self.picture = None
        self.video = False
        self.current_lang = 'en'
        self.last_frame = None
        self.zoom_mode = 0
        self.recording_mode = 'full'

        inst_dir = os.path.dirname(sys.argv[0])
        if os.path.islink(sys.argv[0]):
            inst_dir = os.path.join(inst_dir, os.path.dirname(os.readlink(sys.argv[0])))
        self.icon_dir = os.path.join(inst_dir, 'icons')

        self.file_writer = FileWriter(self._show_message_from_thread)
        self.requests_queue = queue.Queue(5)

        self._init_ui()
        self.enable_buttons(False)

        self.recording_timer = QTimer()
        self.recording_timer.timeout.connect(self.update_recording_time)
        self.recording_elapsed = 0

        self.frame_count = 0
        self.fps_timer = QTimer()
        self.fps_timer.timeout.connect(self.calc_fps)
        self.last_fps_time = time.time()
        self.current_fps = 0.0
        debug_log("CameraWidget.__init__ done")

    def _init_ui(self):
        self.btn_update_cameras = QPushButton('Re-Scan Cameras')
        self.btn_update_cameras.clicked.connect(self.update_cameras)

        self.combo_cams = QComboBox()
        self.combo_cams.currentIndexChanged.connect(self.change_camera)

        self.combo_resolution = QComboBox()
        self.combo_resolution.currentIndexChanged.connect(self.change_resolution)

        self.combo_format = QComboBox()
        self.combo_format.currentIndexChanged.connect(self.change_format)

        self.combo_flip = QComboBox()
        self.combo_flip.currentIndexChanged.connect(self.change_flip)
        for item in ['No Flip', 'Flip Horizontally', 'Flip Vertically', 'Flip Both']:
            self.combo_flip.addItem(item)

        self.label_camera = QLabel('Camera:')
        self.label_resolution = QLabel('Resolution:')
        self.label_format = QLabel('Format:')
        self.label_flip = QLabel('Flip:')

        self.combo_zoom = QComboBox()
        self.combo_zoom.addItem('Adaptive')
        self.combo_zoom.addItem('Original (Scroll)')
        self.combo_zoom.currentIndexChanged.connect(self.change_zoom_mode)

        layout_group_cam = QHBoxLayout()
        layout_group_cam.addWidget(self.label_camera)
        layout_group_cam.addWidget(self.combo_cams)
        layout_group_cam.addWidget(self.label_resolution)
        layout_group_cam.addWidget(self.combo_resolution)
        layout_group_cam.addWidget(self.label_format)
        layout_group_cam.addWidget(self.combo_format)
        layout_group_cam.addWidget(self.label_flip)
        layout_group_cam.addWidget(self.combo_flip)
        layout_group_cam.addWidget(QLabel('Zoom:'))
        layout_group_cam.addWidget(self.combo_zoom)
        layout_group_cam.addWidget(self.btn_update_cameras)

        self.pixmap_view = CameraPicture(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.pixmap_view)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignCenter)

        layout_save = QHBoxLayout()

        self.btn_directory = QPushButton('Output Directory')
        self.btn_directory.clicked.connect(self.change_output_directory)
        layout_save.addWidget(self.btn_directory)

        self.label_directory = QLabel('')
        layout_save.addWidget(self.label_directory, stretch=1)
        self.set_output_directory(os.getcwd())

        self.combo_image_format = QComboBox()
        self.combo_image_format.addItem('JPEG (*.jpg)', 'jpg')
        self.combo_image_format.addItem('PNG (*.png)', 'png')
        self.combo_image_format.addItem('BMP (*.bmp)', 'bmp')
        layout_save.addWidget(QLabel('Photo Format:'))
        layout_save.addWidget(self.combo_image_format)

        self.combo_recording_mode = QComboBox()
        self.combo_recording_mode.addItem('Full Screen', 'full')
        self.combo_recording_mode.addItem('Region', 'region')
        self.combo_recording_mode.currentIndexChanged.connect(self.change_recording_mode)
        layout_save.addWidget(QLabel('Recording Mode:'))
        layout_save.addWidget(self.combo_recording_mode)

        self.btn_take_photo = QPushButton('Take Photo')
        self.btn_take_photo.setIcon(QIcon(os.path.join(self.icon_dir, self.CAMERA_ICON)))
        self.btn_take_photo.clicked.connect(self.take_picture)
        layout_save.addWidget(self.btn_take_photo)

        self.btn_record_video = QPushButton('Record Video')
        self.btn_record_video.setIcon(QIcon(os.path.join(self.icon_dir, self.RECORD_ICON)))
        self.btn_record_video.clicked.connect(self.record_video)
        layout_save.addWidget(self.btn_record_video)

        self.btn_select_region = QPushButton('Select Region')
        self.btn_select_region.setCheckable(True)
        self.btn_select_region.toggled.connect(self.toggle_region_selection)
        layout_save.addWidget(self.btn_select_region)

        # 添加帮助按钮
        self.btn_help = QPushButton('Help')
        self.btn_help.clicked.connect(self.show_help)
        layout_save.addWidget(self.btn_help)

        self.label_recording_time = QLabel('')
        self.label_recording_time.setStyleSheet('color: red; font-weight: bold;')
        self.label_recording_time.hide()
        layout_save.addWidget(self.label_recording_time)

        # 容量录制设置
        layout_capacity = QHBoxLayout()
        self.check_capacity_limit = QCheckBox('Limit Capacity')
        self.check_capacity_limit.setChecked(True)
        layout_capacity.addWidget(self.check_capacity_limit)

        self.label_segment_size = QLabel('Segment Size (MB):')
        layout_capacity.addWidget(self.label_segment_size)
        self.spin_segment_size = QSpinBox()
        self.spin_segment_size.setRange(1, 100000)
        self.spin_segment_size.setValue(500)
        layout_capacity.addWidget(self.spin_segment_size)

        self.label_total_capacity = QLabel('Total Capacity (GB):')
        layout_capacity.addWidget(self.label_total_capacity)
        self.spin_total_capacity = QSpinBox()
        self.spin_total_capacity.setRange(1, 10000)
        self.spin_total_capacity.setValue(10)
        layout_capacity.addWidget(self.spin_total_capacity)

        self.btn_use_disk_50 = QPushButton('Use 50% of free disk')
        self.btn_use_disk_50.clicked.connect(self.use_disk_50)
        layout_capacity.addWidget(self.btn_use_disk_50)

        self.label_capacity_status = QLabel('')
        layout_capacity.addWidget(self.label_capacity_status)

        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(layout_group_cam)
        self.main_layout.addWidget(self.scroll_area)
        self.main_layout.addLayout(layout_save)
        self.main_layout.addLayout(layout_capacity)
        self.setLayout(self.main_layout)

        self.retranslate()

    def show_help(self):
        """打开当前目录下的 UserReader.md 帮助文档"""
        help_path = os.path.join(os.getcwd(), 'UserReader.md')
        if os.path.exists(help_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(help_path))
        else:
            self.show_message(tr('Help file not found.', self.current_lang))

    def use_disk_50(self):
        """根据输出目录所在磁盘剩余空间，建议总容量为剩余空间的 50%"""
        free = shutil.disk_usage(self.output_path).free
        suggested_gb = int(free * 0.5 / (1024 ** 3))
        if suggested_gb < 1:
            suggested_gb = 1
        self.spin_total_capacity.setValue(suggested_gb)

    def change_recording_mode(self, index):
        mode = self.combo_recording_mode.currentData()
        if self.video:
            self.show_message(tr('Cannot change mode while recording.', self.current_lang))
            self.combo_recording_mode.blockSignals(True)
            self.combo_recording_mode.setCurrentIndex(0 if mode == 'region' else 1)
            self.combo_recording_mode.blockSignals(False)
            return

        self.recording_mode = mode
        if mode == 'full':
            self.pixmap_view.clear_stored_rect()
            if self.btn_select_region.isChecked():
                self.btn_select_region.setChecked(False)
            if self.pixmap_view.select_mode_active:
                self.pixmap_view.set_select_mode(False)
        else:
            if not self.btn_select_region.isChecked():
                self.btn_select_region.setChecked(True)
            if not self.pixmap_view.select_mode_active:
                self.pixmap_view.set_select_mode(True)
            self.show_message(tr('Adjust the rectangle, click button again to fix.', self.current_lang))
        self.clear_message()

    def change_zoom_mode(self, index):
        self.zoom_mode = index
        if self.last_frame is not None:
            self.pixmap_view.display_frame(self.last_frame)

    def resizeEvent(self, event):
        if self.zoom_mode == 0 and self.last_frame is not None:
            self.pixmap_view.display_frame(self.last_frame)
        super().resizeEvent(event)

    def toggle_region_selection(self, checked):
        if self.video:
            self.show_message(tr('Cannot change region while recording.', self.current_lang))
            self.btn_select_region.blockSignals(True)
            self.btn_select_region.setChecked(not checked)
            self.btn_select_region.blockSignals(False)
            return
        if checked:
            self.pixmap_view.set_select_mode(True)
            self.show_message(tr('Adjust the rectangle, click button again to fix.', self.current_lang))
        else:
            self.pixmap_view.set_select_mode(False)
            self.clear_message()

    def pause_video(self, pause):
        if self.timer:
            if pause:
                self.timer.stop()
            else:
                self.timer.start(self.timer_delay)

    def take_picture(self):
        ext = self.combo_image_format.currentData()
        filename = self.generate_filename(ext) + '.' + ext
        self.picture = filename

    def update_recording_time(self):
        self.recording_elapsed += 1
        hours = self.recording_elapsed // 3600
        minutes = (self.recording_elapsed % 3600) // 60
        seconds = self.recording_elapsed % 60
        time_str = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        if self.video:
            recorded, total, remaining, capacity_reached = self.file_writer.get_recording_status()
            if total > 0 and total < 2**63 - 1:
                recorded_gb = recorded / (1024 ** 3)
                total_gb = total / (1024 ** 3)
                remaining_gb = remaining / (1024 ** 3)
                status = f'{time_str} | {tr("Recorded", self.current_lang)} {recorded_gb:.2f} GB / {total_gb:.2f} GB | {tr("Remaining", self.current_lang)} {remaining_gb:.2f} GB'
            else:
                status = time_str
            self.label_recording_time.setText(status)
            if capacity_reached:
                self.show_message(tr('Capacity reached, recording stopped.', self.current_lang))
                self.end_video()
        else:
            self.label_recording_time.setText(time_str)

    def calc_fps(self):
        now = time.time()
        elapsed = now - self.last_fps_time
        if elapsed >= 0.5:
            self.current_fps = self.frame_count / elapsed
            self.frame_count = 0
            self.last_fps_time = now

    def retranslate(self):
        lang = self.current_lang
        self.btn_directory.setText(tr('Output Directory', lang))
        self.btn_take_photo.setText(tr('Take Photo', lang))
        self.btn_update_cameras.setText(tr('Re-Scan Cameras', lang))
        self.label_camera.setText(tr('Camera:', lang))
        self.label_resolution.setText(tr('Resolution:', lang))
        self.label_format.setText(tr('Format:', lang))
        self.label_flip.setText(tr('Flip:', lang))
        self.btn_select_region.setText(tr('Select Region', lang))
        self.btn_help.setText(tr('Help', lang))
        self.check_capacity_limit.setText(tr('Limit Capacity', lang))
        self.label_segment_size.setText(tr('Segment Size (MB):', lang))
        self.label_total_capacity.setText(tr('Total Capacity (GB):', lang))
        self.btn_use_disk_50.setText(tr('Use 50% of free disk', lang))
        self.combo_zoom.setItemText(0, tr('Adaptive', lang))
        self.combo_zoom.setItemText(1, tr('Original (Scroll)', lang))

        flip_items = ['No Flip', 'Flip Horizontally', 'Flip Vertically', 'Flip Both']
        current_flip = self.combo_flip.currentIndex()
        self.combo_flip.blockSignals(True)
        self.combo_flip.clear()
        for item in flip_items:
            self.combo_flip.addItem(tr(item, lang))
        self.combo_flip.setCurrentIndex(current_flip if current_flip >= 0 else 0)
        self.combo_flip.blockSignals(False)

        format_options = [
            (tr('Default', lang), None),
            (tr('MJPEG', lang), cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')),
            (tr('YUYV', lang), cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V')),
            (tr('RGB3', lang), cv2.VideoWriter_fourcc('R', 'G', 'B', '3'))
        ]
        current_format_idx = self.combo_format.currentIndex()
        self.combo_format.blockSignals(True)
        self.combo_format.clear()
        for text, data in format_options:
            self.combo_format.addItem(text, data)
        if current_format_idx >= 0 and current_format_idx < self.combo_format.count():
            self.combo_format.setCurrentIndex(current_format_idx)
        self.combo_format.blockSignals(False)

        mode_idx = self.combo_recording_mode.currentIndex()
        self.combo_recording_mode.blockSignals(True)
        self.combo_recording_mode.clear()
        self.combo_recording_mode.addItem(tr('Full Screen', lang), 'full')
        self.combo_recording_mode.addItem(tr('Region', lang), 'region')
        self.combo_recording_mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self.combo_recording_mode.blockSignals(False)

        if self.video:
            self.btn_record_video.setText(tr('Stop Recording', lang))
        else:
            self.btn_record_video.setText(tr('Record Video', lang))

    def set_language(self, lang):
        if lang not in ['en', 'zh']:
            return
        self.current_lang = lang
        self.retranslate()
        if self.main_window:
            self.main_window.retranslate()

    def _show_message_from_thread(self, msg_key, arg=''):
        self.requests_queue.put(lambda: self.show_message(tr(msg_key, self.current_lang) % arg))

    def show_message(self, msg):
        if self.main_window:
            self.main_window.show_message(msg)

    def clear_message(self):
        self.show_message('')

    def enable_buttons(self, enable):
        for btn in [self.btn_take_photo, self.btn_record_video,
                    self.combo_flip, self.combo_resolution, self.combo_format,
                    self.btn_select_region, self.combo_zoom, self.combo_image_format,
                    self.combo_recording_mode, self.check_capacity_limit,
                    self.spin_segment_size, self.spin_total_capacity, self.btn_use_disk_50]:
            btn.setEnabled(enable)

    def change_output_directory(self):
        directory = QFileDialog.getExistingDirectory(
            None, tr('choose output directory', self.current_lang),
            self.output_path, QFileDialog.ShowDirsOnly)
        if directory:
            self.set_output_directory(directory)
            self.clear_message()
        else:
            self.show_message(tr('Output directory not changed.', self.current_lang))

    def set_output_directory(self, directory):
        self.output_path = directory
        self.label_directory.setText(directory)

    def update_cameras(self):
        self.end_camera()
        cameras = CameraController.enumerate_cameras()
        self.combo_cams.clear()
        self.combo_cams2camera = {}
        for idx, info in cameras.items():
            item = f'{idx}: {info}'
            self.combo_cams2camera[item] = idx
            self.combo_cams.addItem(item)
        if not cameras:
            self.show_message(tr('NO_CAMERAS', self.current_lang))

    def change_camera(self, i):
        if i < 0:
            return
        self.end_camera()
        item_text = self.combo_cams.itemText(i)
        idx = self.combo_cams2camera[item_text]

        yuyv_fourcc = cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V')
        if self.controller.open_camera(idx, fourcc=yuyv_fourcc):
            self._on_camera_opened()
        else:
            if self.controller.open_camera(idx):
                self._on_camera_opened()
            else:
                self.show_message(tr('CANNOT_OPEN', self.current_lang) % idx)

    def _on_camera_opened(self):
        self.cam_width, self.cam_height = self.controller.get_resolution()
        self.cam_fps = self.controller.get_fps()
        self.pixmap_view.setMinimumSize(self.cam_width // 2, self.cam_height // 2)

        cam = self.controller.cam
        if cam:
            supported = CameraController.enumerate_resolutions(cam)
            if supported:
                supported.sort(key=lambda x: x[0] * x[1], reverse=True)
                best_w, best_h = supported[0]
                if (best_w, best_h) != (self.cam_width, self.cam_height):
                    if self.controller.set_resolution(best_w, best_h):
                        self.cam_width, self.cam_height = best_w, best_h
                        self.cam_fps = self.controller.get_fps()
                        self.pixmap_view.setMinimumSize(self.cam_width // 2, self.cam_height // 2)
            supported = CameraController.enumerate_resolutions(cam)
            current_res = (self.cam_width, self.cam_height)
            if current_res not in supported:
                supported.append(current_res)
            supported.sort(key=lambda x: x[0] * x[1])
            self.combo_resolution.blockSignals(True)
            self.combo_resolution.clear()
            for w, h in supported:
                self.combo_resolution.addItem(f"{w}x{h}")
            idx = self.combo_resolution.findText(f"{self.cam_width}x{self.cam_height}")
            if idx >= 0:
                self.combo_resolution.setCurrentIndex(idx)
            self.combo_resolution.blockSignals(False)

            actual_fourcc = self.controller.get_actual_fourcc()
            if actual_fourcc is not None:
                self.combo_format.blockSignals(True)
                for i in range(self.combo_format.count()):
                    if self.combo_format.itemData(i) == actual_fourcc:
                        self.combo_format.setCurrentIndex(i)
                        break
                self.combo_format.blockSignals(False)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer_delay = int(1000.0 / self.cam_fps)
        if self.timer_delay < self.MIN_TIMER_DELAY:
            self.timer_delay = self.MIN_TIMER_DELAY
        self.timer.start(self.timer_delay)
        self.enable_buttons(True)
        self.clear_message()

        self.frame_count = 0
        self.last_fps_time = time.time()
        self.fps_timer.start(500)

    def end_camera(self):
        self.enable_buttons(False)
        if self.timer:
            self.timer.stop()
            self.timer = None
        self.fps_timer.stop()
        self.controller.close_camera()
        self.end_video()

    def change_resolution(self, i):
        if i < 0 or not self.controller.is_opened():
            return
        res_str = self.combo_resolution.currentText()
        w, h = map(int, res_str.split('x'))
        if (self.cam_width, self.cam_height) == (w, h):
            return
        if self.controller.set_resolution(w, h):
            new_w, new_h = self.controller.get_resolution()
            self.cam_width, self.cam_height = new_w, new_h
            self.pixmap_view.setMinimumSize(self.cam_width // 2, self.cam_height // 2)
            self.show_message(tr('Resolution set', self.current_lang) % (new_w, new_h))
        else:
            new_w, new_h = self.controller.get_resolution()
            self.show_message(tr('Resolution not supported', self.current_lang) % (new_w, new_h))

    def change_format(self, i):
        if i < 0 or not self.controller.is_opened():
            return
        fourcc = self.combo_format.itemData(i)
        if fourcc is None:
            return
        if self.controller.set_fourcc(fourcc):
            self.show_message(tr('Format set', self.current_lang) % self.controller.fourcc_to_str(fourcc))
        else:
            actual = self.controller.get_actual_fourcc()
            self.show_message(tr('Format not supported', self.current_lang) % self.controller.fourcc_to_str(actual))

    def change_flip(self, i):
        idx2flip = [None, 1, 0, -1]
        self.flip = idx2flip[i]

    def update_frame(self):
        while not self.requests_queue.empty():
            req = self.requests_queue.get()
            req()
            self.requests_queue.task_done()

        bgr_frame, rgb_frame = self.controller.read_frame()
        if rgb_frame is None:
            return
        if self.flip is not None:
            bgr_frame = cv2.flip(bgr_frame, self.flip)
            rgb_frame = cv2.flip(rgb_frame, self.flip)

        self.last_frame = rgb_frame
        self.frame_count += 1

        if self.picture:
            self.file_writer.save_picture(self.picture, bgr_frame)
            self.picture = None

        if self.video:
            if self.recording_mode == 'region' and self.pixmap_view.has_selection():
                rect = self.pixmap_view.get_image_rect()
                if rect and rect.isValid():
                    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
                    x = max(0, min(x, bgr_frame.shape[1] - 1))
                    y = max(0, min(y, bgr_frame.shape[0] - 1))
                    w = min(w, bgr_frame.shape[1] - x)
                    h = min(h, bgr_frame.shape[0] - y)
                    if w > 0 and h > 0:
                        cropped = bgr_frame[y:y+h, x:x+w]
                        self.file_writer.write_video_frame(cropped)
                    else:
                        self.file_writer.write_video_frame(bgr_frame)
                else:
                    self.file_writer.write_video_frame(bgr_frame)
            else:
                self.file_writer.write_video_frame(bgr_frame)

        self.pixmap_view.display_frame(rgb_frame, self.current_fps)

    # ---------- 录制控制（分段 + 容量限制） ----------
    def record_video(self):
        debug_log(f"record_video called, self.video={self.video}, select_mode_active={self.pixmap_view.select_mode_active}, _stored_rect={self.pixmap_view._stored_rect}")
        if self.video:
            debug_log("record_video: self.video is True, calling end_video() and returning")
            self.end_video()
            return

        # 启动逻辑
        if self.pixmap_view.select_mode_active:
            debug_log("record_video: exiting select mode")
            self.pixmap_view.set_select_mode(False)
            self.btn_select_region.blockSignals(True)
            self.btn_select_region.setChecked(False)
            self.btn_select_region.blockSignals(False)

        if self.recording_mode == 'region':
            rect_to_use = None
            if self.pixmap_view._stored_rect is not None:
                rect_to_use = QRect(self.pixmap_view._stored_rect)
                debug_log(f"record_video: using stored rect {rect_to_use}")
            else:
                debug_log("record_video: region mode but no stored rect")
                self.show_message(tr('Please select a region first.', self.current_lang))
                return

            self.pixmap_view.rect_img = rect_to_use
            video_width = rect_to_use.width()
            video_height = rect_to_use.height()
            self.pixmap_view.set_recording_locked(True)
        else:
            video_width = self.cam_width
            video_height = self.cam_height

        # 容量参数
        if self.check_capacity_limit.isChecked():
            segment_mb = self.spin_segment_size.value()
            total_gb = self.spin_total_capacity.value()
            segment_limit_bytes = segment_mb * 1024 * 1024
            total_limit_bytes = total_gb * 1024 * 1024 * 1024
            free = shutil.disk_usage(self.output_path).free
            if total_limit_bytes > free * 0.9:
                self.show_message(tr('Not enough disk space.', self.current_lang))
                return
        else:
            segment_limit_bytes = 2**63 - 1
            total_limit_bytes = 2**63 - 1

        base_filename = self.generate_filename('mp4')
        fps = 1000.0 / self.timer_delay

        debug_log(f"record_video: starting video to {base_filename}, width={video_width}, height={video_height}, fps={fps}, segment={segment_limit_bytes}, total={total_limit_bytes}")
        self.file_writer.start_video(base_filename, video_width, video_height, fps, segment_limit_bytes, total_limit_bytes)
        self.video = True
        self.btn_record_video.setText(tr('Stop Recording', self.current_lang))
        self.btn_record_video.setIcon(QIcon(os.path.join(self.icon_dir, self.STOP_ICON)))
        self.recording_elapsed = 0
        self.label_recording_time.setText('00:00:00')
        self.label_recording_time.show()
        self.recording_timer.start(1000)
        self.clear_message()
        self.btn_select_region.setEnabled(False)

        # 禁用可能影响录制的控件
        self.combo_resolution.setEnabled(False)
        self.combo_format.setEnabled(False)
        self.combo_recording_mode.setEnabled(False)
        self.combo_zoom.setEnabled(False)
        self.check_capacity_limit.setEnabled(False)
        self.spin_segment_size.setEnabled(False)
        self.spin_total_capacity.setEnabled(False)
        self.btn_use_disk_50.setEnabled(False)

        debug_log("record_video: recording started successfully")

    def end_video(self):
        debug_log(f"end_video called, self.video={self.video}")
        if self.video:
            debug_log("end_video: stopping video")
            self.file_writer.stop_video()
            self.video = False
            self.btn_record_video.setText(tr('Record Video', self.current_lang))
            self.btn_record_video.setIcon(QIcon(os.path.join(self.icon_dir, self.RECORD_ICON)))
            self.recording_timer.stop()
            self.label_recording_time.hide()
            self.pixmap_view.set_recording_locked(False)
            self.btn_select_region.setEnabled(True)
            self.clear_message()
            debug_log("end_video: video stopped")

            # 恢复控件
            self.combo_resolution.setEnabled(True)
            self.combo_format.setEnabled(True)
            self.combo_recording_mode.setEnabled(True)
            self.combo_zoom.setEnabled(True)
            self.check_capacity_limit.setEnabled(True)
            self.spin_segment_size.setEnabled(True)
            self.spin_total_capacity.setEnabled(True)
            self.btn_use_disk_50.setEnabled(True)
            self.label_capacity_status.setText('')

            if self.recording_mode == 'region':
                debug_log("end_video: region mode, restoring select mode")
                if self.pixmap_view._stored_rect is not None:
                    self.pixmap_view.set_select_mode(True)
                    self.btn_select_region.setChecked(True)
                    self.show_message(tr('Region ready, adjust or record again.', self.current_lang))
                else:
                    self.pixmap_view.set_select_mode(True)
                    self.btn_select_region.setChecked(True)
                    self.show_message(tr('Please adjust the region on the preview.', self.current_lang))
        else:
            debug_log("end_video: self.video is False, nothing to stop")

    def generate_filename(self, ext):
        fmt = 'yyyy-MM-dd_HH-mm-ss'
        return os.path.join(self.output_path,
                            QDateTime.currentDateTime().toString(fmt))

    def initialize(self, main_window):
        self.main_window = main_window
        self.update_cameras()
        if self.combo_cams.count() > 0:
            self.change_camera(0)

    def end_widget(self):
        self.end_camera()
        self.file_writer.stop_all()
