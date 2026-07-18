"""Thin paho-mqtt wrapper for audio-scout."""
import json
import logging
import os
import time

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

log = logging.getLogger("audio-scout.mqtt")


class MQTTClient:
    def __init__(self):
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._connected = False

    def connect(self) -> None:
        self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        self._client.loop_start()
        for _ in range(20):
            if self._connected:
                return
            time.sleep(0.25)
        raise RuntimeError(f"MQTT connect timeout ({MQTT_HOST}:{MQTT_PORT})")

    def publish(self, topic: str, payload: dict | str) -> None:
        msg = json.dumps(payload) if isinstance(payload, dict) else payload
        self._client.publish(topic, msg, qos=1)

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self._connected = (rc == 0)
        if rc == 0:
            log.info("MQTT connected (%s:%s)", MQTT_HOST, MQTT_PORT)
        else:
            log.error("MQTT connect failed rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc, properties=None, reason=None):
        self._connected = False
        log.warning("MQTT disconnected rc=%s", rc)
