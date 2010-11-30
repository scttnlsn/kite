import cgi
import re
import StringIO
import traceback

STATUS_CODES = {
    100: 'Continue',
    101: 'Switching Protocols',
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary Redirect',
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Time-out',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Request Entity Too Large',
    414: 'Request-URI Too Large',
    415: 'Unsupported Media Type',
    416: 'Requested range not satisfiable',
    417: 'Expectation Failed',
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Time-out',
    505: 'HTTP Version not supported',
}

class memoized(object):
    
    def __init__(self, func):
        self.func = func
        self.called = False
        self.value = None
        
    def __call__(self, instance):
        if not self.called:
            self.value = self.func(instance)
            self.called = True
        return self.value

class Request(object):

    def __init__(self, environ):
        self.environ = environ
        self.method = environ['REQUEST_METHOD'].upper()
        self.path = environ['PATH_INFO']
    
    @property
    @memoized
    def params(self):
        return self.get_params()
    
    @property
    @memoized
    def body(self):
        content_length = 0
        try:
            content_length = int(self.environ.get('CONTENT_LENGTH', '0'))
        except ValueError:
            pass
        return self.environ['wsgi.input'].read(content_length)
        
    def get_params(self):
        if self.method == 'POST' or self.method == 'PUT':
            return cgi.FieldStorage(fp = StringIO.StringIO(self.body), environ = self.environ)
        elif self.method == 'GET' and len(self.environ['QUERY_STRING']):
            return cgi.parse_qs(self.environ['QUERY_STRING'])
        else:
            return {}

class Response(object):

    def __init__(self, content = '', headers = None, status = 200):
        self.content = content
        self.headers = headers
        self.status = status

    @property
    def content(self):
        return self._content

    @content.setter
    def content(self, content):
        if isinstance(content, unicode):
            content = content.encode('utf8')
        self._content = content

    @property
    def headers(self):
        return self._headers

    @headers.setter
    def headers(self, headers):
        headers = headers or {}
        if not 'content-type' in map(str.lower, headers):
            headers['Content-Type'] = 'text/html'
        self._headers = headers

    @property
    def status(self):
        return '%s %s' % (self._status, STATUS_CODES[self._status])

    @status.setter
    def status(self, status):
        if status not in STATUS_CODES:
            status = 500
        self._status = status

    def __call__(self, start_response):
        start_response(self.status, self.headers.items())
        return [self.content]

class Application(object):

    def __init__(self, debug = False, routes = None):
        self.debug = debug
        self.routes = []
        for url, handler, method in routes or []:
            self.route(url, method)(handler)

    def __call__(self, environ, start_response):
        request = Request(environ)
        handler, kwargs = self.match(request)
        try:
            response = handler(request, **kwargs)
        except Exception, e:
            response = status_response(500)
            if self.debug:
                trace = '<pre>%s</pre>' % traceback.format_exc()
                response.content += trace
        if isinstance(response, basestring):
            response = Response(response)
        return response(start_response)

    def match(self, request):
        status = 404
        for regex, handler, method in self.routes:
            match = regex.match(request.path)
            if match:
                status = 405
                if method == request.method:
                    return (handler, match.groupdict())
        return (lambda request: status_response(status), {})

    def route(self, url, method):
        if not url.endswith('/'):
            url += '/'
        regex = re.compile('^%s$' % url)
        def register(handler):
            self.routes.append((regex, handler, method))
            return handler
        return register

    def get(self, url):
        return self.route(url, 'GET')

    def post(self, url):
        return self.route(url, 'POST')

    def put(self, url):
        return self.route(url, 'PUT')

    def delete(self, url):
        return self.route(url, 'DELETE')

    def run(self, host = 'localhost', port = 8000):
        from wsgiref.simple_server import make_server
        make_server(host, port, self).serve_forever()

def redirect(location):
    return Response(
        headers = {'Location': location},
        status = 301)

def status_response(status):
    response = Response(status = status)
    response.content = '<h1>%s</h1>' % response.status
    return response
