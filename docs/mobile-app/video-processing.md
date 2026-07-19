# Video processing

Upload from Finora admin `/mobile-app/videos` or admin API.

Pipeline (`services/video_processing.py` + Celery task when worker available):

1. Store original under tenant media path
2. Generate thumbnail / quality variants when ffmpeg available
3. Prefer HLS master when produced; else fall back to original URL
4. Mark `processing_status=ready` then allow publish

Feed only returns videos with `processing_status=ready` and `status in (published, ready)`.
