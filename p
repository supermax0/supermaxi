Create a **professional video upload system** for a Flask-based web application (Autoposter module).
The system must support large video uploads, be optimized for Nginx serving, and provide a modern UI.

## Backend Requirements (Python Flask)

Build a Flask module with the following capabilities:

1. **Upload API**
   Endpoint:
   POST `/autoposter/api/upload`

Features:

* Accept video uploads using `multipart/form-data`.
* Supported formats: mp4, mov, webm.
* Maximum upload size: 2GB.
* Validate file type and size.
* Generate a unique filename using UUID.
* Save videos to:

```
/var/www/finora/uploads/videos/
```

Example response JSON:

```json
{
  "ok": true,
  "type": "video",
  "url": "/uploads/videos/<filename>.mp4",
  "size_mb": 4.51,
  "thumbnail_url": "/uploads/thumbnails/<filename>.jpg"
}
```

2. **Video Processing**

After upload:

* Convert `.mov` → `.mp4` automatically using FFmpeg.
* Generate a thumbnail image at 3 seconds.
* Extract metadata:

  * duration
  * width
  * height

Example command:

```
ffmpeg -i input.mov -ss 00:00:03 -vframes 1 thumbnail.jpg
```

3. **Security**

Implement:

* file extension validation
* MIME validation
* size limits
* path sanitization
* rate limiting

4. **Error Handling**

Return structured errors:

```json
{
  "ok": false,
  "error_code": "INVALID_FORMAT",
  "message": "Only MP4, MOV, WEBM are supported."
}
```

---

## Frontend Requirements (HTML + CSS + JS)

Create a **modern drag-and-drop uploader UI**.

Features:

* Drag and drop upload area
* Video preview
* Upload progress bar
* Cancel upload
* Error messages
* Mobile responsive design

Example UI structure:

```
Upload Area
Progress Bar
Preview Player
Upload Button
```

---

## JavaScript Upload Logic

Implement:

* Fetch API upload
* Real-time progress
* Drag & drop events
* File validation before upload

Example:

```javascript
const formData = new FormData();
formData.append("video", file);

fetch("/autoposter/api/upload", {
    method: "POST",
    body: formData
});
```

---

## Nginx Integration

Configure Nginx to serve uploaded videos directly:

```
location /uploads/ {
    alias /var/www/finora/uploads/;
}
```

Benefits:

* reduces Flask load
* faster video streaming
* supports Facebook crawler

---

## Video Player

Include a video preview component:

```html
<video controls width="100%">
  <source src="/uploads/videos/sample.mp4" type="video/mp4">
</video>
```

---

## Advanced Features

Implement:

* chunk upload for files >500MB
* resume upload
* upload queue
* parallel uploads
* automatic retry on failure
* thumbnail preview

---

## Folder Structure

```
autoposter/
 ├─ api/
 │   └─ upload.py
 ├─ services/
 │   └─ video_processor.py
 ├─ static/
 │   └─ uploader.js
 ├─ templates/
 │   └─ upload.html
```

---

## Performance Goals

* Upload up to **2GB videos**
* Minimal Flask CPU usage
* Nginx serves videos directly
* Compatible with **Facebook autoposting**

---

## Output

Provide:

* Flask API code
* HTML uploader page
* CSS styling
* JavaScript uploader
* FFmpeg integration
* Nginx configuration
* Folder structure
* example requests and responses
