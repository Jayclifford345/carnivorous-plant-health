import time
import board
import adafruit_sht31d
# Import metrics-related modules for managing and exporting metrics with OpenTelemetry.
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

# Create sensor object, communicating over the board's default I2C bus
i2c = board.I2C()  # uses board.SCL and board.SDA
sensor = adafruit_sht31d.SHT31D(i2c)
sensor_name = "SHT31-D"
serial_number = sensor.serial_number  # Retrieve sensor's serial number
service_name = "sensor_reader"

temp = 0
hum = 0


INTERVAL_SEC=5

def read_temperature(observer):
    global temp
    return [metrics.Observation(value=temp)]

def read_humidity(observer):
    global hum
    return [metrics.Observation(value=hum)]

def create_guage():
    exporter = OTLPMetricExporter(endpoint="http://plant-hub:4318/v1/metrics")
    metric_reader = PeriodicExportingMetricReader(exporter, INTERVAL_SEC)
    meter_provider = MeterProvider(
                    metric_readers=[metric_reader], 
                    resource=Resource.create({"service.name": service_name, "serial_number": serial_number, "sensor_name": sensor_name})
                )

    metrics.set_meter_provider(meter_provider)

    meter = metrics.get_meter(__name__)

    temp_guage = meter.create_observable_gauge(
                name="temperature_celsius",
                description="Temperature in Celsius",
                callbacks=[read_temperature]
            )

    humidity_gauge = meter.create_observable_gauge(
                name="humidity_percent",
                description="Relative Humidity",
                callbacks=[read_humidity]
            )
    return temp_guage, humidity_gauge

def main():
    """Main loop with controlled heater usage."""
    heater_on = False
    last_heater_time = 0
    last_reading = 0
    create_guage()

    while True:
        global temp, hum
        temp = sensor.temperature
        hum = sensor.relative_humidity
        current_time = time.time()

        # 🌡️ **Heater Strategy**
        if hum >= 99.5 and not heater_on:  
            print("⚠️ Condensation risk detected! Enabling heater for 1 min.")
            sensor.heater = True
            heater_on = True
            last_heater_time = current_time  # Store heater activation time

        # 🔄 **Turn off heater after 1 min**
        if heater_on and (current_time - last_heater_time > 60):
            print("✅ Heater cycle complete, turning off.")
            sensor.heater = False
            heater_on = False

        if current_time - last_reading > 60:
             print(f"🌡️ Temp: {temp:.2f}°C | 💧 Humidity: {hum:.2f}%")
             last_reading = current_time
        time.sleep(5)
        
if __name__ == "__main__":
    main()