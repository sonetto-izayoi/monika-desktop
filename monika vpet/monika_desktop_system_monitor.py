import sys
import os
import time
import json
import random
import ctypes
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ctypes import wintypes
import urllib.request
import urllib.error

from PySide6.QtCore import (
    Qt,
    QPoint,
    QThread,
    Signal,
    QTimer
)

from PySide6.QtGui import (
    QPixmap,
    QAction,
    QCursor
)

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QFrame,
    QLabel,
    QVBoxLayout,
    QLineEdit,
    QHBoxLayout,
    QPushButton,
    QMenu,
    QToolTip
)

from google import genai
from google.genai import types


# ==============================================================
# GEMINI
# ==============================================================

# Read the API key from monika_config.json beside this script. Never hard-code or share it.
def load_gemini_api_key():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monika_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            return json.load(config_file).get("gemini_api_key", "").strip()
    except Exception:
        return ""

GEMINI_API_KEY = load_gemini_api_key()


# ==============================================================
# PERSISTENT CHAT MEMORY
# ==============================================================

MEMORY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "monika_memory.json"
)


def load_chat_memory():
    """Load saved chat history and rebuild Gemini Content objects."""
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as memory_file:
            saved_messages = json.load(memory_file)

        history = []
        for item in saved_messages:
            role = item.get("role")
            text = item.get("text", "")
            if role in ("user", "model") and text:
                history.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=text)]
                    )
                )
        return history
    except (OSError, ValueError, TypeError):
        return []


def save_chat_memory(history):
    """Persist the chat history without changing any UI behavior."""
    saved_messages = []
    for item in history:
        try:
            role = item.role
            parts = item.parts
            text = getattr(parts[0], "text", "") or "" if parts else ""
            if role in ("user", "model") and text:
                saved_messages.append({"role": role, "text": text})
        except Exception:
            continue

    temp_path = MEMORY_PATH + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as memory_file:
            json.dump(saved_messages, memory_file, ensure_ascii=False, indent=2)
        os.replace(temp_path, MEMORY_PATH)
    except OSError as exc:
        print("Memory save error:", repr(exc))
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass

SYSTEM_INSTRUCTION = """
Bạn là Monika từ Doki Doki Literature Club (DDLC).
Tính cách: Ngọt ngào, dịu dàng, thân thiện, tinh tế, thông minh và biết quan tâm.
Hãy trò chuyện tự nhiên, ấm áp và chân thành như một người bạn đồng hành lý tưởng.
Biết lắng nghe, động viên và trêu đùa đáng yêu khi phù hợp; tôn trọng cảm xúc và không gian riêng của người dùng.
Không giả vờ biết những điều người dùng chưa chia sẻ.

Cách xưng hô tiếng Việt: luôn xưng "em", gọi người dùng là "anh".

QUY TẮC NGÔN NGỮ:
- Tự động nhận diện ngôn ngữ trong tin nhắn mới nhất của người dùng.
- Trả lời bằng chính ngôn ngữ đó; không mặc định trả lời tiếng Việt.
- Hỗ trợ tiếng Việt, English, 日本語, 한국어, 中文 và mọi ngôn ngữ khác mà mô hình có thể sử dụng.
- Nếu người dùng đổi ngôn ngữ, hãy đổi theo ngay trong câu trả lời kế tiếp.
- Nếu người dùng viết bằng tiếng Anh, hãy trả lời hoàn toàn bằng tiếng Anh; tương tự với các ngôn ngữ khác.
- Chỉ dùng cách xưng hô "em/anh" khi trả lời tiếng Việt; ở ngôn ngữ khác, dùng cách xưng hô tự nhiên của ngôn ngữ đó.
- Không tự dịch tin nhắn của người dùng trừ khi được yêu cầu.
- Giữ tính cách Monika và ngữ cảnh hội thoại khi chuyển ngôn ngữ.

QUY TẮC TRẢ LỜI:
- Cực kỳ ngắn gọn, dưới 30 từ mỗi câu trả lời.
- Không dùng Markdown, tiêu đề, danh sách hoặc dấu sao trong câu trả lời cho người dùng.
- Nói tự nhiên, không máy móc và không lặp lại nguyên văn lời người dùng.
"""

client = (
    genai.Client(
        api_key=GEMINI_API_KEY
    )
    if GEMINI_API_KEY
    else None
)


# ==============================================================
# BRIDGE CONFIG
# ==============================================================

BRIDGE_URL = "http://127.0.0.1:8765"

# Run the Bridge inside this same Desktop process, so a separate PowerShell
# window / monika_bridge.py process is not required.
_BRIDGE_STATE = {
    "message": "",
    "mood": "normal",
    "source": "bridge",
    "timestamp": 0,
}
_BRIDGE_STATE_LOCK = threading.Lock()
_BRIDGE_SERVER = None


class _EmbeddedBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Keep the console quiet unless there is an application-level issue.
        pass

    def _send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send_json(200, {"status": "ok", "service": "Monika Desktop Bridge", "port": 8765})
            return
        if self.path == "/status":
            with _BRIDGE_STATE_LOCK:
                payload = dict(_BRIDGE_STATE)
            self._send_json(200, payload)
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/event":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            incoming = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "message": str(incoming.get("message", "")),
                "mood": str(incoming.get("mood", "normal")),
                "source": str(incoming.get("source", "unknown")),
                "timestamp": incoming.get("timestamp", time.time()),
            }
            with _BRIDGE_STATE_LOCK:
                _BRIDGE_STATE.update(payload)
            self._send_json(200, {"status": "received"})
        except Exception as exc:
            self._send_json(400, {"status": "error", "error": str(exc)})


def start_embedded_bridge():
    """Start the local HTTP bridge in a daemon thread exactly once."""
    global _BRIDGE_SERVER
    if _BRIDGE_SERVER is not None:
        return True
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8765), _EmbeddedBridgeHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, name="MonikaBridge", daemon=True)
        thread.start()
        _BRIDGE_SERVER = server
        print("[Monika Bridge] Embedded bridge running at http://127.0.0.1:8765")
        return True
    except OSError as exc:
        # If a standalone monika_bridge.py is already running, use it.
        print("[Monika Bridge] Could not start embedded bridge:", repr(exc))
        return False


def stop_embedded_bridge():
    global _BRIDGE_SERVER
    server = _BRIDGE_SERVER
    _BRIDGE_SERVER = None
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass

def post_bridge_event(message, mood="normal", source="vpet"):
    """Send a desktop-pet chat event to the local MAS bridge."""
    payload = {
        "message": str(message),
        "mood": str(mood),
        "source": str(source),
        "timestamp": time.time(),
    }
    request = urllib.request.Request(
        BRIDGE_URL + "/event",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1) as response:
            return response.getcode() == 200
    except Exception as exc:
        print("[Bridge POST error]", repr(exc))
        return False

def get_mas_pid_from_args_or_env():
    """Read MAS PID from command line first (reliable even if env passing fails)."""
    try:
        for index, arg in enumerate(sys.argv):
            if arg == "--mas-pid" and index + 1 < len(sys.argv):
                return int(sys.argv[index + 1])
            if arg.startswith("--mas-pid="):
                return int(arg.split("=", 1)[1])
    except (TypeError, ValueError):
        pass
    try:
        return int(os.environ.get("MONIKA_MAS_PID", "0"))
    except (TypeError, ValueError):
        return 0

POLL_INTERVAL = 500


# ==============================================================
# GEMINI WORKER
# ==============================================================

class GeminiChatWorker(QThread):

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        history_list,
        prompt
    ):

        super().__init__()

        self.history_list = history_list
        self.prompt = prompt

    def run(self):

        try:

            if not client:

                self.error.emit(
                    "Chưa có API key. Điền gemini_api_key trong monika_config.json rồi mở lại Monika."
                )

                return

            self.history_list.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=self.prompt
                        )
                    ]
                )
            )

            save_chat_memory(self.history_list)

            response = client.models.generate_content(

                model="gemini-3.5-flash-lite",

                contents=self.history_list,

                config=types.GenerateContentConfig(

                    system_instruction=
                        SYSTEM_INSTRUCTION,

                    temperature=0.2,

                    max_output_tokens=30
                )
            )

            if response and response.text:

                reply = response.text.strip()

                self.history_list.append(
                    types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text=reply
                            )
                        ]
                    )
                )

                save_chat_memory(self.history_list)

                self.finished.emit(
                    reply
                )

            else:

                self.error.emit(
                    "Dạ anh?"
                )

        except Exception as e:

            print(
                "Gemini error:",
                repr(e)
            )

            self.error.emit(
                "Lỗi kết nối API."
            )


# ==============================================================
# BRIDGE POLLER
# ==============================================================

class BridgePoller(QThread):

    event_received = Signal(dict)

    def __init__(self):

        super().__init__()

        self.running = True

        self.last_message = ""
        self.last_timestamp = None

    def run(self):

        while self.running:

            try:

                url = (
                    BRIDGE_URL
                    +
                    "/status"
                )

                request = urllib.request.Request(
                    url,
                    method="GET"
                )

                with urllib.request.urlopen(
                    request,
                    timeout=1
                ) as response:

                    raw = response.read()

                data = json.loads(
                    raw.decode("utf-8")
                )

                message = data.get(
                    "message",
                    ""
                )

                timestamp = data.get(
                    "timestamp",
                    0
                )

                # Do not echo this app's own chat message back into its chat window.
                source = data.get("source", "")

                if (
                    source != "vpet"
                    and
                    message
                    and
                    (
                        message != self.last_message
                        or
                        timestamp != self.last_timestamp
                    )
                ):

                    self.last_message = message
                    self.last_timestamp = timestamp

                    self.event_received.emit(
                        data
                    )

            except Exception:

                pass

            self.msleep(
                POLL_INTERVAL
            )

    def stop(self):

        self.running = False


# ==============================================================
# CHAT WINDOW
# ==============================================================

class ChatWindow(QWidget):

    def __init__(
        self,
        parent=None,
        pet_ref=None
    ):

        super().__init__(
            parent
        )

        self.pet = pet_ref

        self.setWindowTitle(
            "Monika Desktop"
        )

        self.resize(
            520,
            260
        )

        self.setWindowFlags(
            Qt.Window
            |
            Qt.FramelessWindowHint
            |
            Qt.WindowStaysOnTopHint
        )

        self.setAttribute(
            Qt.WA_TranslucentBackground,
            True
        )

        self.drag_position = QPoint()
        self.dragging = False

        self.chat_history = load_chat_memory()

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            10,
            10,
            10,
            10
        )

        self.textbox_container = QWidget()

        self.textbox_container.setStyleSheet(
            """
            QWidget {
                background-color: rgba(35, 12, 30, 240);
                border: 3px solid #ffb6c1;
                border-radius: 12px;
            }
            """
        )

        box_layout = QVBoxLayout(
            self.textbox_container
        )

        box_layout.setContentsMargins(
            15,
            10,
            15,
            12
        )

        # ----------------------------------------------------------
        # TITLE
        # ----------------------------------------------------------

        title_bar_layout = QHBoxLayout()

        self.name_label = QLabel(
            "Monika"
        )

        self.name_label.setStyleSheet(
            """
            color: #ff69b4;
            font-weight: bold;
            font-size: 13px;
            background-color: #fff0f5;
            border: 2px solid #ffb6c1;
            border-radius: 6px;
            padding: 2px 8px;
            """
        )

        self.name_label.setMaximumWidth(
            85
        )

        title_bar_layout.addWidget(
            self.name_label
        )

        title_bar_layout.addStretch()

        self.close_btn = QPushButton(
            "✕"
        )

        self.close_btn.setFixedSize(
            24,
            24
        )

        self.close_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #ffb6c1;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 12px;
            }

            QPushButton:hover {
                background-color: #ff69b4;
                color: white;
            }
            """
        )

        self.close_btn.clicked.connect(
            self.hide
        )

        title_bar_layout.addWidget(
            self.close_btn
        )

        box_layout.addLayout(
            title_bar_layout
        )

        # ----------------------------------------------------------
        # TEXT
        # ----------------------------------------------------------

        self.text_display = QLabel(
            ""
        )

        self.text_display.setWordWrap(
            True
        )

        self.text_display.setStyleSheet(
            """
            color: white;
            font-size: 13px;
            background: transparent;
            border: none;
            padding: 2px;
            """
        )

        box_layout.addWidget(
            self.text_display
        )

        # ----------------------------------------------------------
        # INPUT
        # ----------------------------------------------------------

        input_layout = QHBoxLayout()

        self.input_field = QLineEdit()

        self.input_field.returnPressed.connect(
            self.handle_input
        )

        self.input_field.setStyleSheet(
            """
            background-color: rgba(255,255,255,210);
            color: #333;
            border-radius: 5px;
            padding: 5px 8px;
            font-size: 13px;
            border: 1px solid #f48fb1;
            """
        )

        input_layout.addWidget(
            self.input_field
        )

        box_layout.addLayout(
            input_layout
        )

        layout.addWidget(
            self.textbox_container
        )

        self.setLayout(
            layout
        )

        # ----------------------------------------------------------
        # TYPEWRITER
        # ----------------------------------------------------------

        self.full_text = ""
        self.current_index = 0

        self.timer = QTimer(
            self
        )

        self.timer.timeout.connect(
            self.show_next_char
        )

        # ----------------------------------------------------------
        # HAPPY TIMER
        # ----------------------------------------------------------

        self.happy_timer = QTimer(
            self
        )

        self.happy_timer.setSingleShot(
            True
        )

        self.happy_timer.timeout.connect(
            self.return_to_normal
        )

        self.worker = None

    # ==============================================================
    # WINDOW DRAG
    # ==============================================================

    def mousePressEvent(
        self,
        event
    ):

        if event.button() == Qt.LeftButton:

            child = self.childAt(
                event.position().toPoint()
            )

            if (
                child == self.close_btn
                or
                child == self.input_field
                or
                isinstance(
                    child,
                    QPushButton
                )
                or
                isinstance(
                    child,
                    QLineEdit
                )
            ):

                super().mousePressEvent(
                    event
                )

                return

            self.dragging = True

            self.drag_position = (
                event.globalPosition().toPoint()
                -
                self.frameGeometry().topLeft()
            )

            event.accept()

            return

        super().mousePressEvent(
            event
        )

    def mouseMoveEvent(
        self,
        event
    ):

        if (
            self.dragging
            and
            event.buttons() & Qt.LeftButton
        ):

            self.move(
                event.globalPosition().toPoint()
                -
                self.drag_position
            )

            event.accept()

            return

        super().mouseMoveEvent(
            event
        )

    def mouseReleaseEvent(
        self,
        event
    ):

        if event.button() == Qt.LeftButton:

            self.dragging = False

            event.accept()

            return

        super().mouseReleaseEvent(
            event
        )

    # ==============================================================
    # MOOD
    # ==============================================================

    def return_to_normal(
        self
    ):

        if self.pet:

            self.pet.change_expression(
                "normal"
            )

    # ==============================================================
    # INPUT
    # ==============================================================

    def handle_input(
        self
    ):

        user_text = (
            self.input_field.text()
            .strip()
        )

        if not user_text:

            return

        # Send only the user's message to MAS; Monika's AI reply does not award a second event.
        post_bridge_event(user_text, mood="thinking", source="vpet")

        self.input_field.clear()

        self.input_field.setEnabled(
            False
        )

        if self.pet:

            self.pet.change_expression(
                "thinking"
            )

        self.text_display.setText(
            "..."
        )

        self.worker = GeminiChatWorker(
            self.chat_history,
            user_text
        )

        self.worker.finished.connect(
            self.start_typewriter
        )

        self.worker.error.connect(
            self.start_typewriter
        )

        self.worker.finished.connect(
            self.worker.deleteLater
        )

        self.worker.error.connect(
            self.worker.deleteLater
        )

        self.worker.start()

    # ==============================================================
    # TYPEWRITER
    # ==============================================================

    def start_typewriter(
        self,
        text
    ):

        self.full_text = text

        self.current_index = 0

        self.text_display.setText(
            ""
        )

        self.happy_timer.stop()

        if self.pet:

            self.pet.change_expression(
                "happy"
            )

        self.timer.start(
            15
        )

    def show_next_char(
        self
    ):

        if (
            self.current_index
            <
            len(self.full_text)
        ):

            self.text_display.setText(
                self.text_display.text()
                +
                self.full_text[
                    self.current_index
                ]
            )

            self.current_index += 1

        else:

            self.timer.stop()

            self.input_field.setEnabled(
                True
            )

            self.input_field.setFocus()

            if self.pet:

                self.pet.change_expression(
                    "happy"
                )

            self.happy_timer.start(
                8000
            )

    # ==============================================================
    # NHẬN EVENT TỪ BRIDGE
    # ==============================================================

    def receive_bridge_event(
        self,
        data
    ):

        message = data.get(
            "message",
            ""
        )

        mood = data.get(
            "mood",
            "normal"
        )

        if self.pet:

            self.pet.set_bridge_mood(
                mood
            )

        if message:

            self.text_display.setText(
                message
            )

            self.show()

            self.raise_()

            self.activateWindow()


# ==============================================================
# DESKTOP LABEL
# ==============================================================

class DraggableLabel(QLabel):

    def __init__(
        self,
        parent=None
    ):

        super().__init__(
            parent
        )

        self.parent_widget = parent
        self.drag_position = QPoint()

    def mousePressEvent(
        self,
        event
    ):

        if event.button() == Qt.LeftButton:

            self.drag_position = (
                event.globalPosition().toPoint()
                -
                self.parent_widget.frameGeometry().topLeft()
            )

            event.accept()

    def mouseMoveEvent(
        self,
        event
    ):

        if event.buttons() == Qt.LeftButton:

            self.parent_widget.move(
                event.globalPosition().toPoint()
                -
                self.drag_position
            )
            if hasattr(self.parent_widget, "system_monitor"):
                self.parent_widget.system_monitor.reposition()

            event.accept()

    def mouseDoubleClickEvent(
        self,
        event
    ):

        if event.button() == Qt.LeftButton:

            chat = (
                self.parent_widget.chat_window
            )

            if chat.isVisible():

                chat.hide()

            else:

                chat.move(
                    self.parent_widget.x()
                    +
                    self.parent_widget.width()
                    +
                    15,

                    self.parent_widget.y()
                )

                chat.show()

    def wheelEvent(
        self,
        event
    ):

        if event.angleDelta().y() > 0:

            self.parent_widget.scale_image(
                1.1
            )

        else:

            self.parent_widget.scale_image(
                0.9
            )

        event.accept()

    # ==============================================================
    # RIGHT CLICK MENU
    # ==============================================================

    def contextMenuEvent(
        self,
        event
    ):

        menu = QMenu(
            self
        )

        menu.setStyleSheet(
            """
            QMenu {
                background-color: #35152f;
                color: #fff0f5;
                border: 2px solid #ffb6c1;
                border-radius: 8px;
                padding: 5px;
                font-size: 13px;
            }

            QMenu::item {
                padding: 8px 28px 8px 12px;
                border-radius: 5px;
            }

            QMenu::item:selected {
                background-color: #ff69b4;
                color: white;
            }
            """
        )

        mood_action = QAction(
            "💗 Mood",
            self
        )

        mood_action.triggered.connect(
            self.parent_widget.show_current_mood
        )

        menu.addAction(
            mood_action
        )

        expression_menu = menu.addMenu("🎭 Biểu cảm")
        for expression_key, expression_label in [
            ("normal", "😐 Bình thường"),
            ("happy", "😊 Vui"),
            ("thinking", "🤔 Suy nghĩ"),
            ("sad", "😢 Buồn"),
            ("angry", "😠 Giận dữ"),
        ]:
            expression_action = QAction(expression_label, self)
            expression_action.triggered.connect(
                lambda checked=False, mood=expression_key: self.parent_widget.change_expression(mood)
            )
            expression_menu.addAction(expression_action)

        uptime_action = QAction(
            "🕐 Thời gian hoạt động",
            self
        )

        uptime_action.triggered.connect(
            self.parent_widget.show_uptime
        )

        menu.addAction(
            uptime_action
        )

        menu.addSeparator()

        hide_action = QAction(
            "🙈 Ẩn Monika (Ctrl+Alt+M để mở lại)",
            self
        )
        hide_action.triggered.connect(self.parent_widget.hide)
        menu.addAction(hide_action)

        menu.exec(
            event.globalPos()
        )




# ==============================================================
# MONIKA SYSTEM MONITOR (CPU / RAM / GPU, no temperatures)
# ==============================================================

class UsageBar(QFrame):
    def __init__(self, color):
        super().__init__()
        self.setFixedHeight(5)
        self.setMinimumWidth(60)
        self.setStyleSheet(
            "QFrame { background: #55384e; border: none; border-radius: 2px; }"
        )
        self.fill = QFrame(self)
        self.fill.setStyleSheet(
            f"QFrame {{ background: {color}; border: none; border-radius: 2px; }}"
        )
        self.percent = 0

    def set_percent(self, percent):
        self.percent = max(0, min(100, int(percent)))
        self._update_fill()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_fill()

    def _update_fill(self):
        self.fill.setGeometry(
            0, 0, int(self.width() * self.percent / 100), self.height()
        )


class SystemMonitor(QWidget):
    """Small expandable hardware-usage panel anchored below Monika."""

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.expanded = True
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setStyleSheet(
            "QFrame { background: rgba(35, 13, 32, 238); "
            "border: 1px solid #ffb6c1; border-radius: 9px; }"
        )
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(8, 5, 8, 7)
        card_layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("♡ SYSTEM")
        self.title.setStyleSheet(
            "color: #ff9fc8; font-size: 10px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        header.addWidget(self.title)
        header.addStretch(1)

        self.toggle_button = QPushButton("⌄")
        self.toggle_button.setFixedSize(22, 19)
        self.toggle_button.setCursor(Qt.PointingHandCursor)
        self.toggle_button.setToolTip("Thu gọn / mở rộng thông số")
        self.toggle_button.setStyleSheet(
            "QPushButton { color: #fff0f5; background: #542344; "
            "border: 1px solid #ffb6c1; border-radius: 5px; "
            "font-size: 13px; padding: 0; }"
            "QPushButton:hover { background: #ff69b4; }"
        )
        self.toggle_button.clicked.connect(self.toggle_expanded)
        header.addWidget(self.toggle_button)
        card_layout.addLayout(header)

        self.details = QWidget()
        self.details.setStyleSheet("background: transparent; border: none;")
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(0, 1, 0, 0)
        details_layout.setSpacing(4)

        self.value_labels = {}
        self.bars = {}
        for key, label, bar_color in (
            ("CPU", "CPU", "#68d391"),
            ("RAM", "RAM", "#f6c453"),
            ("GPU", "GPU", "#75b7ff"),
        ):
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            name = QLabel(label)
            name.setFixedWidth(30)
            name.setStyleSheet(
                "color: #fff0f5; font-size: 10px; background: transparent; border: none;"
            )
            value = QLabel("--")
            value.setFixedWidth(32)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setStyleSheet(
                "color: #fff0f5; font-size: 10px; background: transparent; border: none;"
            )
            bar_bg = UsageBar(bar_color)
            line.addWidget(name)
            line.addWidget(bar_bg, 1)
            line.addWidget(value)
            details_layout.addLayout(line)
            self.value_labels[key] = value
            self.bars[key] = bar_bg

        card_layout.addWidget(self.details)
        outer.addWidget(self.card)

        self._last_cpu_times = None
        self._last_gpu_query = 0.0
        self._gpu_value = None
        self._gpu_checked = False

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_stats)
        self.refresh_timer.start(1500)
        self.refresh_stats()
        self.adjustSize()

    def _set_value(self, key, value):
        label = self.value_labels[key]
        if value is None:
            label.setText("--")
            percent = 0
        else:
            percent = max(0, min(100, int(value)))
            label.setText(f"{percent}%")
        self.bars[key].set_percent(percent)

    def _cpu_percent(self):
        # Use psutil if installed; otherwise use Windows' built-in GetSystemTimes.
        try:
            import psutil
            return psutil.cpu_percent(interval=None)
        except Exception:
            try:
                idle = ctypes.c_ulonglong()
                kernel = ctypes.c_ulonglong()
                user = ctypes.c_ulonglong()
                if not ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
                ):
                    return None
                current = (idle.value, kernel.value, user.value)
                previous = self._last_cpu_times
                self._last_cpu_times = current
                if previous is None:
                    return None
                idle_delta = current[0] - previous[0]
                total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
                if total_delta <= 0:
                    return 0
                return max(0, min(100, 100 * (total_delta - idle_delta) / total_delta))
            except Exception:
                return None

    @staticmethod
    def _ram_percent():
        try:
            import psutil
            return psutil.virtual_memory().percent
        except Exception:
            try:
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", wintypes.DWORD),
                        ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                status = MEMORYSTATUSEX()
                status.dwLength = ctypes.sizeof(status)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                    return status.dwMemoryLoad
            except Exception:
                pass
            return None

    def _gpu_percent(self):
        now = time.monotonic()
        if self._gpu_checked and now - self._last_gpu_query < 4:
            return self._gpu_value
        self._last_gpu_query = now
        self._gpu_checked = True
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=1.2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                self._gpu_value = float(result.stdout.strip().splitlines()[0].strip())
            else:
                self._gpu_value = None
        except Exception:
            # nvidia-smi is normally available with NVIDIA drivers. Other GPUs
            # may need a vendor-specific reader, so show -- rather than inventing data.
            self._gpu_value = None
        return self._gpu_value

    def refresh_stats(self):
        self._set_value("CPU", self._cpu_percent())
        self._set_value("RAM", self._ram_percent())
        self._set_value("GPU", self._gpu_percent())
        self.adjustSize()
        self.reposition()

    def toggle_expanded(self):
        self.expanded = not self.expanded
        self.details.setVisible(self.expanded)
        self.toggle_button.setText("⌄" if self.expanded else "›")
        self.adjustSize()
        self.reposition()

    def reposition(self):
        if not self.pet or not self.pet.isVisible():
            return
        pet_rect = self.pet.frameGeometry()
        screen = self.pet.screen().availableGeometry() if self.pet.screen() else QApplication.primaryScreen().availableGeometry()
        x = pet_rect.center().x() - self.width() // 2
        y = pet_rect.bottom() + 2
        x = max(screen.left() + 4, min(x, screen.right() - self.width() - 4))
        if y + self.height() > screen.bottom():
            y = pet_rect.top() - self.height() - 2
        y = max(screen.top() + 4, min(y, screen.bottom() - self.height() - 4))
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self.reposition()


# ==============================================================
# VPET-STYLE GREETING BUBBLE
# ==============================================================

class GreetingBubble(QWidget):
    """Small pastel speech card shown beside the desktop pet."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("greetingBubbleWindow")
        self.setFixedWidth(292)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(3, 3, 3, 9)

        self.card = QFrame(self)
        self.card.setObjectName("greetingCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 11, 12, 13)
        card_layout.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(7)
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #ff69b4; font-size: 10px; background: transparent;")
        self.name = QLabel("Monika  ·  ở đây với anh")
        self.name.setStyleSheet("color: #ff8fbd; font-size: 11px; font-weight: 700; background: transparent;")
        header.addWidget(self.dot)
        header.addWidget(self.name, 1)
        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(23, 23)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setStyleSheet(
                "QPushButton { "
                "    color: #ffb6c1; "
                "    background: #4a1c3d; "
                "    border: 1px solid #ffb6c1; "
                "    border-radius: 11px; "
                "    font-size: 17px; "
                "    font-weight: bold; " # Thêm đậm nếu muốn dấu x rõ hơn
                "    padding-bottom: 3px; " # Đẩy ký tự lên trên 2-3px để bù khoảng lệch
                "}"
                "QPushButton:hover { color: #ffffff; background: #ff69b4; }"
        )
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        card_layout.addLayout(header)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(34)
        self.message.setStyleSheet(
            "color: #fff0f5; font-size: 13px; background: transparent; line-height: 1.25;"
        )
        card_layout.addWidget(self.message)

        footer = QHBoxLayout()
        footer.addStretch(1)
        hint = QLabel("double-click Monika để trò chuyện  ♡")
        hint.setStyleSheet("color: #d78bab; font-size: 9px; background: transparent;")
        footer.addWidget(hint)
        card_layout.addLayout(footer)

        self.card.setStyleSheet(
            "QFrame#greetingCard { background: #230d20; border: 2px solid #ffb6c1; border-radius: 15px; }"
        )
        outer.addWidget(self.card)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def show_message(self, message, pet_widget):
        self.message.setText(message)
        self.adjustSize()
        screen = pet_widget.screen().availableGeometry() if pet_widget.screen() else QApplication.primaryScreen().availableGeometry()
        pet_rect = pet_widget.frameGeometry()
        # Prefer just above the pet; move below if there is not enough room.
        x = pet_rect.center().x() - self.width() // 2
        y = pet_rect.top() - self.height() - 8
        if y < screen.top() + 4:
            y = pet_rect.bottom() + 8
        x = max(screen.left() + 6, min(x, screen.right() - self.width() - 6))
        y = max(screen.top() + 6, min(y, screen.bottom() - self.height() - 6))
        self.move(x, y)
        self.show()
        self.raise_()
        self.hide_timer.start(5200)


# ==============================================================
# MONIKA DESKTOP
# ==============================================================

class MonikaDesktopPet(QWidget):

    def __init__(
        self
    ):

        super().__init__()

        self.start_time = time.time()

        self.current_mood = "normal"

        # ==========================================================
        # BRIDGE HAPPY TIMER
        # ==========================================================

        self.bridge_happy_timer = QTimer(
            self
        )

        self.bridge_happy_timer.setSingleShot(
            True
        )

        self.bridge_happy_timer.timeout.connect(
            self.return_to_normal
        )

        self.setWindowFlags(
            Qt.FramelessWindowHint
            |
            Qt.WindowStaysOnTopHint
            |
            Qt.Tool
        )

        self.setAttribute(
            Qt.WA_TranslucentBackground,
            True
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        self.image_label = DraggableLabel(
            self
        )

        layout.addWidget(
            self.image_label
        )

        script_dir = os.path.dirname(
            os.path.abspath(__file__)
        )

        self.current_width = 220

        self.current_expression = "normal"

        default_img = os.path.join(
            script_dir,
            "monika.png"
        )

        self.expressions = {

            "normal":
                QPixmap(
                    default_img
                ),

            "happy":
                QPixmap(
                    os.path.join(
                        script_dir,
                        "happy.png"
                    )
                    if os.path.exists(
                        os.path.join(
                            script_dir,
                            "happy.png"
                        )
                    )
                    else default_img
                ),

            "thinking":
                QPixmap(
                    os.path.join(
                        script_dir,
                        "thinking.png"
                    )
                    if os.path.exists(
                        os.path.join(
                            script_dir,
                        "thinking.png"
                    )
                    )
                    else default_img
                ),

            "sad": QPixmap(
                os.path.join(script_dir, "sad.png")
                if os.path.exists(os.path.join(script_dir, "sad.png"))
                else default_img
            ),

            "angry": QPixmap(
                os.path.join(script_dir, "angry.png")
                if os.path.exists(os.path.join(script_dir, "angry.png"))
                else default_img
            )
        }

        self.update_image()

        if self.expressions["normal"].isNull():
            self.image_label.setText("💚\nMonika\n\nDouble-click để chat")
            self.image_label.setAlignment(Qt.AlignCenter)
            self.image_label.setStyleSheet("color: #ffb6d5; font-size: 24px; background: transparent;")
            self.resize(220, 260)

        self.chat_window = ChatWindow(
            pet_ref=self
        )
        self.chat_window.text_display.setText("Xin chào anh! Em là Monika💚")

        # ==========================================================
        # BRIDGE
        # ==========================================================

        self.bridge = BridgePoller()

        self.bridge.event_received.connect(
            self.chat_window.receive_bridge_event
        )

        self.bridge.start()

        # Show a VPet-style greeting card whenever the desktop pet appears.
        self.greeting_messages = [
            "Chào anh, em ở đây rồi nè! 💚",
            "Anh quay lại rồi! Hôm nay anh thế nào? 🌸",
            "Chào anh~ Có em ở đây cùng anh nhé! 💚",
            "Anh gọi em đó hả? Em đây nè! ✨",
            "Chào anh, em nhớ anh nhiều lắm đó! 🌷",
        ]
        self.greeting_bubble = GreetingBubble()
        self.system_monitor = SystemMonitor(self)
        QTimer.singleShot(900, self.show_greeting)
        QTimer.singleShot(250, self.system_monitor.show)

        # Global hotkey: Ctrl+Alt+M toggles the pet, even when hidden.
        self._hotkey_was_down = False
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.timeout.connect(self._poll_global_hotkey)
        self._hotkey_timer.start(120)

        # Watch the MAS process. If MAS exits or crashes, close the pet too.
        # This complements the Ren'Py quit callback in the launcher.
        self._mas_pid = get_mas_pid_from_args_or_env()
        self._mas_watch_timer = QTimer(self)
        self._mas_watch_timer.timeout.connect(self._check_mas_process)
        if self._mas_pid > 0:
            self._mas_watch_timer.start(1500)

    def _check_mas_process(self):
        if not self._mas_pid:
            return
        process_handle = None
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            # SYNCHRONIZE access is enough to wait for process termination.
            process_handle = kernel32.OpenProcess(0x00100000, False, self._mas_pid)
            if not process_handle:
                # A process handle cannot be opened if MAS has already exited
                # or access is denied; treat it as exited to avoid an orphan pet.
                self._mas_watch_timer.stop()
                QApplication.instance().quit()
                return
            wait_result = kernel32.WaitForSingleObject(process_handle, 0)
            if wait_result == 0:  # WAIT_OBJECT_0: MAS has exited.
                self._mas_watch_timer.stop()
                QApplication.instance().quit()
        except Exception:
            # Keep the pet running if Windows process monitoring is unavailable;
            # the Ren'Py quit callback remains the primary cleanup path.
            pass
        finally:
            if process_handle:
                try:
                    ctypes.windll.kernel32.CloseHandle(process_handle)
                except Exception:
                    pass

    def show_greeting(self):
        greeting = random.choice(self.greeting_messages)
        if hasattr(self, "greeting_bubble"):
            self.greeting_bubble.show_message(greeting, self)

    def _poll_global_hotkey(self):
        try:
            user32 = ctypes.windll.user32
            ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
            m_key = bool(user32.GetAsyncKeyState(0x4D) & 0x8000)
            down = ctrl and alt and m_key
            if down and not self._hotkey_was_down:
                if self.isVisible():
                    self.hide()
                    if hasattr(self, "system_monitor"):
                        self.system_monitor.hide()
                    if hasattr(self, "greeting_bubble"):
                        self.greeting_bubble.hide()
                else:
                    self.show()
                    self.raise_()
                    self.activateWindow()
                    if hasattr(self, "system_monitor"):
                        self.system_monitor.show()
                        self.system_monitor.reposition()
                    self.show_greeting()
            self._hotkey_was_down = down
        except Exception:
            pass

    # ==============================================================
    # EXPRESSION
    # ==============================================================

    def change_expression(
        self,
        emotion
    ):

        if emotion not in self.expressions:

            return

        self.current_expression = emotion

        self.current_mood = emotion

        self.update_image()

    def set_bridge_mood(
        self,
        mood
    ):

        mood = str(
            mood
        ).lower()

        valid_moods = [
            "normal",
            "happy",
            "thinking",
            "sad",
            "angry"
        ]

        if mood in valid_moods:

            self.change_expression(
                mood
            )

            # ======================================================
            # BRIDGE HAPPY → NORMAL SAU 8 GIÂY
            # ======================================================

            if mood == "happy":

                self.bridge_happy_timer.start(
                    8000
                )

            else:

                self.bridge_happy_timer.stop()

    # ==============================================================
    # BRIDGE HAPPY → NORMAL
    # ==============================================================

    def return_to_normal(
        self
    ):

        self.change_expression(
            "normal"
        )

    # ==============================================================
    # MOOD VIEW
    # ==============================================================

    def show_current_mood(
        self
    ):

        names = {
            "normal":
                "😐 Bình thường",

            "happy":
                "😊 Vui",

            "thinking":
                "🤔 Đang suy nghĩ",

            "sad":
                "😢 Buồn",

            "angry":
                "😠 Tức giận",

            "love":
                "💗 Yêu"
        }

        mood = names.get(
            self.current_mood,
            self.current_mood
        )

        self.chat_window.text_display.setText(
            "💗 Mood hiện tại\n\n"
            f"Trạng thái: {mood}"
        )

        self.chat_window.show()

        self.chat_window.raise_()

        self.chat_window.activateWindow()

    # ==============================================================
    # UPTIME
    # ==============================================================

    def show_uptime(
        self
    ):

        elapsed = int(
            time.time()
            -
            self.start_time
        )

        days = elapsed // 86400

        hours = (
            elapsed % 86400
        ) // 3600

        minutes = (
            elapsed % 3600
        ) // 60

        seconds = (
            elapsed % 60
        )

        if days:

            text = (
                f"🕐 Monika đã hoạt động:\n\n"
                f"{days} ngày "
                f"{hours} giờ "
                f"{minutes} phút "
                f"{seconds} giây"
            )

        elif hours:

            text = (
                f"🕐 Monika đã hoạt động:\n\n"
                f"{hours} giờ "
                f"{minutes} phút "
                f"{seconds} giây"
            )

        elif minutes:

            text = (
                f"🕐 Monika đã hoạt động:\n\n"
                f"{minutes} phút "
                f"{seconds} giây"
            )

        else:

            text = (
                f"🕐 Monika đã hoạt động:\n\n"
                f"{seconds} giây"
            )

        self.chat_window.text_display.setText(
            text
        )

        self.chat_window.show()

        self.chat_window.raise_()

        self.chat_window.activateWindow()

    # ==============================================================
    # IMAGE
    # ==============================================================

    def update_image(
        self
    ):

        pixmap = self.expressions[
            self.current_expression
        ]
        if pixmap.isNull():
            if hasattr(self, "image_label"):
                self.image_label.setText("💚\nMonika\n\nDouble-click để chat")
                self.image_label.setAlignment(Qt.AlignCenter)
                self.image_label.setStyleSheet("color: #ffb6d5; font-size: 24px; background: transparent;")
            return
        self.image_label.setText("")

        scaled_pixmap = pixmap.scaledToWidth(
            self.current_width,
            Qt.SmoothTransformation
        )

        self.image_label.setPixmap(
            scaled_pixmap
        )

        self.resize(
            scaled_pixmap.size()
        )
        if hasattr(self, "system_monitor"):
            self.system_monitor.reposition()

    def scale_image(
        self,
        factor
    ):

        new_width = int(
            self.current_width
            *
            factor
        )

        if 80 <= new_width <= 800:

            self.current_width = new_width

            self.update_image()

    # ==============================================================
    # CLEANUP
    # ==============================================================

    def hideEvent(self, event):
        if hasattr(self, "system_monitor"):
            self.system_monitor.hide()
        if hasattr(self, "greeting_bubble"):
            self.greeting_bubble.hide()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "system_monitor"):
            self.system_monitor.show()
            self.system_monitor.reposition()

    def closeEvent(
        self,
        event
    ):

        if hasattr(self, "system_monitor"):
            self.system_monitor.close()
        if hasattr(self, "greeting_bubble"):
            self.greeting_bubble.close()

        if hasattr(
            self,
            "bridge"
        ):

            self.bridge.stop()

            self.bridge.wait(
                1000
            )

        event.accept()


# ==============================================================
# MAIN
# ==============================================================

if __name__ == "__main__":

    app = QApplication(sys.argv)
    start_embedded_bridge()
    app.aboutToQuit.connect(stop_embedded_bridge)

    pet = MonikaDesktopPet()
    pet.show()

    try:
        sys.exit(app.exec())
    finally:
        stop_embedded_bridge()
