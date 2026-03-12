You are a senior backend engineer.

I have a Flask web application that contains an autoposter system.
Text posts publish correctly, but when I upload a video (~68MB) the API returns:

POST /autoposter/api/posts
500 Internal Server Error

The nginx upload limit is already 100MB and the video size is 68MB.

Goal:
Fix the upload system so the API correctly supports video uploads.

Tasks:

1. Inspect the endpoint:
   /autoposter/api/posts

2. Ensure the API supports multipart uploads instead of JSON.

3. The endpoint must correctly handle:
   - text content
   - optional video file
   - scheduled date (optional)

4. Use:

request.form
request.files

instead of request.json when a file is uploaded.

5. Save the uploaded video to:

/uploads/videos/

Create the folder automatically if it does not exist.

6. Add safe error handling so the API never crashes with 500.
Return proper JSON errors.

7. Ensure the backend allows uploads up to 200MB.

Add:

app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

8. Update the frontend JS so posts are sent using FormData instead of JSON.

Correct implementation example:

const formData = new FormData()
formData.append("content", content)

if(videoFile){
   formData.append("video", videoFile)
}

fetch("/autoposter/api/posts",{
   method:"POST",
   body:formData
})

Do NOT set Content-Type manually.

9. Ensure compatibility with:
Flask + Gunicorn + Nginx production setup.

10. Add logging so upload errors are visible in server logs.

Output:
Return the corrected Flask route and the corrected JavaScript upload code.