export interface Details { sessionId: string; firstName: string; mobile: string }
export interface Dataset {
  fileName: string; rowCount: number; columnCount: number; columns: string[];
  rows: Record<string, string | null>[]; texts: string[]; vectors: string[];
}
export interface Hit { index: number; score: number; vectorScore: number; bm25Score: number }
export interface SearchResult { query: string; totalRows: number; results: Hit[]; method: string; model: string }

// Relative URL: the same build works at the site root and under a sub-path such as /smart-search/
// (the page URL must end in a slash there).
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`api${path}`, init);
  const body = res.headers.get('content-type')?.includes('json') ? await res.json() : await res.text();
  if (!res.ok) {
    const d = typeof body === 'object' && body ? (body as { detail?: unknown }).detail : body;
    const msg = Array.isArray(d) ? d.map((e: { msg?: string }) => e.msg).join(' ') : String(d || '');
    throw new Error(msg.replace(/^Value error, /, '') || `Request failed (${res.status}).`);
  }
  return body as T;
}

const json = (data: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
});

export const createSession = (firstName: string, mobile: string) =>
  call<Details>('/details', json({ firstName, mobile }));

/** Parse the file, then embed its rows in small batches so progress is real and each call stays fast. */
export async function indexFile(file: File, onProgress: (done: number, total: number) => void): Promise<Dataset> {
  const form = new FormData();
  form.append('file', file);
  const parsed = await call<Omit<Dataset, 'vectors'>>('/parse', { method: 'POST', body: form });
  const vectors: string[] = [];
  const BATCH = 64;
  onProgress(0, parsed.texts.length);
  for (let i = 0; i < parsed.texts.length; i += BATCH) {
    const chunk = parsed.texts.slice(i, i + BATCH);
    vectors.push((await call<{ vectors: string }>('/embed', json({ texts: chunk }))).vectors);
    onProgress(Math.min(i + BATCH, parsed.texts.length), parsed.texts.length);
  }
  return { ...parsed, vectors };
}

export const search = (ds: Dataset, query: string) =>
  call<SearchResult>('/search', json({ query, texts: ds.texts, vectors: ds.vectors, limit: 20 }));
