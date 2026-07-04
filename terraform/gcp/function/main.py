import os
import time
import requests
from google.cloud import storage

storage_client = storage.Client()
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'kamloops-gtfs-rt-data')

FEEDS = {
    'tripupdates': 'https://bct.tmix.se/gtfs-realtime/tripupdates.pb?operatorIds=46',
    'vehicleupdates': 'https://bct.tmix.se/gtfs-realtime/vehicleupdates.pb?operatorIds=46'
}

def collect_feed(request):
    bucket = storage_client.bucket(BUCKET_NAME)
    timestamp = int(time.time())
    date_path = time.strftime('year=%Y/month=%m/day=%d')
    
    for feed_type, url in FEEDS.items():
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                blob_name = f"{feed_type}/{date_path}/{feed_type}_{timestamp}.pb"
                blob = bucket.blob(blob_name)
                blob.upload_from_string(response.content, content_type='application/x-protobuf')
                print(f"Uploaded {feed_type} to GCS: {blob_name}")
            else:
                print(f"Failed to fetch {feed_type}: Status {response.status_code}")
        except Exception as e:
            print(f"Error collecting {feed_type}: {e}")
            
    return "OK", 200
