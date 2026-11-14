# Audio tracks

An **audio track** is a piece of audio (a song, a live track, a recording) kept with its audio file in its author's
own atproto account. It is a record of the kind `cafe.thunderbird.audio.track`. The Web Tile Foundry's importer
writes them (songs from the Live Music Archive, converted once to Opus in WebM); its Mixtape Burndown tapes can use
them; later, Raku will play one on its own.

This repo holds the audio family's lexicons (`cafe.thunderbird.audio.*`, published from thunderbird.cafe), the script
that publishes them, and a small Python script that lists and deletes track records. The Foundry (writing) and Raku
(reading) both use it; neither owns it.

## The record: `cafe.thunderbird.audio.track`

`lexicons/cafe.thunderbird.audio.track.json`. Record keys are TIDs (time-based, like Bluesky posts). The basic fields
use the names plyr.fm's `fm.plyr.track` uses, so a music app can read both with little code. One difference: here
`artist` is the **performer** (for example the band), not the account that uploaded it.

| Field | | |
|---|---|---|
| `title` | required | the track's title |
| `audioBlob` | required | the audio file (WebM, Ogg, MP3, MP4, FLAC or WAV; the importer stores Opus in WebM). Bluesky-hosted accounts hold a file to 50 MB |
| `createdAt` | required | when the track was added |
| `artist` | optional | the performer |
| `album` | optional | the show or album, for example `Galactic · Moguls · 1997-08-15` |
| `trackNumber` | optional | its place in the show or album |
| `duration` | optional | in seconds |
| `fileType` | optional | the file's format, for example `webm` |
| `description` | optional | liner notes, show notes, setlist or lineage notes (up to 5,000 characters) |
| `tags` | optional | up to 20 tags |
| `imageBlob` | optional | cover art |
| `recording` | optional | for live recordings: `date` (YYYY-MM-DD, YYYY-MM or YYYY), `venue`, `place`, `set`, `taper`, `source` (soundboard or audience, and the lineage), `archiveUrl` (the show's page), `policyUrl` (the performer's sharing policy) |

An example:

```json
{
  "$type": "cafe.thunderbird.audio.track",
  "title": "Funky Bird",
  "artist": "Galactic",
  "album": "Galactic · Moguls · 1997-08-15",
  "trackNumber": 3,
  "duration": 245,
  "audioBlob": { "$type": "blob", "ref": { "$link": "bafkrei…" }, "mimeType": "audio/webm", "size": 2940000 },
  "fileType": "webm",
  "description": "The show's info file: setlist, taper, lineage…",
  "recording": {
    "date": "1997-08-15",
    "venue": "Moguls",
    "set": "Set 1",
    "source": "Audience: …",
    "archiveUrl": "https://archive.org/details/…"
  },
  "createdAt": "2026-11-15T10:00:00.000Z"
}
```

Anyone can write one, with any tool. Tracks are public, like everything in an atproto account: put up only audio you
may share. New fields will all be optional; later pieces of the family (for example a list of tracks) will join under
the same `cafe.thunderbird.audio.` prefix.

## Publishing the lexicons

The names belong to thunderbird.cafe: a TXT record at `_lexicon.audio.thunderbird.cafe` with the value
`did=did:plc:6vxjigxrqizmbo56gojxico3` says so. Then, in this folder (Node 22, nothing to install):

```
node scripts/publish-lexicons.mjs --dry-run
node scripts/publish-lexicons.mjs
```

Each lexicon is written as a `com.atproto.lexicon.schema` record in thunderbird.cafe's repo (key: its NSID), only
when it is new or changed, and read back to check. The app password comes from `$env:BSKY_APP_PASSWORD`, or is asked
for. `published.json` records what was published: commit it.

## Listing and deleting tracks (`scripts/audio_track.py`)

Python 3, standard library only. Deleting needs an app password for the account in this terminal (one per task,
deleted after); listing and dry runs don't:

```
python scripts/audio_track.py list
python scripts/audio_track.py list --album "Galactic · Moguls · 1997-08-15"
python scripts/audio_track.py delete --rkey 3m… --rkey 3m… --dry-run
$env:BSKY_APP_PASSWORD = Read-Host "App password"
python scripts/audio_track.py delete --album "Galactic · Moguls · 1997-08-15"
```

- `list` shows an account's tracks grouped by album, each with its length, file size and key.
- `delete` removes tracks by key (`--rkey`, repeatable) or every track of one album (`--album`, matched exactly),
  after showing them and asking "Really delete them?"; each is read back to check it's gone.
- The default account is pyxorium.com; `--handle thunderbird.cafe` (or a DID) works on another.
- Deleting a track doesn't touch tapes made from it: a tape keeps its own copy of the song.

## Tests

```
npm test
python -m unittest discover -s test -v
```

`npm test` checks the lexicon and the publish script against a stand-in account server (and, once `published.json`
is committed, that it matches the lexicons); the Python tests run `audio_track.py` against stand-in servers on this
computer (127.0.0.1).

## Files

| | |
|---|---|
| `lexicons/` | the lexicons, one file each, named by NSID |
| `scripts/publish-lexicons.mjs` | publishes them from thunderbird.cafe |
| `scripts/audio_track.py` | lists and deletes track records |
| `published.json` | what was published (written by the publish script) |
| `test/` | `publish-lexicons.test.mjs` (Node), `test_audio_track.py` (Python) |
