# Ecowitt Weather Station Integration Design

**Date:** 2026-06-05
**Hardware:** Ecowitt GW3000 (W3000) gateway + WS90 7-in-1 outdoor array

## Overview

Connect the Ecowitt weather station to the Ground Truth Network so real sensor readings flow into InfluxDB and power the existing HA automations (storm alerts, daily summary, golden-hour window).

## Architecture

```
WS90 array (868 MHz wireless)
  → GW3000 gateway (HTTP push, 60s interval)
    → Home Assistant :4199  [built-in Ecowitt integration]
      → native entities (sensor.gw3000_*)
        → template sensors (sensor.weather_*)
          → InfluxDB bucket: sensor_data  [existing HA integration]
            → Grafana dashboards
```

No new Docker service. MQTT is not involved for weather data.

## Sensors

The WS90 reports:

| Physical sensor | Template entity | Unit |
|---|---|---|
| Outdoor temperature | `sensor.weather_temperature` | °F |
| Outdoor humidity | `sensor.weather_humidity` | % |
| Wind speed | `sensor.weather_wind_speed` | mph |
| Wind direction | `sensor.weather_wind_direction` | ° |
| Wind gust | `sensor.weather_wind_gust` | mph |
| Rain rate | `sensor.weather_precipitation_rate` | in/hr |
| Daily rain accumulation | `sensor.weather_precipitation` | in |
| UV index | `sensor.weather_uv_index` | UV index |
| Solar radiation | `sensor.weather_solar_radiation` | W/m² |

The GW3000 gateway reports:

| Physical sensor | Template entity | Unit |
|---|---|---|
| Barometric pressure | `sensor.weather_pressure` | inHg |

## Implementation Phases

### Phase 1 — Hardware + HA integration (one-time manual steps)

1. **Configure gateway push** — in Ecowitt app or gateway web UI (`http://<gateway-ip>`):
   - Custom server: protocol `Ecowitt`, IP `192.168.100.202`, port `4199`, path `/data/report/`
   - Upload interval: 60 s
2. **Add HA integration** — Settings → Integrations → Add → Ecowitt
   - HA listens on port 4199; auto-discovers all WS90 channels on first push
3. **Record entity IDs** — note the exact entity IDs HA assigns (they depend on the device name set in the gateway, e.g. `sensor.gw3000_outdoor_temperature`)

### Phase 2 — Template sensors + config reload

4. **Add template sensors** to `ha-configuration.yaml` — extend the existing `template: - sensor:` block with one entry per weather entity, mapping each Ecowitt native entity → `sensor.weather_*`
5. **Deploy updated config** via `docker cp ha-configuration.yaml homeassistant:/config/configuration.yaml` and reload HA
6. **Verify InfluxDB logging** — existing `entity_globs: sensor.weather_*` already captures all template sensors; confirm with a quick Flux query

### Phase 3 — Cleanup

7. **Retire `pi-sensor-publisher.py`** — add a header comment marking it superseded; do not delete (documents the original MQTT sensor schema)

## Constraints

- Template sensor names must remain `sensor.weather_*` — automations (`storm_detected`, `storm_severity`, `sensor_data_to_mqtt`, daily summary) reference these entity IDs directly
- Phase 2 cannot start until Phase 1 is complete and entity IDs are known
- HA config deploy must use `docker cp` (never stdin redirect — silently empties the file)

## Out of Scope

- Grafana dashboard changes (existing panels will populate automatically once entities exist)
- MQTT republishing of weather data (not needed; no other service currently consumes sensor readings from MQTT)
- Indoor temperature / secondary sensors (only standard WS90 outdoor array + GW3000 barometric)
