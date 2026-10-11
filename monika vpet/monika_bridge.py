import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8765

state = {
    "message": "",
    "mood": "normal",
    "source": "bridge",
    "timestamp": 0
}

state_lock = threading.Lock()


class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print("[Bridge]", format % args)

    def send_json(self, status_code, data):
        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status_code)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):

        if self.path == "/":

            self.send_json(
                200,
                {
                    "status": "ok",
                    "service": "Monika Bridge",
                    "port": PORT
                }
            )

            return

        if self.path == "/status":

            with state_lock:
                current_state = dict(state)

            self.send_json(
                200,
                current_state
            )

            return

        self.send_json(
            404,
            {
                "error": "Not found"
            }
        )

    def do_POST(self):

        if self.path != "/event":

            self.send_json(
                404,
                {
                    "error": "Not found"
                }
            )

            return

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            raw_data = self.rfile.read(
                content_length
            )

            data = json.loads(
                raw_data.decode("utf-8")
            )

            message = data.get(
                "message",
                ""
            )

            mood = data.get(
                "mood",
                "normal"
            )

            source = data.get(
                "source",
                "unknown"
            )

            timestamp = data.get(
                "timestamp",
                0
            )

            with state_lock:

                state["message"] = str(
                    message
                )

                state["mood"] = str(
                    mood
                )

                state["source"] = str(
                    source
                )

                state["timestamp"] = timestamp

            print()
            print("================================")
            print(" Bridge nhận dữ liệu")
            print("================================")
            print("Message:", message)
            print("Mood   :", mood)
            print("Source :", source)
            print("================================")
            print()

            self.send_json(
                200,
                {
                    "status": "received"
                }
            )

        except Exception as e:

            print(
                "[Bridge ERROR]",
                repr(e)
            )

            self.send_json(
                400,
                {
                    "status": "error",
                    "error": str(e)
                }
            )


def main():

    server = ThreadingHTTPServer(
        (HOST, PORT),
        BridgeHandler
    )

    print()
    print("======================================")
    print("       MONIKA DESKTOP BRIDGE")
    print("======================================")
    print()
    print(
        f"Bridge đang chạy tại "
        f"http://{HOST}:{PORT}"
    )
    print()
    print("GET  /status")
    print("POST /event")
    print()
    print("Đang chờ MAS / Desktop...")
    print()
    print("Nhấn Ctrl+C để thoát.")
    print()

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print()
        print("Đang đóng Bridge...")

    finally:

        server.server_close()


if __name__ == "__main__":
    main()