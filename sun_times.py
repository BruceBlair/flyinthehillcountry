#!/usr/bin/env python3
"""
sun_times.py — outputs sunrise/sunset as seconds-since-local-midnight.

Usage: sun_times.py <lat> <lon> <YYYYMMDD>

Requires: pip install astral --break-system-packages
"""
import sys
from astral import LocationInfo
from astral.sun import sun
from datetime import datetime

lat, lon, datestr = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
date = datetime.strptime(datestr, "%Y%m%d").date()
loc = LocationInfo(latitude=lat, longitude=lon)
s = sun(loc.observer, date=date, tzinfo="America/Chicago")

def to_secs(dt):
    return dt.hour * 3600 + dt.minute * 60 + dt.second

print(to_secs(s["sunrise"]), to_secs(s["sunset"]))
