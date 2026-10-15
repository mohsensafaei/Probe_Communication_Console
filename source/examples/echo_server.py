"""A local byte-exact echo server for testing Probe Client or Proxy."""
import socketserver
class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data=self.request.recv(65536)
            if not data:break
            self.request.sendall(data)
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
if __name__=="__main__":
    with Server(("127.0.0.1",9000),Echo) as server:
        print("Echo server: 127.0.0.1:9000 · Ctrl+C to stop")
        try:server.serve_forever()
        except KeyboardInterrupt:pass
