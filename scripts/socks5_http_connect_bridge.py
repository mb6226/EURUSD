import select
import socket
import socketserver

SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 10808
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 18080


def recv_exact(sock, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = sock.recv(size - len(chunks))
        if not part:
            raise ConnectionError("SOCKS proxy closed connection")
        chunks.extend(part)
    return bytes(chunks)


class ConnectBridge(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        upstream = None
        try:
            client.settimeout(15)
            request = bytearray()
            while b"\r\n\r\n" not in request and len(request) < 16384:
                chunk = client.recv(4096)
                if not chunk:
                    return
                request.extend(chunk)
            first = bytes(request).split(b"\r\n", 1)[0].decode("ascii", "replace")
            parts = first.split()
            if len(parts) < 3 or parts[0].upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                return
            host, port_text = parts[1].rsplit(":", 1)
            port = int(port_text)
            host_bytes = host.encode("idna")
            if len(host_bytes) > 255:
                raise ValueError("Host name too long")

            upstream = socket.create_connection((SOCKS_HOST, SOCKS_PORT), timeout=15)
            upstream.sendall(b"\x05\x01\x00")
            if recv_exact(upstream, 2) != b"\x05\x00":
                raise ConnectionError("SOCKS5 proxy rejected no-auth mode")
            upstream.sendall(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + port.to_bytes(2, "big"))
            reply = recv_exact(upstream, 4)
            if reply[0] != 5 or reply[1] != 0:
                raise ConnectionError("SOCKS5 connect failed, code=" + str(reply[1]))
            atyp = reply[3]
            if atyp == 1:
                recv_exact(upstream, 4)
            elif atyp == 3:
                recv_exact(upstream, recv_exact(upstream, 1)[0])
            elif atyp == 4:
                recv_exact(upstream, 16)
            recv_exact(upstream, 2)

            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.settimeout(None)
            upstream.settimeout(None)
            sockets = [client, upstream]
            while True:
                readable, _, exceptional = select.select(sockets, [], sockets, 60)
                if exceptional or not readable:
                    break
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    target = upstream if source is client else client
                    target.sendall(data)
        except Exception as exc:
            try:
                client.sendall(("HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nX-Bridge-Error: " + str(exc).replace("\r", " ").replace("\n", " ") + "\r\n\r\n").encode("ascii", "replace"))
            except Exception:
                pass
        finally:
            if upstream is not None:
                upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server((LISTEN_HOST, LISTEN_PORT), ConnectBridge) as server:
        print(f"Loopback HTTP CONNECT bridge listening on {LISTEN_HOST}:{LISTEN_PORT}; SOCKS5 upstream {SOCKS_HOST}:{SOCKS_PORT}", flush=True)
        server.serve_forever()
