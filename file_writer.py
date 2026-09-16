import cv2
import queue
import threading
import os

class FileWriter:
    """管理图片保存和视频录制的线程，支持分段录制和容量限制。"""
    VIDEO_OPEN = 0
    VIDEO_FRAME = 1
    VIDEO_CLOSE = 2
    VIDEO_EXIT = 3

    def __init__(self, callback_show_message):
        """
        callback_show_message: 函数，用于在主线程显示状态消息
        """
        self.callback_show_message = callback_show_message
        self.video_queue = queue.Queue(100)
        self.picture_queue = queue.Queue(5)
        self.thread_videos = threading.Thread(target=self._video_worker)
        self.thread_pictures = threading.Thread(target=self._picture_worker)
        self.thread_videos.start()
        self.thread_pictures.start()

        self._status_lock = threading.Lock()
        self._total_recorded_bytes = 0
        self._total_limit_bytes = 0
        self._capacity_reached = False

    def stop_all(self):
        self.picture_queue.put(None)
        self.video_queue.put((self.VIDEO_EXIT, None))
        self.thread_pictures.join()
        self.thread_videos.join()

    def save_picture(self, filename, frame):
        """将帧放入图片队列"""
        self.picture_queue.put((filename, frame))

    def start_video(self, base_filename, width, height, fps, segment_limit_bytes, total_limit_bytes):
        """开始分段录制。base_filename 不含扩展名和分段编号。"""
        with self._status_lock:
            self._capacity_reached = False
            self._total_recorded_bytes = 0
            self._total_limit_bytes = total_limit_bytes
        self.video_queue.put((self.VIDEO_OPEN, (base_filename, width, height, fps, segment_limit_bytes, total_limit_bytes)))

    def stop_video(self):
        """停止录制"""
        self.video_queue.put((self.VIDEO_CLOSE, None))

    def write_video_frame(self, frame):
        """将视频帧放入队列"""
        self.video_queue.put((self.VIDEO_FRAME, frame))

    def is_capacity_reached(self):
        with self._status_lock:
            return self._capacity_reached

    def get_recording_status(self):
        """返回 (已录制字节, 总容量字节, 剩余字节, 是否达到容量)"""
        with self._status_lock:
            return (self._total_recorded_bytes, self._total_limit_bytes,
                    max(0, self._total_limit_bytes - self._total_recorded_bytes),
                    self._capacity_reached)

    def _picture_worker(self):
        while True:
            item = self.picture_queue.get()
            if item is None:
                break
            filename, frame = item
            success = cv2.imwrite(filename, frame)
            if success:
                self.callback_show_message('TAKING_PICTURE', filename)
            else:
                self.callback_show_message('CANNOT_WRITE_PICTURE', filename)
            self.picture_queue.task_done()

    def _video_worker(self):
        # 后台线程局部状态
        video_writer = None
        base_filename = None
        width = 0
        height = 0
        fps = 0
        segment_limit_bytes = 0
        total_limit_bytes = 0
        segment_index = 0
        frame_counter = 0
        completed_bytes = 0
        current_segment_path = None
        current_segment_bytes = 0

        def open_new_segment():
            nonlocal video_writer, segment_index, current_segment_path, current_segment_bytes
            segment_index += 1
            current_segment_path = f"{base_filename}_{segment_index:03d}.mp4"
            fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
            video_writer = cv2.VideoWriter(
                current_segment_path, fourcc, fps, (width, height)
            )
            if not video_writer.isOpened():
                self.callback_show_message('CANNOT_WRITE_VIDEO', current_segment_path)
                video_writer = None
                return False
            self.callback_show_message('RECORDING_VIDEO', current_segment_path)
            current_segment_bytes = 0
            return True

        while True:
            cmd, arg = self.video_queue.get()
            if cmd == self.VIDEO_FRAME:
                if video_writer and not self.is_capacity_reached():
                    video_writer.write(arg)
                    frame_counter += 1
                    if frame_counter % 30 == 0:
                        try:
                            current_segment_bytes = os.path.getsize(current_segment_path)
                        except OSError:
                            current_segment_bytes = 0
                        with self._status_lock:
                            self._total_recorded_bytes = completed_bytes + current_segment_bytes
                        if current_segment_bytes >= segment_limit_bytes:
                            video_writer.release()
                            video_writer = None
                            completed_bytes += current_segment_bytes
                            with self._status_lock:
                                self._total_recorded_bytes = completed_bytes
                            if completed_bytes >= total_limit_bytes:
                                with self._status_lock:
                                    self._capacity_reached = True
                                self.callback_show_message('CAPACITY_REACHED', '')
                            else:
                                if not open_new_segment():
                                    with self._status_lock:
                                        self._capacity_reached = True
                                    self.callback_show_message('CANNOT_WRITE_VIDEO', current_segment_path)
            elif cmd == self.VIDEO_OPEN:
                base_filename, width, height, fps, segment_limit_bytes, total_limit_bytes = arg
                segment_index = 0
                completed_bytes = 0
                frame_counter = 0
                with self._status_lock:
                    self._capacity_reached = False
                    self._total_recorded_bytes = 0
                    self._total_limit_bytes = total_limit_bytes
                if not open_new_segment():
                    with self._status_lock:
                        self._capacity_reached = True
            elif cmd == self.VIDEO_CLOSE:
                if video_writer:
                    video_writer.release()
                    video_writer = None
                    try:
                        current_segment_bytes = os.path.getsize(current_segment_path)
                    except OSError:
                        current_segment_bytes = 0
                    completed_bytes += current_segment_bytes
                    with self._status_lock:
                        self._total_recorded_bytes = completed_bytes
                with self._status_lock:
                    self._capacity_reached = False
                # 重置
                base_filename = None
                segment_index = 0
                completed_bytes = 0
                current_segment_bytes = 0
                frame_counter = 0
            elif cmd == self.VIDEO_EXIT:
                if video_writer:
                    video_writer.release()
                    video_writer = None
                break
            self.video_queue.task_done()
