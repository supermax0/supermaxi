You are a senior Python Flask backend engineer.

I have a production web application using:

* Flask
* Gunicorn
* Nginx
* JavaScript frontend

Project path:

/var/www/finora/supermaxi

The system contains a media uploader used by the AutoPoster module.

Currently:

Images upload correctly.
Videos fail to upload when the file format is .MOV.

Example failing file:

IMG_0330.MOV

This file comes from iPhone cameras and uses MIME type:

video/quicktime

---

GOAL

Fix the media uploader so it supports both MP4 and MOV video files.

---

REQUIRED CHANGES

1. Backend (Flask)

Update the allowed upload MIME types to support:

video/mp4
video/quicktime
video/webm

Example:

ALLOWED_TYPES = (
"image/jpeg",
"image/png",
"image/gif",
"image/webp",
"video/mp4",
"video/quicktime",
"video/webm"
)

Ensure the upload route correctly validates MIME type using:

file.mimetype

---

2. Frontend (HTML)

Update the file input to allow MOV videos.

Change:

<input type="file" accept="video/mp4">

to:

<input type="file" accept="video/*">

---

3. UI Text

Update uploader instructions from:

فيديو: mp4

to:

فيديو: mp4 / mov

---

4. Optional improvement

Automatically convert MOV videos to MP4 after upload using ffmpeg:

ffmpeg -i input.mov -vcodec libx264 -acodec aac output.mp4

---

5. Upload directory

Ensure uploaded videos are saved in:

/var/www/finora/uploads/videos

Create the directory automatically if missing.

---

6. Logging

Add error logging in the upload route:

current_app.logger.exception()

---

OUTPUT REQUIRED

Provide:

1. Updated Flask upload route
2. Updated MIME validation
3. Updated HTML uploader input
4. Updated UI text
5. Optional ffmpeg conversion logic

The final result must allow uploading:

* MP4 videos
* MOV videos from iPhone
* Images

without breaking the existing uploader system.
Version: 1.0.0
