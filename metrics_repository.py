import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

# Responsibilities: reading and writing logs and making sure the JSONL file
# is accessible.  All read methods share a single _read_entries() generator.


class MetricsRepository:
    def __init__(self, filepath=None):
        if filepath is None:
            filepath = "data_log.jsonl"
        self.filepath = filepath
        try:
            if not os.path.exists(self.filepath):
                print(f"Creating {self.filepath}...")
                with open(self.filepath, 'a'):
                    pass
        except OSError as e:
            raise OSError(f"Error loading filepath: {e}") from e

    # ── Write ──────────────────────────────────────────────────

    def save_log(self, human_count):
        log_entry = {
            "timestamp": datetime.now().timestamp(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "human_count": human_count
        }
        try:
            with open(self.filepath, 'a') as f:
                f.write(json.dumps(log_entry) + "\n")
                print(f"Log saved in {self.filepath}: {log_entry}")
        except OSError as e:
            raise OSError(f"Error writing in filepath: {e}") from e

    # ── Shared read helper ─────────────────────────────────────

    def _read_entries(self, since: str = None):
        """Generator.  Lazily yields every valid JSON object from the log
        file.  Corrupted lines are silently skipped.  File-not-found or
        permission errors end the stream cleanly (no exception raised).

        Args:
            since: Optional "YYYY-MM-DD" string.  When provided, entries
                   before this date are skipped.  Since lines are written
                   in chronological order the skip is efficient."""
        try:
            with open(self.filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if since:
                        dt = entry.get("datetime", "")
                        if dt[:10] < since:
                            continue          # Still before the cutoff
                        since = None            # Past the cutoff — stop checking
                    yield entry
        except OSError:
            return

    # ── Hourly averages ────────────────────────────────────────

    def get_hourly_averages(self, days: int = None):
        """Returns { 'YYYY-MM-DD HH': avg_count }.

        Args:
            days: Only include the last N calendar days.  None → all data.
        """
        since = None
        if days is not None:
            since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

        hourly = defaultdict(list)

        for entry in self._read_entries(since=since):
            dt = entry.get("datetime", "")
            if len(dt) < 13:
                continue
            hour_key = dt[:13]
            hourly[hour_key].append(entry.get("human_count", 0))

        return {hour: sum(counts) / len(counts) for hour, counts in hourly.items()}

    # ── Peak Window Detection ──────────────────────────────────

    def _get_peak_window(self, date_str: str, window_minutes: int = None) -> dict:
        """Group entries for *date_str* into *window_minutes* buckets,
        return the bucket with the highest average count.

        Returns on success:
            {"peak_time": "14:30", "peak_count": 12.3, "window_minutes": 15}
        Returns on failure:
            {"error": "..."}
        """
        from config import Config

        if window_minutes is None:
            window_minutes = Config.PEAK_WINDOW_MINUTES

        window_seconds = window_minutes * 60
        buckets = defaultdict(list)

        for entry in self._read_entries(since=date_str):
            dt = entry.get("datetime", "")
            if not dt.startswith(date_str):
                continue

            ts = entry.get("timestamp", 0)
            bucket_key = ts - (ts % window_seconds)
            buckets[bucket_key].append(entry.get("human_count", 0))

        if not buckets:
            return {"error": f"No data for {date_str}"}

        # Find the bucket with the highest average
        peak_bucket = max(buckets, key=lambda k: sum(buckets[k]) / len(buckets[k]))
        peak_count = sum(buckets[peak_bucket]) / len(buckets[peak_bucket])

        peak_dt = datetime.fromtimestamp(peak_bucket)
        peak_time = peak_dt.strftime("%H:%M")

        return {
            "peak_time": peak_time,
            "peak_count": round(peak_count, 1),
            "window_minutes": window_minutes
        }

    def get_today_peak(self) -> dict:
        """Peak window for the current calendar day."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self._get_peak_window(today_str)

    def get_yesterday_peak(self) -> dict:
        """Peak window for the most recent date that is NOT today.
        Reads the log once, buckets by date, then walks backward."""
        from config import Config

        since = (
            datetime.now() - timedelta(days=Config.MAX_ANALYTICS_DAYS)
        ).strftime("%Y-%m-%d")

        window_seconds = Config.PEAK_WINDOW_MINUTES * 60
        buckets_by_date = defaultdict(lambda: defaultdict(list))

        for entry in self._read_entries(since=since):
            dt = entry.get("datetime", "")
            ts = entry.get("timestamp", 0)
            date_key = dt[:10]
            bucket_key = ts - (ts % window_seconds)
            buckets_by_date[date_key][bucket_key].append(entry.get("human_count", 0))

        # Walk backward from yesterday
        for days_back in range(1, Config.MAX_ANALYTICS_DAYS + 1):
            date_str = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            buckets = buckets_by_date.get(date_str)
            if not buckets:
                continue

            peak_bucket = max(buckets, key=lambda k: sum(buckets[k]) / len(buckets[k]))
            peak_count = sum(buckets[peak_bucket]) / len(buckets[peak_bucket])
            peak_dt = datetime.fromtimestamp(peak_bucket)

            return {
                "date": date_str,
                "peak_time": peak_dt.strftime("%H:%M"),
                "peak_count": round(peak_count, 1),
                "window_minutes": Config.PEAK_WINDOW_MINUTES
            }

        return {"error": "No data from any recent day"}

    # ── Latest entry ───────────────────────────────────────────

    def get_latest_count(self) -> float:
        """Return the human_count from the most recent log entry.
        Seeks to the end of the file instead of scanning all entries.
        Returns 0.0 when the file is empty or missing."""
        try:
            with open(self.filepath, 'rb') as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                if file_size == 0:
                    return 0.0

                # Walk backwards from the end to find the last newline
                pos = file_size - 1
                while pos > 0:
                    f.seek(pos)
                    if f.read(1) == b'\n':
                        break
                    pos -= 1

                last_line = f.readline().decode().strip()
                if not last_line:
                    return 0.0

                entry = json.loads(last_line)
                return float(entry.get("human_count", 0.0))
        except (OSError, json.JSONDecodeError):
            return 0.0

    # ── Heatmap ────────────────────────────────────────────────

    def get_heatmap_data(self) -> dict:
        """Group counts by (weekday, hour) across all available data.

        Returns:
            {"Mon": {"08": 12.5, "09": 15.3, ...}, "Tue": ...}
            or {"insufficient": True, "message": "..."}
        """
        from config import Config

        since = (
            datetime.now() - timedelta(days=Config.MAX_ANALYTICS_DAYS)
        ).strftime("%Y-%m-%d")

        heatmap = {day: defaultdict(list) for day in
                   ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
        dates_seen = set()

        for entry in self._read_entries(since=since):
            dt = entry.get("datetime", "")
            if len(dt) < 13:
                continue
            try:
                d = datetime.strptime(dt[:10], "%Y-%m-%d")
            except ValueError:
                continue

            weekday = d.strftime("%a")         # Mon, Tue, ...
            hour = dt[11:13]                   # 08, 14, ...
            heatmap[weekday][hour].append(entry.get("human_count", 0))
            dates_seen.add(dt[:10])

        if len(dates_seen) < Config.HEATMAP_MIN_WEEKS * 7:
            return {
                "insufficient": True,
                "message": f"Need at least {Config.HEATMAP_MIN_WEEKS} week(s) of data "
                           f"(have {len(dates_seen)} day(s))."
            }

        # Collapse lists → averages; empty cells → 0.0
        return {
            day: {h: round(sum(v) / len(v), 1) if v else 0.0
                  for h, v in hours.items()}
            for day, hours in heatmap.items()
        }

    # ── Smart Insights ─────────────────────────────────────────

    def get_busiest_hour_this_week(self) -> dict:
        """Find the (day, hour) with the highest average count in the
        last DEFAULT_CHART_DAYS.

        Returns:
            {"ready": True, "text": "Tuesday at 2:00 PM", "avg": 24.3, ...}
            or {"ready": False, "reason": "..."}
        """
        from config import Config

        hourly = self.get_hourly_averages(days=Config.DEFAULT_CHART_DAYS)

        # Count distinct dates to decide whether we have enough data
        distinct_dates = {k[:10] for k in hourly}
        if len(distinct_dates) < Config.INSIGHT_MIN_DAYS:
            return {
                "ready": False,
                "reason": f"Need at least {Config.INSIGHT_MIN_DAYS} days of data "
                          f"(have {len(distinct_dates)})."
            }

        if not hourly:
            return {"ready": False, "reason": "No hourly data available."}

        best_key = max(hourly, key=hourly.get)
        best_val = hourly[best_key]

        try:
            d = datetime.strptime(best_key[:10], "%Y-%m-%d")
            weekday = d.strftime("%A")                     # Tuesday
        except ValueError:
            weekday = best_key[:10]

        hour_int = int(best_key[11:13])
        suffix = "AM" if hour_int < 12 else "PM"
        display_hour = hour_int if hour_int <= 12 else hour_int - 12
        if display_hour == 0:
            display_hour = 12

        result = {
            "ready": True,
            "text": f"{weekday} at {display_hour}:00 {suffix}",
            "avg": round(best_val, 1),
            "date": best_key[:10],
            "hour": best_key[11:13]
        }
        if best_val < 0.01:
            result["note"] = "No significant activity detected"
        return result

    def get_current_vs_historical(self, current_count: float) -> dict:
        """Compare *current_count* against the historical average for the
        same hour of day (across all days in the analysis window).

        Returns:
            {"ready": True, "text": "... 15% lower than ...", "pct_diff": -14.9}
            or {"ready": False, "reason": "..."}
        """
        from config import Config

        current_hour = datetime.now().strftime("%H")       # e.g. "14"
        hourly = self.get_hourly_averages(
            days=Config.HISTORICAL_COMPARISON_DAYS
        )

        # Collect all hours whose key ends with the current hour
        same_hour_counts = [
            v for k, v in hourly.items() if k.endswith(current_hour)
        ]

        if not same_hour_counts:
            return {
                "ready": False,
                "reason": "No historical data for this hour yet."
            }

        historical_avg = sum(same_hour_counts) / len(same_hour_counts)

        if historical_avg < 0.01:
            return {
                "ready": False,
                "reason": "Historical average too low for meaningful comparison."
            }

        pct_diff = ((current_count - historical_avg) / historical_avg) * 100
        threshold = Config.INSIGHT_NEUTRAL_THRESHOLD

        if pct_diff > threshold:
            text = (f"Current wait times are {pct_diff:.0f}% higher than "
                    f"the historical average for this hour.")
        elif pct_diff < -threshold:
            text = (f"Current wait times are {abs(pct_diff):.0f}% lower than "
                    f"the historical average for this hour.")
        else:
            text = ("Current wait times are about the same as "
                    "the historical average for this hour.")

        return {
            "ready": True,
            "text": text,
            "current": round(current_count, 1),
            "historical_avg": round(historical_avg, 1),
            "pct_diff": round(pct_diff, 1)
        }
