#!/usr/bin/env python3
"""
Weather Station Sensor Publisher — SUPERSEDED 2026-06-05

Placeholder for Raspberry Pi sensor publishing; all sensor readings
were stub values. Replaced by Ecowitt GW3000B + WS90 hardware array
pushing directly to Home Assistant's Ecowitt integration (port 8123
webhook) as of 2026-06-05.

Kept for reference: documents the original MQTT schema
(sensors/outdoor/<metric>) and JSON payload format.
"""

import time
import json
import paho.mqtt.client as mqtt
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MQTT Configuration
MQTT_BROKER = "YOUR_NAS_IP"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "weather_station_pi"
MQTT_BASE_TOPIC = "sensors/outdoor"

# Sensor Configuration
LOCATION = "outdoor"
PUBLISH_INTERVAL = 60  # seconds

class SensorPublisher:
    def __init__(self):
        self.client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_publish = self.on_publish
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            # Publish connection status
            self.publish_status("online")
        else:
            logger.error(f"Connection failed with code {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        logger.warning(f"Disconnected from MQTT broker with code {rc}")
        if rc != 0:
            logger.info("Attempting to reconnect...")
    
    def on_publish(self, client, userdata, mid):
        logger.debug(f"Message {mid} published")
    
    def publish_status(self, status):
        """Publish station status"""
        topic = f"{MQTT_BASE_TOPIC}/status"
        payload = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "client_id": MQTT_CLIENT_ID
        }
        self.client.publish(topic, json.dumps(payload), retain=True)
    
    def read_temperature(self):
        """Read temperature sensor - IMPLEMENT YOUR SENSOR CODE HERE"""
        # Example for DHT22 or BME280
        # Replace with your actual sensor reading code
        try:
            # Placeholder - replace with actual sensor reading
            temperature = 72.5  # °F
            return temperature
        except Exception as e:
            logger.error(f"Error reading temperature: {e}")
            return None
    
    def read_humidity(self):
        """Read humidity sensor"""
        try:
            # Placeholder - replace with actual sensor reading
            humidity = 65.0  # %
            return humidity
        except Exception as e:
            logger.error(f"Error reading humidity: {e}")
            return None
    
    def read_pressure(self):
        """Read barometric pressure sensor"""
        try:
            # Placeholder - replace with actual sensor reading
            pressure = 29.92  # inHg
            return pressure
        except Exception as e:
            logger.error(f"Error reading pressure: {e}")
            return None
    
    def read_wind_speed(self):
        """Read wind speed sensor"""
        try:
            # Placeholder - replace with actual sensor reading
            wind_speed = 5.2  # mph
            return wind_speed
        except Exception as e:
            logger.error(f"Error reading wind speed: {e}")
            return None
    
    def read_wind_direction(self):
        """Read wind direction sensor"""
        try:
            # Placeholder - replace with actual sensor reading
            wind_direction = 180  # degrees
            return wind_direction
        except Exception as e:
            logger.error(f"Error reading wind direction: {e}")
            return None
    
    def read_rainfall(self):
        """Read rainfall sensor (rain gauge)"""
        try:
            # Placeholder - replace with actual sensor reading
            rainfall = 0.0  # inches
            return rainfall
        except Exception as e:
            logger.error(f"Error reading rainfall: {e}")
            return None
    
    def read_light_level(self):
        """Read light/UV sensor"""
        try:
            # Placeholder - replace with actual sensor reading
            light_level = 50000  # lux
            return light_level
        except Exception as e:
            logger.error(f"Error reading light level: {e}")
            return None
    
    def publish_sensor_reading(self, sensor_id, value, unit):
        """Publish individual sensor reading"""
        if value is None:
            logger.warning(f"Skipping null value for {sensor_id}")
            return
        
        topic = f"{MQTT_BASE_TOPIC}/{sensor_id}"
        payload = {
            "sensor_id": sensor_id,
            "location": LOCATION,
            "value": value,
            "unit": unit,
            "timestamp": datetime.now().isoformat()
        }
        
        result = self.client.publish(topic, json.dumps(payload), qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Published {sensor_id}: {value} {unit}")
        else:
            logger.error(f"Failed to publish {sensor_id}")
    
    def read_and_publish_all_sensors(self):
        """Read all sensors and publish to MQTT"""
        logger.info("Reading sensors...")
        
        # Temperature
        temp = self.read_temperature()
        if temp is not None:
            self.publish_sensor_reading("temperature", temp, "°F")
        
        # Humidity
        humidity = self.read_humidity()
        if humidity is not None:
            self.publish_sensor_reading("humidity", humidity, "%")
        
        # Pressure
        pressure = self.read_pressure()
        if pressure is not None:
            self.publish_sensor_reading("pressure", pressure, "inHg")
        
        # Wind Speed
        wind_speed = self.read_wind_speed()
        if wind_speed is not None:
            self.publish_sensor_reading("wind_speed", wind_speed, "mph")
        
        # Wind Direction
        wind_dir = self.read_wind_direction()
        if wind_dir is not None:
            self.publish_sensor_reading("wind_direction", wind_dir, "°")
        
        # Rainfall
        rainfall = self.read_rainfall()
        if rainfall is not None:
            self.publish_sensor_reading("rainfall", rainfall, "in")
        
        # Light Level
        light = self.read_light_level()
        if light is not None:
            self.publish_sensor_reading("light_level", light, "lux")
        
        # Publish aggregated reading
        self.publish_aggregated_reading({
            "temperature": temp,
            "humidity": humidity,
            "pressure": pressure,
            "wind_speed": wind_speed,
            "wind_direction": wind_dir,
            "rainfall": rainfall,
            "light_level": light
        })
    
    def publish_aggregated_reading(self, readings):
        """Publish all sensor readings as single message"""
        topic = f"{MQTT_BASE_TOPIC}/all"
        payload = {
            "location": LOCATION,
            "timestamp": datetime.now().isoformat(),
            "readings": readings
        }
        self.client.publish(topic, json.dumps(payload), qos=1)
    
    def run(self):
        """Main loop"""
        try:
            # Connect to MQTT broker
            logger.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            
            # Wait for connection
            time.sleep(2)
            
            # Main publish loop
            while True:
                try:
                    self.read_and_publish_all_sensors()
                    time.sleep(PUBLISH_INTERVAL)
                except KeyboardInterrupt:
                    logger.info("Shutting down...")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    time.sleep(10)  # Wait before retry
            
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            # Cleanup
            self.publish_status("offline")
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("Shutdown complete")

if __name__ == "__main__":
    publisher = SensorPublisher()
    publisher.run()
