import requests
import json
import re
import datetime
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request
from zoneinfo import ZoneInfo

app = Flask(__name__)

cached_data = []
last_fetch_time = None
vehicle_count = 0
cache_lock = threading.Lock()
CACHE_DURATION = timedelta(minutes=5)
HUNGARY_TZ = ZoneInfo("Europe/Budapest")

last_force_fetch_time = None
FORCE_COOLDOWN = timedelta(minutes=1)

API_URL = "https://emma.mav.hu/otp2-backend/otp/routers/default/index/graphql"
GRAPHQL_QUERY = """
{
  vehiclePositions(
    swLat: 45.7,
    swLon: 16.1,
    neLat: 48.6,
    neLon: 22.9
  ) {
    vehicleId
    lat
    lon
    speed
    trip {
      gtfsId
      tripHeadsign
      directionId
      route {
        shortName
        longName
        type
      }
    }
    nextStop {
      arrivalDelay
      departureDelay
      stop {
        gtfsId
        name
        lat
        lon
      }
    }
  }
}
"""
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://emma.mav.hu",
    "Referer": "https://emma.mav.hu/",
}

LINE_1_EXCLUSIVE_STATIONS = {
    "Budaörs", "Törökbálint",
    "Biatorbágy", "Herceghalom", "Bicske alsó", "Bicske", "Szár",
    "Szárliget", "Alsógalla", "Tatabánya", "Vértesszőlős", "Tóvároskert",
    "Tata", "Almásfüzitő", "Almásfüzitő felső", "Komárom", "Ács",
    "Nagyszentjános", "Győrszentiván", "Abda", "Öttevény",
    "Lébény-Mosonszentmiklós", "Moson", "Mosonmagyaróvár", "Levél",
    "Hegyeshalom", "Bánhida", "Oroszlány"
}
ZONAL_ROUTES = ["S10", "G10", "S12"]
ROUTE_KEYWORDS = [
    "győr", "tatabánya", "hegyeshalom", "oroszlány", "wien", "komárom",
    "csárdás", "kálmán imre", "railjet", "rjx", "dráva", "mura", "savaria",
    "advent", "lehár", "liszt ferenc", "semmelweis", "dacia"
]

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>|&.*?;')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext

def get_delayed_trains_data():
    print("GYORSÍTÓTÁR FRISSÍTÉSE: Új adatok lekérése a MÁV API-tól...")
    try:
        response = requests.post(API_URL, headers=HEADERS, json={"query": GRAPHQL_QUERY})
        response.raise_for_status()
        data = response.json()

        if "data" not in data or "vehiclePositions" not in data["data"]:
            print("Hiba: Nem található 'vehiclePositions' az API válaszában.")
            return [], 0

        all_vehicles = data["data"]["vehiclePositions"]
        vehicle_count_now = len(all_vehicles)
        filtered_delayed_trains = []

        for vehicle in all_vehicles:
            trip = vehicle.get("trip")
            if not trip: continue
            route = trip.get("route")
            if not route: continue
            route_type = route.get("type")
            if not route_type: continue

            if not (100 < route_type < 200):
                continue

            longName_raw = route.get("longName")
            longName_lower = (longName_raw or "").lower()
            headsign_lower = (trip.get("tripHeadsign") or "").lower()

            next_stop_name = "N/A"
            nextStop = vehicle.get("nextStop")
            if nextStop and nextStop.get("stop"):
                next_stop_name = nextStop["stop"].get("name", "N/A")

            is_on_line_1 = False

            if longName_raw in ZONAL_ROUTES:
                is_on_line_1 = True
            else:
                for keyword in ROUTE_KEYWORDS:
                    if keyword in longName_lower or keyword in headsign_lower:
                        is_on_line_1 = True
                        break

            if not is_on_line_1:
                if next_stop_name in LINE_1_EXCLUSIVE_STATIONS:
                    is_on_line_1 = True

            if not is_on_line_1:
                continue

            delay_sec = 0
            if nextStop:
                arrival_delay = nextStop.get("arrivalDelay", 0) or 0
                departure_delay = nextStop.get("departureDelay", 0) or 0
                delay_sec = max(arrival_delay, departure_delay)

            if delay_sec > 0:
                train_longName = vehicle.get("trip", {}).get("route", {}).get("longName", "Ismeretlen")
                train_shortName_raw = vehicle.get("trip", {}).get("route", {}).get("shortName", "Ismeretlen")
                train_shortName = clean_html(train_shortName_raw)
                train_headsign = vehicle.get("trip", {}).get("tripHeadsign", "Ismeretlen")

                speed_kmh = vehicle.get("speed")
                speed_str = f"{int(speed_kmh)} km/h" if speed_kmh is not None else "N/A"
                delay_min = int(delay_sec / 60)

                vonat_nev = train_longName
                if "S" in vonat_nev or "G" in vonat_nev or "Z" in vonat_nev:
                     vonat_nev = f"{train_longName} ({train_shortName})"

                train_data = {
                    "delay_min": delay_min,
                    "delay_sec": delay_sec,
                    "name": vonat_nev,
                    "destination": train_headsign,
                    "next_stop": next_stop_name,
                    "speed": speed_str
                }
                filtered_delayed_trains.append(train_data)

        filtered_delayed_trains.sort(key=lambda x: x['delay_sec'], reverse=True)

        return filtered_delayed_trains, vehicle_count_now

    except requests.exceptions.RequestException as e:
        print(f"Hiba az adatlekérés során: {e}")
        return [], 0
    except json.JSONDecodeError:
        print("Hiba: Nem sikerült feldgozni a szerver válaszát (JSON).")
        return [], 0

@app.route('/')
def index():
    global cached_data, last_fetch_time, vehicle_count, last_force_fetch_time

    now = datetime.now(HUNGARY_TZ)
    force_refresh = request.args.get('force') == 'true'
    message = None
    message_type = "info"

    with cache_lock:
        perform_refresh = False

        if force_refresh:
            if not last_force_fetch_time or (now - last_force_fetch_time) > FORCE_COOLDOWN:
                perform_refresh = True
                last_force_fetch_time = now
                message = "Sikeres adatfrissítés"
                message_type = "info"
            else:
                message = "Túl gyakori kérés! A gyorsítótárazott adatok jelennek meg."
                message_type = "warning"

        elif not last_fetch_time or (now - last_fetch_time) > CACHE_DURATION:
            perform_refresh = True

        if perform_refresh:
            new_data, new_vehicle_count = get_delayed_trains_data()

            if new_vehicle_count > 100:
                print(f"Sikeres frissítés. Járműszám: {new_vehicle_count}. Cache frissítve.")
                cached_data = new_data
                vehicle_count = new_vehicle_count
                last_fetch_time = now
            else:
                print(f"API Hiba: Érvénytelen adat (járműszám: {new_vehicle_count}). A cache-t NEM frissítem.")
                if force_refresh:
                    message = "Hiba az API-tól (túl kevés adat). A gyorsítótárban lévő utolsó ismert adatok jelennek meg."
                    message_type = "warning"
        else:
            if not message:
                print("GYORSÍTÓTÁR HASZNÁLATA: Friss (5 percen belüli) adatokkal.")

    display_time = last_fetch_time if last_fetch_time else now

    update_time_str = display_time.strftime("%Y-%m-%d %H:%M:%S %Z")

    return render_template('index.html',
                           trains=cached_data,
                           vehicle_count=vehicle_count,
                           update_time=update_time_str,
                           message=message,
                           message_type=message_type)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
