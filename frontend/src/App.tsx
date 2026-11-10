import { useMemo, useState, type DragEvent, type FormEvent } from 'react';
import {
  AlertCircle, ArrowRight, Check, FileSpreadsheet, LoaderCircle, RotateCcw, Search, ShieldCheck,
  Sparkles, UploadCloud, X,
} from 'lucide-react';
import { createSession, indexFile, search, type Dataset, type SearchResult } from './api';

type Step = 0 | 1 | 2;
const STEPS = ['Your details', 'Upload data', 'Search'];

/** Suggestions come from the uploaded data: a short value from three evenly spaced rows. */
function suggestions(ds: Dataset): string[] {
  const col = ds.columns[Math.min(1, ds.columns.length - 1)];
  const out = new Set<string>();
  for (let i = 0; i < 3; i++) {
    const v = ds.rows[Math.floor(((i + 0.5) * ds.rows.length) / 3)]?.[col];
    if (v) out.add(v.length > 40 ? `${v.slice(0, 40).trim()}…` : v);
  }
  return [...out];
}

function Brand() {
  return (
    <div className="brand">
      <span className="logo"><Search size={17} strokeWidth={3} /></span>
      <span>Soldrin <b>Smart Search</b></span>
    </div>
  );
}

function Stepper({ step }: { step: Step }) {
  return (
    <ol className="stepper">
      {STEPS.map((label, i) => (
        <li key={label} className={i === step ? 'on' : i < step ? 'done' : ''}>
          <span>{i < step ? <Check size={12} strokeWidth={3} /> : i + 1}</span>{label}
        </li>
      ))}
    </ol>
  );
}

function Err({ msg, clear }: { msg: string; clear: () => void }) {
  return (
    <div className="err" role="alert">
      <AlertCircle size={16} /><span>{msg}</span>
      <button type="button" onClick={clear} aria-label="Dismiss"><X size={14} /></button>
    </div>
  );
}

function Details({ onDone }: { onDone: (name: string) => void }) {
  const [name, setName] = useState('');
  const [mobile, setMobile] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr('');
    try { onDone((await createSession(name, mobile)).firstName); }
    catch (x) { setErr(x instanceof Error ? x.message : 'Something went wrong.'); }
    finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="card">
      <h2>Welcome, let’s get started</h2>
      <p className="muted">Tell us who’s searching. We’ll share your name and number with the Soldrin team so they can follow up.</p>
      <label>First name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Samira" autoComplete="given-name" required /></label>
      <label>Mobile number<input value={mobile} onChange={(e) => setMobile(e.target.value)} placeholder="+1 415 555 0182" autoComplete="tel" inputMode="tel" required /></label>
      {err && <Err msg={err} clear={() => setErr('')} />}
      <button className="btn" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <ArrowRight size={16} />} Continue</button>
    </form>
  );
}

function Upload({ onDone }: { onDone: (d: Dataset) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<[number, number] | null>(null);
  const [err, setErr] = useState('');

  function pick(f?: File) {
    if (!f) return;
    if (!/\.(csv|xlsx)$/i.test(f.name)) return setErr('Choose a .csv or .xlsx file.');
    if (f.size > 4 * 1024 * 1024) return setErr('Keep the file under 4 MB.');
    setErr(''); setFile(f);
  }
  async function go() {
    if (!file) return;
    setErr(''); setProgress([0, 1]);
    try { onDone(await indexFile(file, (d, t) => setProgress([d, t]))); }
    catch (x) { setErr(x instanceof Error ? x.message : 'Could not index this file.'); setProgress(null); }
  }
  const drop = (e: DragEvent) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); };

  if (progress) {
    const pct = Math.round((progress[0] / progress[1]) * 100);
    return (
      <div className="card center">
        <h2>Building your search index</h2>
        <p className="muted">Reading {progress[1]} rows with the embedding model…</p>
        <div className="bar"><i style={{ width: `${pct}%` }} /></div>
        <p className="mono">{pct}%</p>
      </div>
    );
  }
  return (
    <div className="card">
      <h2>Upload your spreadsheet</h2>
      <p className="muted">CSV or XLSX · up to 1,000 rows · 4 MB. Every original value comes back in the results.</p>
      <label className={`drop ${drag ? 'drag' : ''}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={drop}>
        <input type="file" accept=".csv,.xlsx" onChange={(e) => pick(e.target.files?.[0])} hidden />
        <UploadCloud size={28} /><b>Drop a file or click to browse</b>
      </label>
      {file && <div className="file"><FileSpreadsheet size={18} /><span>{file.name}</span><button type="button" onClick={() => setFile(null)} aria-label="Remove file"><X size={14} /></button></div>}
      {err && <Err msg={err} clear={() => setErr('')} />}
      <button className="btn" disabled={!file} onClick={go}><Sparkles size={16} /> Index this file</button>
    </div>
  );
}

function Results({ ds, res }: { ds: Dataset; res: SearchResult }) {
  const cols = useMemo(() => ds.columns, [ds]);
  if (!res.results.length) return <p className="muted">No matches for “{res.query}”.</p>;
  return (
    <section>
      <p className="muted"><b>{res.results.length}</b> best matches of {res.totalRows} rows · {res.method} · <span className="mono">{res.model}</span></p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Row</th>{cols.map((c) => <th key={c}>{c}</th>)}<th>Match</th></tr></thead>
          <tbody>
            {res.results.map((h) => (
              <tr key={h.index}>
                <td className="mono">#{h.index + 1}</td>
                {cols.map((c) => <td key={c}>{ds.rows[h.index][c] ?? '—'}</td>)}
                <td><span className="pill" title={`semantic ${h.vectorScore.toFixed(2)} · keyword ${h.bm25Score.toFixed(2)}`}>{Math.round(h.score * 100)}%</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="cards">
        {res.results.map((h) => (
          <article key={h.index}>
            <header><span className="mono">Row #{h.index + 1}</span><span className="pill">{Math.round(h.score * 100)}%</span></header>
            <dl>{cols.map((c) => ds.rows[h.index][c] && <div key={c}><dt>{c}</dt><dd>{ds.rows[h.index][c]}</dd></div>)}</dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function SearchStep({ ds, onReplace }: { ds: Dataset; onReplace: () => void }) {
  const [q, setQ] = useState('');
  const [res, setRes] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  async function run(query: string) {
    if (query.trim().length < 2) return setErr('Type at least two characters.');
    setBusy(true); setErr('');
    try { setRes(await search(ds, query.trim())); }
    catch (x) { setErr(x instanceof Error ? x.message : 'Search failed.'); }
    finally { setBusy(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); run(q); };
  return (
    <div className="card wide">
      <div className="file"><FileSpreadsheet size={18} /><span>{ds.fileName} · {ds.rowCount} rows · {ds.columnCount} columns</span><button type="button" onClick={onReplace}><RotateCcw size={13} /> Replace</button></div>
      <form onSubmit={submit} className="searchbar">
        <Search size={18} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Describe what you’re looking for…" aria-label="Search your data" autoFocus />
        <button className="btn" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : 'Search'}</button>
      </form>
      <div className="chips">{useMemo(() => suggestions(ds), [ds]).map((x) => <button key={x} type="button" onClick={() => { setQ(x); run(x); }}>{x}</button>)}</div>
      {err && <Err msg={err} clear={() => setErr('')} />}
      {res && <Results ds={ds} res={res} />}
    </div>
  );
}

export default function App() {
  const [step, setStep] = useState<Step>(0);
  const [name, setName] = useState('');
  const [ds, setDs] = useState<Dataset | null>(null);

  return (
    <div className="shell">
      <header><Brand /><span className="status"><i /> {name ? `Signed in as ${name}` : 'Private session'}</span></header>
      <main>
        <div className="hero">
          <h1>Find rows by <em>meaning</em>, not just keywords.</h1>
          <p>Upload a spreadsheet and ask in plain language. Soldrin Smart Search blends semantic embeddings with keyword ranking.</p>
        </div>
        <Stepper step={step} />
        {step === 0 && <Details onDone={(n) => { setName(n); setStep(1); }} />}
        {step === 1 && <Upload onDone={(d) => { setDs(d); setStep(2); }} />}
        {step === 2 && ds && <SearchStep ds={ds} onReplace={() => setStep(1)} />}
      </main>
      <footer><ShieldCheck size={13} /> Your file is processed in memory and never stored. © Soldrin</footer>
    </div>
  );
}
