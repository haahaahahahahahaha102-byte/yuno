import asyncio
import threading
import json
import os
from functools import partial

import httpx
import websockets
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.properties import StringProperty, ListProperty, ObjectProperty, BooleanProperty
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.image import Image
from kivy.uix.videoplayer import VideoPlayer
from kivy.uix.behaviors import ButtonBehavior

from PIL import Image as PILImage

from state import save_state, load_state

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
WS_BASE = os.getenv("WS_BASE", "ws://127.0.0.1:8000")

class ClickableImage(ButtonBehavior, Image):
    pass

class LoginScreen(Screen): pass
class RegisterScreen(Screen): pass
class VerifyScreen(Screen):
    email = StringProperty("")
class ChatListScreen(Screen):
    chats = ListProperty([])
class ChatScreen(Screen):
    chat_id = StringProperty("")
    chat_title = StringProperty("")
    messages = ListProperty([])
    wallpaper_path = StringProperty("")
    ws = None
class NewChatScreen(Screen): pass
class SettingsScreen(Screen): pass

class Root(ScreenManager):
    token = StringProperty("")
    user = ObjectProperty(allownone=True)

class MessengerApp(App):
    def build(self):
        Window.minimum_width, Window.minimum_height = 360, 640
        self.title = "Messenger (Kivy)"
        self.root = Root(transition=NoTransition())
        Builder.load_file(os.path.join(os.path.dirname(__file__), "messenger.kv"))
        st = load_state()
        if st.get("token"):
            self.root.token = st["token"]
            self.root.user = st.get("user")
            Clock.schedule_once(lambda *_: self.load_chats(), 0.1)
            self.root.current = "chat_list"
        else:
            self.root.current = "login"
        return self.root

    # -------- HTTP helpers --------
    async def _post(self, path, json_data=None, files=None, data=None):
        async with httpx.AsyncClient(base_url=API_BASE, timeout=20) as client:
            return await client.post(path, json=json_data, files=files, data=data)

    async def _get(self, path, params=None):
        async with httpx.AsyncClient(base_url=API_BASE, timeout=20) as client:
            return await client.get(path, params=params)

    def run_async(self, coro, callback=None, err=None):
        def runner():
            try:
                res = asyncio.run(coro)
                if callback:
                    Clock.schedule_once(lambda *_: callback(res))
            except Exception as e:
                if err:
                    Clock.schedule_once(lambda *_: err(e))
        threading.Thread(target=runner, daemon=True).start()

    # -------- AUTH --------
    def login(self, email, password):
        async def task():
            r = await self._post("/login", json_data={"email": email, "password": password})
            if r.status_code == 403:
                raise Exception("VERIFY_REQUIRED")
            r.raise_for_status()
            return r.json()
        def done(resp):
            self.root.token = resp["token"]
            self.root.user = resp["user"]
            save_state({"token": self.root.token, "user": self.root.user})
            self.load_chats()
            self.root.current = "chat_list"
        def on_err(e):
            if str(e) == "VERIFY_REQUIRED":
                vs = self.root.get_screen("verify")
                vs.email = email
                self.root.current = "verify"
        self.run_async(task(), done, on_err)

    def register(self, email, password, display_name):
        async def task():
            r = await self._post("/register", json_data={"email": email, "password": password, "display_name": display_name})
            r.raise_for_status()
            return r.json()
        def done(resp):
            vs = self.root.get_screen("verify")
            vs.email = email
            self.root.current = "verify"
        self.run_async(task(), done)

    def request_verify(self, email):
        async def task():
            r = await self._post("/request_verify", json_data={"email": email})
            r.raise_for_status()
            return r.json()
        self.run_async(task(), lambda *_: None)

    def submit_verify(self, email, code):
        async def task():
            r = await self._post("/verify", json_data={"email": email, "code": code})
            r.raise_for_status()
            return r.json()
        def done(_):
            # после успешной верификации возвращаемся на экран логина
            self.root.current = "login"
        self.run_async(task(), done)

    # -------- CHATS --------
    def load_chats(self):
        async def task():
            r = await self._get("/my_chats", params={"token": self.root.token})
            r.raise_for_status()
            return r.json()
        def done(chats):
            scr: ChatListScreen = self.root.get_screen("chat_list")
            scr.chats = chats
        self.run_async(task(), done)

    def create_chat(self, title, is_channel, member_ids_csv):
        try:
            member_ids = [int(x.strip()) for x in member_ids_csv.split(',') if x.strip()]
        except Exception:
            member_ids = []
        async def task():
            data = {"title": title, "is_channel": bool(is_channel), "member_ids": member_ids}
            r = await self._post("/chats", data={"token": self.root.token, "payload": json.dumps(data)}, json_data=None)
            r.raise_for_status()
            return r.json()
        def done(_):
            self.load_chats()
            self.root.current = "chat_list"
        self.run_async(task(), done)

    # -------- Upload & Media --------
    def upload_file(self, file_path, callback):
        async def task():
            filename = os.path.basename(file_path)
            files = {"file": (filename, open(file_path, "rb"), "application/octet-stream")}
            r = await self._post("/upload", files=files)
            r.raise_for_status()
            return r.json()
        def done(resp):
            url = API_BASE + resp["url"]
            mtype = resp.get("type", "image")
            callback(url, mtype)
        self.run_async(task(), done)

    def open_chat(self, chat_id, title):
        scr: ChatScreen = self.root.get_screen("chat")
        scr.chat_id = str(chat_id)
        scr.chat_title = title
        scr.messages = []
        st = load_state()
        wall = st.get("wallpapers", {}).get(scr.chat_id)
        scr.wallpaper_path = wall or ""
        self.root.current = "chat"
        threading.Thread(target=partial(self._ws_loop, scr.chat_id), daemon=True).start()

    def _ws_loop(self, chat_id):
        async def runner():
            uri = f"{WS_BASE}/ws/{chat_id}?token={self.root.token}"
            async with websockets.connect(uri, ping_interval=20) as ws:
                scr: ChatScreen = self.root.get_screen("chat")
                scr.ws = ws
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    Clock.schedule_once(lambda *_: self._append_message(data))
        asyncio.run(runner())

    def _append_message(self, data):
        scr: ChatScreen = self.root.get_screen("chat")
        scr.messages.append(data)

    def send_text(self, text):
        scr: ChatScreen = self.root.get_screen("chat")
        if scr.ws and text.strip():
            asyncio.run(self._ws_send({"type": "text", "content": text.strip()}))

    def send_media_url(self, url, mtype):
        scr: ChatScreen = self.root.get_screen("chat")
        if scr.ws:
            asyncio.run(self._ws_send({"type": mtype, "content": url}))

    async def _ws_send(self, data):
        scr: ChatScreen = self.root.get_screen("chat")
        try:
            await scr.ws.send(json.dumps(data))
        except Exception:
            pass

    def set_wallpaper(self, chat_id, image_path):
        try:
            img = PILImage.open(image_path); img.verify()
        except Exception:
            return
        st = load_state()
        walls = st.get("wallpapers", {})
        walls[str(chat_id)] = image_path
        st["wallpapers"] = walls
        save_state(st)
        scr: ChatScreen = self.root.get_screen("chat")
        if str(chat_id) == scr.chat_id:
            scr.wallpaper_path = image_path

if __name__ == "__main__":
    MessengerApp().run()
