import argparse
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "output" / "frontend" / "map_bundle.json"


class BundleStore:
    def __init__(self, bundle_path: Path):
        self.bundle_path = bundle_path
        self._mtime = None
        self._data = None

    def load(self):
        if not self.bundle_path.exists():
            raise FileNotFoundError(
                f"Bundle not found: {self.bundle_path}. Run: python scripts/export_map_frontend_payload.py"
            )

        mtime = self.bundle_path.stat().st_mtime
        if self._data is None or self._mtime != mtime:
            self._data = json.loads(self.bundle_path.read_text(encoding="utf-8"))
            self._mtime = mtime
        return self._data


def json_response(handler: BaseHTTPRequestHandler, status: int, body: dict, allow_origin: str):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Access-Control-Allow-Origin", allow_origin)
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.end_headers()
    handler.wfile.write(payload)


def create_handler(store: BundleStore, allow_origin: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A003
            # Keep logs concise for local dev.
            print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))

        def do_OPTIONS(self):
            json_response(self, 200, {"ok": True}, allow_origin)

        def do_GET(self):
            try:
                bundle = store.load()
            except FileNotFoundError as e:
                json_response(
                    self,
                    500,
                    {
                        "error": "bundle_missing",
                        "message": str(e),
                    },
                    allow_origin,
                )
                return
            except json.JSONDecodeError as e:
                json_response(
                    self,
                    500,
                    {
                        "error": "bundle_invalid_json",
                        "message": str(e),
                    },
                    allow_origin,
                )
                return

            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
            segments = [unquote(s) for s in path.split("/") if s]

            if path == "/":
                json_response(
                    self,
                    200,
                    {
                        "service": "au-health-map-api",
                        "now": datetime.now(timezone.utc).isoformat(),
                        "endpoints": [
                            "/health",
                            "/api/map",
                            "/api/map/summary",
                            "/api/map/lanes",
                            "/api/map/branches",
                            "/api/map/lines",
                            "/api/map/lines/{lineId}",
                            "/api/map/lines/{lineId}/details",
                            "/api/map/lines/{lineId}/datasets",
                        ],
                    },
                    allow_origin,
                )
                return

            if path == "/health":
                summary = bundle.get("summary", {})
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "bundlePath": str(store.bundle_path),
                        "summary": summary,
                        "bundleGeneratedAt": bundle.get("generatedAt"),
                    },
                    allow_origin,
                )
                return

            if path == "/api/map":
                json_response(self, 200, bundle, allow_origin)
                return

            if path == "/api/map/summary":
                json_response(
                    self,
                    200,
                    {
                        "generatedAt": bundle.get("generatedAt"),
                        "summary": bundle.get("summary", {}),
                    },
                    allow_origin,
                )
                return

            if path == "/api/map/lanes":
                json_response(self, 200, {"lanes": bundle.get("lanes", [])}, allow_origin)
                return

            if path == "/api/map/branches":
                json_response(self, 200, {"branches": bundle.get("branches", [])}, allow_origin)
                return

            if path == "/api/map/lines":
                lines = bundle.get("lines", [])
                line_index = [
                    {
                        "lineId": l.get("lineId"),
                        "lineName": l.get("lineName"),
                        "stepCount": l.get("stepCount"),
                        "custodianId": l.get("custodianId"),
                        "custodianName": l.get("custodianName"),
                    }
                    for l in lines
                ]
                json_response(self, 200, {"lines": line_index}, allow_origin)
                return

            # /api/map/lines/{lineId}
            # /api/map/lines/{lineId}/details
            # /api/map/lines/{lineId}/datasets
            if len(segments) >= 4 and segments[:3] == ["api", "map", "lines"]:
                line_id = segments[3]
                lines = bundle.get("lines", [])
                line = next((x for x in lines if x.get("lineId") == line_id), None)
                if line is None:
                    json_response(
                        self,
                        404,
                        {"error": "line_not_found", "lineId": line_id},
                        allow_origin,
                    )
                    return

                if len(segments) == 4:
                    json_response(self, 200, line, allow_origin)
                    return

                if len(segments) == 5 and segments[4] == "details":
                    details = line.get("details", {})
                    json_response(
                        self,
                        200,
                        {
                            "lineId": line.get("lineId"),
                            "lineName": line.get("lineName"),
                            "details": details,
                        },
                        allow_origin,
                    )
                    return

                if len(segments) == 5 and segments[4] == "datasets":
                    json_response(
                        self,
                        200,
                        {
                            "lineId": line.get("lineId"),
                            "lineName": line.get("lineName"),
                            "datasets": line.get("datasets", []),
                        },
                        allow_origin,
                    )
                    return

            json_response(
                self,
                404,
                {
                    "error": "not_found",
                    "path": path,
                },
                allow_origin,
            )

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Serve AU health map bundle as a local JSON API")
    parser.add_argument("--host", default=os.environ.get("MAP_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MAP_API_PORT", "8787")))
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--allow-origin", default=os.environ.get("MAP_API_ALLOW_ORIGIN", "*"))
    args = parser.parse_args()

    bundle_path = Path(args.bundle).resolve()
    store = BundleStore(bundle_path)
    handler_cls = create_handler(store, args.allow_origin)
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)

    print(f"Serving map API at http://{args.host}:{args.port}")
    print(f"Bundle: {bundle_path}")
    print("Try: /health, /api/map/summary, /api/map/lines")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
