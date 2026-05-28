# ChatUI 图像线程（PySide6）。

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QThread, Signal


class ImageDisplayThread(QThread):
    """图像显示线程，负责从队列获取图像并更新UI"""

    update_signal = Signal(np.ndarray)

    def __init__(self, image_queue):
        super().__init__()
        self.image_queue = image_queue
        self.running = True
        self.font_size = "48px;"

    def run(self):
        while self.running:
            try:
                if not self.image_queue.empty():
                    image = self.image_queue.get()
                    self.update_signal.emit(image)
                QThread.msleep(10)
            except Exception as e:
                print(f"Display error: {e}")

    def stop(self):
        self.running = False
