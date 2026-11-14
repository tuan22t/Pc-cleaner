package com.tananpalace.pccleaner

import android.Manifest
import android.app.Activity
import android.content.ContentUris
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.StatFs
import android.provider.MediaStore
import android.provider.Settings
import android.util.Size
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.util.concurrent.Executors

/**
 * The bridge between the Flutter UI and Android's MediaStore.
 *
 * Safety: this code never deletes anything. Removal goes through
 * MediaStore.createTrashRequest, which shows Android's own confirmation and
 * keeps the items in the system trash for 30 days, where they can be
 * restored (by this app or by the gallery / Files app).
 */
class MainActivity : FlutterActivity() {
    private val channelName = "pccleaner/media"
    private val reqPermission = 4101
    private val reqTrash = 4102
    private val worker = Executors.newFixedThreadPool(3)
    private val main = Handler(Looper.getMainLooper())
    private var pendingPermission: MethodChannel.Result? = null
    private var pendingTrash: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result -> handle(call, result) }
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "permissionState" -> result.success(permissionState())
            "requestPermission" -> requestPermission(result)
            "openSettings" -> {
                startActivity(
                    Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
                )
                result.success(null)
            }
            "storage" -> {
                val st = StatFs(Environment.getDataDirectory().path)
                result.success(mapOf("total" to st.totalBytes, "free" to st.availableBytes))
            }
            "listAll" -> background(result) { listAll() }
            "thumbnail" -> background(result) {
                thumbnailJpeg(uriOf(call), call.argument<Int>("side") ?: 256)
            }
            "grey" -> background(result) { greyThumb(uriOf(call), call.argument<Int>("side") ?: 256) }
            "contentHash" -> background(result) { md5(uriOf(call)) }
            "trash" -> setTrashed(call, true, result)
            "restore" -> setTrashed(call, false, result)
            "stillTrashed" -> background(result) { stillTrashed(call) }
            "open" -> {
                val uri = uriOf(call)
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, contentResolver.getType(uri))
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                try {
                    startActivity(intent)
                    result.success(true)
                } catch (e: Exception) {
                    result.success(false)
                }
            }
            else -> result.notImplemented()
        }
    }

    private fun background(result: MethodChannel.Result, work: () -> Any?) {
        worker.execute {
            try {
                val v = work()
                main.post { result.success(v) }
            } catch (e: Exception) {
                main.post { result.error("failed", e.message, null) }
            }
        }
    }

    // ---------- permissions ----------

    private fun mediaPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 34) arrayOf(
            Manifest.permission.READ_MEDIA_IMAGES,
            Manifest.permission.READ_MEDIA_VIDEO,
            Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED,
        ) else if (Build.VERSION.SDK_INT >= 33) arrayOf(
            Manifest.permission.READ_MEDIA_IMAGES,
            Manifest.permission.READ_MEDIA_VIDEO,
        ) else arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)

    private fun granted(p: String) = checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    /** "granted" (everything), "limited" (Android 14 "select photos"), or "denied". */
    private fun permissionState(): String {
        if (Build.VERSION.SDK_INT >= 33) {
            if (granted(Manifest.permission.READ_MEDIA_IMAGES) && granted(Manifest.permission.READ_MEDIA_VIDEO)) return "granted"
            if (Build.VERSION.SDK_INT >= 34 && granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)) return "limited"
            return "denied"
        }
        return if (granted(Manifest.permission.READ_EXTERNAL_STORAGE)) "granted" else "denied"
    }

    private fun requestPermission(result: MethodChannel.Result) {
        if (permissionState() == "granted") {
            result.success("granted")
            return
        }
        pendingPermission?.success(permissionState())
        pendingPermission = result
        requestPermissions(mediaPermissions(), reqPermission)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == reqPermission) {
            pendingPermission?.success(permissionState())
            pendingPermission = null
        }
    }

    // ---------- listing ----------

    private fun collection(kind: String): Uri =
        if (kind == "video") MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)
        else MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL)

    private fun uriOf(call: MethodCall): Uri {
        val id = call.argument<String>("id")!!.toLong()
        return ContentUris.withAppendedId(collection(call.argument<String>("kind") ?: "image"), id)
    }

    private fun listAll(): List<Map<String, Any?>> {
        val out = ArrayList<Map<String, Any?>>()
        for (kind in listOf("image", "video")) {
            val cols = mutableListOf(
                MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.SIZE,
                MediaStore.MediaColumns.WIDTH,
                MediaStore.MediaColumns.HEIGHT,
                MediaStore.MediaColumns.DATE_TAKEN,
                MediaStore.MediaColumns.DATE_ADDED,
                MediaStore.MediaColumns.DATE_MODIFIED,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.RELATIVE_PATH,
                MediaStore.MediaColumns.BUCKET_DISPLAY_NAME,
                MediaStore.MediaColumns.IS_FAVORITE,
                MediaStore.MediaColumns.DURATION,
            )
            contentResolver.query(collection(kind), cols.toTypedArray(), null, null, null)?.use { c ->
                val iId = c.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
                val iSize = c.getColumnIndexOrThrow(MediaStore.MediaColumns.SIZE)
                val iW = c.getColumnIndexOrThrow(MediaStore.MediaColumns.WIDTH)
                val iH = c.getColumnIndexOrThrow(MediaStore.MediaColumns.HEIGHT)
                val iTaken = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_TAKEN)
                val iAdded = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_ADDED)
                val iMod = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED)
                val iName = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                val iRel = c.getColumnIndexOrThrow(MediaStore.MediaColumns.RELATIVE_PATH)
                val iBucket = c.getColumnIndexOrThrow(MediaStore.MediaColumns.BUCKET_DISPLAY_NAME)
                val iFav = c.getColumnIndexOrThrow(MediaStore.MediaColumns.IS_FAVORITE)
                val iDur = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DURATION)
                while (c.moveToNext()) {
                    val added = c.getLong(iAdded) * 1000
                    val taken = if (c.isNull(iTaken)) 0L else c.getLong(iTaken)
                    out.add(
                        mapOf(
                            "id" to c.getLong(iId).toString(),
                            "kind" to kind,
                            "size" to c.getLong(iSize),
                            "width" to c.getInt(iW),
                            "height" to c.getInt(iH),
                            "created" to (if (taken > 0) taken else added),
                            "modified" to c.getLong(iMod) * 1000,
                            "title" to (c.getString(iName) ?: ""),
                            "path" to (c.getString(iRel) ?: ""),
                            "bucket" to (c.getString(iBucket) ?: ""),
                            "favorite" to (c.getInt(iFav) == 1),
                            "duration" to (if (c.isNull(iDur)) 0L else c.getLong(iDur)),
                        )
                    )
                }
            }
        }
        return out
    }

    // ---------- thumbnails and analysis input ----------

    private fun loadFitted(uri: Uri, side: Int): Bitmap {
        val bmp = contentResolver.loadThumbnail(uri, Size(side, side), null)
        val scale = side.toFloat() / maxOf(bmp.width, bmp.height)
        if (scale >= 1f) return bmp
        val w = maxOf(1, (bmp.width * scale).toInt())
        val h = maxOf(1, (bmp.height * scale).toInt())
        val scaled = Bitmap.createScaledBitmap(bmp, w, h, true)
        if (scaled != bmp) bmp.recycle()
        return scaled
    }

    private fun thumbnailJpeg(uri: Uri, side: Int): ByteArray {
        val bmp = loadFitted(uri, side)
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, out)
        bmp.recycle()
        return out.toByteArray()
    }

    /** Grey pixels of a thumbnail whose longest side is exactly `side`,
     *  so sharpness values are comparable between photos. */
    private fun greyThumb(uri: Uri, side: Int): Map<String, Any> {
        var bmp = loadFitted(uri, side)
        val longest = maxOf(bmp.width, bmp.height)
        if (longest < side) {
            val s = side.toFloat() / longest
            val up = Bitmap.createScaledBitmap(bmp, maxOf(1, (bmp.width * s).toInt()), maxOf(1, (bmp.height * s).toInt()), true)
            if (up != bmp) bmp.recycle()
            bmp = up
        }
        val w = bmp.width
        val h = bmp.height
        val px = IntArray(w * h)
        bmp.getPixels(px, 0, w, 0, 0, w, h)
        bmp.recycle()
        val grey = ByteArray(w * h)
        for (i in px.indices) {
            val p = px[i]
            grey[i] = ((Color.red(p) * 299 + Color.green(p) * 587 + Color.blue(p) * 114) / 1000).toByte()
        }
        return mapOf("w" to w, "h" to h, "px" to grey)
    }

    private fun md5(uri: Uri): String? {
        val md = MessageDigest.getInstance("MD5")
        contentResolver.openInputStream(uri)?.use { s ->
            val buf = ByteArray(1 shl 16)
            while (true) {
                val n = s.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        } ?: return null
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    // ---------- trash ----------

    @Suppress("UNCHECKED_CAST")
    private fun urisOf(call: MethodCall): List<Uri> {
        val items = call.argument<List<Map<String, String>>>("items") ?: emptyList()
        return items.map {
            ContentUris.withAppendedId(collection(it["kind"] ?: "image"), it["id"]!!.toLong())
        }
    }

    private fun setTrashed(call: MethodCall, trashed: Boolean, result: MethodChannel.Result) {
        val uris = urisOf(call)
        if (uris.isEmpty()) {
            result.success(true)
            return
        }
        if (pendingTrash != null) {
            result.error("busy", "another request is open", null)
            return
        }
        try {
            val pi = MediaStore.createTrashRequest(contentResolver, uris, trashed)
            pendingTrash = result
            startIntentSenderForResult(pi.intentSender, reqTrash, null, 0, 0, 0)
        } catch (e: Exception) {
            pendingTrash = null
            result.error("failed", e.message, null)
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == reqTrash) {
            pendingTrash?.success(resultCode == Activity.RESULT_OK)
            pendingTrash = null
        }
    }

    private fun stillTrashed(call: MethodCall): List<Map<String, Any?>> {
        val items = call.argument<List<Map<String, String>>>("items") ?: emptyList()
        val out = ArrayList<Map<String, Any?>>()
        for ((kind, group) in items.groupBy { it["kind"] ?: "image" }) {
            for (chunk in group.chunked(400)) {
                val ids = chunk.map { it["id"]!! }
                val args = Bundle().apply {
                    putInt(MediaStore.QUERY_ARG_MATCH_TRASHED, MediaStore.MATCH_ONLY)
                    putString(
                        android.content.ContentResolver.QUERY_ARG_SQL_SELECTION,
                        "${MediaStore.MediaColumns._ID} IN (${ids.joinToString(",") { "?" }})"
                    )
                    putStringArray(android.content.ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, ids.toTypedArray())
                }
                val cols = arrayOf(MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DATE_EXPIRES)
                contentResolver.query(collection(kind), cols, args, null)?.use { c ->
                    while (c.moveToNext()) {
                        out.add(
                            mapOf(
                                "id" to c.getLong(0).toString(),
                                "kind" to kind,
                                "expires" to (if (c.isNull(1)) null else c.getLong(1) * 1000),
                            )
                        )
                    }
                }
            }
        }
        return out
    }
}
