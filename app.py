import sys
import os
import time
import base64
import cv2
import json
from PyQt6.QtCore import QThread, pyqtSignal, QUrl, pyqtSlot, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from config import Config
# Import decoupled worker
from vision_worker import VisionWorker
# Import data manager for parsing data log (jsonl)
from metrics_repository import MetricsRepository


class VisionThread(QThread):
    # Signal definition: sends (human_count, base64_image_string)
    update_ui_signal = pyqtSignal(int, str)

    def __init__(self, worker, metrics_repository):
        super().__init__()
        self.running = True
        self.worker = worker
        self.metrics_repository = metrics_repository
        self.generator = None

    def run(self):
        # 1. Initialize Hardware & AI
        self.worker.load_model()
        self.worker.open_camera()
        self.generator = self.worker.generate_frames()

        # Optimization 1: Target UI Framerate (15 FPS = ~0.066 seconds per frame)
        target_frame_time = 1.0 / 15.0
        last_sent_time = 0

        # Rolling average accumulator
        last_average_time = 0
        count_samples = []        # Accumulates all counts within the window

        for payload in self.generator:
            if not self.running:
                break

            current_time = time.time()

            # --- Frame sending (unchanged) ---
            if (current_time - last_sent_time) >= target_frame_time:
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 60]
                success, buffer = cv2.imencode('.jpg', payload.ui_video_feed, encode_param)
                if success:
                    b64_str = base64.b64encode(buffer).decode('utf-8')
                    self.update_ui_signal.emit(payload.ui_human_count, b64_str)
                    last_sent_time = current_time

            # --- Rolling average logging ---
            count_samples.append(payload.ui_human_count)

            if (current_time - last_average_time) >= Config.AVERAGE_COUNT_INTERVAL:
                if count_samples:
                    average = sum(count_samples) / len(count_samples)
                    print(f"15-min average: {average:.1f} (from {len(count_samples)} samples)")
                    self.metrics_repository.save_log(average)
                last_average_time = current_time
                count_samples = []  # Reset for next window

    def stop(self):
        """Safely shuts down the thread and hardware"""
        self.running = False
        if self.generator:
            self.generator.close() # Forces the generator's 'finally' block to run
        self.wait()


class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monay-1: Waiting Time Estimator")
        self.resize(1280, 720) # Dashboard default size
        self.worker = VisionWorker()
        self.metrics_repository = MetricsRepository()
        self.human_count_log = 0

        # 1. Setup the Web Engine (Chromium Browser inside PyQt)
        self.browser = QWebEngineView()

        # Enable loading of remote CDN scripts (Tailwind CSS) on local HTML files
        settings = self.browser.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        self.setCentralWidget(self.browser)

        # 2. Load the HTML file (Requires absolute path)
        html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui", "main_dashboard.html"))
        self.browser.load(QUrl.fromLocalFile(html_path))

        # 3. Setup and start the AI Background Thread
        print("Initializing Vision thread...")
        self.ai_thread = VisionThread(self.worker, self.metrics_repository)
        self.ai_thread.update_ui_signal.connect(self.update_dashboard)

        # Wait for the browser to finish loading HTML before starting the camera
        self.browser.loadFinished.connect(self.on_html_loaded)

        # Analytics timer — refreshes automatically every 60 seconds
        self.analytics_timer = QTimer()
        self.analytics_timer.timeout.connect(self.fetch_analytics)
        self.analytics_timer.start(60_000)

    def fetch_analytics(self):
        """Create a fresh AnalyticsThread each cycle.  The old one
        garbage-collects after emitting its signal."""
        self.analytics_thread = AnalyticsThread(self.metrics_repository)
        self.analytics_thread.analytics_ready_signal.connect(self.on_analytics_ready)
        self.analytics_thread.start()

    @pyqtSlot(str)
    def on_analytics_ready(self, json_payload):
        """Receives data safely on the main UI thread and pushes it into
        the JavaScript render pipeline."""
        try:
            data = json.loads(json_payload)
            if data.get("error"):
                print(f"[Analytics Error] {data['message']}")
                return
            self.browser.page().runJavaScript(
                f"window.renderAnalytics({json_payload});"
            )
        except Exception as e:
            print(f"[UI Error] Analytics injection failed: {e}")



    @pyqtSlot(int, str)
    def update_dashboard(self, human_count, b64_str):
        """
        This slot runs on the GUI thread. It injects the data straight into
        the DOM using the IDs we set up in the HTML file.
        """
        # Optimization 3: Only update innerText if the count actually changed.
        js_video_update = f"""
            var img = document.getElementById('ui_video_feed');
            if (img) {{
                img.src = 'data:image/jpeg;base64,{b64_str}';
            }}
        """
        self.browser.page().runJavaScript(js_video_update)

        if (human_count == self.human_count_log):
            return

        self.human_count_log = human_count
        wait_time = human_count * Config.AVERAGE_WAITING_TIME
        active_tellers = min((human_count // Config.PEOPLE_PER_TELLER), Config.MAX_TELLER_COUNT - 1)
        js_count_update = f"""
            var count_elem = document.getElementById('ui_human_count');
            if (count_elem) {{
                count_elem.innerText = '{human_count}';
            }}

            var waiting_time = document.getElementById('ui_waiting_time');
            if (waiting_time){{
                waiting_time.innerText = '{wait_time} mins.';
            }}

            var teller_count = document.getElementById('ui_teller_count');
            if (teller_count){{
                teller_count.innerText =  '{active_tellers + 1}';
            }}

            var kpi_occupancy =  document.getElementById('kpi-occupancy');
            if (kpi_occupancy){{
                kpi_occupancy.innerText = '{human_count} persons';
            }}

            var kpi_wait = document.getElementById('kpi-wait');
            if (kpi_wait){{
                kpi_wait.innerText = '{wait_time} minutes';
            }}
        """
        self.browser.page().runJavaScript(js_count_update)

    def on_html_loaded(self, success):
        if success:
            print("[+] HTML Dashboard Loaded. Starting AI Engine...")
            self.ai_thread.start()
        else:
            print("[-] Failed to load HTML file.")

    def closeEvent(self, event):
        """Triggered when the user clicks the 'X' to close the window"""
        print("[*] Shutting down application cleanly...")
        self.ai_thread.stop()
        event.accept()


class AnalyticsThread(QThread):
    analytics_ready_signal = pyqtSignal(str)

    def __init__(self, metrics_repository):
        super().__init__()
        try:
            self.metrics_repository =  metrics_repository
        except Exception as e:
            raise RuntimeError(f"Error initializing MetricsRepository: {e}")

    def run(self):
        try:
            hourly = self.metrics_repository.get_hourly_averages(days=Config.DEFAULT_CHART_DAYS)
            latest_key = sorted(hourly.keys())[-1]
            latest_avg = hourly[latest_key]
            payload = {
                "kpis": {
                    "today_peak": self.metrics_repository.get_today_peak()
                },
                "charts": {
                    "hourly_week": hourly,
                    "heatmap": self.metrics_repository.get_heatmap_data()
                },
                "insights": [
                    self.metrics_repository.get_busiest_hour_this_week(),
                    self.metrics_repository.get_current_vs_historical(latest_avg)
                ]
            }

            self.analytics_ready_signal.emit(json.dumps(payload))

        except Exception as e:
            self.analytics_ready_signal.emit(json.dumps({
                "error": True,
                "message": f"Analytics processing failed: {str(e)}"
            }))




def main():
    app = QApplication(sys.argv)
    window = DashboardWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
