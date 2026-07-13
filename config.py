
class Config:
    AVERAGE_WAITING_TIME = 2.5
    METRICS_FILE_PATH = "data_log.jsonl"
    AVERAGE_COUNT_INTERVAL = 900
    MODEL_NAME = "yolo11s.pt"
    DETECTION_CLASSES = [0]
    CAMERA_INDEX = 0

    MAX_ANALYTICS_DAYS = 30          # Only process last 30 days of data
    HEATMAP_MIN_WEEKS = 1            # Need at least this many weeks for heatmap
    INSIGHT_MIN_ENTRIES = 3          # Minimum entries before generating any insight

    # Insight thresholds
    PEAK_CAPACITY_THRESHOLD = 20     # human_count above this = "peak"
    STREAK_MIN_MINUTES = 15          # Consecutive minutes to qualify as a "streak"

    # Peak window detection
    PEAK_WINDOW_MINUTES = 15         # Size of peak-detection bucket

    # Chart and insight tuning
    DEFAULT_CHART_DAYS = 7           # Days shown in the weekly chart
    HISTORICAL_COMPARISON_DAYS = 30  # How far back "current vs historical" looks
    INSIGHT_MIN_DAYS = 3             # Minimum distinct dates before insights fire
    INSIGHT_NEUTRAL_THRESHOLD = 5    # ±5% difference → "about the same"
