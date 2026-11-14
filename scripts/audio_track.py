"""List and delete audio tracks (cafe.thunderbird.audio.track records) in your own atproto account.

claude/mixtape-3b-importer-notes.md, R3b-12. The Web Tile Foundry's importer writes these records; this script is for
looking at them and clearing out test imports. Standard library only: nothing to install. Run it from VS Code's
terminal in C:\\thunderbird-cafe\\audio-tracks:

    python scripts/audio_track.py list [--album "..."]
    python scripts/audio_track.py delete --rkey ... [--rkey ...] [--dry-run]
    python scripts/audio_track.py delete --album "..." [--dry-run]

Add --handle thunderbird.cafe (or a DID) to any of them for another account; the default is pyxorium.com, where the
importer keeps its songs.

Deleting needs an app password for that account, taken from $env:BSKY_APP_PASSWORD (one per task, deleted after):

    $env:BSKY_APP_PASSWORD = Read-Host "App password"

Listing and dry runs need none. Deleting a track removes its record; its audio file is no longer used by it, and the
account's server lets go of files that no record uses. Tapes made from a track keep their own copy of the song.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

COLLECTION = 'cafe.thunderbird.audio.track'
DEFAULT_HANDLE = 'pyxorium.com'
HANDLE_RESOLVER = 'https://public.api.bsky.app'
PLC_DIRECTORY = 'https://plc.directory'
TIMEOUT = 20
MOST = 5000                                        # list at most this many tracks
USER_AGENT = 'audio_track.py (github.com/pyxorium/audio-tracks)'

DID_RE = re.compile(r'^did:(plc:[a-z2-7]{24}|web:[a-zA-Z0-9.%:-]+)$')
HANDLE_RE = re.compile(r'^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$')
RKEY_RE = re.compile(r'^[A-Za-z0-9._~:-]{1,512}$')


class Stop(Exception):
    """Something to tell the person, then stop (no traceback)."""


# ---------- the network ----------

def _check_url(url):
    u = urllib.parse.urlparse(url)
    # https only; plain http just for a stand-in server on this computer (the tests)
    if u.scheme == 'https' or (u.scheme == 'http' and u.hostname == '127.0.0.1'):
        return
    raise Stop(f'Refusing to talk to {url}: https only.')


def http_json(url, data=None, token=None):
    """GET (or POST when data is given) a JSON answer. Raises Stop with the server's message on an error."""
    _check_url(url)
    headers = {'Accept': 'application/json', 'User-Agent': USER_AGENT}
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, data=body, headers=headers, method='POST' if body is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            text = res.read().decode('utf-8')
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as err:
        try:
            answer = json.loads(err.read().decode('utf-8'))
        except Exception:
            answer = {}
        finally:
            err.close()
        e = Stop(answer.get('message') or answer.get('error') or f'{err.code} {err.reason}')
        e.status, e.error = err.code, answer.get('error')
        raise e
    except urllib.error.URLError as err:
        raise Stop(f"Couldn't reach {urllib.parse.urlparse(url).hostname}: {err.reason}")


def xrpc(base, nsid, params=None, data=None, token=None):
    url = f'{base}/xrpc/{nsid}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    return http_json(url, data=data, token=token)


# ---------- the account ----------

def resolve_did(actor):
    """A handle (or a DID) -> its DID."""
    actor = actor.strip().lstrip('@').lower() if not actor.startswith('did:') else actor.strip()
    if DID_RE.match(actor):
        return actor
    if not HANDLE_RE.match(actor):
        raise Stop(f'"{actor}" is neither a handle nor a DID.')
    try:
        did = xrpc(HANDLE_RESOLVER, 'com.atproto.identity.resolveHandle', {'handle': actor}).get('did')
    except Stop as err:
        raise Stop(f"Couldn't find the account @{actor} ({err}).")
    if not isinstance(did, str) or not DID_RE.match(did):
        raise Stop(f"Couldn't find the account @{actor}.")
    return did


def account(did):
    """A DID -> {'did', 'handle', 'pds'} from its DID document."""
    if did.startswith('did:plc:'):
        doc = http_json(f'{PLC_DIRECTORY}/{did}')
    else:
        host = urllib.parse.unquote(did[len('did:web:'):])
        doc = http_json(f'https://{host}/.well-known/did.json')
    if doc.get('id') != did:
        raise Stop(f"The account document for {did} doesn't match it.")
    pds = next((s.get('serviceEndpoint') for s in doc.get('service', [])
                if s.get('id') in ('#atproto_pds', f'{did}#atproto_pds') or s.get('type') == 'AtprotoPersonalDataServer'), None)
    if not isinstance(pds, str):
        raise Stop(f'The account {did} names no server.')
    handle = next((a[5:] for a in doc.get('alsoKnownAs', []) if isinstance(a, str) and a.startswith('at://')), did)
    return {'did': did, 'handle': handle, 'pds': pds.rstrip('/')}


def sign_in(acct, env=os.environ):
    password = (env.get('BSKY_APP_PASSWORD') or '').strip()
    if not password:
        raise Stop('No app password: in this terminal, run\n    $env:BSKY_APP_PASSWORD = Read-Host "App password"\nthen try again.')
    try:
        session = xrpc(acct['pds'], 'com.atproto.server.createSession', data={'identifier': acct['did'], 'password': password})
    except Stop as err:
        raise Stop(f'Signing in as @{acct["handle"]} failed: {err}')
    if session.get('did') != acct['did']:
        raise Stop('That app password belongs to a different account.')
    return session['accessJwt']


# ---------- tracks ----------

def list_tracks(acct):
    """Every track record in the account, newest first (as the server lists them), up to MOST."""
    tracks, cursor = [], None
    while True:
        params = {'repo': acct['did'], 'collection': COLLECTION, 'limit': 100}
        if cursor:
            params['cursor'] = cursor
        page = xrpc(acct['pds'], 'com.atproto.repo.listRecords', params)
        records = page.get('records') or []
        tracks += records
        cursor = page.get('cursor')
        if not cursor or not records or len(tracks) >= MOST:
            return tracks[:MOST]


def rkey_of(record):
    return str(record.get('uri', '')).rsplit('/', 1)[-1]


def clock(seconds):
    """Seconds -> 4:05 or 1:02:03; '' when unknown."""
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
        return ''
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def blob_size(value):
    size = (value.get('audioBlob') or {}).get('size') if isinstance(value.get('audioBlob'), dict) else None
    return size if isinstance(size, int) and not isinstance(size, bool) else None


def megabytes(n):
    return f'{n / 1_000_000:.1f} MB'


def describe(record):
    """Two lines about one track, for list and delete."""
    v = record.get('value') or {}
    num = v.get('trackNumber')
    first = f'{num}. ' if isinstance(num, int) and not isinstance(num, bool) else ''
    first += v.get('title') or '(no title)'
    if v.get('artist'):
        first += f' · {v["artist"]}'
    extra = [x for x in (clock(v.get('duration')), megabytes(blob_size(v)) if blob_size(v) is not None else '', v.get('fileType') or '') if x]
    if extra:
        first += f'  ({", ".join(extra)})'
    second = f'{rkey_of(record)}  {v.get("createdAt", "")}'
    return first, second


def by_album(tracks, album):
    return [t for t in tracks if ((t.get('value') or {}).get('album') or '') == album]


def show_list(args, out=print, env=os.environ):
    acct = account(resolve_did(args.handle))
    tracks = list_tracks(acct)
    if args.album is not None:
        tracks = by_album(tracks, args.album)
    total = sum(blob_size(t.get('value') or {}) or 0 for t in tracks)
    where = f' in "{args.album}"' if args.album is not None else ''
    out(f'Audio tracks by @{acct["handle"]} ({acct["did"]}){where}: {len(tracks)}, audio {megabytes(total)}')
    shows = {}
    for t in tracks:
        shows.setdefault((t.get('value') or {}).get('album') or '(no album)', []).append(t)
    for album, items in shows.items():
        out(f'\n  {album}')
        for t in items:
            first, second = describe(t)
            out(f'    {first}')
            out(f'      {second}')
    return tracks


def delete(args, out=print, env=os.environ, ask=input):
    if not args.rkey and args.album is None:
        raise Stop('Say which tracks: --rkey (one or more) or --album "…".')
    if args.rkey and args.album is not None:
        raise Stop('Use --rkey or --album, not both.')
    for k in args.rkey or []:
        if not RKEY_RE.match(k):
            raise Stop(f'"{k}" is not a record key.')
    acct = account(resolve_did(args.handle))
    if args.album is not None:
        chosen = by_album(list_tracks(acct), args.album)
        if not chosen:
            raise Stop(f'@{acct["handle"]} has no tracks in "{args.album}".')
    else:
        chosen = []
        for k in dict.fromkeys(args.rkey):
            try:
                chosen.append(xrpc(acct['pds'], 'com.atproto.repo.getRecord', {'repo': acct['did'], 'collection': COLLECTION, 'rkey': k}))
            except Stop as err:
                if getattr(err, 'status', None) in (400, 404):
                    raise Stop(f'@{acct["handle"]} has no audio track with the key {k}.')
                raise
    total = sum(blob_size(t.get('value') or {}) or 0 for t in chosen)
    out(f'{len(chosen)} audio track{"s" if len(chosen) != 1 else ""} by @{acct["handle"]} (audio {megabytes(total)}):')
    for t in chosen:
        first, second = describe(t)
        out(f'  {first}')
        out(f'    {second}')
    if args.dry_run:
        out('\nDry run: nothing was deleted.')
        return []
    token = sign_in(acct, env)
    if ask(f'Really delete {"them" if len(chosen) != 1 else "it"}? [y/N] ').strip().lower() not in ('y', 'yes'):
        out('Stopped; nothing was deleted.')
        return []
    gone = []
    for t in chosen:
        k = rkey_of(t)
        xrpc(acct['pds'], 'com.atproto.repo.deleteRecord', data={'repo': acct['did'], 'collection': COLLECTION, 'rkey': k}, token=token)
        try:
            xrpc(acct['pds'], 'com.atproto.repo.getRecord', {'repo': acct['did'], 'collection': COLLECTION, 'rkey': k})
        except Stop as err:
            if getattr(err, 'status', None) in (400, 404):
                gone.append(k)
                out(f'  deleted {k}')
                continue
            raise
        raise Stop(f'The server said it deleted {k}, but it still reads back: look at it in PDSls.')
    out(f'Deleted {len(gone)} (they no longer read back).' if len(gone) != 1 else 'Deleted (it no longer reads back).')
    return gone


def parser():
    p = argparse.ArgumentParser(prog='audio_track.py', description='List and delete audio tracks (cafe.thunderbird.audio.track).')
    sub = p.add_subparsers(dest='command', required=True)
    def common(s):
        s.add_argument('--handle', default=DEFAULT_HANDLE, help=f'the account (a handle or DID; default {DEFAULT_HANDLE})')
    s = sub.add_parser('list', help="list an account's audio tracks, grouped by album (show)")
    s.add_argument('--album', default=None, help='only the tracks whose album is exactly this')
    common(s)
    s = sub.add_parser('delete', help='delete audio tracks, after asking')
    s.add_argument('--rkey', action='append', help='a track\'s key (the last part of its address; see list); repeat for more')
    s.add_argument('--album', default=None, help='every track whose album is exactly this')
    s.add_argument('--dry-run', action='store_true', help='show what would be deleted, delete nothing')
    common(s)
    return p


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    args = parser().parse_args(argv)
    try:
        {'list': show_list, 'delete': delete}[args.command](args)
        return 0
    except Stop as err:
        print(f'\n{err}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nStopped.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
