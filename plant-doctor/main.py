import os
import time
import json
from datetime import datetime
import cv2
import numpy as np
import base64
from flask import Flask, jsonify, send_file, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from openai import OpenAI
from pydantic import BaseModel
# Import OpenTelemetry modules for logging AI results only
from opentelemetry import _logs
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk.resources import Resource

# Set up Flask application
app = Flask(__name__)

# File paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "images")
CURRENT_IMAGE_PATH = os.path.join(IMAGE_DIR, "current.jpg")
LATEST_ANALYSIS_PATH = os.path.join(IMAGE_DIR, "latest_analysis.json")

# Create images directory if it doesn't exist
os.makedirs(IMAGE_DIR, exist_ok=True)

# Initialize OpenAI client
openai_client = OpenAI()

# Global variable to store the latest analysis
latest_analysis = None
service_name = "plant_doctor"

# Classes for plant health data
class PlantHealth(BaseModel):
    plant_status: str  # info, warning, critical
    plant_type: str    # venus flytrap, pitcher plant, sundew
    plant_id: int
    plant_diagnosis: str

class HealthResponse(BaseModel):
    log: list[PlantHealth]

# Set up OpenTelemetry logging for AI analysis results only
def setup_otlp_logging():
    resource = Resource.create({"service.name": service_name})
    
    # Create and configure the OTel logger provider
    logger_provider = LoggerProvider(resource=resource)
    
    # Create OTLP exporter for logs
    otlp_exporter = OTLPLogExporter(endpoint="http://plant-hub:4318/v1/logs")
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_exporter))
    
    # Set the global logger provider
    set_logger_provider(logger_provider)
    
    # Return a logger instance
    return _logs.get_logger("plant_doctor", "1.0.0")

# Initialize the OpenTelemetry logger for AI results only
ai_logger = setup_otlp_logging()

# Function to encode the image for OpenAI
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# Function to improve image quality
def enhance_image(image):
    """Apply image enhancement to improve visibility for analysis."""
    
    # Convert to LAB color space
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    
    # Merge the CLAHE enhanced L-channel with the original A and B channels
    limg = cv2.merge((cl, a, b))
    
    # Convert back to BGR color space
    enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
    
    # Apply additional brightness/contrast adjustment if needed
    brightness = 10
    contrast = 1.25  # 1.0 means no change
    
    # Apply brightness/contrast adjustment
    enhanced = cv2.addWeighted(enhanced, contrast, enhanced, 0, brightness)
    
    return enhanced

# Function to take a picture
def take_picture():
    try:
        print(f"[{datetime.now()}] Taking a picture...")
        cam_port = 0
        cam = cv2.VideoCapture(cam_port)
        
        # Set camera properties for better exposure
        cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # Auto exposure
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)    # Higher resolution
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)    # Higher resolution
        
        # Reading the input using the camera
        result, image = cam.read()
        
        if result:
            # Apply image enhancement
            enhanced_image = enhance_image(image)
            
            # Save timestamped copy for records
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = os.path.join(IMAGE_DIR, f"plant_{timestamp}.jpg")
            cv2.imwrite(archive_path, enhanced_image)
            
            # Save as current image (will be overwritten on next capture)
            cv2.imwrite(CURRENT_IMAGE_PATH, enhanced_image)
            
            # Release the camera
            cam.release()
            
            print(f"[{datetime.now()}] Image captured and saved to {archive_path}")
            return CURRENT_IMAGE_PATH
        else:
            print(f"[{datetime.now()}] ERROR: Failed to access the camera")
            return None
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to take picture: {str(e)}")
        return None

# Analyze the image using OpenAI
def analyze_image(image_path):
    global latest_analysis
    
    print(f"[{datetime.now()}] Analyzing image: {image_path}")
    start_time = time.time()
    
    try:
        # Check if image exists
        if not os.path.exists(image_path):
            print(f"[{datetime.now()}] ERROR: Image file not found: {image_path}")
            return None
        
        # Encode the image
        encoded_image = encode_image(image_path)
        
        # Create a new OpenAI request
        response = openai_client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a carnivorous plant health expert. Examine the daily picture of the plant and provide a state of health."},
                {"role": "system", "content": "plant_status follows log info, warning, critical. plant_type to be venus flytrap, pitcher plant, sundew. plant_id is the unique identifier of the plant. plant_diagnosis is the diagnosis of the plant."},
                {"role": "system", "content": "There could be multiple plants in the image. Please provide the diagnosis for each plant 1 by 1."},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze all plants in this image",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpg;base64,{encoded_image}"},
                        },
                    ],
                }
            ],
            response_format=HealthResponse
        )
        
        # Extract the analysis results
        analysis_result = response.choices[0].message.parsed
        
        # Save the analysis to a file
        with open(LATEST_ANALYSIS_PATH, 'w') as f:
            json.dump(analysis_result.model_dump(), f, indent=2)
        
        latest_analysis = analysis_result
        
        # Only send AI analysis results to OpenTelemetry
        for plant in analysis_result.log:
            # Determine severity based on plant status
            severity = _logs.Severity.INFO
            if plant.plant_status == "warning":
                severity = _logs.Severity.WARN
            elif plant.plant_status == "critical":
                severity = _logs.Severity.ERROR
                
            # Send plant health data to OpenTelemetry logs
            ai_logger.log(
                severity,
                f"Plant #{plant.plant_id} ({plant.plant_type}): {plant.plant_diagnosis}",
                {
                    "plant.id": plant.plant_id,
                    "plant.type": plant.plant_type,
                    "plant.status": plant.plant_status,
                    "plant.diagnosis": plant.plant_diagnosis,
                    "analysis_timestamp": datetime.now().isoformat(),
                    "image_path": image_path
                }
            )
        
        # Print summary for application logs
        duration_ms = (time.time() - start_time) * 1000
        print(f"[{datetime.now()}] Successfully analyzed {len(analysis_result.log)} plants in {duration_ms:.2f}ms")
        
        return analysis_result
        
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to analyze image: {str(e)}")
        return None

# Function to capture image and analyze
def capture_and_analyze():
    print(f"[{datetime.now()}] Starting scheduled plant health check")
    
    # Take a picture
    image_path = take_picture()
    
    if image_path:
        # Analyze the image
        analysis = analyze_image(image_path)
        if analysis:
            print(f"[{datetime.now()}] Plant health check completed successfully")
        else:
            print(f"[{datetime.now()}] ERROR: Failed to analyze the image")
    else:
        print(f"[{datetime.now()}] ERROR: Failed to capture the image")

# Flask routes
@app.route('/')
def index():
    """Render the main page"""
    capture_time = "Never"
    if os.path.exists(CURRENT_IMAGE_PATH):
        capture_time = datetime.fromtimestamp(os.path.getmtime(CURRENT_IMAGE_PATH)).strftime("%Y-%m-%d %H:%M:%S")
    
    return render_template('index.html', health_data=latest_analysis, capture_time=capture_time)

@app.route('/image')
def get_image():
    """Serve the current plant image"""
    if os.path.exists(CURRENT_IMAGE_PATH):
        return send_file(CURRENT_IMAGE_PATH, mimetype='image/jpeg')
    else:
        return "No image available", 404

@app.route('/api/health')
def get_health():
    """Return plant health data as JSON"""
    if latest_analysis:
        return jsonify(latest_analysis.model_dump())
    elif os.path.exists(LATEST_ANALYSIS_PATH):
        with open(LATEST_ANALYSIS_PATH, 'r') as f:
            return jsonify(json.load(f))
    else:
        return jsonify({"error": "No analysis data available yet"})

@app.route('/api/capture')
def trigger_capture():
    """Manually trigger a capture and analysis"""
    try:
        print(f"[{datetime.now()}] Manual capture triggered")
        capture_and_analyze()
        return jsonify({"status": "success", "message": "Capture and analysis triggered"})
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Manual capture failed: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# Main entry point
if __name__ == "__main__":
    # Set up the scheduler for 9am and 5pm captures
    scheduler = BackgroundScheduler()
    scheduler.add_job(capture_and_analyze, 'cron', hour='9,17')
    scheduler.start()
    
    # Load any existing analysis data
    if os.path.exists(LATEST_ANALYSIS_PATH):
        try:
            with open(LATEST_ANALYSIS_PATH, 'r') as f:
                analysis_data = json.load(f)
                latest_analysis = HealthResponse.model_validate(analysis_data)
            print(f"[{datetime.now()}] Loaded existing analysis data")
        except Exception as e:
            print(f"[{datetime.now()}] WARNING: Failed to load existing analysis: {str(e)}")
    
    # Take an initial picture and analyze at startup if needed
    if not os.path.exists(CURRENT_IMAGE_PATH):
        print(f"[{datetime.now()}] Taking initial picture at startup")
        capture_and_analyze()
    
    # Start the Flask web server
    print(f"[{datetime.now()}] Starting web server on port 5000")
    app.run(host='0.0.0.0', port=5000)
