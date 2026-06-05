# Ecowitt W3000 + WS90 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the Ecowitt GW3000 gateway and WS90 sensor array to Home Assistant so real weather readings flow into InfluxDB and power existing storm/automation logic.

**Architecture:** The GW3000 pushes HTTP data to HA's built-in Ecowitt integration (port 4199). HA auto-creates native entities; template sensors in `ha-configuration.yaml` map those to the `sensor.weather_*` names that automations and InfluxDB entity globs already reference. No new Docker service needed.

**Tech Stack:** Ecowitt HA integration (built-in ≥ 2023.x), Home Assistant YAML config, InfluxDB 2.7 (existing), Docker

---

## File Map

| File | Change |
|---|---|
| `ha-configuration.yaml` | Extend `template: - sensor:` block with 10 weather template sensors |
| `pi-sensor-publisher.py` | Add deprecation header replacing the existing docstring |

`homeassistant/config/configuration.yaml` is the runtime copy of `ha-configuration.yaml` — deployed via `docker cp`, not edited directly.

---

### Task 1: Configure GW3000 gateway to push to Home Assistant

**No files changed — manual configuration on the gateway device.**

- [ ] **Step 1: Find the gateway's IP address**

On the NAS:
```bash
nmap -sn 192.168.100.0/24 | grep -B1 -i "ecowitt\|gw3000\|easyweather"
```
If nmap isn't available, check your router's DHCP leases for a device named `GW3000` or `EasyWeather`. Note the IP.

- [ ] **Step 2: Open the gateway web UI**

Browse to `http://<gateway-ip>` in a browser. Default credentials: `admin` / `admin`.

- [ ] **Step 3: Configure the custom server push**

Navigate to **Weather Services → Customized** (some firmware versions label it **Custom Server**) and enter:

| Field | Value |
|---|---|
| Protocol | Ecowitt |
| Server IP / Hostname | `192.168.100.202` |
| Server Port | `4199` |
| Upload Path | `/data/report/` |
| Upload Interval | `60` (seconds) |

Save. The page should confirm "Customized: Enabled".

- [ ] **Step 4: Verify the gateway is sending packets**

HA is not listening on 4199 yet, so use netcat to confirm data arrives:
```bash
nc -l 4199 &
NC_PID=$!
echo "Waiting up to 75s for gateway push..."
sleep 75 && kill $NC_PID 2>/dev/null
```
Expected: an HTTP POST body appears before the 75s timeout, containing field names like `tempf`, `humidity`, `windspeedmph`, etc. If nothing arrives, recheck the gateway IP/port settings.

---

### Task 2: Add Ecowitt integration in Home Assistant and discover entity IDs

**No files changed — manual HA UI steps.**

- [ ] **Step 1: Add the Ecowitt integration**

In HA: **Settings → Integrations → Add Integration → search "Ecowitt"**

When prompted for port, enter `4199` and click **Submit**. HA will show "Waiting for device…" — it will auto-configure on the next gateway push (up to 60s).

- [ ] **Step 2: Confirm device discovered**

After the first push the integration shows the GW3000 device with all WS90 channels. Go to **Settings → Devices & Services → Ecowitt → [your device]** and open the entity list to confirm sensors are present.

- [ ] **Step 3: Record the exact entity IDs**

Go to **Developer Tools → States**, filter by typing part of the gateway's device name (e.g. `gw3000` or `ws90`). For each row below, find the entity ID HA assigned and write it down — you will substitute it in Task 3.

| Physical reading | Look for entity containing… | Write actual entity ID here |
|---|---|---|
| Outdoor temperature | `temperature` | |
| Outdoor humidity | `humidity` | |
| Wind speed | `wind_speed` | |
| Wind direction | `wind_dir` or `bearing` | |
| Wind gust | `gust` | |
| Rain rate | `rain_rate` or `precipitation_rate` | |
| Daily rain accumulation | `rain` + `daily` or `event` | |
| UV index | `uv` | |
| Solar radiation | `solar` | |
| Barometric pressure | `pressure` or `baromrelin` | |

---

### Task 3: Add template sensors to ha-configuration.yaml

**File:** `ha-configuration.yaml`

- [ ] **Step 1: Locate the existing template sensor list**

```bash
grep -n "template:\|- sensor:\|Sun Azimuth" /home/HighlyReflective/weather-station/ha-configuration.yaml
```
The `template:` block starts around line 131. The last entry in the `- sensor:` list is `Sun Azimuth` (around line 165). The 10 new sensors go after it, inside the same `- sensor:` list.

- [ ] **Step 2: Add template sensors after "Sun Azimuth"**

In `ha-configuration.yaml`, append the following entries to the `- sensor:` list (inside `template:`). Substitute each `sensor.REPLACE_ME_*` with the actual entity IDs from Task 2 Step 3.

```yaml
    - name: "Weather Temperature"
      unique_id: weather_temperature
      state: "{{ states('sensor.REPLACE_ME_temperature') | float(0) | round(1) }}"
      unit_of_measurement: "°F"
      device_class: temperature
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_temperature') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Humidity"
      unique_id: weather_humidity
      state: "{{ states('sensor.REPLACE_ME_humidity') | float(0) | round(1) }}"
      unit_of_measurement: "%"
      device_class: humidity
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_humidity') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Wind Speed"
      unique_id: weather_wind_speed
      state: "{{ states('sensor.REPLACE_ME_wind_speed') | float(0) | round(1) }}"
      unit_of_measurement: "mph"
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_wind_speed') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Wind Direction"
      unique_id: weather_wind_direction
      state: "{{ states('sensor.REPLACE_ME_wind_direction') | float(0) | round(0) }}"
      unit_of_measurement: "°"
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_wind_direction') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Wind Gust"
      unique_id: weather_wind_gust
      state: "{{ states('sensor.REPLACE_ME_wind_gust') | float(0) | round(1) }}"
      unit_of_measurement: "mph"
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_wind_gust') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Precipitation Rate"
      unique_id: weather_precipitation_rate
      state: "{{ states('sensor.REPLACE_ME_rain_rate') | float(0) | round(3) }}"
      unit_of_measurement: "in/hr"
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_rain_rate') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Precipitation"
      unique_id: weather_precipitation
      state: "{{ states('sensor.REPLACE_ME_rain_daily') | float(0) | round(3) }}"
      unit_of_measurement: "in"
      state_class: total_increasing
      availability: "{{ states('sensor.REPLACE_ME_rain_daily') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Pressure"
      unique_id: weather_pressure
      state: "{{ states('sensor.REPLACE_ME_pressure') | float(0) | round(2) }}"
      unit_of_measurement: "inHg"
      device_class: atmospheric_pressure
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_pressure') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather UV Index"
      unique_id: weather_uv_index
      state: "{{ states('sensor.REPLACE_ME_uv') | float(0) | round(1) }}"
      unit_of_measurement: "UV index"
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_uv') not in ['unavailable', 'unknown', 'none'] }}"

    - name: "Weather Solar Radiation"
      unique_id: weather_solar_radiation
      state: "{{ states('sensor.REPLACE_ME_solar') | float(0) | round(1) }}"
      unit_of_measurement: "W/m²"
      device_class: irradiance
      state_class: measurement
      availability: "{{ states('sensor.REPLACE_ME_solar') not in ['unavailable', 'unknown', 'none'] }}"
```

- [ ] **Step 3: Validate the YAML is well-formed**

```bash
cd /home/HighlyReflective/weather-station
python3 -c "import yaml; yaml.safe_load(open('ha-configuration.yaml'))" && echo "YAML OK"
```
Expected: `YAML OK`. If it errors, the output shows the line number — fix indentation and retry.

- [ ] **Step 4: Commit**

```bash
cd /home/HighlyReflective/weather-station
git add ha-configuration.yaml
git commit -m "feat: add sensor.weather_* template sensors mapped from Ecowitt entities"
```

---

### Task 4: Deploy config and verify end-to-end

- [ ] **Step 1: Copy config into the HA container**

```bash
cd /home/HighlyReflective/weather-station
docker cp ha-configuration.yaml homeassistant:/config/configuration.yaml
```

- [ ] **Step 2: Validate config inside HA before reloading**

```bash
docker exec homeassistant python3 -m homeassistant --config /config --script check_config
```
Expected: `Configuration check passed!`

If it fails, the error shows which line is invalid. Fix in `ha-configuration.yaml`, repeat Step 1, then re-run check.

- [ ] **Step 3: Reload HA configuration**

```bash
curl -s -X POST http://localhost:8123/api/services/homeassistant/reload_all \
  -H "Authorization: Bearer $(grep HA_TOKEN .env | cut -d= -f2)" \
  -H "Content-Type: application/json"
```

Or via UI: **Developer Tools → YAML → Reload All YAML Configuration**.

- [ ] **Step 4: Verify all 10 template sensors are live**

```bash
curl -s http://localhost:8123/api/states \
  -H "Authorization: Bearer $(grep HA_TOKEN .env | cut -d= -f2)" \
  | python3 -c "
import sys, json
states = json.load(sys.stdin)
weather = [s for s in states if s['entity_id'].startswith('sensor.weather_')]
for s in sorted(weather, key=lambda x: x['entity_id']):
    unit = s['attributes'].get('unit_of_measurement', '')
    print(f\"{s['entity_id']}: {s['state']} {unit}\")
print(f\"\n{len(weather)} sensor.weather_* entities found\")
"
```

Expected (values will be real readings):
```
sensor.weather_humidity: 68.0 %
sensor.weather_precipitation: 0.000 in
sensor.weather_precipitation_rate: 0.000 in/hr
sensor.weather_pressure: 29.92 inHg
sensor.weather_solar_radiation: 412.5 W/m²
sensor.weather_temperature: 76.4 °F
sensor.weather_uv_index: 3.2 UV index
sensor.weather_wind_direction: 180.0 °
sensor.weather_wind_gust: 8.3 mph
sensor.weather_wind_speed: 5.1 mph

10 sensor.weather_* entities found
```

If any show `unavailable`: the source entity ID in that template is wrong — go back to Task 2 Step 3, find the correct ID in Developer Tools → States, and update `ha-configuration.yaml`.

- [ ] **Step 5: Verify InfluxDB is receiving weather data**

```bash
docker exec influxdb influx query '
  from(bucket:"sensor_data")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "state")
  |> filter(fn: (r) => r.entity_id =~ /weather_/)
  |> keep(columns: ["entity_id", "_value", "_time"])
  |> sort(columns: ["entity_id"])
' 2>/dev/null | head -30
```

Expected: rows for each `sensor.weather_*` entity with numeric values and recent timestamps.

- [ ] **Step 6: Verify storm detection is healthy**

```bash
curl -s http://localhost:8123/api/states/binary_sensor.storm_detected \
  -H "Authorization: Bearer $(grep HA_TOKEN .env | cut -d= -f2)" \
  | python3 -c "import sys,json; s=json.load(sys.stdin); print('storm_detected:', s['state'])"
```

Expected: `storm_detected: off` (assuming no storm). If `unavailable`, `sensor.weather_wind_speed` or `sensor.weather_precipitation_rate` is still unavailable — recheck Task 4 Step 4.

---

### Task 5: Retire pi-sensor-publisher.py and final commit

- [ ] **Step 1: Replace the existing docstring in pi-sensor-publisher.py**

Find the existing docstring at the top of the file (lines 2–6) and replace it with:

```python
#!/usr/bin/env python3
"""
Weather Station Sensor Publisher — SUPERSEDED 2026-06-05

Placeholder for Raspberry Pi sensor publishing; all sensor readings
were stub values. Replaced by Ecowitt GW3000 + WS90 hardware array
pushing directly to Home Assistant's Ecowitt integration (port 4199).

Kept for reference: documents the original MQTT schema
(sensors/outdoor/<metric>) and JSON payload format.
"""
```

- [ ] **Step 2: Commit**

```bash
cd /home/HighlyReflective/weather-station
git add pi-sensor-publisher.py
git commit -m "chore: mark pi-sensor-publisher superseded by Ecowitt hardware"
```
