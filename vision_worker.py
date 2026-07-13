from dataclasses import dataclass
import  numpy as np
import cv2
from ultralytics import YOLO
from config import Config

@dataclass
class DashboardPayload:
    # 1. The Heavy Data: Kept separate because UI needs to convert this to a QImage
    ui_video_feed: np.ndarray

    # 2. The Light Data: Maps exact UI Widget IDs to their new values
    ui_human_count: int

class VisionWorker:
    def __init__(self):
        self.model_name = Config.MODEL_NAME
        self.detection_classes = Config.DETECTION_CLASSES
        self.camera_index = Config.CAMERA_INDEX
        self.capture_backend = [cv2.CAP_DSHOW, cv2.CAP_MSMF]
        self.model = None
        self.cap = None

    def load_model(self):
        print(f"Loading AI Model: '{self.model_name}'...")
        try:
            self.model = YOLO(self.model_name)
            print(f"'{self.model_name}' successfully loaded!")
        except Exception as e:
            # [FIX] Raise an exception instead of killing the whole program
            raise RuntimeError(f"Error loading model '{self.model_name}': {e}")

    def open_camera(self):
        print(f"Opening camera at index {self.camera_index}")
        for backend in self.capture_backend:
            self.cap = cv2.VideoCapture(self.camera_index, backend)
            if self.cap.isOpened():
                print(f"[+] Camera opened successfully using backend flag: {backend}")
                break
            else:
                print(f"[-] Backend {backend} failed to initialize...")
        else:
            raise RuntimeError("CRITICAL: All capture backends failed. Could not open webcam.")

        # Configure video dimensions
        # self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        # self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def generate_frames(self):
        """
        [FIX] Changed to a generator. This decouples the ML/Camera logic
        from the UI, allowing PyQt to consume frames smoothly.
        """
        if self.cap is None or not self.cap.isOpened():
            raise RuntimeError("Camera is not opened. Call open_camera() first.")

        try:
            while True:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    print("[-] Error: Lost camera frame. Exiting stream...")
                    break

                results = self.model(frame, stream=True, verbose=False, classes = self.detection_classes)

                for result in results:
                    annotated_frame = result.plot()

                    current_human_count = len(result.boxes)

                    payload = DashboardPayload(
                        ui_video_feed = annotated_frame,
                        ui_human_count = current_human_count
                    )

                    yield payload

        finally:
            # [FIX] Guaranteed execution: releases the hardware camera even if the loop crashes.
            self.cleanup()

    def cleanup(self):
        if self.cap is not None:
            self.cap.release()
        # Note: If migrating to PyQt, you won't need cv2.destroyAllWindows()
        cv2.destroyAllWindows()
