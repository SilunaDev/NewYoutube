import os
from flask import Flask, render_template, request, send_from_directory, url_for
import yt_dlp
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Set the base directory and define paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Custom user agent to mimic a real browser
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'

# Function to get available formats
def get_formats(url, cookies_file_path):
    ydl_opts = {
        'quiet': True,               # Prevent output in console
        'extract_flat': True,        # Only get info, don't download
        'user_agent': USER_AGENT,
        'cookies': cookies_file_path,  # Use uploaded cookies
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
            if 'formats' not in result:
                return None
            return result.get('formats', [])
    except Exception as e:
        print("Error in get_formats:", e)
        return None

# Function to download video
def download_video(url, format_code, cookies_file_path):
    ydl_opts = {
        'format': format_code,
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'user_agent': USER_AGENT,
        'cookies': cookies_file_path,  # Use uploaded cookies
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=True)
        return result

# Function to delete video after being served
def delete_after_serving(video_path):
    try:
        os.remove(video_path)
    except Exception as e:
        print(f"Error while deleting the file: {e}")

# Create a lock file for a video
def create_lock_file(video_name):
    lock_file_path = os.path.join(DOWNLOAD_FOLDER, f"{video_name}.lock")
    open(lock_file_path, 'w').close()

# Delete a lock file for a video
def delete_lock_file(video_name):
    lock_file_path = os.path.join(DOWNLOAD_FOLDER, f"{video_name}.lock")
    if os.path.exists(lock_file_path):
        os.remove(lock_file_path)

# Clean up old videos in the downloads folder
def cleanup_downloads_folder():
    print("Cleaning up downloads folder...")
    for filename in os.listdir(DOWNLOAD_FOLDER):
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        # Skip locked files (those being processed)
        if filename.endswith(".lock"):
            continue
        if os.path.isfile(file_path):
            os.remove(file_path)

# Set up the APScheduler to run cleanup every 5 minutes
scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_downloads_folder, trigger="interval", minutes=5)
scheduler.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    video_url = request.form.get('url')
    quality = request.form.get('quality', 'best')
    error_message = None

    # Get the uploaded cookies file
    cookies_file = request.files.get('cookies')
    cookies_file_path = os.path.join(BASE_DIR, 'cookies_uploaded.txt')
    if cookies_file:
        cookies_file.save(cookies_file_path)
    else:
        error_message = "Please upload a cookies.txt file."
        return render_template('index.html', error_message=error_message)

    try:
        # Get available formats for the video
        formats = get_formats(video_url, cookies_file_path)  # Pass the uploaded cookies file
        if not formats:
            error_message = "Invalid URL or the video is unavailable."
            return render_template('index.html', error_message=error_message)

        # Select format based on requested quality
        selected_format = None
        for fmt in formats:
            if 'p' in quality:
                if f'{quality}' in fmt.get('format_note', ''):
                    selected_format = fmt['format_id']
                    break
            elif quality == 'best' and fmt.get('format_id') == 'best':
                selected_format = fmt['format_id']
                break
            elif quality == 'worst' and fmt.get('format_id') == 'worst':
                selected_format = fmt['format_id']
                break

        # Default to 'best' if no matching format is found
        if not selected_format:
            selected_format = 'best'

        # Download the video using the selected format
        result = download_video(video_url, selected_format, cookies_file_path)  # Pass the cookies file
        video_name = f"{result['title']}.{result['ext']}"
        video_path = os.path.join(DOWNLOAD_FOLDER, secure_filename(video_name))

        # Create a lock file to prevent cleanup during download
        create_lock_file(video_name)

        # Generate a URL for the downloaded video
        download_link = url_for('download_file', filename=video_name)
        return render_template('download_complete.html', video_name=video_name, video_url=download_link)
    except Exception as e:
        error_message = f"An error occurred: {str(e)}"
        return render_template('index.html', error_message=error_message)
    finally:
        # Clean up the uploaded cookies file after use
        if os.path.exists(cookies_file_path):
            os.remove(cookies_file_path)

@app.route('/downloads/<filename>')
def download_file(filename):
    video_path = os.path.join(DOWNLOAD_FOLDER, filename)
    response = send_from_directory(DOWNLOAD_FOLDER, filename)
    response.call_on_close(lambda: delete_after_serving(video_path))
    delete_lock_file(filename)
    return response
