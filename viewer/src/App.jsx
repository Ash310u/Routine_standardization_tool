import React, { useEffect, useMemo, useRef, useState } from 'react';
import { demoCases } from './demoData.js';

const CAUSES = [
  { id: 'no_catalog_candidates', label: 'No catalog candidates', short: 'No candidates', tone: 'slate',
    description: 'No usable code was extracted, and the parsed context did not return a catalog candidate.' },
  { id: 'unmatched_code', label: 'Code absent from catalog', short: 'Code absent', tone: 'rose',
    description: 'A code was extracted, but its normalized form has no exact match in the saved catalog.' },
  { id: 'non_subject_activity', label: 'Non-subject activity', short: 'Activity', tone: 'blue',
    description: 'The cell is an activity such as research hours rather than a catalog subject.' },
  { id: 'semantic', label: 'Semantic match needs review', short: 'Semantic review', tone: 'violet',
    description: 'No usable code was found; a text similarity suggestion needs validation.' },
  { id: 'code_concern', label: 'Code matched with concern', short: 'Code concern', tone: 'amber',
    description: 'One catalog record was identified by code, but time, context, or cell structure still needs review.' },
  { id: 'duplicate_code', label: 'Duplicate catalog code', short: 'Duplicate code', tone: 'orange',
    description: 'The same code belongs to multiple catalog records, and the routine context cannot pick one safely.' },
  { id: 'fuzzy', label: 'Fuzzy code conflict', short: 'Fuzzy conflict', tone: 'pink',
    description: 'A historical parser example where a split code led to a fuzzy name suggestion. Current code-first matching no longer uses this route.' },
  { id: 'accepted', label: 'Accepted code match', short: 'Accepted', tone: 'green',
    description: 'A unique catalog code matched and the pipeline has no review reason for this record.' },
  { id: 'other', label: 'Other review case', short: 'Other', tone: 'slate',
    description: 'This result has a match method outside the main cause groups shown here.' },
];

const PAGE_SIZE = 12;
const categoryById = Object.fromEntries(CAUSES.map((cause) => [cause.id, cause]));

function categoryOf(record) {
  if (record.match_method === 'code') return record.requires_review ? 'code_concern' : 'accepted';
  return categoryById[record.match_method] ? record.match_method : 'other';
}

function normalize(records) {
  return records.map((record, index) => ({ ...record, _id: String(index), _category: categoryOf(record) }));
}

function percent(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—';
}

function display(value) {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

function Marker({ category }) {
  const cause = categoryById[category];
  return <span className="marker" data-tone={cause.tone}>{cause.short}</span>;
}

function Status({ record }) {
  return <span className={`status ${record.requires_review ? 'status-review' : 'status-accepted'}`}>
    <span className="status-dot" />{record.requires_review ? 'Needs review' : 'Accepted'}
  </span>;
}

function Detail({ record }) {
  if (!record) {
    return <aside className="detail empty-detail"><div className="empty-icon">⌕</div><h3>No case selected</h3><p>Adjust the filters to see matching records.</p></aside>;
  }
  const cause = categoryById[record._category];
  const candidates = Array.isArray(record.match_candidates) ? record.match_candidates : [];
  return <aside className="detail" aria-label="Case details">
    <div className="detail-topline"><span>CASE DETAIL</span><span className="mono">{display(record.cell_ref || (record.page && `Page ${record.page}`))}</span></div>
    <div className="detail-title-row"><div><h2>{display(record.subject_raw)}</h2><p>{display(record.department)} · {display(record.semester)} semester · {display(record.day)} {display(record.start_time)}–{display(record.end_time)}</p></div></div>
    <div className="detail-tags"><Marker category={record._category} /><Status record={record} /></div>
    <section className="detail-callout" data-tone={cause.tone}>
      <strong>Why this case appears here</strong>
      <p>{record.scenario_note || cause.description}</p>
    </section>
    <section className="detail-section">
      <h3>Source → catalog</h3>
      <div className="comparison">
        <div><span className="field-label">EXTRACTED CODE</span><strong className="mono">{display(record.subject_code_raw)}</strong></div>
        <span className="comparison-arrow" aria-hidden="true">→</span>
        <div><span className="field-label">CATALOG CODE</span><strong className="mono">{display(record.subject_code)}</strong></div>
      </div>
      <div className="data-line"><span>Catalog name</span><strong>{display(record.subject_name)}</strong></div>
      <div className="data-line"><span>Catalog record ID</span><strong className="mono">{display(record.subject_master_id)}</strong></div>
      <div className="data-line"><span>Catalog context</span><strong>{[record.catalog_course, record.catalog_stream, record.catalog_semester].filter(Boolean).join(' / ') || '—'}</strong></div>
    </section>
    <section className="detail-section">
      <h3>Review flags <span className="small-count">{record.review_reasons?.length || 0}</span></h3>
      {record.review_reasons?.length ? <ul className="reason-list">{record.review_reasons.map((reason, index) => <li key={`${reason}-${index}`}><span className="reason-bullet" />{reason}</li>)}</ul> : <p className="muted">No review flag for this record.</p>}
    </section>
    {candidates.length > 0 && <section className="detail-section"><h3>Candidate subjects</h3><div className="candidate-list">{candidates.slice(0, 3).map((candidate, index) => <div className="candidate" key={`${candidate.code}-${index}`}><div><strong>{candidate.name}</strong><span className="mono">{candidate.code}</span></div><b>{percent(candidate.score)}</b></div>)}</div></section>}
    <p className="confidence-note">Pipeline confidence: <strong>{percent(record.confidence)}</strong>. This is a heuristic score, not measured accuracy.</p>
  </aside>;
}

export default function App() {
  const [records, setRecords] = useState(() => normalize(demoCases));
  const [sourceName, setSourceName] = useState('Fictional examples');
  const [mode, setMode] = useState('demo');
  const [category, setCategory] = useState('all');
  const [status, setStatus] = useState('all');
  const [department, setDepartment] = useState('all');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState('');
  const fileRef = useRef(null);

  const totals = useMemo(() => Object.fromEntries(CAUSES.map((cause) => [cause.id, records.filter((record) => record._category === cause.id).length])), [records]);
  const departments = useMemo(() => [...new Set(records.map((record) => record.department).filter(Boolean))].sort(), [records]);
  const reviewCount = useMemo(() => records.filter((record) => record.requires_review).length, [records]);
  const codeMatchCount = totals.code_concern + totals.accepted;

  const filtered = useMemo(() => records.filter((record) => {
    if (category !== 'all' && record._category !== category) return false;
    if (status === 'review' && !record.requires_review) return false;
    if (status === 'accepted' && record.requires_review) return false;
    if (department !== 'all' && record.department !== department) return false;
    if (!query.trim()) return true;
    const haystack = [record.cell_ref, record.subject_raw, record.subject_code_raw, record.subject_name,
      record.subject_code, record.department, record.semester, ...(record.review_reasons || [])].join(' ').toLowerCase();
    return haystack.includes(query.trim().toLowerCase());
  }), [records, category, status, department, query]);

  useEffect(() => { setPage(1); setSelectedId(null); }, [category, status, department, query, records]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const selected = filtered.find((record) => record._id === selectedId) || visible[0];

  async function loadJson(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      if (!Array.isArray(parsed.classes)) throw new Error('This file needs a classes array from the routine JSON output.');
      setRecords(normalize(parsed.classes));
      setSourceName(file.name);
      setMode('file');
      setCategory('all'); setStatus('all'); setDepartment('all'); setQuery('');
      setError('');
    } catch (caught) {
      setError(`Could not load JSON: ${caught.message}`);
    } finally {
      event.target.value = '';
    }
  }

  function resetDemo() {
    setRecords(normalize(demoCases)); setSourceName('Fictional examples'); setMode('demo');
    setCategory('all'); setStatus('all'); setDepartment('all'); setQuery(''); setError('');
  }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark">R<span>·</span></div><div><strong>Routine Standardizer</strong><small>CASE EXPLORER</small></div></div>
      <div className="top-actions"><span className="source-label"><span className="live-dot" />{sourceName}</span><button className="button button-quiet" onClick={resetDemo}>Reset demo</button><button className="button button-primary" onClick={() => fileRef.current?.click()}>↑ &nbsp; Load routine JSON</button><input ref={fileRef} type="file" accept=".json,application/json" onChange={loadJson} hidden aria-label="Load routine JSON" /></div>
    </header>
    <main className="main-wrap">
      <div className="intro"><div><div className="eyebrow"><span className="eyebrow-line" /> REVIEW WORKSPACE <span className="mode-pill">{mode === 'demo' ? 'DEMO SCENARIOS' : 'LOADED FILE'}</span></div><h1>Every flag, in context.</h1><p>Explore why a routine cell was flagged, what the parser extracted, and what the saved subject catalog could resolve.</p></div><div className="intro-aside"><div className="intro-symbol">⌁</div><span>Inspect the evidence before accepting a match.</span></div></div>
      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
      <div className="metrics"><div className="metric"><span>Records in view</span><strong>{records.length.toLocaleString()}</strong><small>{mode === 'demo' ? 'fictional records' : 'loaded from JSON'}</small></div><div className="metric"><span>Need review</span><strong className="accent-amber">{reviewCount.toLocaleString()}</strong><small>{records.length ? percent(reviewCount / records.length) : '0%'} of records</small></div><div className="metric"><span>Code matched</span><strong className="accent-blue">{codeMatchCount.toLocaleString()}</strong><small>unique catalog records</small></div><div className="metric"><span>Accepted</span><strong className="accent-green">{(records.length - reviewCount).toLocaleString()}</strong><small>without a review flag</small></div></div>
      <section className="cause-section"><div className="section-heading"><div><span className="section-kicker">01 / OVERVIEW</span><h2>Browse by main cause</h2></div><p>Choose a cause to filter the case list.</p></div><div className="cause-grid">{CAUSES.filter((cause) => cause.id !== 'other' || totals.other > 0).map((cause) => <button key={cause.id} className={`cause-card ${category === cause.id ? 'is-active' : ''}`} data-tone={cause.tone} onClick={() => setCategory(category === cause.id ? 'all' : cause.id)} aria-pressed={category === cause.id}><span className="cause-top"><span className="cause-icon">{cause.id === 'accepted' ? '✓' : cause.id === 'duplicate_code' ? 'Ⅱ' : '!'}</span><span className="cause-number">{totals[cause.id]}</span></span><strong>{cause.label}</strong><span className="cause-foot">View cases <span aria-hidden="true">↗</span></span></button>)}</div></section>
      <section className="workspace"><div className="section-heading"><div><span className="section-kicker">02 / CASES</span><h2>Flagged cell explorer</h2></div><p>Click a row for the code, catalog match, and review reasons.</p></div><div className="work-grid"><div className="list-panel"><div className="filter-bar"><label className="search"><span aria-hidden="true">⌕</span><input placeholder="Search code, subject, cell, reason…" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search cases" /></label><select value={department} onChange={(event) => setDepartment(event.target.value)} aria-label="Filter by department"><option value="all">All departments</option>{departments.map((name) => <option key={name} value={name}>{name}</option>)}</select></div><div className="filter-subrow"><div className="segmented" aria-label="Filter by review status"><button className={status === 'all' ? 'on' : ''} onClick={() => setStatus('all')}>All</button><button className={status === 'review' ? 'on' : ''} onClick={() => setStatus('review')}>Needs review</button><button className={status === 'accepted' ? 'on' : ''} onClick={() => setStatus('accepted')}>Accepted</button></div><span>{filtered.length.toLocaleString()} case{filtered.length === 1 ? '' : 's'} shown</span></div><div className="table-head"><span>RAW CELL / LOCATION</span><span>CATALOG RESULT</span><span>CAUSE</span><span>STATUS</span></div><div className="rows">{visible.length ? visible.map((record) => <button key={record._id} className={`case-row ${selected?._id === record._id ? 'selected' : ''}`} onClick={() => setSelectedId(record._id)}><span className="row-source"><strong>{display(record.subject_raw)}</strong><small className="mono">{display(record.cell_ref || (record.page && `Page ${record.page}`))} · {display(record.subject_code_raw)}</small></span><span className="row-match"><strong>{display(record.subject_name)}</strong><small className="mono">{display(record.subject_code)}</small></span><span><Marker category={record._category} /></span><span><Status record={record} /></span></button>) : <div className="no-results"><strong>No cases match these filters.</strong><p>Try another cause, department, or search term.</p><button className="text-button" onClick={() => { setCategory('all'); setStatus('all'); setDepartment('all'); setQuery(''); }}>Clear filters</button></div>}</div><div className="pagination"><span>Page {page} of {pageCount}</span><div><button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} aria-label="Previous page">←</button><button onClick={() => setPage(Math.min(pageCount, page + 1))} disabled={page === pageCount} aria-label="Next page">→</button></div></div></div><Detail record={selected} /></div></section>
      <footer>Demo scenarios are fictional. Load a routine JSON export to inspect actual pipeline output. Review flags and confidence are not measured accuracy.</footer>
    </main>
  </div>;
}
