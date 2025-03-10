import os
import time
import json
import logging
from datetime import datetime
import cv2  # OpenCV for camera access
import base64  # Base64 encoding for image processing
from openai import OpenAI
from pydantic import BaseModel

# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# Class plant health
class PlantHealth(BaseModel):
    plant_status: str
    plant_type: str
    plant_id: int
    plant_diagnosis: str

class Response(BaseModel):
    log: list[PlantHealth]



# Function that accesses the camera and takes a picture. Picture is saved in the same directory as the script. Also encoded in base64 for later processing
def take_picture():
    cam_port = 0
    cam = cv2.VideoCapture(cam_port) 
    
    # reading the input using the camera 
    result, image = cam.read() 
    # Access the camera
    if result: 
    
        # saving image in local storage 
        cv2.imwrite("plant.png", image) 
        cam.release()
    
    else:
        logging.error("Error in accessing the camera")
    
    # Encode the image
    encoded_image = encode_image("plant.png")
    return encoded_image


# Analyze the image using openAI request
def analyze_image(encoded_image):
    # Create a new OpenAI object
    openai = OpenAI()
    # Return the response
    response = openai.beta.chat.completions.parse(
    model="gpt-4o",
    messages=[
           {"role": "system", "content": "Your are a carnivorous plant health expert. Examine the daily picture of the plant and provide a state of health."},
           {"role": "system", "content": "plant_status follows log info, warning, critical. plant_type to be venus flytrap, pitcher plant, sundew. plant_id is the unique identifier of the plant. plant_diagnosis is the diagnosis of the plant."},
           {"role": "system", "content": "Theere could be multiple plants in the image. Please provide the diagnosis for each plant 1 by 1."},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "4 plants in the image",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded_image}"},
                    },
                ],
            }
        ],
        response_format=Response
    )
    print(response.choices[0].message.parsed)


# Main function
def main():
    # Take a picture
    encoded_image = take_picture()
    # Analyze the image
    analyze_image(encoded_image)

# Run the main function
if __name__ == "__main__":
    main()
