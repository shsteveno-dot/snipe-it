import http.server
import json
import socketserver
import threading

messages = []


class SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 closure SMTP fixture\r\n")
        recipient = sender = None
        while line := self.rfile.readline():
            command = line.decode(errors="replace").strip()
            verb = command.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                self.wfile.write(b"250-closure\r\n250 8BITMIME\r\n")
            elif verb == "MAIL":
                sender = command
                self.wfile.write(b"250 OK\r\n")
            elif verb == "RCPT":
                recipient = command
                self.wfile.write(b"250 OK\r\n")
            elif verb == "DATA":
                self.wfile.write(b"354 End with dot\r\n")
                data = []
                while (part := self.rfile.readline()) not in (b".\r\n", b""):
                    data.append(part)
                messages.append({"sender": sender, "recipient": recipient, "data": b"".join(data).decode(errors="replace")})
                self.wfile.write(b"250 Stored\r\n")
            elif verb == "QUIT":
                self.wfile.write(b"221 Bye\r\n")
                break
            else:
                self.wfile.write(b"250 OK\r\n")


class HTTP(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        content = json.dumps(messages).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(content)


smtp = socketserver.ThreadingTCPServer(("0.0.0.0", 1025), SMTP)
threading.Thread(target=smtp.serve_forever, daemon=True).start()
http.server.ThreadingHTTPServer(("0.0.0.0", 8025), HTTP).serve_forever()
