from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging

log = logging.getLogger("heidi.health")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress health check logs to reduce noise
        pass

def start_health_server(port=8000):  # Default to 8000 for Koyeb
    """Start a simple health check server in background"""
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"✅ Health server started on port {port}")
    return server
