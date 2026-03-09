import os
import sys
import asyncio
import logging

logging.basicConfig(
    filename='passenger_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s'
)

def make_asgi_scope(environ):
    """Convert WSGI environ to a minimal ASGI HTTP scope."""
    headers = []
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            name = key[5:].replace('_', '-').lower().encode()
            headers.append((name, value.encode()))
        elif key == 'CONTENT_TYPE' and value:
            headers.append((b'content-type', value.encode()))
        elif key == 'CONTENT_LENGTH' and value:
            headers.append((b'content-length', value.encode()))

    return {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': environ.get('SERVER_PROTOCOL', 'HTTP/1.1').split('/')[-1],
        'method': environ.get('REQUEST_METHOD', 'GET').upper(),
        'headers': headers,
        'path': environ.get('PATH_INFO', '/'),
        'query_string': environ.get('QUERY_STRING', '').encode(),
        'root_path': environ.get('SCRIPT_NAME', ''),
        'scheme': environ.get('wsgi.url_scheme', 'https'),
        'server': (environ.get('SERVER_NAME', 'localhost'), int(environ.get('SERVER_PORT', 443))),
        'client': None,
        'extensions': {},
    }


def run_asgi(asgi_app, environ, start_response):
    """
    Custom ASGI-to-WSGI bridge using asyncio directly.
    Avoids a2wsgi's thread-pool which deadlocks in Phusion Passenger.
    """
    scope = make_asgi_scope(environ)

    # Read request body safely
    try:
        content_length = int(environ.get('CONTENT_LENGTH') or 0)
        body = environ['wsgi.input'].read(content_length) if content_length > 0 else b''
    except Exception:
        body = b''

    # Holders for the ASGI response
    response_metadata = {}
    response_chunks = []

    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}

    async def send(message):
        if message['type'] == 'http.response.start':
            response_metadata['status'] = message['status']
            response_metadata['headers'] = [
                (k.decode('latin-1'), v.decode('latin-1'))
                for k, v in message.get('headers', [])
            ]
        elif message['type'] == 'http.response.body':
            chunk = message.get('body', b'')
            if chunk:
                response_chunks.append(chunk)

    # Run the ASGI coroutine in a fresh event loop (avoids threading conflicts)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asgi_app(scope, receive, send))
    finally:
        loop.close()

    status = response_metadata.get('status', 500)
    # Build HTTP status string
    status_strings = {200: '200 OK', 404: '404 Not Found', 500: '500 Internal Server Error'}
    status_str = status_strings.get(status, f'{status} Status')
    headers = response_metadata.get('headers', [('Content-Type', 'text/plain')])
    start_response(status_str, headers)
    return response_chunks


# --- Main Startup ---
try:
    logging.info("--- STARTUP (Custom ASGI Bridge) ---")

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    logging.info("Importing FastAPI app...")
    from app.main import app
    logging.info("FastAPI app imported successfully")

    def application(environ, start_response):
        path = environ.get('PATH_INFO', '')
        method = environ.get('REQUEST_METHOD', 'GET')
        logging.info(f"INCOMING: {method} {path}")

        # Fast internal ping — no ASGI needed
        if path == '/ping':
            logging.info("Serving /ping internally")
            start_response('200 OK', [('Content-Type', 'text/plain')])
            return [b"cPanel is ALIVE!"]

        # Pass all paths through to FastAPI as-is (root deployment)
        try:
            logging.info("Calling custom ASGI bridge...")
            result = run_asgi(app, environ, start_response)
            logging.info(f"Custom ASGI bridge done ({len(result)} chunks)")
            return result
        except Exception as e:
            logging.error(f"ASGI Bridge Error: {e}", exc_info=True)
            start_response('500 Error', [('Content-Type', 'text/plain')])
            return [f"ASGI Error: {e}".encode()]

except Exception as e:
    logging.error(f"FATAL STARTUP: {e}", exc_info=True)
    def application(environ, start_response):
        start_response('500 Error', [('Content-Type', 'text/plain')])
        return [f"FATAL STARTUP: {e}".encode()]
