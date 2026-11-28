const express = require('express');
const fs = require('fs');
const path = require('path');

const RESULTS = process.env.RESULTS_DIR || path.join(__dirname, '..', 'results');
const app = express();

function readCsv(name) {
  const p = path.join(RESULTS, name);
  if (!fs.existsSync(p)) return { headers: [], rows: [] };
  const lines = fs.readFileSync(p, 'utf8').trim().split(/\r?\n/);
  return { headers: lines[0].split(','), rows: lines.slice(1).map(l => l.split(',')) };
}

app.get('/api/summary', (req, res) => res.json(readCsv('summary.csv')));
app.get('/api/ab', (req, res) => res.json(readCsv('ab_summary.csv')));
app.get('/api/raw', (req, res) => {
  const p = path.join(RESULTS, 'raw.jsonl');
  if (!fs.existsSync(p)) return res.json([]);
  const rows = fs.readFileSync(p, 'utf8').trim().split(/\n/).filter(Boolean).map(l => JSON.parse(l));
  res.json(rows);
});
app.use(express.static(path.join(__dirname, 'public')));

app.listen(3000, '0.0.0.0', () => console.log('dashboard on :3000, results from ' + RESULTS));
