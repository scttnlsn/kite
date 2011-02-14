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
        return self._get_params()
    
    @property
    @memoized
    def body(self):
        content_length = 0
        try:
            content_length = int(self.environ.get('CONTENT_LENGTH', '0'))
        except ValueError:
            pass
        return self.environ['wsgi.input'].read(content_length)
        
    def _get_params(self):
        if self.method == 'POST' or self.method == 'PUT':
            return self._get_field_storage()
        elif self.method == 'GET' and len(self.environ['QUERY_STRING']):
            return self._get_query_string()
        else:
            return {}
        
    def _get_query_string(self):
        params = {}
        for key, value in cgi.parse_qs(self.environ['QUERY_STRING']).items():
            params[key] = value[0] if len(value) <= 1 else value
        return params
        
    def _get_field_storage(self):
        params = {}
        data = cgi.FieldStorage(fp = StringIO.StringIO(self.body), environ = self.environ)
        for field in data:
            if isinstance(data[field], list):
                params[field] = [item.value for item in data[field]]
            elif data[field].filename:
                params[field] = data[field]
            else:
                params[field] = data[field].value
        return params

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

class Route(object):

    syntax = re.compile(r'<(?P<name>[a-zA-Z_][a-zA-Z_0-9]*):(?P<pattern>[^>]+)>')

    def __init__(self, pattern, handler, method):
        self.handler = handler
        self.method = method
        self.pattern = self._pattern(pattern)
        parts = self._parse(pattern)
        self.regex = self._regex(parts)
        self.url = self._url(parts)
        self.params = self._params(parts)

    def _pattern(self, pattern):
        if not pattern.endswith('/')
            pattern += '/'
        return pattern

    def _regex(self, parts):
        regex = ''
        for part in self._parse(pattern):
            if isinstance(part, basestring):
                regex += part
            elif isinstance(part, dict):
                regex += '(?P<%s>%s)' % (part['name'], part['pattern'])
            else:
                raise TypeError
        return re.compile('^%s$' % regex)

    def _url(self, pattern):
        url = ''
        for part in self._parse(pattern):
            if isinstance(part, basestring):
                url += part
            else:
                url += '%s'
        return url

    def _params(self, pattern):
        params = []
        for part in self._parse(pattern):
            if isinstance(part, dict):
                params += [{'name': part['name'], 'regex': re.compile(part['pattern'])}]
        return params

    @memoized
    def _parse(self, pattern):
        start = end = 0
        parts = []
        for match in self.syntax.finditer(pattern):
            start = match.start()
            parts += [pattern[end:start], match.groupdict()]
            end = match.end()
        return parts + [pattern[end:]]

class Application(object):

    def __init__(self, debug = False, routes = None):
        self.debug = debug
        self.routes = []
        for pattern, handler, method in routes or []:
            self.route(pattern, method)(handler)

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
        if not request.path.endswith('/'):
            request.path += '/'
        status = 404
        for route in self.routes:
            match = route.regex.match(request.path)
            if match:
                status = 405
                if route.method == request.method:
                    return (route.handler, match.groupdict())
        return (lambda request: status_response(status), {})

    def route(self, pattern, method):
        def register(handler):
            route = Route(pattern, handler, method)
            self.routes.append(route)
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
