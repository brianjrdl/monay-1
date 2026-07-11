import json
from json.decoder import JSONDecodeError
import os
from datetime import datetime
from collections import defaultdict
import logging

class DataManager:
    def __init__(self, filepath="data_log.jsonl"):
        self.filepath = filepath
        try:
            if not os.path.exists(self.filepath):
                print("Creating data_log.jsonl...")
                open(self.filepath, 'a').close()
        except Exception as e:
            raise OSError(f"Error loading filepath: {e}")

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
        except Exception as e:
            raise OSError(f"Error writing in filepath: {e}")

    def get_hourly_averages(self):
        hourly_data = defaultdict(list)
        analytics = {}
        try:
            with open(self.filepath, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data =  json.loads(line)
                        hour_key = data["datetime"][:13]
                        hourly_data[hour_key].append(data["human_count"])
                    except json.JSONDecodeError:
                        print("Corrupted JSON line skipped")
                        continue

        except OSError as e:
            logging.error(f"Error getting hourly averages: {e}")
            return {}

        for hour, counts in hourly_data.items():
            analytics[hour] = sum(counts) / len(counts)

        return analytics
