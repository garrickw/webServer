"""A wsgi webserver using selectors, which is provided by python3"""

import selectors
import socket
from io import StringIO
import sys
from wsgiref.handlers import format_date_time
from time import time

class Server(object):

    def __init__(self, server_address):

        # create socket
        self._sock = sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(0)
        sock.bind(server_address)
        sock.listen(1024)

        # create DefaultSelector
        self._selector = selectors.DefaultSelector()

        host, port = sock.getsockname()[:2]
        self.server_name = socket.getfqdn(host)
        self.server_port = port
        self.headers_set = []

        self.fd_to_connection = {}
        self.results = {}

    def serve_forever(self):
        """start the server"""
        selector = self._selector
        # register the server sock to accept new connections
        selector.register(self._sock.fileno(), selectors.EVENT_READ, self._accept)
        self.fd_to_connection[self._sock.fileno()] = self._sock

        while True:
            events = selector.select(1)  # 1s timeout
            for key, mask in events:
                callback = key.data
                callback(key.fd, mask)

    def _accept(self, fd, mask):
        sock = self.fd_to_connection[fd]
        connection, client_address = sock.accept()
        self.fd_to_connection[connection.fileno()] = connection
        connection.setblocking(0)
        self._selector.register(
                        connection.fileno(),
                        selectors.EVENT_READ,
                        self._handle_one_request
                        )

    def set_app(self, application):
        self.application = application

    def _handle_one_request(self, fd, mask):
        sock = self.fd_to_connection[fd]
        self._selector.unregister(fd)

        # get request
        self.request_data = request_data = sock.recv(1024)
        # read nothing , disconneting it
        if not request_data:
            self._selector.unregister(fd)
            del self.fd_to_connection[fd]
            sock.close()

        # print the request information from client
        print(''.join(
            '<{line}\n'.format(line=line)
            for line in request_data.splitlines()
            ))

        self._parse_request(request_data)
        env = self._get_environ()
        self.results[fd] = self.application(env, self._start_response)

        # register wirtable
        self._selector.register(fd, selectors.EVENT_WRITE, self._finish_response)

    def _parse_request(self, text):
        request_line = text.splitlines()[0]
        #request_line = request_line.rstrip('\r\n')
        data = request_line.split()
        self.request_method, self.path, self.request_version = data

    def _get_environ(self):
        env = {}
        env['wsgi.version']      = (1, 0)
        env['wsgi.url_scheme']   = 'http'
        env['wsgi.input']        = StringIO(str(self.request_data))
        env['wsgi.errors']       = sys.stderr
        env['wsgi.multithread']  = False
        env['wsgi.multiprocess'] = False
        env['wsgi.run_once']     = False

        # Required CGI variables
        env['REQUEST_METHOD']    = self.request_method
        env['PATH_INFO']         = self.path
        env['SERVER_NAME']       = self.server_name
        env['SERVER_PORT']       = str(self.server_port)
        return env

    def _start_response(self, status, response_headers, exc_info=None):
        server_headers = [
                ('Date', str(format_date_time(time()))),
                ('Server', 'WSGIServer 0.2'),
                ]

        self.headers_set = [status, response_headers + server_headers]

    def _finish_response(self, fd, mask):
        try:
            sock = self.fd_to_connection[fd]
            status, response_headers = self.headers_set
            response = 'HTTP/1.1 {status}\r\n'.format(status=status)
            for header in response_headers:
                response += '{0}:{1}\r\n'.format(*header)
            response += '\r\n'
            for data in self.results[fd]:
                response += data

            print(''.join(
                '>{line}\n'.format(line=line)
                for line in response.splitlines()
                ))
            sock.sendall(response.encode("utf8"))
        finally:
            self._selector.unregister(fd)
            del self.fd_to_connection[fd]
            sock.close()


def make_server(server_address, application):
    server = Server(server_address)
    server.set_app(application)
    return server

SERVER_ADDRESS = (HOST, PORT) = ("", 8888)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('Provide a WSGI application object as module:callable')
    app_path = sys.argv[1]
    module, application = app_path.split(':')
    module = __import__(module)
    application = getattr(module, application)
    httpd = make_server(SERVER_ADDRESS, application)
    print('WSGIServer: Serving HTTP on port {port}...\n'.format(port=PORT))
    httpd.serve_forever()
