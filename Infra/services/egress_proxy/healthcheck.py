import socket, sys
try:
    socket.create_connection(('localhost', 3128), 2).close()
    sys.exit(0)
except Exception:
    sys.exit(1)
