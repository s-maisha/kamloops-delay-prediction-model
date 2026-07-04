import os
import sys
import time
import sqlite3
import requests
from google.transit import gtfs_realtime_pb2

DB_PATH = "gtfs.db"
TRIP_UPDATES_URL = "https://bct.tmix.se/gtfs-realtime/tripupdates.pb?operatorIds=46"
VEHICLE_POSITIONS_URL = "https://bct.tmix.se/gtfs-realtime/vehicleupdates.pb?operatorIds=46"

def initialize_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create realtime_trip_updates table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS "realtime_trip_updates" (
            "feed_timestamp" INTEGER,
            "trip_id" TEXT,
            "route_id" TEXT,
            "start_time" TEXT,
            "start_date" TEXT,
            "stop_sequence" INTEGER,
            "stop_id" TEXT,
            "arrival_delay" INTEGER,
            "arrival_time" INTEGER,
            "departure_delay" INTEGER,
            "departure_time" INTEGER,
            PRIMARY KEY ("trip_id", "stop_sequence", "feed_timestamp"),
            FOREIGN KEY ("trip_id") REFERENCES "trips" ("trip_id"),
            FOREIGN KEY ("stop_id") REFERENCES "stops" ("stop_id")
        )
    """)
    
    # Create realtime_vehicle_positions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS "realtime_vehicle_positions" (
            "feed_timestamp" INTEGER,
            "vehicle_id" TEXT,
            "trip_id" TEXT,
            "route_id" TEXT,
            "start_time" TEXT,
            "start_date" TEXT,
            "latitude" REAL,
            "longitude" REAL,
            "bearing" REAL,
            "speed" REAL,
            "current_status" TEXT,
            "current_stop_sequence" INTEGER,
            "stop_id" TEXT,
            PRIMARY KEY ("vehicle_id", "feed_timestamp")
        )
    """)
    
    conn.commit()
    conn.close()

def fetch_and_save_trip_updates():
    try:
        response = requests.get(TRIP_UPDATES_URL, timeout=10)
        if response.status_code != 200:
            print(f"Failed to fetch trip updates: {response.status_code}")
            return 0
        
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        
        feed_timestamp = feed.header.timestamp
        print(f"Parsed trip updates feed. Timestamp: {feed_timestamp}, Entities: {len(feed.entity)}")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        records = []
        for entity in feed.entity:
            if not entity.HasField('trip_update'):
                continue
                
            tu = entity.trip_update
            trip = tu.trip
            trip_id = trip.trip_id if trip.HasField('trip_id') else None
            route_id = trip.route_id if trip.HasField('route_id') else None
            start_time = trip.start_time if trip.HasField('start_time') else None
            start_date = trip.start_date if trip.HasField('start_date') else None
            
            for stu in tu.stop_time_update:
                stop_sequence = stu.stop_sequence if stu.HasField('stop_sequence') else None
                stop_id = stu.stop_id if stu.HasField('stop_id') else None
                
                arrival_delay = None
                arrival_time = None
                if stu.HasField('arrival'):
                    if stu.arrival.HasField('delay'):
                        arrival_delay = stu.arrival.delay
                    if stu.arrival.HasField('time'):
                        arrival_time = stu.arrival.time
                        
                departure_delay = None
                departure_time = None
                if stu.HasField('departure'):
                    if stu.departure.HasField('delay'):
                        departure_delay = stu.departure.delay
                    if stu.departure.HasField('time'):
                        departure_time = stu.departure.time
                
                if trip_id is not None and stop_sequence is not None:
                    records.append((
                        feed_timestamp, trip_id, route_id, start_time, start_date,
                        stop_sequence, stop_id, arrival_delay, arrival_time,
                        departure_delay, departure_time
                    ))
        
        if records:
            cursor.executemany("""
                INSERT OR IGNORE INTO "realtime_trip_updates" (
                    "feed_timestamp", "trip_id", "route_id", "start_time", "start_date",
                    "stop_sequence", "stop_id", "arrival_delay", "arrival_time",
                    "departure_delay", "departure_time"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()
            print(f"Saved {len(records)} stop time updates (ignored duplicates).")
            
        conn.close()
        return len(records)
    except Exception as e:
        print(f"Error fetching/saving trip updates: {e}")
        return 0

def fetch_and_save_vehicle_positions():
    try:
        response = requests.get(VEHICLE_POSITIONS_URL, timeout=10)
        if response.status_code != 200:
            print(f"Failed to fetch vehicle positions: {response.status_code}")
            return 0
        
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        
        feed_timestamp = feed.header.timestamp
        print(f"Parsed vehicle positions feed. Timestamp: {feed_timestamp}, Entities: {len(feed.entity)}")
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        records = []
        for entity in feed.entity:
            if not entity.HasField('vehicle'):
                continue
                
            v = entity.vehicle
            vehicle_id = v.vehicle.id if v.HasField('vehicle') and v.vehicle.HasField('id') else None
            
            if not vehicle_id:
                vehicle_id = v.vehicle.label if v.HasField('vehicle') and v.vehicle.HasField('label') else None
                
            if not vehicle_id:
                continue
                
            trip = v.trip if v.HasField('trip') else None
            trip_id = trip.trip_id if trip and trip.HasField('trip_id') else None
            route_id = trip.route_id if trip and trip.HasField('route_id') else None
            start_time = trip.start_time if trip and trip.HasField('start_time') else None
            start_date = trip.start_date if trip and trip.HasField('start_date') else None
            
            pos = v.position if v.HasField('position') else None
            latitude = pos.latitude if pos and pos.HasField('latitude') else None
            longitude = pos.longitude if pos and pos.HasField('longitude') else None
            bearing = pos.bearing if pos and pos.HasField('bearing') else None
            speed = pos.speed if pos and pos.HasField('speed') else None
            
            current_status = v.current_status if v.HasField('current_status') else None
            if current_status is not None:
                try:
                    current_status = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.Name(current_status)
                except ValueError:
                    current_status = str(current_status)
                
            current_stop_sequence = v.current_stop_sequence if v.HasField('current_stop_sequence') else None
            stop_id = v.stop_id if v.HasField('stop_id') else None
            
            timestamp = v.timestamp if v.HasField('timestamp') else feed_timestamp
            
            records.append((
                timestamp, vehicle_id, trip_id, route_id, start_time, start_date,
                latitude, longitude, bearing, speed, current_status,
                current_stop_sequence, stop_id
            ))
            
        if records:
            cursor.executemany("""
                INSERT OR IGNORE INTO "realtime_vehicle_positions" (
                    "feed_timestamp", "vehicle_id", "trip_id", "route_id", "start_time", "start_date",
                    "latitude", "longitude", "bearing", "speed", "current_status",
                    "current_stop_sequence", "stop_id"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()
            print(f"Saved {len(records)} vehicle positions (ignored duplicates).")
            
        conn.close()
        return len(records)
    except Exception as e:
        print(f"Error fetching/saving vehicle positions: {e}")
        return 0

def main():
    initialize_database()
    print("Database initialized.")
    
    run_once = "--once" in sys.argv
    poll_interval = 60
    
    print("Starting collection loop. Press Ctrl+C to stop.")
    while True:
        t0 = time.time()
        print(f"\n--- Polling at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
        fetch_and_save_trip_updates()
        fetch_and_save_vehicle_positions()
        
        if run_once:
            print("Run once requested. Exiting.")
            break
            
        elapsed = time.time() - t0
        sleep_time = max(1, poll_interval - elapsed)
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
