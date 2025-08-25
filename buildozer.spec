[app]
title = YunoMessage
package.name = yuno
package.domain = com.yuno.app
source.dir = client
source.include_exts = py,kv,png,jpg,jpeg,txt,ttf,mp4,mov,mkv,webm
version = 0.1
requirements = python3,kivy,httpx,websockets,pillow
orientation = portrait
fullscreen = 0

[buildozer]
log_level = 2
warn_on_root = 0

[android]
android.api = 33
android.minapi = 21
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
# Optional for file pickers on newer Androids:
# android.permissions = READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,INTERNET
