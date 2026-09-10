// pglite_bridge.cjs — JSON-over-stdio driver for PGlite (development only).
//
// PGlite is "Postgres compiled to WASM" (https://github.com/electric-sql/pglite):
// it executes the SAME SQL dialect as a real Supabase Postgres instance, so
// schema.sql and the seed SQL can be validated locally without a live DB.
//
// Usage (from Python, e.g. verify_supabase.py):
//     const { PGlite } = require(PGLITE_MODULE_PATH or resolved pglite)
//     stdin lines:  {"cmd":"exec","sql":"..."} | {"cmd":"query","sql":"...","params":[...]}
//     stdout lines: {"ok":true,"rows":[...] } | {"ok":false,"error":"..."}
//
// Install pglite somewhere once (NOT committed):
//     mkdir -p /tmp/pgverify && cd /tmp/pgverify && npm install @electric-sql/pglite
//     PGLITE_MODULE_PATH=/tmp/pgverify/node_modules/@electric-sql/pglite
//
// `exec` runs multi-statement SQL (DDL, scripts). `query` runs a single
// statement with $1..$n params. Out-of-band text goes to stderr, never stdout.

'use strict';

const path = require('path');
const fs = require('fs');
const readline = require('readline');

function resolvePglite() {
  const envDir = process.env.PGLITE_MODULE_PATH;
  if (envDir && envDir.trim()) {
    const cand = path.join(envDir.trim(), '@electric-sql', 'pglite');
    if (fs.existsSync(path.join(cand, 'package.json'))) return cand;
  }
  const here = path.join(__dirname, 'pglite', 'node_modules', '@electric-sql', 'pglite');
  if (fs.existsSync(path.join(here, 'package.json'))) return here;
  throw new Error('pglite not found. Install it (npm install @electric-sql/pglite) and set PGLITE_MODULE_PATH, or put it in scripts/pglite/node_modules');
}

(async () => {
  const modulePath = resolvePglite();
  const { PGlite } = require(modulePath);
  const db = new PGlite();
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  let closed = false;

  const respond = (obj) => {
    process.stdout.write(JSON.stringify(obj) + '\n');
  };

  rl.on('line', async (line) => {
    if (closed) return;
    if (!line.trim()) return;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch (e) {
      respond({ ok: false, error: 'bad json: ' + e.message });
      return;
    }
    try {
      if (msg.cmd === 'exec') {
        if (!msg.sql || !msg.sql.trim()) throw new Error('exec: empty sql');
        const results = await db.exec(msg.sql);
        respond({ ok: true, rows: results });
      } else if (msg.cmd === 'query') {
        if (!msg.sql || !msg.sql.trim()) throw new Error('query: empty sql');
        const rows = await db.query(msg.sql, msg.params || []);
        respond({ ok: true, rows: rows.rows });
      } else if (msg.cmd === 'close') {
        closed = true;
        await db.close();
        respond({ ok: true, rows: [] });
        rl.close();
      } else {
        respond({ ok: false, error: 'unknown cmd: ' + msg.cmd });
      }
    } catch (e) {
      respond({ ok: false, error: String((e && e.message) || e) });
      if (closed) process.exit(1);
    }
  });

  rl.on('close', async () => {
    if (!closed) {
      closed = true;
      try { await db.close(); } catch (_) {}
    }
    process.exit(0);
  });
})().catch((e) => {
  process.stderr.write('FATAL: ' + (e && e.message) + '\n');
  process.exit(1);
});