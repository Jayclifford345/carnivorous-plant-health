import subprocess
import time
import socket

# Get the device's IP address
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print(f"[ERROR] Failed to get device IP: {e}")
        return "127.0.0.1"  # Fallback to localhost

# Define the RTSP stream URL
ip_address = get_ip()
rtsp_url = f"rtsp://localhost:8554/mystream"

# FFmpeg command to stream webcam to RTSP
ffmpeg_cmd = [
    "ffmpeg", "-re", "-f", "v4l2", "-i", "/dev/video0",
    "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
    "-f", "rtsp", rtsp_url
]

# Start the RTSP server process
print(f"[INFO] Starting RTSP stream at {rtsp_url}")
rtsp_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

try:
    while True:
        time.sleep(1)  # Keep the script running
        output = rtsp_process.stderr.readline()
        if output:
            print(f"[DEBUG] {output.strip()}")  # Print FFmpeg logs
except KeyboardInterrupt:
    print("[INFO] Stopping RTSP stream.")
    rtsp_process.terminate()
    print("[INFO] RTSP Server stopped.")
