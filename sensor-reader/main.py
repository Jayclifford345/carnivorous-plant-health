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
exporter = OTLPMetricExporter(endpoint="http://plant-hub:4318/v1/metrics")
metric_reader = PeriodicExportingMetricReader(exporter, INTERVAL_SEC)
meter_provider = MeterProvider(
                metric_readers=[metric_reader], 
                resource=Resource.create({"service.name": service_name, "serial_number": serial_number, "sensor_name": sensor_name})
            )
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(__name__)


def read_temperature():
    return [metrics.Observation(value=temp)]

def read_humidity(observer):
    return [metrics.Observation(value=hum)]




        # Create an observable gauge for the forge heat level (keep this as gauge)
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

def main(): 
    global temp, hum
    # Keep the application running indefinitely
    while True:
        sensor.heater = True
        time.sleep(1)  # Allow sensor to stabilize
        hum = sensor.relative_humidity
        temp = sensor.temperature
        sensor.heater = False
        print(f"Humidity: {hum:.2f}%")
        print(f"Temperature: {temp:.2f}°C")

if __name__ == "__main__":
    main()