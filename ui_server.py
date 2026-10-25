"""Local UI adapter. Run: python ui_server.py"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json
import mimetypes
import uuid

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        # Serve only public assets, never project source or environment files.
        from urllib.parse import unquote
        path = unquote(path)
        if path in ('/', '/index.html'):
            target = ROOT / 'frontend' / 'index.html'
        elif path in ('/app.js', '/style.css'):
            target = ROOT / 'frontend' / path[1:]
        elif path.startswith(('/Animal_PNGS/', '/outputs/')) and path.endswith('.png'):
            target = (ROOT / path.lstrip('/')).resolve()
            if not any(target.is_relative_to(ROOT / folder) for folder in ('Animal_PNGS', 'outputs')):
                self.send_error(403)
                return
        else:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(target)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != '/api/create':
            self.send_error(404)
            return
        if self.headers.get('Origin') not in (None, f'http://{self.headers.get("Host")}'):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16000:
                raise ValueError('Request is empty or too large.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object.')
            import logic
            prompt = body.get('prompt', '')
            if not isinstance(prompt, str):
                raise ValueError('Description must be text.')
            request = None if body.get('mode') == 'prompt' else body.get('request')
            if body.get('mode') != 'prompt' and not isinstance(request, dict):
                raise ValueError('Select the creature parts first.')
            output = ROOT / 'outputs' / f'ui_{uuid.uuid4().hex}.png'
            result = logic.generate_creature(prompt, output_path=output, request=request)
            self.send_json(200, {'image': '/outputs/' + output.name,
                                 'warnings': result.plan.warnings,
                                 'request': result.request.model_dump(mode='json')})
        except ImportError:
            self.send_json(503, {'error': 'Install the Python dependencies: python -m pip install -r requirements.txt'})
        except (ValueError, TypeError, OSError) as exc:
            self.send_json(400, {'error': str(exc)})
        except RuntimeError as exc:
            # Report known configuration errors without exposing provider payloads
            # or credentials. Follow the cause chain rather than returning raw errors.
            cause = exc
            authentication_failed = False
            while cause is not None:
                if type(cause).__name__ == 'AuthenticationError':
                    authentication_failed = True
                cause = cause.__cause__
            message = (
                'Google rejected the configured Gemini API key. Update the local .env '
                'with a valid key, check GOOGLE_API_KEY (which takes priority over '
                'GEMINI_API_KEY), and restart the server. You can still use Mix the parts.'
                if authentication_failed else
                'Gemini could not complete this request. Check the server terminal '
                'for configuration or classification errors, or use Mix the parts.'
            )
            if str(exc).startswith(("Gemini classification failed (", "Gemini's classification still broke", "Gemini returned no", "Gemini did not complete")):
                message = str(exc)
                print(message, flush=True)
            self.send_json(502, {'error': message})
        except Exception:
            self.send_json(502, {'error': 'Generation failed. Check your server terminal and Gemini configuration, or try the Parts builder.'})
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    print('Monster Mash: http://127.0.0.1:8000 (Ctrl+C to stop)')
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
