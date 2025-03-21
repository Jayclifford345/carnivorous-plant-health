import os
import time
import json
from datetime import datetime
import cv2
import base64
from flask import Flask, jsonify, send_file, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from openai import OpenAI
from pydantic import BaseModel
# Import OpenTelemetry modules for logging AI results only
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk.resources import Resource
import logging
import requests
from datetime import datetime, timedelta

# Set up Flask application
app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

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
    plant_position: str

class HealthResponse(BaseModel):
    log: list[PlantHealth]

class TankHealth(BaseModel):
    tank_status: str  # info, warning, critical
    temperature_analysis: str
    humidity_analysis: str
    combined_diagnosis: str
    recommendations: str

resource = Resource.create({"service.name": service_name})
logger_provider = LoggerProvider(resource=resource)
# Create OTLP exporter for logs
otlp_exporter = OTLPLogExporter(endpoint="http://plant-hub:4318/v1/logs")
logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter=otlp_exporter, max_queue_size=5, max_export_batch_size=1))

# 3. Attach the OTLP LoggingHandler to a logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(LoggingHandler(logger_provider=logger_provider))


# Function to encode the image for OpenAI
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# Function to manage image retention
def manage_image_retention():
    """Keep only the 5 most recent images and delete older ones."""
    try:
        # Get all plant images in the directory
        plant_images = [f for f in os.listdir(IMAGE_DIR) if f.startswith("plant_") and f.endswith(".jpg")]
        
        # Sort by modification time, newest first
        plant_images.sort(key=lambda x: os.path.getmtime(os.path.join(IMAGE_DIR, x)), reverse=True)
        
        # Delete all but the 5 most recent images
        for old_image in plant_images[5:]:
            try:
                os.remove(os.path.join(IMAGE_DIR, old_image))
                print(f"[{datetime.now()}] Deleted old image: {old_image}")
            except Exception as e:
                print(f"[{datetime.now()}] ERROR: Failed to delete old image {old_image}: {str(e)}")
                
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to manage image retention: {str(e)}")

# Function to take a picture
def take_picture():
    try:
        print(f"[{datetime.now()}] Taking a picture...")
        cam_port = 0  # Default camera port
        
        try:
            cam = cv2.VideoCapture(cam_port)
            cam.grab()
            
            if not cam.isOpened():
                print(f"[{datetime.now()}] ERROR: Could not open camera on port {cam_port}")
                return None
            
            # Set camera properties - these are the settings that worked well
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            cam.set(cv2.CAP_PROP_BRIGHTNESS, 0)  # Matches v4l2 brightness setting
            cam.set(cv2.CAP_PROP_CONTRAST, 32)   # Matches v4l2 contrast setting
            cam.set(cv2.CAP_PROP_SATURATION, 64) # Matches v4l2 saturation setting
            cam.set(cv2.CAP_PROP_HUE, 0)         # Matches v4l2 hue setting
            cam.set(cv2.CAP_PROP_SHARPNESS, 5)   # Matches v4l2 sharpness setting
            cam.set(cv2.CAP_PROP_GAIN, 10)       # Matches v4l2 gain setting
            cam.set(cv2.CAP_PROP_AUTO_WB, 1)     # Auto white balance ON
            cam.set(cv2.CAP_PROP_BACKLIGHT, 0)   # Backlight compensation OFF
            cam.set(cv2.CAP_PROP_EXPOSURE, 200)  # Exposure setting

            time.sleep(2)    
            
            result, image = cam.read()
    
            # Release the camera
            cam.release()
            
            if result and image is not None:
                # Save original image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                original_path = os.path.join(IMAGE_DIR, f"plant_{timestamp}.jpg")
                cv2.imwrite(original_path, image)
                
                # Also save as current.jpg for web display
                cv2.imwrite(CURRENT_IMAGE_PATH, image)
                
                # Manage image retention to keep only 5 most recent images
                manage_image_retention()
                
                print(f"[{datetime.now()}] Image captured and saved successfully")
                return CURRENT_IMAGE_PATH
            else:
                print(f"[{datetime.now()}] ERROR: Failed to capture valid image")
                return None
                
        except Exception as e:
            print(f"[{datetime.now()}] ERROR with camera: {str(e)}")
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
                {"role": "system", "content": "You are a carnivorous plant health expert. Examine the picture of the tank containing the plants. analyse leaves, colour, pitchers or flytraps, growth and any signs of decay"},
                {"role": "system", "content": "plant_status follows log info, warning, critical. plant_type to be venus flytrap, pitcher plant, sundew. plant_id is the unique identifier of the plant. plant_diagnosis is the diagnosis of the plant. plant_position is where you have seen the plant in frame, for example top left, bottom right etc."},
                {"role": "system", "content": "There are multiple plants in the image. Please provide the diagnosis for each plant 1 by 1. Note there maybe duplicates so pitcher1, pitcher2 etc."},
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

            if plant.plant_status == "info":
                msg = f"{plant.plant_type}: {plant.plant_id} -> {plant.plant_position}" 
                logging.info(msg, extra={
                    "plant.id": plant.plant_id,
                    "plant.type": plant.plant_type,
                    "plant.status": plant.plant_status,
                    "plant.diagnosis": plant.plant_diagnosis,
                    "plant.position": plant.plant_position

                })

            elif plant.plant_status == "warning":
                msg = f"{plant.plant_type}: {plant.plant_id} -> {plant.plant_position}"
                logging.warning(msg, extra={
                    "plant.id": plant.plant_id,
                    "plant.type": plant.plant_type,
                    "plant.status": plant.plant_status,
                    "plant.diagnosis": plant.plant_diagnosis,
                    "plant.position": plant.plant_position
                })
                
            elif plant.plant_status == "critical":
                msg = f"{plant.plant_type}: {plant.plant_id} -> {plant.plant_position}"
                logging.critical(msg, extra={
                    "plant.id": plant.plant_id,
                    "plant.type": plant.plant_type,
                    "plant.status": plant.plant_status,
                    "plant.diagnosis": plant.plant_diagnosis,
                    "plant.position": plant.plant_position
                })
        
        # Print summary for application logs
        duration_ms = (time.time() - start_time) * 1000
        print(f"[{datetime.now()}] Successfully analyzed {len(analysis_result.log)} plants in {duration_ms:.2f}ms")
        
        return analysis_result
        
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to analyze image: {str(e)}")
        return None

# Function to fetch sensor data from Prometheus
def fetch_sensor_data():
    """Fetch the last 12 hours of sensor data from Prometheus using HTTP API"""
    try:
        # Calculate time range (12 hours ago)
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=12)
        
        # Prometheus query endpoint
        prometheus_url = "http://plant-hub:9090/api/v1/query_range"
        
        # Query parameters
        params = {
            "start": start_time.timestamp(),
            "end": end_time.timestamp(),
            "step": "5m"  # 5-minute intervals
        }
        
        # Use Prometheus's built-in functions for calculations
        queries = {
            "temperature": {
                "min": "min_over_time(temperature_celsius[12h])",
                "max": "max_over_time(temperature_celsius[12h])",
                "avg": "avg_over_time(temperature_celsius[12h])",
                "current": "temperature_celsius",
                "histogram": "rate(temperature_celsius[5m])"  # Rate of change over 5m windows
            },
            "humidity": {
                "min": "min_over_time(humidity_percent[12h])",
                "max": "max_over_time(humidity_percent[12h])",
                "avg": "avg_over_time(humidity_percent[12h])",
                "current": "humidity_percent",
                "histogram": "rate(humidity_percent[5m])"  # Rate of change over 5m windows
            }
        }
        
        # Fetch all metrics in one go
        results = {}
        for metric, queries in queries.items():
            results[metric] = {}
            for stat, query in queries.items():
                params["query"] = query
                response = requests.get(prometheus_url, params=params)
                data = response.json()
                
                if data["status"] == "success" and data["data"]["result"]:
                    if stat == "current":
                        value = float(data["data"]["result"][0]["values"][-1][1])
                        results[metric][stat] = value
                    elif stat == "histogram":
                        # For histogram, we'll store the last 12 values (1 hour) of rate changes
                        values = [float(v[1]) for v in data["data"]["result"][0]["values"][-12:]]
                        results[metric][stat] = {
                            "values": values,
                            "avg_rate": sum(values) / len(values) if values else 0,
                            "max_rate": max(values) if values else 0,
                            "min_rate": min(values) if values else 0
                        }
                    else:
                        # For range queries (min/max/avg), the value is in the first result
                        value = float(data["data"]["result"][0]["values"][0][1])
                        results[metric][stat] = value
                else:
                    print(f"[{datetime.now()}] ERROR: Failed to fetch {metric} {stat} from Prometheus")
                    return None
        
        return results
            
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to fetch sensor data: {str(e)}")
        return None

# Function to analyze tank health
def analyze_tank_health(image_path, sensor_data):
    """Analyze tank health using both image and sensor data"""
    try:
        # Encode the image
        encoded_image = encode_image(image_path)
        
        # Create a new OpenAI request
        response = openai_client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a carnivorous plant tank health expert. Analyze the tank conditions based on both the visual image and sensor data."},
                {"role": "system", "content": "tank_status follows log info, warning, critical. temperature_analysis should analyze temperature trends and stability. humidity_analysis should analyze humidity trends and stability. combined_diagnosis should consider both visual and sensor data. recommendations should provide actionable steps."},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Analyze the tank health based on the image and sensor data:\n\nTemperature Data:\nMin: {sensor_data['temperature']['min']:.1f}°C\nMax: {sensor_data['temperature']['max']:.1f}°C\nAvg: {sensor_data['temperature']['avg']:.1f}°C\nCurrent: {sensor_data['temperature']['current']:.1f}°C\n\nHumidity Data:\nMin: {sensor_data['humidity']['min']:.1f}%\nMax: {sensor_data['humidity']['max']:.1f}%\nAvg: {sensor_data['humidity']['avg']:.1f}%\nCurrent: {sensor_data['humidity']['current']:.1f}%",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpg;base64,{encoded_image}"},
                        },
                    ],
                }
            ],
            response_format=TankHealth
        )
        
        # Extract the analysis results
        tank_analysis = response.choices[0].message.parsed
        
        # Log the tank health analysis
        if tank_analysis.tank_status == "info":
            logging.info("Tank Health Analysis", extra={
                "tank.status": tank_analysis.tank_status,
                "temperature.analysis": tank_analysis.temperature_analysis,
                "humidity.analysis": tank_analysis.humidity_analysis,
                "combined.diagnosis": tank_analysis.combined_diagnosis,
                "recommendations": tank_analysis.recommendations
            })
        elif tank_analysis.tank_status == "warning":
            logging.warning("Tank Health Analysis", extra={
                "tank.status": tank_analysis.tank_status,
                "temperature.analysis": tank_analysis.temperature_analysis,
                "humidity.analysis": tank_analysis.humidity_analysis,
                "combined.diagnosis": tank_analysis.combined_diagnosis,
                "recommendations": tank_analysis.recommendations
            })
        else:  # critical
            logging.critical("Tank Health Analysis", extra={
                "tank.status": tank_analysis.tank_status,
                "temperature.analysis": tank_analysis.temperature_analysis,
                "humidity.analysis": tank_analysis.humidity_analysis,
                "combined.diagnosis": tank_analysis.combined_diagnosis,
                "recommendations": tank_analysis.recommendations
            })
        
        return tank_analysis
        
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to analyze tank health: {str(e)}")
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
            
            # Fetch and analyze sensor data
            sensor_data = fetch_sensor_data()
            if sensor_data:
                tank_analysis = analyze_tank_health(image_path, sensor_data)
                if tank_analysis:
                    print(f"[{datetime.now()}] Tank health analysis completed successfully")
                else:
                    print(f"[{datetime.now()}] ERROR: Failed to analyze tank health")
            else:
                print(f"[{datetime.now()}] ERROR: Failed to fetch sensor data")
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

@app.route('/api/metrics')
def test_metrics():
    """Test endpoint to fetch and return sensor metrics"""
    try:
        print(f"[{datetime.now()}] Testing Prometheus queries")
        sensor_data = fetch_sensor_data()
        if sensor_data:
            return jsonify({
                "status": "success",
                "data": sensor_data
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to fetch sensor data"
            }), 500
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Metrics test failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/image/base64')
def get_image_base64():
    """Return the current image in base64 format"""
    try:
        if os.path.exists(CURRENT_IMAGE_PATH):
            with open(CURRENT_IMAGE_PATH, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            return jsonify({
                "status": "success",
                "data": encoded_string
            })
        else:
            return jsonify({
                "status": "error",
                "message": "No image available"
            }), 404
    except Exception as e:
        print(f"[{datetime.now()}] ERROR: Failed to encode image: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# Main entry point
if __name__ == "__main__":
    # Set up the scheduler for 9am and 5pm captures
    scheduler = BackgroundScheduler()
    scheduler.add_job(capture_and_analyze, 'cron', hour='9,12,17')
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
