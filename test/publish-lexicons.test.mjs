// The lexicon and its publish script (claude/mixtape-3b-importer-notes.md, R3b-11, R3b-12), against a stand-in account server.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { runPublish, readLexicons, ACCOUNT, SCHEMA, PUBLISHED_FILE, TXT } from '../scripts/publish-lexicons.mjs';

const PDS = 'https://fibercap.us-west.host.bsky.network';
const ID = 'cafe.thunderbird.audio.track';

test('the lexicons: cafe.thunderbird.audio.track, nothing else', () => {
  assert.deepEqual(readLexicons().map((l) => l.id), [ID]);
  assert.equal(TXT, '_lexicon.audio');
});

test('the lexicon: cafe.thunderbird.audio.track as decided (R3-A9, R3b-11)', () => {
  const l = readLexicons()[0];
  assert.ok(!/draft/i.test(JSON.stringify(l)), 'no draft wording left');
  const m = l.defs.main;
  assert.equal(m.type, 'record');
  assert.equal(m.key, 'tid');
  assert.deepEqual(m.record.required, ['title', 'audioBlob', 'createdAt']);
  const p = m.record.properties;
  assert.deepEqual(Object.keys(p).sort(), ['album', 'artist', 'audioBlob', 'createdAt', 'description', 'duration', 'fileType',
    'imageBlob', 'recording', 'tags', 'title', 'trackNumber']);
  // plyr.fm's names and kinds for the basics
  assert.deepEqual([p.title.type, p.title.minLength, p.title.maxLength], ['string', 1, 256]);
  assert.equal(p.artist.type, 'string');
  assert.equal(p.album.type, 'string');
  assert.deepEqual([p.duration.type, p.duration.minimum], ['integer', 1]);
  assert.deepEqual([p.trackNumber.type, p.trackNumber.minimum, p.trackNumber.maximum], ['integer', 1, 999]);
  assert.equal(p.audioBlob.type, 'blob');
  for (const t of ['audio/webm', 'audio/flac', 'audio/mpeg']) assert.ok(p.audioBlob.accept.includes(t), t);
  assert.equal(p.audioBlob.maxSize, 100000000);
  assert.equal(p.description.maxLength, 5000);
  assert.deepEqual([p.tags.type, p.tags.maxLength, p.tags.items.maxLength], ['array', 20, 50]);
  assert.equal(p.imageBlob.type, 'blob');
  assert.equal(p.createdAt.format, 'datetime');
  assert.deepEqual(p.recording, { type: 'ref', ref: '#recording' });
  // the concert section: all optional
  const r = l.defs.recording;
  assert.equal(r.type, 'object');
  assert.equal(r.required, undefined);
  assert.deepEqual(Object.keys(r.properties).sort(), ['archiveUrl', 'date', 'place', 'policyUrl', 'set', 'source', 'taper', 'venue']);
  assert.equal(r.properties.date.maxLength, 10);
  assert.equal(r.properties.archiveUrl.format, 'uri');
  assert.equal(r.properties.policyUrl.format, 'uri');
});

test('a lexicon outside the audio family is refused', () => {
  const dir = mkdtempSync(join(tmpdir(), 'lex-'));
  writeFileSync(join(dir, 'cafe.thunderbird.tile.post.json'), JSON.stringify({ lexicon: 1, id: 'cafe.thunderbird.tile.post', defs: { main: {} } }));
  assert.throws(() => readLexicons(dir), /isn't in the cafe.thunderbird.audio family \(the _lexicon.audio TXT record/);
});

function server({ password = 'abcd-efgh-ijkl-mnop', sessionDid = ACCOUNT, mangle = false } = {}) {
  const repo = new Map();
  const calls = [];
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  const fetchImpl = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({ path: u.pathname, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null, auth: init.headers?.Authorization });
    if (u.host === 'plc.directory') return json({ id: ACCOUNT, alsoKnownAs: ['at://thunderbird.cafe'], service: [{ id: '#atproto_pds', type: 'AtprotoPersonalDataServer', serviceEndpoint: PDS }] });
    if (u.pathname.endsWith('createSession')) {
      const b = JSON.parse(init.body);
      if (b.password !== password) return json({ error: 'AuthenticationRequired', message: 'Invalid identifier or password' }, 401);
      return json({ did: sessionDid, accessJwt: 'jwt' });
    }
    if (u.pathname.endsWith('putRecord')) {
      const b = JSON.parse(init.body);
      repo.set(`${b.collection}/${b.rkey}`, mangle ? { ...b.record, defs: {} } : b.record);
      return json({ uri: `at://${b.repo}/${b.collection}/${b.rkey}`, cid: 'bafyreilexicon' });
    }
    if (u.pathname.endsWith('getRecord')) {
      const v = repo.get(`${u.searchParams.get('collection')}/${u.searchParams.get('rkey')}`);
      if (!v) return json({ error: 'RecordNotFound' }, 400);
      // keys in another order, as a server may hand them back
      return json({ uri: 'x', cid: 'bafyreilexicon', value: Object.fromEntries(Object.entries(v).reverse()) });
    }
    return json({ error: 'NotFound' }, 404);
  };
  return { fetchImpl, calls, repo };
}
const quiet = () => {};

test('a dry run shows what would be published and writes nothing', async () => {
  const s = server();
  let wrote = false;
  const r = await runPublish({ fetchImpl: s.fetchImpl, log: quiet, dryRun: true, env: {}, readPublished: () => ({}), writePublished: () => { wrote = true; },
    ask: () => assert.fail('no questions in a dry run'), askHidden: () => assert.fail('no password in a dry run') });
  assert.deepEqual(r.due, [ID]);
  assert.equal(wrote, false);
  assert.ok(!s.calls.some((c) => c.method === 'POST'));
});

test('publishing: the password from $env:BSKY_APP_PASSWORD, one record keyed by the NSID, read back, published.json written', async () => {
  const s = server();
  let saved = null;
  const lines = [];
  const r = await runPublish({ fetchImpl: s.fetchImpl, log: (l) => lines.push(l), env: { BSKY_APP_PASSWORD: 'abcd-efgh-ijkl-mnop' }, readPublished: () => ({}),
    writePublished: (o) => { saved = o; }, ask: async () => 'y', askHidden: () => assert.fail('the password came from the environment'), now: () => '2026-11-14T12:00:00.000Z' });
  assert.equal(r.changed, true);
  const puts = s.calls.filter((c) => c.path.endsWith('putRecord'));
  assert.equal(puts.length, 1);
  const put = puts[0];
  assert.equal(put.body.rkey, ID);
  assert.equal(put.body.collection, SCHEMA);
  assert.equal(put.body.repo, ACCOUNT);
  assert.equal(put.body.record.$type, SCHEMA);
  assert.equal(put.auth, 'Bearer jwt');
  const entry = saved.lexicons[ID];
  assert.equal(entry.uri, `at://${ACCOUNT}/${SCHEMA}/${ID}`);
  assert.equal(entry.text, JSON.stringify(readLexicons()[0]));
  assert.ok(lines.some((l) => l.includes('_lexicon.audio')), 'it reminds about the TXT record');

  // again, unchanged: nothing to do, no password asked
  const r2 = await runPublish({ fetchImpl: server().fetchImpl, log: quiet, env: {}, readPublished: () => saved, writePublished: () => assert.fail('nothing to write'),
    ask: () => assert.fail('nothing to ask'), askHidden: () => assert.fail('nothing to ask') });
  assert.equal(r2.changed, false);
  // a changed text is published again
  const old = { lexicons: { [ID]: { ...entry, text: '{"old":1}' } } };
  const r3 = await runPublish({ fetchImpl: server().fetchImpl, log: quiet, dryRun: true, env: {}, readPublished: () => old, ask: quiet, askHidden: quiet });
  assert.deepEqual(r3.due, [ID]);
});

// Before the first publish there is no published.json; once the owner publishes and commits it, it must match.
test('the committed published.json (once there is one) matches the lexicons on disk: nothing due', async (t) => {
  if (!existsSync(PUBLISHED_FILE)) { t.skip('not published yet: no published.json'); return; }
  const committed = JSON.parse(readFileSync(PUBLISHED_FILE, 'utf8'));
  const r = await runPublish({ fetchImpl: server().fetchImpl, log: quiet, dryRun: true, env: {}, readPublished: () => committed, ask: quiet, askHidden: quiet });
  assert.deepEqual(r.due, [], 'a lexicon changed or was added since it was last published: publish it, then commit published.json');
});

test('the password asked for (hidden) when the environment has none; "no" stops before writing', async () => {
  const s = server();
  let asked = 0;
  const r = await runPublish({ fetchImpl: s.fetchImpl, log: quiet, env: {}, readPublished: () => ({}), writePublished: () => assert.fail('stopped'),
    askHidden: async () => { asked++; return 'abcd-efgh-ijkl-mnop'; }, ask: async () => 'n' });
  assert.equal(asked, 1);
  assert.equal(r.changed, false);
  assert.ok(!s.calls.some((c) => c.path.endsWith('putRecord')));
});

test("another account's app password, or a record that doesn't read back, stops it", async () => {
  await assert.rejects(runPublish({ fetchImpl: server({ sessionDid: 'did:plc:rqbqpaaluty5v47jwciowpik' }).fetchImpl, log: quiet, env: { BSKY_APP_PASSWORD: 'abcd-efgh-ijkl-mnop' },
    readPublished: () => ({}), writePublished: () => {}, ask: async () => 'y', askHidden: quiet }), /different account/);
  await assert.rejects(runPublish({ fetchImpl: server({ mangle: true }).fetchImpl, log: quiet, env: { BSKY_APP_PASSWORD: 'abcd-efgh-ijkl-mnop' },
    readPublished: () => ({}), writePublished: () => {}, ask: async () => 'y', askHidden: quiet }), /didn't read back/);
  await assert.rejects(runPublish({ fetchImpl: server().fetchImpl, log: quiet, env: { BSKY_APP_PASSWORD: 'wrong' },
    readPublished: () => ({}), writePublished: () => {}, ask: async () => 'y', askHidden: quiet }), /Invalid identifier or password/);
});
