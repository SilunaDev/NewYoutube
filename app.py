import os
import time
from flask import Flask, render_template, request, send_from_directory, url_for
import yt_dlp
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Folder where videos will be saved temporarily
DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Define a custom user agent to mimic a real browser
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'

# Optional: If you want to use cookies, specify the path to your cookies file
# COOKIES_FILE = '/path/to/cookies.txt'

# Function to get available formats
def get_formats(url):
    ydl_opts = {
        'quiet': True,               # Prevent output in console
        'extract_flat': True,        # Don't download video, just get format info
        'user_agent': USER_AGENT,
        # 'cookies': COOKIES_FILE,    # Uncomment if you have a cookies file
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
            if 'formats' not in result:  # Handle invalid URL or bot protection issue
                return None
            return result.get('formats', [])
    except Exception as e:
        print("Error in get_formats:", e)
        return None  # In case of network error or invalid URL

# Function to download video
def download_video(url, format_code):
    ydl_opts = {
        'format': format_code,
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),  # Path to save video
        'user_agent': USER_AGENT,
        # 'cookies': COOKIES_FILE,    # Uncomment if you have a cookies file
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

# Function to create a lock file for a video
def create_lock_file(video_name):
    lock_file_path = os.path.join(DOWNLOAD_FOLDER, f"{video_name}.lock")
    open(lock_file_path, 'w').close()  # Create an empty lock file

# Function to delete a lock file for a video
def delete_lock_file(video_name):
    lock_file_path = os.path.join(DOWNLOAD_FOLDER, f"{video_name}.lock")
    if os.path.exists(lock_file_path):
        os.remove(lock_file_path)

# Function to clean up old videos in the downloads folder
def cleanup_downloads_folder():
    print("Cleaning up downloads folder...")
    for filename in os.listdir(DOWNLOAD_FOLDER):
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        # Skip locked files (those that are currently being downloaded)
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
    error_message = None  # Default is no error

    try:
        # Get available formats for the video
        formats = get_formats(video_url)

        if not formats:  # If no formats are returned, it's likely an invalid URL or a bot protection issue
            error_message = "Invalid URL or the video is unavailable."
            return render_template('index.html', error_message=error_message)

        # Match formats based on requested quality
        selected_format = None
        for fmt in formats:
            if 'p' in quality:
                # If the user specifies a resolution (e.g., "360p", "480p")
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
        result = download_video(video_url, selected_format)
        # Get the downloaded filename
        video_name = f"{result['title']}.{result['ext']}"
        video_path = os.path.join(DOWNLOAD_FOLDER, secure_filename(video_name))

        # Create a lock file to prevent cleanup during download
        create_lock_file(video_name)

        # Generate a URL for the downloaded video
        download_link = url_for('download_file', filename=video_name)

        # Return the download page with the download link
        return render_template('download_complete.html', video_name=video_name, video_url=download_link)
    except Exception as e:
        error_message = f"An error occurred: {str(e)}"
        return render_template('index.html', error_message=error_message)

@app.route('/downloads/<filename>')
def download_file(filename):
    video_path = os.path.join(DOWNLOAD_FOLDER, filename)
    # Serve the file to the user
    response = send_from_directory(DOWNLOAD_FOLDER, filename)
    
    # Ensure the video is deleted after it's been downloaded
    response.call_on_close(lambda: delete_after_serving(video_path))
    
    # Delete the lock file once the download is complete
    delete_lock_file(filename)

    return response

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
