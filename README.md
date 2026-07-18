# hithc-gtn-depot

Ground Truth Network (GTN) sensor-deployment backend and demo site for High in the Hill Country LLC.

Deployed weather station, camera NVR, and environmental sensing hub. Successor to the `weather-station` practice repo (archived at `weather-station-archive` on the same host) — this repo keeps the network-hardened data-collection layer and drops the placeholder UI in favor of a proper demo site (see `docs/superpowers/specs/` in the `hithc-brainstorms` repo for the design).

## Deployment

```bash
cp .env.example .env   # fill in real credentials
docker compose up -d
```

Services: `mosquitto`, `influxdb`, `homeassistant`, `grafana`, `frigate`, `mediamtx`, `highlight-curator`, `star-scanner`, `vote-server`, `night-sky-patrol`, `sky-watcher`, `audio-scout`, `nginx-ssl`, `ffmpeg-processor`.
