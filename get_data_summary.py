import os
import time
import glob
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys

# --- NEW IMPORTS FOR GOOGLE DRIVE ---
from googleapiclient.http import MediaFileUpload
from google_auth import build_auth_service  # Ensure your auth script is named google_auth.py

def get_data_summary():
    # --- CONFIGURATION ---
    load_dotenv()
    USERNAME = os.getenv("PORTAL_USER")
    PASSWORD = os.getenv("PORTAL_PASS")

    if not USERNAME or not PASSWORD:
        print("⚠️ Error: Credentials not found in .env file.")
        return

    DOWNLOAD_DIR = os.path.join(os.getcwd(), "csvs")
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    # --- BROWSER SETUP (HEADLESS) ---
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)

    print("🚀 Starting Headless Browser...")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 20)

    try:
        # --- STEP 1: LOGIN ---
        print("🔐 Logging in...")
        driver.get("https://post16-portal-service.gov.wales/login")
        wait.until(EC.visibility_of_element_located((By.ID, "f_username"))).send_keys(USERNAME)
        
        password_box = driver.find_element(By.ID, "f_passwd")
        password_box.send_keys(PASSWORD)
        password_box.send_keys(Keys.RETURN) 
        
        time.sleep(3) # Wait for authentication to clear

        # --- STEP 2: NAVIGATE TO REPORT ---
        print("📄 Loading report page...")
        driver.get("https://post16-portal-service.gov.wales/Inform/Reports/RenderInNewWindow.aspx?r=48")

        # --- STEP 3: SELECT PARAMETERS ---
        print("⚙️ Setting parameters...")
        provider_dd = wait.until(EC.presence_of_element_located((By.ID, "reportViewer_ctl08_ctl03_ddValue")))
        Select(provider_dd).select_by_visible_text("Bridgend College (F0009004)")
        time.sleep(2)

        Select(driver.find_element(By.ID, "reportViewer_ctl08_ctl05_ddValue")).select_by_visible_text("2025")
        time.sleep(2) 

        Select(driver.find_element(By.ID, "reportViewer_ctl08_ctl07_ddValue")).select_by_visible_text("All")

        # --- STEP 4: VIEW & EXPORT ---
        print("👀 Rendering report...")
        driver.find_element(By.ID, "reportViewer_ctl08_ctl00").click()
        time.sleep(5) # Allow SSRS to process

        # Snapshot existing CSV files before downloading
        existing_csvs = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.csv")))

        print("💾 Triggering CSV download...")
        try:
            driver.execute_script("$find('reportViewer').exportReport('CSV');")
        except Exception as js_err:
            print(f"⚠️ Export failed: {js_err}")
            return

        # --- STEP 5: WAIT & RENAME FILE ---
        print("🔄 Waiting for download and renaming...")
        new_filename = f"data_summary_{datetime.now().strftime('%y-%m-%d')}.csv"
        new_file_path = os.path.join(DOWNLOAD_DIR, new_filename)

        timeout = 0
        downloaded_file = None
        
        while timeout < 30:
            current_csvs = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.csv")))
            new_csvs = current_csvs - existing_csvs
            
            # Check for temporary Chrome download files
            active_downloads = glob.glob(os.path.join(DOWNLOAD_DIR, "*.crdownload"))
            
            # If a new CSV has appeared AND there are no active .crdownload files
            if new_csvs and not active_downloads:
                downloaded_file = list(new_csvs)[0]
                break
                
            time.sleep(1)
            timeout += 1

        if downloaded_file:
            if os.path.exists(new_file_path):
                os.remove(new_file_path)
                
            os.rename(downloaded_file, new_file_path)
            print(f"✅ Success! Saved locally as: {new_filename}")
            
            # --- STEP 6: UPLOAD TO GOOGLE DRIVE ---
            print("☁️ Uploading to Google Drive...")
            try:
                # Use your existing auth code to get the Drive service
                drive_service = build_auth_service('drive')
                
                folder_id = '1f5GmoNA4CqJ8csagO3-y5l6835TRPkr2'
                
                # Define file metadata (name and parent folder)
                file_metadata = {
                    'name': new_filename,
                    'parents': [folder_id]
                }
                
                # Point to the locally saved file
                media = MediaFileUpload(new_file_path, mimetype='text/csv', resumable=True)
                
                # Execute the upload
                uploaded_file = drive_service.files().create(
                    body=file_metadata, 
                    media_body=media, 
                    fields='id'
                ).execute()
                
                print(f"✅ Successfully uploaded to Drive! File ID: {uploaded_file.get('id')}")
                
                # OPTIONAL: Uncomment the next two lines if you want to delete the local CSV after successful upload
                # os.remove(new_file_path)
                # print("🗑️ Local file deleted to save space.")
                
            except Exception as drive_err:
                print(f"❌ Google Drive upload failed: {drive_err}")

        else:
            print("❌ Error: Download timed out or failed.")

    except Exception as e:
        print(f"❌ Execution error: {e}")

    finally:
        driver.quit()

if __name__ == '__main__':
    get_data_summary()