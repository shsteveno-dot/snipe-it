"""Small S3-shaped HTTP server for the local compose integration test only."""

from hashlib import md5
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from email.utils import formatdate
from xml.sax.saxutils import escape

BUCKETS = {"snipeit-public", "snipeit-private"}
ROOT = Path("/data")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def object_path(self):
        path = unquote(urlsplit(self.path).path)
        parts = path.lstrip("/").split("/", 1)
        if len(parts) != 2 or parts[0] not in BUCKETS:
            return None
        bucket, key = parts
        if not key or any(part in ("", ".", "..") for part in key.split("/")):
            return None
        return ROOT.joinpath(bucket, *key.split("/"))

    def respond(self, code, body=b"", headers=None):
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path == "/_health":
            return self.respond(200, b"ok")
        bucket = request.path.strip("/")
        query = parse_qs(request.query)
        if bucket in BUCKETS and query.get("list-type") == ["2"]:
            prefix = escape(query.get("prefix", [""])[0])
            body = (f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f'<Name>{bucket}</Name><Prefix>{prefix}</Prefix><KeyCount>0</KeyCount>'
                    f'<IsTruncated>false</IsTruncated></ListBucketResult>').encode()
            return self.respond(200, body, {"Content-Type": "application/xml"})
        self.read_object()

    def do_HEAD(self):
        if urlsplit(self.path).path.lstrip("/") in BUCKETS:
            return self.respond(200)
        self.read_object()

    def read_object(self):
        path = self.object_path()
        if path is None or not path.is_file():
            return self.respond(404, b"NoSuchKey")
        body = path.read_bytes()
        self.respond(200, body, {
            "ETag": f'"{md5(body).hexdigest()}"',
            "Last-Modified": formatdate(path.stat().st_mtime, usegmt=True),
            "Content-Type": guess_type(path.name)[0] or "application/octet-stream",
        })

    def do_PUT(self):
        path = self.object_path()
        if path is None:
            return self.respond(404, b"NoSuchBucket")
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        self.respond(200, headers={"ETag": f'"{md5(body).hexdigest()}"'})


ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
