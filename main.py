#!/usr/bin/env python3

import sys
import os
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

# 强制使用软件 OpenGL，避免 rockchip 驱动问题
QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)

from main_window import MainWindow, VERSION
from camera_widget import CameraWidget

if __name__ == '__main__':
    print(f"USB-Camera version {VERSION}")
    app = QApplication(sys.argv)
    widget = CameraWidget()
    main_window = MainWindow(widget, app)
    app.aboutToQuit.connect(widget.end_widget)
    widget.initialize(main_window)
    main_window.show()
    main_window.showMaximized()
    sys.exit(app.exec_())
