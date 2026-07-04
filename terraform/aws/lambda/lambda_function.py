import os
import time
import urllib.request
import boto3

s3_client = boto3.client('s3')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'kamloops-gtfs-rt-data')

FEEDS = {
    'tripupdates': 'https://bct.tmix.se/gtfs-realtime/tripupdates.pb?operatorIds=46',
    'vehicleupdates': 'https://bct.tmix.se/gtfs-realtime/vehicleupdates.pb?operatorIds=46'
}

def lambda_handler(event, context):
    timestamp = int(time.time())
    date_path = time.strftime('year=%Y/month=%m/day=%d')
    
    for feed_type, url in FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read()
                
            # Define file path
            file_key = f"{feed_type}/{date_path}/{feed_type}_{timestamp}.pb"
            
            # Upload to S3
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=file_key,
                Body=data,
                ContentType='application/x-protobuf'
            )
            print(f"Successfully uploaded {feed_type} to S3 Key: {file_key}")
        except Exception as e:
            print(f"Error fetching/uploading {feed_type}: {e}")
            
    return {"statusCode": 200}
