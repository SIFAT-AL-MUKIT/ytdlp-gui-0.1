import os
import sys
import shutil
import threading
import stat
from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivy.core.clipboard import Clipboard
from kivy.utils import platform
from kivy.clock import Clock
import yt_dlp

# --- KV ডিজাইন (UI) ---
KV = '''
MDScreen:
    md_bg_color: 0.95, 0.95, 0.95, 1

    MDBoxLayout:
        orientation: 'vertical'
        spacing: dp(20)
        padding: dp(20)
        pos_hint: {'center_x': 0.5, 'center_y': 0.6}

        MDLabel:
            text: "Easy Downloader"
            font_style: "H4"
            halign: "center"
            theme_text_color: "Primary"
            bold: True

        MDCard:
            size_hint: 0.9, None
            height: dp(100)
            radius: [15, 15, 15, 15]
            elevation: 2
            pos_hint: {'center_x': 0.5}
            padding: dp(15)
            
            MDTextField:
                id: url_field
                hint_text: "Paste Video Link Here..."
                mode: "fill"
                fill_color_normal: 0.9, 0.9, 0.9, 0.5
                icon_right: "content-paste"
                size_hint_y: None
                height: dp(60)
                pos_hint: {'center_y': 0.5}

        MDBoxLayout:
            orientation: 'horizontal'
            spacing: dp(15)
            size_hint: 0.9, None
            height: dp(50)
            pos_hint: {'center_x': 0.5}

            MDRaisedButton:
                text: "🎬 VIDEO (HD)"
                font_size: "16sp"
                size_hint_x: 0.5
                md_bg_color: 0, 0.5, 0.8, 1
                on_release: app.start_download("video")

            MDRaisedButton:
                text: "🎵 AUDIO (MP3)"
                font_size: "16sp"
                size_hint_x: 0.5
                md_bg_color: 0.8, 0.2, 0.2, 1
                on_release: app.start_download("audio")

        MDLabel:
            id: status_label
            text: "Ready to download"
            halign: "center"
            theme_text_color: "Secondary"
            font_style: "Caption"
'''

# --- লগার ক্লাস (yt-dlp কে শান্ত রাখার জন্য) ---
class MyLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): print(msg)

class EasyDownloaderApp(MDApp):
    ffmpeg_path = ""

    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Light"
        return Builder.load_string(KV)

    def on_start(self):
        # ১. অ্যান্ড্রয়েড হলে পারমিশন চেক ও FFmpeg সেটআপ
        if platform == 'android':
            self.check_permissions()
            self.setup_ffmpeg()
            self.check_clipboard()

    def check_clipboard(self):
        # ক্লিপবোর্ডে লিংক থাকলে অটোমেটিক বসিয়ে দেবে
        try:
            text = Clipboard.paste()
            if text and ("youtube.com" in text or "youtu.be" in text or "facebook.com" in text):
                self.root.ids.url_field.text = text
                self.show_toast("Link Detected!")
        except:
            pass

    def check_permissions(self):
        # Android 11+ এর জন্য বিশেষ পারমিশন লজিক
        from jnius import autoclass
        from android.permissions import request_permissions, Permission
        
        Environment = autoclass('android.os.Environment')
        
        # যদি ম্যানেজ স্টোরেজ পারমিশন না থাকে (Android 11+)
        if Environment.isExternalStorageManager():
            pass # পারমিশন আছে
        else:
            try:
                # ইউজারকে সেটিংস পেজে পাঠানো
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Intent = autoclass('android.content.Intent')
                Settings = autoclass('android.provider.Settings')
                Uri = autoclass('android.net.Uri')
                
                activity = PythonActivity.mActivity
                uri = Uri.parse("package:" + activity.getPackageName())
                intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, uri)
                activity.startActivity(intent)
            except Exception as e:
                # পুরনো অ্যান্ড্রয়েডের জন্য ফলব্যাক
                request_permissions([Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])

    def setup_ffmpeg(self):
        # APK এর ভেতর থেকে FFmpeg কপি করে এক্সিকিউটেবল করা
        try:
            app_folder = os.path.dirname(os.path.abspath(__file__))
            original_ffmpeg = os.path.join(app_folder, 'assets', 'ffmpeg')
            
            # অ্যাপের প্রাইভেট ফোল্ডার (যেখানে রান করা যাবে)
            files_dir = self.user_data_dir
            self.ffmpeg_path = os.path.join(files_dir, 'ffmpeg')
            
            if not os.path.exists(self.ffmpeg_path):
                shutil.copyfile(original_ffmpeg, self.ffmpeg_path)
            
            # chmod +x (খুব জরুরি)
            st = os.stat(self.ffmpeg_path)
            os.chmod(self.ffmpeg_path, st.st_mode | stat.S_IEXEC)
            
        except Exception as e:
            self.root.ids.status_label.text = f"FFmpeg Setup Error: {e}"

    def start_download(self, dtype):
        url = self.root.ids.url_field.text
        if not url:
            self.root.ids.status_label.text = "⚠️ Please paste a link first!"
            return
        
        self.root.ids.status_label.text = "⏳ Processing... Please wait"
        threading.Thread(target=self.run_yt_dlp, args=(url, dtype)).start()

    def run_yt_dlp(self, url, dtype):
        try:
            # ডাউনলোড ফোল্ডার
            download_path = "/storage/emulated/0/Download/%(title)s.%(ext)s"
            
            ydl_opts = {
                'outtmpl': download_path,
                'noplaylist': True,
                'logger': MyLogger(),
                'ignoreerrors': True,
                'nocheckcertificate': True,
                'ffmpeg_location': self.ffmpeg_path, # আমাদের সেট করা FFmpeg
            }

            if dtype == "video":
                # ভিডিও + অডিও মার্জ (Best Quality)
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                ydl_opts['merge_output_format'] = 'mp4'
            else:
                # শুধু অডিও (MP3 Convert)
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            Clock.schedule_once(lambda x: self.update_status("✅ Download Complete! Check Gallery"), 0)
            
        except Exception as e:
            error_msg = str(e)
            Clock.schedule_once(lambda x: self.update_status(f"❌ Error: {error_msg}"), 0)

    def update_status(self, text):
        self.root.ids.status_label.text = text
    
    def show_toast(self, text):
        self.root.ids.status_label.text = text

if __name__ == '__main__':
    EasyDownloaderApp().run()
