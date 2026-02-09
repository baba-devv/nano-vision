import cv2
import json
import numpy as np
import yaml


class ZoneSetup:

    def __init__(self, config:dict):
        self.config = config

    def _draw_styled_text(self, img, text, font_size, pos=(20, 50)):
        # 1. Create an overlay for the "Glass" effect
        overlay = img.copy()

        height, width = img.shape[:2]
        
        # 2. Draw a dark semi-transparent rectangle (The Background Bar)
        # Rectangle: (x1, y1), (x2, y2), Color, Thickness (-1 is fill)
        cv2.rectangle(overlay, (0, 0), (width, pos[1]+10), (30, 30, 30), -1)
        
        # 3. Blend the overlay with the original image (0.6 is the opacity)
        cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)
        
        # 4. Draw the text in a modern "Electric Cyan" (BGR: 255, 255, 0)
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 0), int(font_size), cv2.LINE_AA)

    def _draw_zone_overlay(self, frame, points, complete=False):
        """
        Draw the zone being defined on the frame.
        Shows partial polygon while drawing, closed polygon when complete.
        """
        overlay = frame.copy()
        
        if len(points) > 0:
            # Draw points
            for i, point in enumerate(points):
                cv2.circle(overlay, tuple(point), 5, (0, 255, 255), -1)
                cv2.putText(overlay, str(i+1), (point[0]+10, point[1]-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
            
            # Draw lines connecting points
            if len(points) > 1:
                pts = np.array(points, np.int32)
                cv2.polylines(overlay, [pts], isClosed=complete, 
                            color=(0, 255, 0) if complete else (255, 0, 0), 
                            thickness=2)
            
            # If complete, fill with semi-transparent overlay
            if complete and len(points) >= 3:
                pts = np.array(points, np.int32)
                cv2.fillPoly(overlay, [pts], (0, 255, 0))
                frame = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0)
                return frame
        
        return overlay

    def _draw_zone_for_source(self, video_source):
        # Initialize video capture
        cap = cv2.VideoCapture(video_source) # this will open the connection, and start storing frames into buffer
        if not cap.isOpened():
            print("ERROR: Could not open video source!")
            return
        
        # Capture a single reference frame
        print("\nCapturing reference frame...")
        ret, reference_frame = cap.read()
        if not ret:
            print("ERROR: Could not capture frame!")
            cap.release()
            return
        
        print("Frame captured successfully!")
        print("Click on the frame to define your security zone.\n")

        # defining the zone points and state for this video source
        zone_points = []
        drawing_complete = False

        def mouse_callback(event, x, y, flags, param) -> list:
            """
            Mouse callback function for interactive zone drawing.
            Left click to add a point, right click to complete the polygon.
            """
            nonlocal drawing_complete  # we need to modify the outer variable to mark when drawing is complete, since this is a nested function and we want to update the state of the drawing process

            if event == cv2.EVENT_LBUTTONDOWN:
                # Add point to zone
                zone_points.append([x, y])
                print(f"Point {len(zone_points)} added at ({x}, {y})")
                
            elif event == cv2.EVENT_RBUTTONDOWN:
                # Complete the polygon
                if len(zone_points) >= 3:
                    drawing_complete = True
                    print("Zone drawing complete!")
                else:
                    print("Need at least 3 points to define a zone!")

        
        # Create window and set mouse callback
        window_name = "Zone Setup - Define Your Security Zone"
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, mouse_callback)
        
        try:
            # Main interaction loop
            while True:
                # Draw the current state
                display_frame = self._draw_zone_overlay(reference_frame.copy(), 
                                                zone_points, 
                                                drawing_complete)
                
                height, width = display_frame.shape[:2]  # get the frame dimensions to position the text correctly
                base_dimension = min(width, height)  # use the smaller dimension to scale text size

                font_size = max(0.5, base_dimension / 1920)  # scale font size based on frame size, with a minimum size - normalized to 1080p reference frame

                # Add instruction text overlay
                status_text = f"Points: {len(zone_points)}"
                if drawing_complete:
                    status_text = "ZONE COMPLETE - Press 'S' to Save / Press 'R' to Reset"
                    
                    self._draw_styled_text(display_frame, status_text, font_size, pos=(int(width*0.02), int(height*0.05))) # use this at other places
                else:
                    cv2.putText(display_frame, status_text, (int(width*0.02), int(height*0.05)),
                            cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), int(font_size))
                    cv2.putText(display_frame, "Left click: Add point | Right click: Complete", 
                            (int(width*0.02), int(height*0.1)), cv2.FONT_HERSHEY_DUPLEX, 0.5, (255, 255, 255), int(font_size/2))
                
                cv2.imshow(window_name, display_frame)
                
                # Handle keyboard input
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'):
                    print("\nSetup cancelled by user.")
                    zone_points = None
                    
                elif key == ord('r'):
                    # Reset zone
                    zone_points = []
                    drawing_complete = False
                    print("\nZone reset. Start drawing again.")
                    
                elif key == ord('s') and drawing_complete:
                    break

        finally:
            # Cleanup
            try:
                cv2.destroyWindow(window_name)
                # Flush the GUI event loop to actually destroy the window
                for _ in range(10):
                    cv2.waitKey(1)
            except:
                pass
            
            try:
                cap.release()
            except:
                pass

        return zone_points
    

    def run_draw_zone(self):
        """This is the main function to run the zone setup for all video sources defined in the config.
        Interactive zone setup tool.
        
        Workflow:
        1. Capture a frame from the camera
        2. Let user click to define polygon points
        3. Right-click to complete
        4. Save zone to JSON file
        5. Exit

        -> Repeat for multiple video sources
        """
        
        print("=" * 60)
        print("SECURITY ZONE SETUP TOOL")
        print("=" * 60)
        print("\nInstructions:")
        print("  - LEFT CLICK to add a point to the zone boundary")
        print("  - RIGHT CLICK to complete the zone (minimum 3 points)")
        print("  - Press 'R' to reset and start over")
        print("  - Press 'Q' to quit without saving")
        print("=" * 60)

        final_zone_points = {}

        video_sources = self.config.get("video_sources", [])

        for i, source in enumerate(video_sources):
            print(f"\n--- Setting up zone for video source {i}: {source} ---")

            zone_points = self._draw_zone_for_source(source)

            final_zone_points[f"source_{i}"] = zone_points

            print(f"\nZone for source {i}: {source} defined with {len(zone_points)} points.")

        # Save zone configuration
        try:
            output_file = self.config["zone_config_file"] 
            with open(output_file, 'w') as f:
                json.dump(final_zone_points, f, indent=2)
            print(f"\n✓ Zone configuration saved to '{output_file}'")
            print(f"✓ Zone has {len(zone_points)} points")
            print("\nYou can now run main_security.py to start monitoring!")
        except Exception as e:
            print(f"\nERROR saving zone: {e}")


def main():
    # load the config
    with open("configs/env_var.yaml", "r") as f:
        config = yaml.safe_load(f)
    zone_setup = ZoneSetup(config)
    zone_setup.run_draw_zone()


if __name__ == "__main__":
    main()