"""audio_track.py against a stand-in account directory, handle resolver and account server (http://127.0.0.1).

Run from C:\\thunderbird-cafe\\audio-tracks:  python -m unittest discover -s test -v
"""
import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

spec = importlib.util.spec_from_file_location('audio_track', Path(__file__).resolve().parents[1] / 'scripts' / 'audio_track.py')
at = importlib.util.module_from_spec(spec)
spec.loader.exec_module(at)

ME = 'did:plc:rqbqpaaluty5v47jwciowpik'          # pyxorium.com (the importer's account)
OTHER = 'did:plc:6vxjigxrqizmbo56gojxico3'       # thunderbird.cafe
PASSWORD = 'abcd-efgh-ijkl-mnop'
SHOW = 'Galactic · Moguls · 1997-08-15'


def track(title, n, album=SHOW, seconds=245, size=2_940_000):
    return {'$type': at.COLLECTION, 'title': title, 'artist': 'Galactic', 'album': album, 'trackNumber': n, 'duration': seconds,
            'audioBlob': {'$type': 'blob', 'ref': {'$link': 'bafkreiaudio'}, 'mimeType': 'audio/webm', 'size': size},
            'fileType': 'webm', 'recording': {'date': '1997-08-15', 'venue': 'Moguls'}, 'createdAt': '2026-11-15T10:00:00.000Z'}


class World:
    """The stand-in network: one server answering for plc.directory, the handle resolver and both accounts' servers."""
    def __init__(self):
        self.records = {
            (ME, at.COLLECTION, '3mzaaa'): {'cid': 'bafyreia', 'value': track('Funky Bird', 3)},
            (ME, at.COLLECTION, '3mzbbb'): {'cid': 'bafyreib', 'value': track('Tchefuncte', 7, seconds=3725, size=44_700_000)},
            (ME, at.COLLECTION, '3mzccc'): {'cid': 'bafyreic', 'value': track('Field recording', 1, album='Creek, April', seconds=61, size=730_000)},
            (OTHER, at.COLLECTION, '3mzddd'): {'cid': 'bafyreid', 'value': track('Not mine', 1)},
        }
        self.calls = []
        self.keep_after_delete = False
        world = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def answer(self, obj, status=200):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.handle_any(None)

            def do_POST(self):
                n = int(self.headers.get('content-length') or 0)
                self.handle_any(json.loads(self.rfile.read(n) or b'{}'))

            def handle_any(self, data):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                world.calls.append((self.command, u.path, q, data, self.headers.get('Authorization')))
                base = f'http://127.0.0.1:{world.port}'
                if u.path.startswith('/plc/'):
                    did = u.path[len('/plc/'):]
                    hd = {ME: 'pyxorium.com', OTHER: 'thunderbird.cafe'}.get(did)
                    if not hd:
                        return self.answer({'message': 'DID not registered'}, 404)
                    return self.answer({'id': did, 'alsoKnownAs': [f'at://{hd}'], 'service': [{'id': '#atproto_pds', 'type': 'AtprotoPersonalDataServer', 'serviceEndpoint': f'{base}/pds'}]})
                name = u.path.rsplit('/', 1)[-1]
                if name == 'com.atproto.identity.resolveHandle':
                    did = {'pyxorium.com': ME, 'thunderbird.cafe': OTHER}.get(q.get('handle'))
                    return self.answer({'did': did}) if did else self.answer({'error': 'InvalidRequest', 'message': 'Unable to resolve handle'}, 400)
                if name == 'com.atproto.server.createSession':
                    if data.get('password') != PASSWORD:
                        return self.answer({'error': 'AuthenticationRequired', 'message': 'Invalid identifier or password'}, 401)
                    return self.answer({'did': data['identifier'], 'accessJwt': 'jwt-' + data['identifier']})
                if name == 'com.atproto.repo.getRecord':
                    r = world.records.get((q['repo'], q['collection'], q['rkey']))
                    if not r:
                        return self.answer({'error': 'RecordNotFound', 'message': 'Could not locate record'}, 400)
                    return self.answer({'uri': f"at://{q['repo']}/{q['collection']}/{q['rkey']}", **r})
                if name == 'com.atproto.repo.listRecords':
                    keys = sorted([k for k in world.records if k[0] == q['repo'] and k[1] == q['collection']], key=lambda k: k[2], reverse=True)
                    start = int(q.get('cursor') or 0)
                    limit = int(q.get('limit') or 50)
                    page = keys[start:start + min(limit, 2)]      # small pages, to walk the cursor
                    more = start + len(page) < len(keys)
                    out = {'records': [{'uri': f'at://{k[0]}/{k[1]}/{k[2]}', **world.records[k]} for k in page]}
                    if more:
                        out['cursor'] = str(start + len(page))
                    return self.answer(out)
                if name == 'com.atproto.repo.deleteRecord':
                    if self.headers.get('Authorization') != f"Bearer jwt-{data['repo']}":
                        return self.answer({'error': 'AuthRequired'}, 401)
                    if not world.keep_after_delete:
                        world.records.pop((data['repo'], data['collection'], data['rkey']), None)
                    return self.answer({})
                return self.answer({'error': 'NotFound'}, 404)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class AudioTrackTest(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.saved = (at.PLC_DIRECTORY, at.HANDLE_RESOLVER)
        at.PLC_DIRECTORY = f'http://127.0.0.1:{self.w.port}/plc'
        at.HANDLE_RESOLVER = f'http://127.0.0.1:{self.w.port}'
        self.env = {'BSKY_APP_PASSWORD': PASSWORD}

    def tearDown(self):
        at.PLC_DIRECTORY, at.HANDLE_RESOLVER = self.saved
        self.w.close()

    def args(self, argv):
        return at.parser().parse_args(argv)

    def run_quiet(self, fn, *a, **kw):
        lines = []
        result = fn(*a, out=lambda s='': lines.append(str(s)), **kw)
        return result, '\n'.join(lines)

    def mine(self):
        return sorted(k[2] for k in self.w.records if k[0] == ME and k[1] == at.COLLECTION)

    def writes(self):
        return [c for c in self.w.calls if c[0] == 'POST' and c[1].endswith('deleteRecord')]

    def test_list_walks_every_page_and_groups_by_album(self):
        tracks, said = self.run_quiet(at.show_list, self.args(['list']))
        self.assertEqual(sorted(at.rkey_of(t) for t in tracks), ['3mzaaa', '3mzbbb', '3mzccc'], 'all pages, only pyxorium.com\'s')
        self.assertIn('Audio tracks by @pyxorium.com', said)
        self.assertIn(f'  {SHOW}', said)
        self.assertIn('  Creek, April', said)
        self.assertIn('7. Tchefuncte · Galactic  (1:02:05, 44.7 MB, webm)', said)
        self.assertIn('3. Funky Bird · Galactic  (4:05, 2.9 MB, webm)', said)
        self.assertIn('audio 48.4 MB', said)
        self.assertEqual(self.writes(), [])

    def test_list_one_album_and_another_account(self):
        tracks, said = self.run_quiet(at.show_list, self.args(['list', '--album', 'Creek, April']))
        self.assertEqual([at.rkey_of(t) for t in tracks], ['3mzccc'])
        self.assertIn('in "Creek, April": 1', said)
        tracks, _ = self.run_quiet(at.show_list, self.args(['list', '--handle', 'thunderbird.cafe']))
        self.assertEqual([at.rkey_of(t) for t in tracks], ['3mzddd'])

    def test_a_dry_run_deletes_nothing_and_needs_no_password(self):
        _, said = self.run_quiet(at.delete, self.args(['delete', '--album', SHOW, '--dry-run']), env={}, ask=lambda q: self.fail('no question'))
        self.assertIn('2 audio tracks by @pyxorium.com (audio 47.6 MB)', said)
        self.assertIn('Dry run: nothing was deleted.', said)
        self.assertEqual(self.mine(), ['3mzaaa', '3mzbbb', '3mzccc'])
        self.assertEqual(self.writes(), [])

    def test_delete_by_keys_after_asking_and_reads_back(self):
        gone, said = self.run_quiet(at.delete, self.args(['delete', '--rkey', '3mzaaa', '--rkey', '3mzccc']), env=self.env, ask=lambda q: 'y')
        self.assertEqual(gone, ['3mzaaa', '3mzccc'])
        self.assertEqual(self.mine(), ['3mzbbb'])
        self.assertIn('Deleted 2 (they no longer read back).', said)
        for c in self.writes():
            self.assertEqual(c[3]['collection'], at.COLLECTION)
            self.assertEqual(c[3]['repo'], ME)
            self.assertEqual(c[4], f'Bearer jwt-{ME}')

    def test_delete_a_whole_album(self):
        gone, _ = self.run_quiet(at.delete, self.args(['delete', '--album', SHOW]), env=self.env, ask=lambda q: 'yes')
        self.assertEqual(sorted(gone), ['3mzaaa', '3mzbbb'])
        self.assertEqual(self.mine(), ['3mzccc'])

    def test_no_stops_before_deleting(self):
        gone, said = self.run_quiet(at.delete, self.args(['delete', '--rkey', '3mzaaa']), env=self.env, ask=lambda q: 'n')
        self.assertEqual(gone, [])
        self.assertIn('Stopped; nothing was deleted.', said)
        self.assertEqual(self.writes(), [])

    def test_mistakes_stop_with_a_plain_message(self):
        cases = [
            (['delete'], 'Say which tracks'),
            (['delete', '--rkey', '3mzaaa', '--album', SHOW], 'not both'),
            (['delete', '--rkey', 'not a key!'], 'is not a record key'),
            (['delete', '--rkey', '3mzzzz'], 'has no audio track with the key 3mzzzz'),
            (['delete', '--album', 'Nothing here'], 'has no tracks in "Nothing here"'),
            (['list', '--handle', 'nobody.example'], "Couldn't find the account @nobody.example"),
        ]
        for argv, words in cases:
            with self.subTest(argv=argv):
                fn = at.delete if argv[0] == 'delete' else at.show_list
                with self.assertRaises(at.Stop) as caught:
                    self.run_quiet(fn, self.args(argv), env=self.env)
                self.assertIn(words, str(caught.exception))
        self.assertEqual(self.writes(), [])

    def test_no_password_wrong_password_or_another_accounts(self):
        with self.assertRaises(at.Stop) as caught:
            self.run_quiet(at.delete, self.args(['delete', '--rkey', '3mzaaa']), env={}, ask=lambda q: 'y')
        self.assertIn('Read-Host "App password"', str(caught.exception))
        with self.assertRaises(at.Stop) as caught:
            self.run_quiet(at.delete, self.args(['delete', '--rkey', '3mzaaa']), env={'BSKY_APP_PASSWORD': 'wrong'}, ask=lambda q: 'y')
        self.assertIn('Invalid identifier or password', str(caught.exception))
        self.assertEqual(self.mine(), ['3mzaaa', '3mzbbb', '3mzccc'])

    def test_a_record_that_still_reads_back_is_reported(self):
        self.w.keep_after_delete = True
        with self.assertRaises(at.Stop) as caught:
            self.run_quiet(at.delete, self.args(['delete', '--rkey', '3mzaaa']), env=self.env, ask=lambda q: 'y')
        self.assertIn('still reads back', str(caught.exception))

    def test_https_only(self):
        with self.assertRaises(at.Stop):
            at.http_json('http://example.com/xrpc/x')

    def test_clock(self):
        self.assertEqual([at.clock(5), at.clock(245), at.clock(3725), at.clock(None), at.clock(True)], ['0:05', '4:05', '1:02:05', '', ''])


if __name__ == '__main__':
    unittest.main()
