import os
import sys
import sqlite3
import argparse
import requests
from google.transit import gtfs_realtime_pb2

DB_PATH = "gtfs.db"


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


def parse_and_save_trip_updates(content):
    try:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(content)
        feed_timestamp = feed.header.timestamp

        records = []
        for entity in feed.entity:
            if not entity.HasField('trip_update'):
                continue

            tu = entity.trip_update
            trip = tu.trip
            trip_id = trip.trip_id if trip.HasField('trip_id') else None
            route_id = trip.route_id if trip.HasField('route_id') else None
            start_time = trip.start_time if trip.HasField(
                'start_time') else None
            start_date = trip.start_date if trip.HasField(
                'start_date') else None

            for stu in tu.stop_time_update:
                stop_sequence = stu.stop_sequence if stu.HasField(
                    'stop_sequence') else None
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
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR IGNORE INTO "realtime_trip_updates" (
                    "feed_timestamp", "trip_id", "route_id", "start_time", "start_date",
                    "stop_sequence", "stop_id", "arrival_delay", "arrival_time",
                    "departure_delay", "departure_time"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()
            conn.close()
            return len(records)
    except Exception as e:
        print(f"Error parsing trip updates: {e}")
    return 0


def parse_and_save_vehicle_positions(content):
    try:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(content)
        feed_timestamp = feed.header.timestamp

        records = []
        for entity in feed.entity:
            if not entity.HasField('vehicle'):
                continue

            v = entity.vehicle
            vehicle_id = v.vehicle.id if v.HasField(
                'vehicle') and v.vehicle.HasField('id') else None
            if not vehicle_id:
                vehicle_id = v.vehicle.label if v.HasField(
                    'vehicle') and v.vehicle.HasField('label') else None
            if not vehicle_id:
                continue

            trip = v.trip if v.HasField('trip') else None
            trip_id = trip.trip_id if trip and trip.HasField(
                'trip_id') else None
            route_id = trip.route_id if trip and trip.HasField(
                'route_id') else None
            start_time = trip.start_time if trip and trip.HasField(
                'start_time') else None
            start_date = trip.start_date if trip and trip.HasField(
                'start_date') else None

            pos = v.position if v.HasField('position') else None
            latitude = pos.latitude if pos and pos.HasField(
                'latitude') else None
            longitude = pos.longitude if pos and pos.HasField(
                'longitude') else None
            bearing = pos.bearing if pos and pos.HasField('bearing') else None
            speed = pos.speed if pos and pos.HasField('speed') else None

            current_status = v.current_status if v.HasField(
                'current_status') else None
            if current_status is not None:
                try:
                    current_status = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.Name(
                        current_status)
                except ValueError:
                    current_status = str(current_status)

            current_stop_sequence = v.current_stop_sequence if v.HasField(
                'current_stop_sequence') else None
            stop_id = v.stop_id if v.HasField('stop_id') else None
            timestamp = v.timestamp if v.HasField(
                'timestamp') else feed_timestamp

            records.append((
                timestamp, vehicle_id, trip_id, route_id, start_time, start_date,
                latitude, longitude, bearing, speed, current_status,
                current_stop_sequence, stop_id
            ))

        if records:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR IGNORE INTO "realtime_vehicle_positions" (
                    "feed_timestamp", "vehicle_id", "trip_id", "route_id", "start_time", "start_date",
                    "latitude", "longitude", "bearing", "speed", "current_status",
                    "current_stop_sequence", "stop_id"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()
            conn.close()
            return len(records)
    except Exception as e:
        print(f"Error parsing vehicle positions: {e}")
    return 0


def sync_bucket(bucket_name, prefix=None, anonymous=False):
    initialize_database()

    try:
        from google.cloud import storage
    except ImportError:
        print("Error: The 'google-cloud-storage' library is required to sync from a GCS bucket.")
        print("Please install it using: pip install google-cloud-storage")
        sys.exit(1)

    if anonymous:
        print("Connecting to GCS anonymously...")
        storage_client = storage.Client.create_anonymous_client()
    else:
        try:
            storage_client = storage.Client()
        except Exception as e:
            print(f"Failed to initialize authenticated GCS client: {e}")
            print("Attempting to connect anonymously...")
            try:
                storage_client = storage.Client.create_anonymous_client()
            except Exception as anon_err:
                print(
                    f"Error: Could not connect to GCS anonymously: {anon_err}")
                sys.exit(1)

    bucket = storage_client.bucket(bucket_name)

    print(f"Connecting to bucket '{bucket_name}'...")
    blobs = bucket.list_blobs(prefix=prefix)

    trip_count = 0
    vehicle_count = 0
    processed_files = 0

    print("Beginning synchronization of .pb files...")
    for blob in blobs:
        if not blob.name.endswith('.pb'):
            continue

        # Download as bytes
        content = blob.download_as_bytes()

        if 'tripupdates' in blob.name:
            records = parse_and_save_trip_updates(content)
            trip_count += records
        elif 'vehicleupdates' in blob.name or 'vehiclepositions' in blob.name:
            records = parse_and_save_vehicle_positions(content)
            vehicle_count += records

        processed_files += 1
        if processed_files % 100 == 0:
            print(f"Synced {processed_files} files...")

    print(f"\nSync Complete!")
    print(f"  Processed files: {processed_files}")
    print(
        f"  Added {trip_count} new trip update records (duplicates ignored).")
    print(
        f"  Added {vehicle_count} new vehicle position records (duplicates ignored).")


def sync_url(url):
    initialize_database()
    print(f"Downloading {url}...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        content = response.content
    except Exception as e:
        print(f"Error downloading URL: {e}")
        sys.exit(1)

    print(f"Downloaded {len(content)} bytes.")

    trip_count = 0
    vehicle_count = 0

    # Check feed contents to determine update type
    try:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(content)
        has_trip_update = any(entity.HasField('trip_update')
                              for entity in feed.entity)
        has_vehicle = any(entity.HasField('vehicle') for entity in feed.entity)

        if has_trip_update:
            records = parse_and_save_trip_updates(content)
            trip_count += records
            print(
                f"Added {trip_count} new trip update records (duplicates ignored).")
        if has_vehicle:
            records = parse_and_save_vehicle_positions(content)
            vehicle_count += records
            print(
                f"Added {vehicle_count} new vehicle position records (duplicates ignored).")

        if not has_trip_update and not has_vehicle:
            print("No trip updates or vehicle positions found in the feed.")

    except Exception as e:
        print(f"Error parsing feed from URL: {e}")
        sys.exit(1)


def parse_gcs_input(input_str):
    """
    Parses a GCS bucket name, gs:// URL, or storage.googleapis.com HTTPS URL.
    Returns (bucket_name, prefix, is_gcs).
    """
    if input_str.startswith("gs://"):
        path = input_str[5:]
        parts = path.split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else None
        if prefix == "":
            prefix = None
        return bucket, prefix, True

    for prefix_str in ["https://storage.googleapis.com/", "http://storage.googleapis.com/"]:
        if input_str.startswith(prefix_str):
            path = input_str[len(prefix_str):]
            parts = path.split("/", 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else None
            if prefix == "":
                prefix = None
            return bucket, prefix, True

    return None, None, False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync GCS GTFS-RT data to local SQLite database.")
    parser.add_argument(
        "bucket_name",
        nargs="?",
        default="https://storage.googleapis.com/gtfs-public/",
        help="Name of the GCS bucket or a direct HTTP/HTTPS URL (default: %(default)s)"
    )
    parser.add_argument(
        "--prefix", help="GCS prefix/folder path to filter files (optional)", default=None)
    parser.add_argument("--anonymous", "--anon", action="store_true",
                        help="Connect anonymously without GCP credentials")

    args = parser.parse_args()

    bucket_name = args.bucket_name
    prefix = args.prefix

    gcs_bucket, gcs_prefix, is_gcs = parse_gcs_input(bucket_name)
    if is_gcs:
        bucket_name = gcs_bucket
        if gcs_prefix:
            prefix = gcs_prefix if not prefix else os.path.join(gcs_prefix, prefix)
        sync_bucket(bucket_name, prefix=prefix, anonymous=args.anonymous)
    elif bucket_name.startswith("http://") or bucket_name.startswith("https://"):
        sync_url(bucket_name)
    else:
        sync_bucket(bucket_name, prefix=prefix, anonymous=args.anonymous)

