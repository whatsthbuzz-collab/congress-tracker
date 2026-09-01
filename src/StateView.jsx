import React, { useEffect, useMemo, useState } from 'react';

// ---------- small helpers (kept local so this file stands alone) ----------
const partyClass = (p) => (p || '').toLowerCase().replace(/[^a-z]/g, '-');

function Initials({ member, size = 'lg' }) {
  const [failed, setFailed] = useState(false);
  const initials = (member.name || '')
    .split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join('').toUpperCase();
  if (member.photo && !failed) {
    return (
      <img
        className={`member-photo ph-${size} ${partyClass(member.party)}`}
        src={member.photo}
        alt={member.name}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <div className={`member-photo ph-${size} ph-fallback ${partyClass(member.party)}`}>
      {initials}
    </div>
  );
}

const electionLine = (m) => {
  if (m.nextElection) return `on ballot ${m.nextElection}`;
  if (m.termYears) return `${m.termYears}-year term`;
  return null;
};

const seatOf = (m) =>
  `${m.chamber}${m.district ? ` · District ${m.district}` : ''}`;

// ---------- card ----------
function StateCard({ m, index = 0, onOpen, onCompare, inCompare }) {
  const pl = m.voting?.partyLinePct;
  const missed = m.voting?.missedPct;
  return (
    <button
      type="button"
      className={`mcard ${partyClass(m.party)}`}
      onClick={() => onOpen(m)}
      style={{ animationDelay: `${Math.min(index, 20) * 28}ms` }}
    >
      {onCompare && (
        <span
          role="button" tabIndex={0}
          className={`mcard-compare ${inCompare ? 'on' : ''}`}
          title={inCompare ? 'Remove from comparison' : 'Add to comparison'}
          onClick={(e) => { e.stopPropagation(); onCompare(m.id); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onCompare(m.id); } }}
        >{inCompare ? '✓' : '+'}</span>
      )}
      <div className="mcard-head">
        <Initials member={m} />
        <div className="mcard-ident">
          <span className="mcard-name">{m.name}</span>
          <span className="mcard-seat">{seatOf(m)}{electionLine(m) ? ` · ${electionLine(m)}` : ''}</span>
          <span className={`party-tag ${partyClass(m.party)}`}>
            <span className="party-dot" aria-hidden="true" />{m.party}
          </span>
        </div>
      </div>
      <div className="mcard-stats">
        <div className="mstat">
          <span className="mstat-num">{m.billsTotal ?? 'n/a'}</span>
          <span className="mstat-label">bills</span>
        </div>
        <div className="mstat">
          <span className="mstat-num">{m.billsPrimary ?? 'n/a'}</span>
          <span className="mstat-label">as primary</span>
        </div>
        <div className="mstat">
          <span className="mstat-num">{pl != null ? `${pl}%` : 'n/a'}</span>
          <span className="mstat-label">party line</span>
          {pl != null && <span className="mini-bar"><span className="mini-fill partyline" style={{ width: `${pl}%` }} /></span>}
        </div>
        <div className="mstat">
          <span className="mstat-num">{missed != null ? `${missed}%` : 'n/a'}</span>
          <span className="mstat-label">votes missed</span>
          {missed != null && <span className="mini-bar"><span className={`mini-fill ${missed >= 20 ? 'high' : missed >= 10 ? 'mid' : 'low'}`} style={{ width: `${Math.min(100, missed)}%` }} /></span>}
        </div>
      </div>
    </button>
  );
}

// ---------- profile ----------
function StateProfile({ m, stateName, sessionName, onClose, onCompare, inCompare, allMembers = [], onCompareWith }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const bills = m.bills || [];
  const v = m.voting;
  return (
    <div className="profile-backdrop" onClick={onClose} role="presentation">
      <aside className="profile" role="dialog" aria-modal="true" aria-label={`${m.name} profile`} onClick={(e) => e.stopPropagation()}>
        <div className="profile-top">
          <button type="button" className="profile-close" onClick={onClose} aria-label="Close">×</button>
          <Initials member={m} />
          <div className="profile-ident">
            <p className="masthead-eyebrow">{stateName} · {seatOf(m)}</p>
            <h2 className="profile-name">{m.name}</h2>
            <span className={`party-tag ${partyClass(m.party)}`}><span className="party-dot" aria-hidden="true" />{m.party}</span>
            <div className="profile-links">
              {m.sourceUrl && <a href={m.sourceUrl} target="_blank" rel="noopener noreferrer" className="source-link">LegiScan ↗</a>}
              {m.ballotpedia && <a href={m.ballotpedia} target="_blank" rel="noopener noreferrer" className="source-link">Ballotpedia ↗</a>}
              {m.email && <a href={`mailto:${m.email}`} className="source-link">Email ↗</a>}
              {m.financeUrl && <a href={m.financeUrl} target="_blank" rel="noopener noreferrer" className="source-link">Campaign finance ↗</a>}
              {m.links?.[0] && <a href={m.links[0]} target="_blank" rel="noopener noreferrer" className="source-link">Official site ↗</a>}
              {onCompareWith && (
                <button type="button" className={`pill pill-sm ${pickerOpen ? 'active' : ''}`} onClick={() => setPickerOpen((v) => !v)}>
                  Compare with…
                </button>
              )}
            </div>
            {pickerOpen && (
              <div className="compare-picker">
                <label className="picker-label" htmlFor="cmp-pick-state">Pick someone to compare against {m.name.split(' ')[0]}</label>
                <select id="cmp-pick-state" className="state-select" defaultValue="" onChange={(e) => { if (e.target.value) onCompareWith(m.id, e.target.value); }}>
                  <option value="" disabled>Choose a legislator…</option>
                  {['Senate', 'House'].map((ch) => (
                    <optgroup key={ch} label={ch}>
                      {allMembers.filter((x) => x.chamber === ch && x.id !== m.id).map((x) => (
                        <option key={x.id} value={x.id}>{x.name} ({x.partyCode || '?'}{x.district ? `, D-${x.district}` : ''})</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        <div className="finance-grid profile-facts">
          <div className="finance-stat">
            <span className="finance-num">{m.nextElection || (m.termYears ? `${m.termYears}y` : 'n/a')}</span>
            <span className="finance-label">{m.nextElection ? 'next on the ballot' : m.electionNote || 'term'}</span>
          </div>
          <div className="finance-stat"><span className="finance-num">{m.billsTotal ?? 'n/a'}</span><span className="finance-label">bills sponsored · {m.billsPrimary ?? 0} as primary</span></div>
          {v?.partyLinePct != null && <div className="finance-stat"><span className="finance-num">{v.partyLinePct}%</span><span className="finance-label">votes with party</span></div>}
          {v?.missedPct != null && <div className="finance-stat"><span className="finance-num">{v.missedPct}%</span><span className="finance-label">votes missed</span></div>}
          {v && <div className="finance-stat"><span className="finance-num">{v.votesTotal}</span><span className="finance-label">roll calls this session</span></div>}
          {m.committees?.length > 0 && <div className="finance-stat"><span className="finance-num">{m.committees.length}</span><span className="finance-label">{m.committees.length === 1 ? 'committee' : 'committees'}{m.committees.some((c) => c.role !== 'Member') ? ' · leads one' : ''}</span></div>}
        </div>

        {m.committees?.length > 0 && (
          <section className="profile-section">
            <p className="bill-panel-title">Committees</p>
            <ul className="comm-list">
              {m.committees.map((c, i) => (
                <li key={i} className="comm-item">
                  <div className="comm-head">
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noopener noreferrer" className="comm-name">{c.name}</a>
                    ) : (
                      <span className="comm-name">{c.name}</span>
                    )}
                    <span className={`comm-role ${c.role !== 'Member' ? 'lead' : ''}`}>{c.role}</span>
                  </div>
                  {(c.kind === 'subcommittee' || c.chamber === 'Joint') && (
                    <p className="comm-subs">{c.kind === 'subcommittee' ? 'Subcommittee' : 'Joint committee'}</p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {v && (
          <section className="profile-section">
            <p className="bill-panel-title">Voting record · {sessionName}</p>
            <div className="finance-grid">
              <div className="finance-stat"><span className="finance-num">{v.partyLinePct ?? 'n/a'}%</span><span className="finance-label">with their party</span></div>
              <div className="finance-stat"><span className="finance-num">{v.missedPct ?? 'n/a'}%</span><span className="finance-label">votes missed</span></div>
              <div className="finance-stat"><span className="finance-num">{v.votesAgainstParty ?? 'n/a'}</span><span className="finance-label">broke with party</span></div>
            </div>
            {v.recentVotes?.length > 0 && (
              <div className="vote-list">
                {v.recentVotes.map((rv, i) => (
                  <div key={i} className="vote-row">
                    <span className={`vote-pos vote-${(rv.position || '').toLowerCase().replace(/[^a-z]/g, '')}`}>{rv.position}</span>
                    <span className="vote-desc">{rv.bill ? `${rv.bill}: ` : ''}{rv.billTitle || rv.question || rv.result}</span>
                    <span className="vote-date">{rv.date}</span>
                    {rv.billUrl && <a href={rv.billUrl} target="_blank" rel="noopener noreferrer" className="source-link vote-link" onClick={(e) => e.stopPropagation()}>bill ↗</a>}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {bills.length > 0 && (
          <section className="profile-section">
            <p className="bill-panel-title">
              {m.billsTotal > bills.length ? `${bills.length} most recent of ${m.billsTotal} sponsored` : 'Sponsored legislation'}
            </p>
            <div className="bill-grid">
              {bills.map((b, i) => (
                <article key={i} className="bill-card">
                  <p className="bill-number">{b.billNumber}{b.primary ? ' · primary' : ''}</p>
                  <h3 className="bill-title">{b.title || 'Untitled'}</h3>
                  {b.lastAction && <p className="bill-action">{b.lastAction}</p>}
                  <div className="bill-foot">
                    {b.date && <span className="bill-date">{b.date}</span>}
                    {(b.stateUrl || b.url) && <a href={b.stateUrl || b.url} target="_blank" rel="noopener noreferrer" className="source-link" onClick={(e) => e.stopPropagation()}>Full text ↗</a>}
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        <section className="profile-section">
          <p className="bill-panel-title">About this page</p>
          <p className="scope-note" style={{ margin: 0 }}>
            Votes and bills are from LegiScan; photos, contact links, and committees from
            OpenStates; term lengths from NCSL. Campaign finance is a link rather than a
            figure: every state runs its own disclosure system, and there is no single
            source that adds them up honestly. Stock-trade reporting (the STOCK Act) applies
            to Congress only, so there is no state equivalent to show.
          </p>
        </section>
      </aside>
    </div>
  );
}

// ---------- main ----------
export default function StateView({ theme }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [code, setCode] = useState(() => new URLSearchParams(window.location.search).get('st') || '');
  const [q, setQ] = useState('');
  const [party, setParty] = useState('');
  const [chamber, setChamber] = useState('');
  const [myChamber, setMyChamber] = useState('');
  const [myDistrict, setMyDistrict] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [compareIds, setCompareIds] = useState([]);
  const [tab, setTab] = useState('overview');
  const [page, setPage] = useState(0);
  const PAGE = 24;

  const [stateFile, setStateFile] = useState(null);

  // 1) index of available states
  useEffect(() => {
    (async () => {
      try {
        const bust = Math.floor(Date.now() / 3_600_000);
        const r = await fetch(`${import.meta.env.BASE_URL}state/index.json?v=${bust}`, { cache: 'no-cache' });
        if (!r.ok) throw new Error(`No state data yet (HTTP ${r.status}). Run the "Update State Data" workflow.`);
        const j = await r.json();
        setPayload(j);
        const codes = (j.states || []).map((x) => x.code);
        if (!codes.length) setError('No states loaded yet. Run the "Update State Data" workflow.');
        else if (!codes.includes(code)) setCode(codes[0]);
      } catch (e) { setError(e.message); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2) the selected state's file
  useEffect(() => {
    if (!code || !payload) return;
    setStateFile(null);
    (async () => {
      try {
        const bust = Math.floor(Date.now() / 3_600_000);
        const r = await fetch(`${import.meta.env.BASE_URL}state/${code}.json?v=${bust}`, { cache: 'no-cache' });
        if (!r.ok) throw new Error(`Could not load ${code}.json (HTTP ${r.status}).`);
        setStateFile(await r.json());
        setPage(0);
      } catch (e) { setError(e.message); }
    })();
  }, [code, payload]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'state');
    if (code) url.searchParams.set('st', code); else url.searchParams.delete('st');
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }, [code]);

  const st = stateFile;
  const legs = st?.legislators || [];
  const stateList = payload?.states || [];

  const stats = useMemo(() => {
    const byParty = {};
    for (const m of legs) byParty[m.party] = (byParty[m.party] || 0) + 1;
    return {
      total: legs.length, byParty,
      house: legs.filter((m) => m.chamber === 'House').length,
      senate: legs.filter((m) => m.chamber === 'Senate').length,
      parties: Object.keys(byParty).sort(),
    };
  }, [legs]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return legs.filter((m) =>
      (!party || m.party === party) &&
      (!chamber || m.chamber === chamber) &&
      (!needle || m.name.toLowerCase().includes(needle) || String(m.district || '').includes(needle))
    );
  }, [legs, q, party, chamber]);

  const myReps = useMemo(() => {
    if (!myChamber) return [];
    return legs.filter((m) => m.chamber === myChamber && (!myDistrict || String(m.district) === String(myDistrict)));
  }, [legs, myChamber, myDistrict]);
  const districtsFor = useMemo(() =>
    [...new Set(legs.filter((m) => m.chamber === myChamber).map((m) => m.district))].filter(Boolean)
      .sort((a, b) => Number(a) - Number(b)), [legs, myChamber]);

  const compare = useMemo(() => {
    const parties = ['Democratic', 'Republican'];
    const g = Object.fromEntries(parties.map((p) => [p, legs.filter((m) => m.party === p)]));
    const avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
    const row = (label, fmt, pick, group = 'overview', note) => ({ label, fmt, group, note, values: Object.fromEntries(parties.map((p) => [p, pick(g[p])])) });
    return [
      row('Seats held', (v) => v, (x) => x.length),
      row('Avg. votes with party', (v) => (v == null ? 'n/a' : `${Math.round(v)}%`), (x) => avg(x.filter((m) => m.voting?.partyLinePct != null).map((m) => m.voting.partyLinePct))),
      row('Avg. votes missed', (v) => (v == null ? 'n/a' : `${v.toFixed(1)}%`), (x) => avg(x.filter((m) => m.voting?.missedPct != null).map((m) => m.voting.missedPct))),
      row('Avg. bills sponsored', (v) => (v == null ? 'n/a' : v.toFixed(1)), (x) => avg(x.map((m) => m.billsTotal || 0))),
      row('Members missing 10%+ of votes', (v) => v, (x) => x.filter((m) => m.voting?.missedPct != null && m.voting.missedPct >= 10).length, 'voting'),
      row('Members who broke with party 10+ times', (v) => v, (x) => x.filter((m) => (m.voting?.votesAgainstParty || 0) >= 10).length, 'voting'),
      row('Total bills sponsored', (v) => v, (x) => x.reduce((a, m) => a + (m.billsTotal || 0), 0), 'bills'),
      row('Total primary sponsorships', (v) => v, (x) => x.reduce((a, m) => a + (m.billsPrimary || 0), 0), 'bills'),
    ];
  }, [legs]);

  const selected = legs.find((m) => m.id === selectedId) || null;
  const compareMembers = compareIds.map((id) => legs.find((m) => m.id === id)).filter(Boolean);
  const toggleCompare = (id) => setCompareIds((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]));
  const [scrollToCompare, setScrollToCompare] = useState(false);
  const compareWith = (a, b) => { setCompareIds([a, b]); setScrollToCompare(true); setSelectedId(null); };
  useEffect(() => {
    if (!scrollToCompare) return;
    const el = document.querySelector('.compare2');
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); setScrollToCompare(false); }
  }, [scrollToCompare, compareIds]);

  useEffect(() => {
    if (!selected) return;
    const onKey = (e) => e.key === 'Escape' && setSelectedId(null);
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = ''; };
  }, [selected]);

  if (error) return <div className="ct-status ct-error">{error}</div>;
  if (!payload || !st) return <div className="ct-status">Loading the state record…</div>;

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const shown = filtered.slice(page * PAGE, page * PAGE + PAGE);

  return (
    <>
      <div className="hero">
        <header className="masthead">
          <p className="masthead-eyebrow">State legislature</p>
          <h1 className="masthead-title">Who&rsquo;s serving you in {st.name}?</h1>
          <p className="masthead-dek">
            Every current member of the {st.name} Legislature ({st.session?.name}) with their
            party, what they&rsquo;ve sponsored, and how they vote. Sourced from LegiScan.
          </p>
          {payload.lastUpdated && (
            <p className="record-stamp">
              Record current as of {new Date(payload.lastUpdated).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })}
            </p>
          )}
        </header>
      </div>

      {stateList.length > 1 && stateList.length <= 8 && (
        <div className="pill-group state-picker" role="group" aria-label="Choose a state">
          {stateList.map((x) => (
            <button key={x.code} type="button" className={`pill ${code === x.code ? 'active' : ''}`} onClick={() => setCode(x.code)}>{x.name}</button>
          ))}
        </div>
      )}
      {stateList.length > 8 && (
        <div className="state-picker state-picker-select">
          <label className="picker-label" htmlFor="state-pick">State</label>
          <select id="state-pick" className="state-select" value={code} onChange={(e) => setCode(e.target.value)}>
            {stateList.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
          </select>
          <span className="result-count">{stateList.length} states loaded</span>
        </div>
      )}

      <section className="scoreboard" aria-label={`${st.name} at a glance`}>
        <div className="split-bar" role="img" aria-label="Party split">
          {stats.parties.map((p) => (
            <div key={p} className={`split-seg ${partyClass(p)}`} style={{ width: `${(stats.byParty[p] / stats.total) * 100}%` }} title={`${p}: ${stats.byParty[p]}`} />
          ))}
        </div>
        <div className="split-legend">
          {stats.parties.map((p) => (
            <span key={p} className={`legend-item ${partyClass(p)}`}><span className="party-dot" aria-hidden="true" />{p} <strong>{stats.byParty[p]}</strong></span>
          ))}
        </div>
        <div className="stat-strip">
          <div className="stat"><span className="stat-num">{stats.total}</span><span className="stat-label">legislators</span></div>
          <div className="stat"><span className="stat-num">{stats.senate}</span><span className="stat-label">state senators</span></div>
          <div className="stat"><span className="stat-num">{stats.house}</span><span className="stat-label">state representatives</span></div>
          <div className="stat stat-accent"><span className="stat-num">{st.counts?.rollCalls ?? 'n/a'}</span><span className="stat-label">roll calls this session</span></div>
        </div>
      </section>

      <section className="compare" aria-label="How the parties compare">
        <div className="compare-head">
          <div><h2 className="compare-title">How the parties compare</h2><p className="compare-sub">Same facts, side by side. No scores, just the record.</p></div>
          <div className="pill-group compare-tabs" role="tablist">
            {[['overview', 'Overview'], ['voting', 'Voting'], ['bills', 'Bills']].map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} className={`pill pill-sm ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="compare-cols">
          <span className="compare-col democratic"><span className="party-dot" aria-hidden="true" /> Democrats</span><span />
          <span className="compare-col republican">Republicans <span className="party-dot" aria-hidden="true" /></span>
        </div>
        {compare.filter((r) => r.group === tab).map((r) => {
          const d = r.values.Democratic, rp = r.values.Republican;
          const dn = typeof d === 'number' ? d : 0, rn = typeof rp === 'number' ? rp : 0, tot = dn + rn || 1;
          return (
            <div key={r.label} className="compare-row">
              <span className="compare-label">{r.label}</span>
              <span className="compare-val democratic">{r.fmt(d)}</span>
              <span className="compare-bar" aria-hidden="true"><span className="compare-fill democratic" style={{ width: `${(dn / tot) * 100}%` }} /><span className="compare-fill republican" style={{ width: `${(rn / tot) * 100}%` }} /></span>
              <span className="compare-val republican">{r.fmt(rp)}</span>
            </div>
          );
        })}
      </section>

      <section className="findreps" aria-label="Find your state legislators">
        <div className="findreps-head">
          <h2 className="findreps-title">Find your state legislators</h2>
          <p className="findreps-sub">Pick a chamber and your district. Not sure of your district? Your state&rsquo;s legislature site has a lookup by address.</p>
        </div>
        <div className="findreps-controls">
          <select className="state-select" value={myChamber} onChange={(e) => { setMyChamber(e.target.value); setMyDistrict(''); }} aria-label="Chamber">
            <option value="">Choose a chamber…</option><option value="House">State House</option><option value="Senate">State Senate</option>
          </select>
          {myChamber && (
            <select className="state-select" value={myDistrict} onChange={(e) => setMyDistrict(e.target.value)} aria-label="District">
              <option value="">All districts</option>
              {districtsFor.map((d) => <option key={d} value={d}>District {d}</option>)}
            </select>
          )}
          {myChamber && <button type="button" className="pill" onClick={() => { setMyChamber(''); setMyDistrict(''); }}>Clear</button>}
        </div>
        {myReps.length > 0 && (
          <div className="reps-grid">
            {myReps.slice(0, 12).map((m) => <StateCard key={m.id} m={m} onOpen={(x) => setSelectedId(x.id)} onCompare={toggleCompare} inCompare={compareIds.includes(m.id)} />)}
          </div>
        )}
      </section>

      <section className="toolbar" aria-label="Filter legislators">
        <input type="search" className="search-input" placeholder="Search by name or district…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
        <div className="pill-group">
          <button type="button" className={`pill ${party === '' ? 'active' : ''}`} onClick={() => setParty('')}>All parties</button>
          {stats.parties.map((p) => (
            <button key={p} type="button" className={`pill pill-${partyClass(p)} ${party === p ? 'active' : ''}`} onClick={() => { setParty(party === p ? '' : p); setPage(0); }}>{p}</button>
          ))}
        </div>
        <div className="pill-group">
          {['Senate', 'House'].map((c) => (
            <button key={c} type="button" className={`pill ${chamber === c ? 'active' : ''}`} onClick={() => { setChamber(chamber === c ? '' : c); setPage(0); }}>{c}</button>
          ))}
        </div>
        <span className="result-count">{filtered.length} of {legs.length}</span>
      </section>

      <div className="cards-grid">
        {shown.map((m, i) => <StateCard key={m.id} m={m} index={i} onOpen={(x) => setSelectedId(x.id)} onCompare={toggleCompare} inCompare={compareIds.includes(m.id)} />)}
      </div>

      <div className="pager">
        <button type="button" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>← Previous</button>
        <span className="pager-info">Page {page + 1} of {pages}</span>
        <button type="button" onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}>Next →</button>
      </div>

      {compareMembers.length > 0 && (
        <section className="compare2" aria-label="Compare two legislators">
          <div className="compare2-head">
            <h2 className="compare-title">{compareMembers.length === 2 ? 'Side by side' : 'Pick one more to compare'}</h2>
            <div className="compare2-actions"><button type="button" className="pill pill-sm" onClick={() => setCompareIds([])}>Clear</button></div>
          </div>
          <div className={`compare2-grid ${compareMembers.length === 2 ? 'two' : ''}`}>
            {compareMembers.map((m) => (
              <div key={m.id} className={`compare2-card ${partyClass(m.party)}`}>
                <div className="mcard-head">
                  <Initials member={m} />
                  <div className="mcard-ident">
                    <button type="button" className="mcard-name member-link" onClick={() => setSelectedId(m.id)}>{m.name}</button>
                    <span className="mcard-seat">{seatOf(m)}</span>
                    <span className={`party-tag ${partyClass(m.party)}`}><span className="party-dot" aria-hidden="true" />{m.party}</span>
                  </div>
                  <button type="button" className="compare2-remove" aria-label="Remove" onClick={() => toggleCompare(m.id)}>×</button>
                </div>
                <dl className="compare2-facts">
                  <div><dt>Bills sponsored</dt><dd>{m.billsTotal ?? 0} <small>{m.billsPrimary ?? 0} primary</small></dd></div>
                  <div><dt>Votes with party</dt><dd>{m.voting?.partyLinePct != null ? `${m.voting.partyLinePct}%` : 'n/a'}</dd></div>
                  <div><dt>Votes missed</dt><dd>{m.voting?.missedPct != null ? `${m.voting.missedPct}%` : 'n/a'}</dd></div>
                  <div><dt>Broke with party</dt><dd>{m.voting?.votesAgainstParty ?? 'n/a'}</dd></div>
                  <div><dt>Committees</dt><dd>{m.committees?.length ?? 0}{m.committees?.some((c) => c.role !== 'Member') ? <small> incl. leadership</small> : null}</dd></div>
                </dl>
              </div>
            ))}
          </div>
        </section>
      )}

      <footer className="colophon">
        <p>
          State data: <a href="https://legiscan.com" target="_blank" rel="noopener noreferrer">LegiScan</a> (CC BY 4.0) ·
          {' '}{st.session?.name} · dataset {st.datasetDate || 'n/a'} · updated weekly
        </p>
        <p className="colophon-note">
          Party-line is measured against each party&rsquo;s majority on each roll call; missed votes include
          &ldquo;not voting&rdquo; and absences.
          {st.counts?.former > 0 && (
            <> {st.counts.former} {st.counts.former === 1 ? 'member' : 'members'} who left office during this
            session {st.counts.former === 1 ? 'is' : 'are'} not shown; their replacements are.</>
          )}
          {st.counts?.multiMemberDistricts && (
            <> This state has multi-member districts, so members who left mid-session may still appear.</>
          )}
          {' '}For official records, verify at your state legislature&rsquo;s site.
        </p>
      </footer>

      {selected && (
        <StateProfile m={selected} stateName={st.name} sessionName={st.session?.name} onClose={() => setSelectedId(null)} onCompare={toggleCompare} inCompare={compareIds.includes(selected.id)} allMembers={legs} onCompareWith={compareWith} />
      )}
    </>
  );
}
