from __future__ import print_function

import os.path
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/documents','https://www.googleapis.com/auth/drive','https://www.googleapis.com/auth/admin.directory.user.readonly']

def build_auth_service(auth_type):
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        match auth_type:
            case 'sheets':
                return build('sheets', 'v4', credentials=creds) 
            case 'docs':
                return build('docs', 'v1', credentials=creds)
            case 'drive':
                return build('drive','v3',credentials=creds)
            case 'admin':
                return build('admin','directory_v1',credentials=creds)
    except HttpError as err:
        print(err)

def exponential_backoff(api_function, *args, **kwargs):
  max_retries = 10  # You can adjust this value as needed
  retry_delay = 1  # Initial retry delay in seconds

  for retry in range(max_retries):
    try:
      result = api_function(*args, **kwargs)
      return result
    except HttpError as error:
      if error.resp.status == 429:  # HTTP status code for rate limit exceeded
        print(f"Rate limit exceeded. Retrying in {retry_delay} seconds...")
        time.sleep(retry_delay)
        retry_delay *= 2  # Exponential backoff
      else:
        raise  # Raise other HTTP errors

if __name__ == '__main__':
  build_auth_service('sheets')