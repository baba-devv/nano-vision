import cv2

VIDEO_SOURCE = "rtsp://admin:admin%40123@192.168.29.17:554/cam/realmonitor?channel=2&subtype=1"

def check_connection():
    cap = cv2.VideoCapture(VIDEO_SOURCE)

    if not cap.isOpened():
        print("Error: Unable to connect to the video source.")
        return False
    
    else:
        print("Successfully connected to the video source.")
        ret, frame = cap.read()
        if ret:
            print("Frame captured successfully.")
            cv2.imshow("Captured Frame", frame)
            cv2.waitKey(3000)  # Display the frame for 3 seconds
        else:
            print("Error: Unable to read frame from the video source.")

        cap.release()
        cv2.destroyAllWindows()
        return True
    
if __name__ == "__main__":
    check_connection()