import cv2
import time
import platform


class CameraController:
    """摄像头底层控制（打开、关闭、设置参数、枚举分辨率、读帧）"""
    def __init__(self):
        self.cam = None
        self.width = 640
        self.height = 480
        self.fps = 25.0
        self.current_index = None
        self.current_fourcc = None

    def is_opened(self):
        return self.cam is not None and self.cam.isOpened()

    def open_camera(self, index, width=None, height=None, fourcc=None):
        """打开摄像头，可指定分辨率与格式。返回是否成功。"""
        self.close_camera()
        # 选择后端
        sys_name = platform.system()
        if sys_name == 'Windows':
            backend = cv2.CAP_DSHOW
        elif sys_name == 'Linux':
            backend = cv2.CAP_V4L2
        else:
            backend = cv2.CAP_ANY

        self.cam = cv2.VideoCapture(index, backend)

        if not self.cam.isOpened():
            # 尝试重试
            for _ in range(5):
                time.sleep(1)
                self.cam.open(index, backend)
                if self.cam.isOpened():
                    break
            if not self.cam.isOpened():
                self.cam = None
                return False

        # 设置格式
        if fourcc is not None:
            self.cam.set(cv2.CAP_PROP_FOURCC, fourcc)
            actual = int(self.cam.get(cv2.CAP_PROP_FOURCC))
            if actual != fourcc:
                # 格式不支持，但继续
                pass
            self.current_fourcc = actual

        # 设置分辨率
        if width is not None and height is not None:
            self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # Windows: 显式请求 30fps（DSHOW 有时会报 1，导致定时器被设成 1 秒一次）
        if sys_name == 'Windows':
            try:
                self.cam.set(cv2.CAP_PROP_FPS, 30)
            except Exception:
                pass

        self.width = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if sys_name == 'Windows':
            reported = self.cam.get(cv2.CAP_PROP_FPS)
            if reported is None or reported <= 1.0 or reported > 1000:
                # 明显不是真实值，兜底为 30
                reported = 30.0
            self.fps = max(1.0, reported)
        else:
            # Linux / 其他平台保持原有逻辑
            self.fps = max(1, self.cam.get(cv2.CAP_PROP_FPS))

        self.current_index = index
        if self.current_fourcc is None:
            self.current_fourcc = int(self.cam.get(cv2.CAP_PROP_FOURCC))
        return True

    def close_camera(self):
        if self.cam:
            self.cam.release()
            self.cam = None
        self.current_index = None
        self.current_fourcc = None

    def read_frame(self):
        """返回 (bgr_frame, rgb_frame)，若失败返回 (None, None)"""
        if self.cam:
            ret, bgr = self.cam.read()
            if ret:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                return bgr, rgb
        return None, None

    def set_resolution(self, width, height):
        if not self.cam:
            return False
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        actual_w = int(self.cam.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.width = actual_w
        self.height = actual_h
        return (actual_w == width and actual_h == height)

    def set_fourcc(self, fourcc):
        if not self.cam:
            return False
        self.cam.set(cv2.CAP_PROP_FOURCC, fourcc)
        actual = int(self.cam.get(cv2.CAP_PROP_FOURCC))
        self.current_fourcc = actual
        return (actual == fourcc)

    def get_actual_fourcc(self):
        if self.cam:
            return int(self.cam.get(cv2.CAP_PROP_FOURCC))
        return None

    def get_resolution(self):
        return self.width, self.height

    def get_fps(self):
        return self.fps

    @staticmethod
    def enumerate_cameras():
        """返回 dict {index: info_string}"""
        cameras = {}
        idx = 0
        no_failures = 0
        MAX_FAILURES = 2
        sys_name = platform.system()
        while True:
            cap = None
            try:
                if sys_name == 'Windows':
                    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                elif sys_name == 'Linux':
                    cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                else:
                    cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    cameras[idx] = f'{w}x{h} {fps:.1f}fps'
                    no_failures = 0
                else:
                    no_failures += 1
                cap.release()
            except:
                no_failures += 1
            if no_failures > MAX_FAILURES:
                break
            idx += 1
        return cameras

    @staticmethod
    def enumerate_resolutions(cam):
        """尝试常见分辨率，返回支持列表 [(w, h), ...]"""
        common_res = [
            (640, 480), (800, 600), (1024, 768), (1280, 720),
            (1280, 1024), (1600, 1200), (1920, 1080), (1920, 1200),
            (2048, 1536), (2560, 1440), (2592, 1944), (3840, 2160)
        ]
        supported = []
        orig_w = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
        for w, h in common_res:
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            aw = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            ah = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if aw == w and ah == h:
                supported.append((w, h))
        # 恢复
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, orig_w)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, orig_h)
        return supported

    @staticmethod
    def fourcc_to_str(fourcc):
        if fourcc is None:
            return 'Default'
        return chr(fourcc & 0xff) + chr((fourcc >> 8) & 0xff) + \
               chr((fourcc >> 16) & 0xff) + chr((fourcc >> 24) & 0xff)