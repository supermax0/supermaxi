package iq.finora.finora_phone.call

import android.content.Context
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import java.io.File

/**
 * Locates the native dialer's call recording (Xiaomi MIUI/HyperOS first,
 * generic vendor folders as fallback) and copies it into the app cache so
 * Flutter can upload it.
 */
object CallRecordingFinder {

    private val FOLDER_HINTS = listOf(
        "sound_recorder/call_rec", // MIUI classic
        "call_rec",
        "call recordings",         // HyperOS / Samsung
        "recordings/call",
        "callrecord",
        "record/call",
        "phonerecord",
    )

    private val NAME_HINTS = listOf(
        "call recording",
        "callrecording",
        "call_",
        "通话录音",
    )

    /**
     * Finds the best matching recording for a call window.
     * Returns metadata + a cache-local copy path, or null.
     */
    fun find(
        context: Context,
        phone: String,
        startedAtMs: Long,
        endedAtMs: Long,
    ): Map<String, Any?>? {
        val digits = phone.filter { it.isDigit() }
        val matchDigits = if (digits.length > 8) digits.takeLast(8) else digits
        val fromSec = (startedAtMs / 1000) - 180
        val toSec = (endedAtMs / 1000) + 600

        val candidates = mutableListOf<Candidate>()
        for (uri in queryUris()) {
            collect(context, uri, fromSec, toSec, matchDigits, candidates)
        }
        val best = candidates.maxByOrNull { it.score * 1_000_000_000L + it.dateAddedSec }
            ?: return null

        val cached = copyToCache(context, best) ?: return null
        return mapOf(
            "path" to cached.absolutePath,
            "name" to best.name,
            "size" to cached.length(),
            "durationMs" to best.durationMs,
            "dateAddedSec" to best.dateAddedSec,
            "mime" to best.mime,
        )
    }

    private data class Candidate(
        val id: Long,
        val contentUri: Uri,
        val name: String,
        val fullPath: String,
        val size: Long,
        val durationMs: Long?,
        val dateAddedSec: Long,
        val mime: String?,
        val score: Int,
    )

    private fun queryUris(): List<Uri> = listOf(
        MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
        MediaStore.Files.getContentUri("external"),
    )

    private fun collect(
        context: Context,
        baseUri: Uri,
        fromSec: Long,
        toSec: Long,
        matchDigits: String,
        out: MutableList<Candidate>,
    ) {
        val projection = mutableListOf(
            MediaStore.MediaColumns._ID,
            MediaStore.MediaColumns.DISPLAY_NAME,
            MediaStore.MediaColumns.SIZE,
            MediaStore.MediaColumns.DATE_ADDED,
            MediaStore.MediaColumns.MIME_TYPE,
            MediaStore.MediaColumns.DATA,
        )
        if (Build.VERSION.SDK_INT >= 29) {
            projection.add(MediaStore.MediaColumns.RELATIVE_PATH)
        }
        try {
            projection.add(MediaStore.Audio.Media.DURATION)
        } catch (_: Exception) {
        }

        val selection = "${MediaStore.MediaColumns.DATE_ADDED} BETWEEN ? AND ?"
        val args = arrayOf(fromSec.toString(), toSec.toString())
        try {
            context.contentResolver.query(
                baseUri,
                projection.toTypedArray(),
                selection,
                args,
                "${MediaStore.MediaColumns.DATE_ADDED} DESC",
            )?.use { cursor ->
                val idIdx = cursor.getColumnIndex(MediaStore.MediaColumns._ID)
                val nameIdx = cursor.getColumnIndex(MediaStore.MediaColumns.DISPLAY_NAME)
                val sizeIdx = cursor.getColumnIndex(MediaStore.MediaColumns.SIZE)
                val dateIdx = cursor.getColumnIndex(MediaStore.MediaColumns.DATE_ADDED)
                val mimeIdx = cursor.getColumnIndex(MediaStore.MediaColumns.MIME_TYPE)
                val dataIdx = cursor.getColumnIndex(MediaStore.MediaColumns.DATA)
                val relIdx = if (Build.VERSION.SDK_INT >= 29)
                    cursor.getColumnIndex(MediaStore.MediaColumns.RELATIVE_PATH) else -1
                val durIdx = cursor.getColumnIndex(MediaStore.Audio.Media.DURATION)

                var scanned = 0
                while (cursor.moveToNext() && scanned < 300) {
                    scanned++
                    val id = if (idIdx >= 0) cursor.getLong(idIdx) else continue
                    val name = (if (nameIdx >= 0) cursor.getString(nameIdx) else null) ?: continue
                    val data = if (dataIdx >= 0) cursor.getString(dataIdx) ?: "" else ""
                    val rel = if (relIdx >= 0) cursor.getString(relIdx) ?: "" else ""
                    val haystack = "${rel.lowercase()} ${data.lowercase()}"
                    val nameLower = name.lowercase()

                    val inRecordingFolder = FOLDER_HINTS.any { haystack.contains(it) }
                    val nameLooksLikeRecording = NAME_HINTS.any { nameLower.contains(it) }
                    val nameHasNumber =
                        matchDigits.isNotEmpty() &&
                            name.filter { it.isDigit() }.contains(matchDigits)
                    if (!inRecordingFolder && !nameLooksLikeRecording && !nameHasNumber) continue

                    val mime = if (mimeIdx >= 0) cursor.getString(mimeIdx) else null
                    if (mime != null && !mime.startsWith("audio")) continue

                    var score = 0
                    if (inRecordingFolder) score += 2
                    if (nameLooksLikeRecording) score += 1
                    if (nameHasNumber) score += 4

                    out.add(
                        Candidate(
                            id = id,
                            contentUri = Uri.withAppendedPath(baseUri, id.toString()),
                            name = name,
                            fullPath = data,
                            size = if (sizeIdx >= 0) cursor.getLong(sizeIdx) else 0L,
                            durationMs = if (durIdx >= 0) cursor.getLong(durIdx) else null,
                            dateAddedSec = if (dateIdx >= 0) cursor.getLong(dateIdx) else 0L,
                            mime = mime,
                            score = score,
                        )
                    )
                }
            }
        } catch (_: Exception) {
        }
    }

    private fun copyToCache(context: Context, candidate: Candidate): File? {
        val ext = candidate.name.substringAfterLast('.', "m4a").lowercase()
        val dir = File(context.cacheDir, "call_recordings").apply { mkdirs() }
        val dest = File(dir, "rec_${candidate.id}.$ext")
        if (dest.exists() && dest.length() > 0) return dest
        return try {
            context.contentResolver.openInputStream(candidate.contentUri)?.use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            } ?: return null
            if (dest.length() > 0) dest else null
        } catch (e: Exception) {
            // Direct path fallback for legacy storage.
            try {
                val src = File(candidate.fullPath)
                if (src.exists() && src.canRead()) {
                    src.copyTo(dest, overwrite = true)
                    dest
                } else null
            } catch (_: Exception) {
                null
            }
        }
    }
}
