import cv2
import json
import numpy as np
from ultralytics import YOLO
from collections import defaultdict, deque
import time
import io
import yaml
import threading
import os
from datetime import datetime

import torch

from telegram_notifier.notifier import AsyncTelegramNotifier
  

class SecuritySystem:
    def __init__(self, config: dict):
        self.config = config
        
        model_name = self.config.get("object_detection_model", {}).get("yolo_model", "")
        print(f"Loading {model_name}...")
        self.model = YOLO(model_name)

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model.to(device)

        print(f"YOLO running on : {device}")

        self.video_sources = self.config.get("video_sources", [])
        if not self.video_sources:
            raise ValueError("No video sources provided in config!")
        # For now, we will only handle the first video source - multi-camera support is a future enhancement         

        self.load_zone() # assuming only a single footage is being processed as of now                                           

        # Initializes RTSP stream via FFmpeg; starts an internal C++ worker thread 
        # that buffers/decodes frames outside the Python GIL - no need of handling this manually here
        self.cap = cv2.VideoCapture(self.video_sources[0])
        
        # Track history: {track_id: [ (x,y), (x,y)... ]}
        self.track_history = defaultdict(lambda: deque(maxlen=self.config.get("object_detection_model", {}).get("history_frames", 10)))  # Stores recent positions for movement analysis - the size constraint will automatically discard old positions, keeping only the most recent ones for analysis
        self.last_trigger_time = time.time() - 60 # temporary variable for handling the alert cooldown

        self.track_alert = defaultdict(lambda: 0)  # To avoid repeated alerts

        ## threading variables - again assuming single footage for now
        self.frame = None
        self.stopped = False
        self.lock = threading.Lock()

        ## start background thread for frame capture - again assuming single footage for now
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()

        ## initialize Telegram Notifier
        self.notifier = AsyncTelegramNotifier(config)
        
        # Start background cron job for purging old image folders
        from image_manager import start_purge_scheduler
        start_purge_scheduler(config)


    def update(self):
        """BACKGROUND THREAD: Constant capture to prevent buffer lag."""
        while not self.stopped:
            ret, frame = self.cap.read()
            if not ret:
                print("Stream disconnected in background thread. Retrying...")
                time.sleep(2)
                self.cap = cv2.VideoCapture(self.video_sources[0])  
                continue

            time.sleep(1 / 60)  # simulate 60 FPS capture rate

            # update the shared frame variable - take care of thread safety with lock
            with self.lock:
                self.frame = frame

        
    def load_zone(self):
        zone_config = self.config.get("zone_config_file", "zone_config.json")
        try:
            with open(zone_config, "r") as f:
                zones = json.load(f)
                # assuming single footage for now
                self.zone_polygon = np.array(zones[f"source_{0}"], np.int32)
                self.zone_polygon = self.zone_polygon.reshape((-1, 1, 2))
                print("Zone loaded successfully.")
        except FileNotFoundError:
            print("ERROR: Zone config not found. Run setup_zone.py first!")
            exit()


    def get_frame(self):
        """Helper to get the latest frame with thread safety."""
        with self.lock:
            return self.frame.copy() if self.frame is not None else None
        

    def is_inside_zone(self, point):
        # returns True if point is inside the polygon
        return cv2.pointPolygonTest(self.zone_polygon, point, False) >= 0


    def analyze_movement(self, track_id, current_pos):
        """
        Determines if a tracked object is 'Moving' or 'Stationary' 
        based on history.
        """
        history = self.track_history[track_id]
        history.append(current_pos)
            
        if len(history) < 2:
            return "ANALYZING"

        # Check distance between oldest known point and current point
        start_pos = np.array(history[0])
        curr_pos = np.array(current_pos)
        distance = np.linalg.norm(curr_pos - start_pos)

        if distance < self.config.get("object_detection_model", {}).get("movement_threshold", 15):
            return "STATIONARY"
        else:
            return "MOVING"


    def run(self):
        print("--- SYSTEM ARMED ---")
        
        while not self.stopped:
            
            frame = self.get_frame()

            if frame is None:
                continue

            # Run YOLO with Tracking enabled (persist=True is crucial for ID tracking)
            # classes=[0] filters for 'person' only
            config_threshold = self.config.get("object_detection_model", {}).get("confidence_threshold", 0.4)
            max_det = self.config.get("object_detection_model", {}).get("max_detections", 10)
            results = self.model.track(frame, persist=True, classes=[0], verbose=False, conf=config_threshold, max_det=max_det)  # Adjust max_det as needed for performance

            # Draw the Safe Zone (Green Boundary)
            cv2.polylines(frame, [self.zone_polygon], isClosed=True, color=(0, 255, 0), thickness=2)

            if results[0].boxes.id is not None:

                # ## check if the alert_cooldown has passed - this is to avoid spamming, ideally should be at track id level, but will handle this later when implementing face detection or fine tuning the YOLO model
                # if (time.time() - self.last_trigger_time < self.config.get("object_detection_model", {}).get("alert_cooldown", 60)):
                #     continue

                boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
                track_ids = results[0].boxes.id.cpu().numpy().astype(int)
                confs = results[0].boxes.conf.cpu().numpy()

                for box, track_id, conf in zip(boxes, track_ids, confs):

                    x1, y1, x2, y2 = box

                    # print("processing box:", box, "with ID:", track_id)

                    # Calculate 'feet' coordinates (bottom center)
                    feet_pos = (int((x1 + x2) / 2), int((y1 + y2) / 2))

                    # LOGIC 1: Check if inside House Boundary
                    if self.is_inside_zone(feet_pos):
                        
                        # LOGIC 2: Analyze Movement
                        status = self.analyze_movement(track_id, feet_pos)
                        
                        # Visualization Logic
                        color = (0, 0, 255) # Red for intrusion
                        label = f"ID:{track_id} {status}"

                        # Draw Bounding Box & Text
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 4)
                        cv2.putText(frame, label, (x1, y1 - 10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 3)
                        
                        # Draw feet point
                        cv2.circle(frame, feet_pos, 5, (0, 255, 255), -1)

                        # trigger alert only if the last trigger was more than xx seconds ago - this is to avoid spamming the alerts for the same person in case they are stationary or moving inside the boundary for a long time
                        # also this is more specific to person / track id 
                        if (time.time() - self.track_alert[track_id] > self.config.get("object_detection_model", {}).get("alert_cooldown", 60)):
                            self.track_alert[track_id] = time.time()
                            self.last_trigger_time = time.time() # update the global trigger time as well to avoid spamming for other IDs in case of multiple people inside the boundary

                            print("Generating trigger for ID:", track_id, "Status:", status, "since the last alert was more than 30 seconds ago.")

                            # Trigger Placeholder
                            if status == "STATIONARY":
                                trigger_msg = f"Trigger: Person {track_id} is LOITERING inside boundary."
                            else:
                                trigger_msg = f"Trigger: Person {track_id} is MOVING inside boundary."

                            # save optimized screenshot
                            image_stream = self.save_optimized_screenshot(frame, track_id)

                            self.notifier.send_message(trigger_msg, image_stream=image_stream)
                            
                            # Console Log (Simulating the Trigger)
                            print(f"TRIGGER ALERT - movement detected :  {trigger_msg}") 

            if self.config.get("open_cam_viewer", False):
                # Display Status - comment when running headless
                cv2.imshow("Conference AI Security System", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.stopped = True

            # time.sleep(1/30)

        print("--- SYSTEM DISARMED ---")
        self.cap.release()
        cv2.destroyAllWindows()


    def save_optimized_screenshot(self, frame, track_id: str) -> io.BytesIO:
        """
        Save screenshot with conditional compression based on file size.
        Creates directory structure if needed.
        Returns BytesIO object for telegram/VLM.
        """

        # Generate screenshot filename with proper structure
        base_folder = self.config.get("image_storage", {}).get("base_folder", "captured_images")
        date_folder = datetime.now().strftime("%Y%m%d")
        timestamp = int(time.time())
        filename = f"{base_folder}/{date_folder}/intrusion_ID{track_id}_{timestamp}.jpg"

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        # First, encode with high quality to check size
        _, buffer_high_quality = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        size_kb = len(buffer_high_quality) / 1024
        
        # Get compression threshold from config
        compress_threshold_kb = self.config.get("image_storage", {}).get("compress_threshold_kb", 1048)
        
        # Conditional compression based on size
        if size_kb > compress_threshold_kb:
            # Compress to quality 50 if above threshold
            compression_params = [cv2.IMWRITE_JPEG_QUALITY, 50]
            cv2.imwrite(filename, frame, compression_params)
            _, buffer = cv2.imencode('.jpg', frame, compression_params)
            print(f"Image compressed: {size_kb:.1f}KB -> {len(buffer)/1024:.1f}KB")
        else:
            # Use high quality if below threshold
            cv2.imwrite(filename, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            buffer = buffer_high_quality
            print(f"Image saved without compression: {size_kb:.1f}KB")
        
        # Convert buffer to BytesIO for telegram/VLM
        image_stream = io.BytesIO(buffer)
        image_stream.seek(0) # Reset pointer to beginning
        
        return image_stream


if __name__ == "__main__":
    with open("configs/env_var.yaml", "r") as f:
        config = yaml.safe_load(f)
    system = SecuritySystem(config)
    system.run()




### @PLAN:
# 1. Implement the VLM model
# 2. Modularize the code and make it structured - similar to a well maintained Open Source repo - with the right folder structure, etc. 
# 3a. 
# 3b. Packaging the code - maybe pyproject.toml or something - want to ship this as a binary.
# 3c. enable the ssh part of the code so that any external system can take the access via ssh login and see the camera feeds, etc.

# 4. Integrating the VLM model which takes image as an input and generates a description - which goes to the telegram bot.

### ---- record the first video over here -------

# 5. environment setup, like the number of cams, telegram bot token, chat id, etc. should be set externally by the user prior to running.
# 6. When implementing multi-camera setup, make sure to have a upper limit on the number of cameras, say 5 or something for the detection.
# this is the first pass

### shift the code to the raspberry pi and handle everything via ssh login ----- do the ssh setup over here -----

# 7. next phase: we activate the chat cli agent, which can recieve the input messages from telegram bot and answer back to the user using 
# the VLM or LLM - make it a good agent for handling atleast the basic queries with the image and description as the context.
# 8. This agent will get the inputs from the saved images and previous conversation history - its a little more complicated but well let the 
# agent create the agent for handling memory, etc.

#### some questions can be asked intelligently:
    # 1. who is this person ?
    # 2. have you seen this person before ?
    # 3. What is the person doing or trying to do ?

    ## on a high level, the query should include the timestamp and the camera number atleast as input - currently 

### ------ record the second video over here -------

# 9. Adding a face detection algorithm to the system or maybe fine tuning the YOLO model to be able to recognize familiar faces and not raise an
# alert for them

# 10. Adding multiple - mutually exclusive camera setups over here - complete the engineering behind them as well - managing the threads, etc.