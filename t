You are working on a Flask SaaS project called Finora.

The project has an autoposter module that publishes content to Facebook pages.

There is a bug:

Video uploads are not working correctly.
The preview shows an image instead of a video and the system sends the file as an image.

Fix the entire media upload pipeline.

---------------------------------------------

GOALS

Fix media handling for:

1) image
2) video
3) reel
4) story

Ensure that videos are uploaded correctly and published using Facebook Graph API.

---------------------------------------------

FRONTEND FIX

Update the media preview logic.

Detect file type.

If image → show <img>
If video → show <video>

Example:

const file = mediaInput.files[0]

if (file.type.startsWith("video")) {

preview.innerHTML = `
<video controls style="max-width:100%">
<source src="${URL.createObjectURL(file)}">
</video>
`

} else {

preview.innerHTML = `
<img src="${URL.createObjectURL(file)}" style="max-width:100%">
`

}

---------------------------------------------

FORM FIX

Ensure the form uses multipart upload:

<form enctype="multipart/form-data">

---------------------------------------------

FLASK BACKEND FIX

Use request.files instead of request.form.

Example:

file = request.files.get("media")

if not file:
    return {"error":"media missing"},400

filename = secure_filename(file.filename)

upload_path = os.path.join("uploads", filename)

file.save(upload_path)

---------------------------------------------

MEDIA TYPE DETECTION

Detect media type:

if file.content_type.startswith("video"):
    media_type = "video"
else:
    media_type = "image"

Save media_type in database.

---------------------------------------------

FACEBOOK PUBLISHING FIX

Images must be published using:

POST /{page-id}/photos

Videos must be published using:

POST /{page-id}/videos

Example video upload:

url = f"https://graph.facebook.com/v21.0/{page_id}/videos"

files = {
"source": open(video_path, "rb")
}

data = {
"description": caption,
"access_token": page_token
}

requests.post(url, data=data, files=files)

---------------------------------------------

DATABASE

Ensure autoposter_posts table supports media:

Add columns if missing:

media_type
image_url
video_url

---------------------------------------------

UI UPDATE

Add media type selector:

<select name="media_type">
<option value="image">Image</option>
<option value="video">Video</option>
<option value="reel">Reel</option>
<option value="story">Story</option>
</select>

---------------------------------------------

VALIDATION

Limit file size to 100MB.

Allowed formats:

Images:
jpg
png
webp

Videos:
mp4
mov

---------------------------------------------

OUTPUT

Modify:

routes/autoposter.py
templates/autoposter/create_post.html
services/facebook_service.py

Ensure videos upload correctly and publish to Facebook pages.