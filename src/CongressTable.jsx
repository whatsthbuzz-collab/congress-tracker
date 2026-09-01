import React, { useEffect, useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  createColumnHelper,
  flexRender,
} from '@tanstack/react-table';
import './CongressTable.css';

const columnHelper = createColumnHelper();

const fmtDate = (iso) => {
  if (!iso) return null;
  const d = new Date(`${iso}T00:00:00Z`);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
};

// Compact money: 1_234_567 -> "$1.2M", 45_000 -> "$45K".
const fmtMoney = (n) => {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${Math.round(n / 1_000)}K`;
  return `$${n}`;
};


// Human text for a vote row. The API list endpoint sometimes lacks a real
// question, and an older fallback stored the bill type ("HR") there — treat
// that as empty and show the result instead.
const voteText = (rv) => {
  const q = (rv.question || '').trim();
  const looksLikeType = /^(H|S)(R|RES|JRES|CONRES)?$/i.test(q);
  if (q && !looksLikeType) return q;
  return rv.result || 'Recorded vote';
};


// Draws a clean, neutral share card for one member onto a canvas and returns
// a PNG blob. No server, no image service -- runs entirely in the browser.
async function renderShareCard(m, theme) {
  const W = 1200, H = 630;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const x = c.getContext('2d');
  const dark = theme === 'dark';
  const bg = dark ? '#0d1218' : '#f3f4f1';
  const ink = dark ? '#eef2f6' : '#0f1720';
  const ink2 = dark ? '#b6c0cb' : '#4b5563';
  const partyColor = m.party === 'Democratic' ? '#2952cc' : m.party === 'Republican' ? '#c0332b' : '#7a6bae';

  x.fillStyle = bg; x.fillRect(0, 0, W, H);
  x.fillStyle = partyColor; x.fillRect(0, 0, 14, H);

  // photo (may fail cross-origin; fall back to initials)
  const px = 70, py = 90, pw = 220, ph = 268;
  try {
    const img = await new Promise((res, rej) => {
      const i = new Image(); i.crossOrigin = 'anonymous';
      i.onload = () => res(i); i.onerror = rej;
      i.src = `https://unitedstates.github.io/images/congress/450x550/${m.bioguideId}.jpg`;
    });
    x.save();
    roundRect(x, px, py, pw, ph, 18); x.clip();
    x.drawImage(img, px, py, pw, ph);
    x.restore();
  } catch {
    x.fillStyle = partyColor; roundRect(x, px, py, pw, ph, 18); x.fill();
    x.fillStyle = '#fff'; x.font = '800 96px "Libre Franklin", sans-serif';
    x.textAlign = 'center'; x.textBaseline = 'middle';
    const initials = (m.name || '').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();
    x.fillText(initials, px + pw / 2, py + ph / 2);
    x.textAlign = 'left'; x.textBaseline = 'alphabetic';
  }

  const tx = 340;
  x.fillStyle = '#c39a1a'; x.font = '600 20px "IBM Plex Mono", monospace';
  const seat = m.chamber === 'House' && m.district != null ? `${m.state} · District ${m.district}` : `${m.state} · ${m.chamber}`;
  x.fillText(seat.toUpperCase(), tx, 120);

  x.fillStyle = ink; x.font = '900 62px "Libre Franklin", sans-serif';
  wrapText(x, m.name, tx, 190, W - tx - 60, 66);

  x.fillStyle = partyColor; x.font = '700 26px "Public Sans", sans-serif';
  x.fillText(m.party, tx, 290);

  const stats = [
    [String(m.termsServed ?? '—'), m.termsServed === 1 ? 'term' : 'terms'],
    [m.nextElection || '—', 'on ballot'],
    [m.voting?.partyLinePct != null ? `${m.voting.partyLinePct}%` : '—', 'party line'],
    [m.finance?.pacPct != null ? `${m.finance.pacPct}%` : '—', 'PAC money'],
  ];
  const colW = (W - tx - 60) / 4;
  stats.forEach(([n, l], i) => {
    const sx = tx + i * colW;
    x.fillStyle = ink; x.font = '800 54px "Libre Franklin", sans-serif';
    x.fillText(n, sx, 420);
    x.fillStyle = ink2; x.font = '500 22px "Public Sans", sans-serif';
    x.fillText(l, sx, 456);
  });

  x.fillStyle = ink2; x.font = '500 20px "Public Sans", sans-serif';
  x.fillText('congress-tracker · sourced from Congress.gov, FEC, House Clerk', tx, 570);

  return new Promise((res) => c.toBlob(res, 'image/png'));
}
function roundRect(x, X, Y, W, H, r) {
  x.beginPath();
  x.moveTo(X + r, Y); x.arcTo(X + W, Y, X + W, Y + H, r); x.arcTo(X + W, Y + H, X, Y + H, r);
  x.arcTo(X, Y + H, X, Y, r); x.arcTo(X, Y, X + W, Y, r); x.closePath();
}
function wrapText(x, text, X, Y, maxW, lh) {
  const words = (text || '').split(' '); let line = ''; let y = Y;
  for (const w of words) {
    const t = line ? `${line} ${w}` : w;
    if (x.measureText(t).width > maxW && line) { x.fillText(line, X, y); line = w; y += lh; }
    else line = t;
  }
  if (line) x.fillText(line, X, y);
}


// Age from an ISO birthday, computed at render so it never goes stale.
const ageOf = (iso) => {
  if (!iso) return null;
  const b = new Date(`${iso}T00:00:00Z`);
  if (isNaN(b)) return null;
  const now = new Date();
  let a = now.getUTCFullYear() - b.getUTCFullYear();
  const m = now.getUTCMonth() - b.getUTCMonth();
  if (m < 0 || (m === 0 && now.getUTCDate() < b.getUTCDate())) a -= 1;
  return a;
};

const partyClass = (party) =>
  (party || '').toLowerCase().replace(/[^a-z]/g, '-');

// Public-domain congressional headshots, keyed by Bioguide ID, served from
// GitHub Pages. Falls back to colored initials if a photo 404s (freshmen
// sometimes lag). Two sizes: sm for rows, lg for cards.
function MemberPhoto({ member, size = 'sm' }) {
  const [failed, setFailed] = useState(false);
  const bid = member.bioguideId;
  const url = `https://unitedstates.github.io/images/congress/225x275/${bid}.jpg`;
  const initials = (member.name || '')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  if (failed || !bid) {
    return (
      <div className={`member-photo ph-${size} ph-fallback ${partyClass(member.party)}`}>
        {initials}
      </div>
    );
  }
  return (
    <img
      className={`member-photo ph-${size} ${partyClass(member.party)}`}
      src={url}
      alt={member.name}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

function MemberCard({ member, onOpen, index = 0, onCompare, inCompare }) {
  const m = member;
  const seat =
    m.chamber === 'House' && m.district != null
      ? `${m.state} · District ${m.district}`
      : `${m.state} · ${m.chamber}`;
  const pl = m.voting?.partyLinePct;
  const pac = m.finance?.pacPct;
  return (
    <button
      type="button"
      className={`mcard ${partyClass(m.party)}`}
      onClick={() => onOpen && onOpen(m)}
      style={{ animationDelay: `${Math.min(index, 20) * 28}ms` }}
    >
      <div className="mcard-head">
        <MemberPhoto member={m} size="lg" />
        <div className="mcard-ident">
          <span className="mcard-name">{m.name}</span>
          <span className="mcard-seat">
            {seat}{ageOf(m.birthday) != null ? ` · ${ageOf(m.birthday)}` : ''}
          </span>
          <span className={`party-tag ${partyClass(m.party)}`}>
            <span className="party-dot" aria-hidden="true" />
            {m.party}
          </span>
        </div>
      </div>
      {onCompare && (
        <span
          role="button"
          tabIndex={0}
          className={`mcard-compare ${inCompare ? 'on' : ''}`}
          title={inCompare ? 'Remove from comparison' : 'Add to comparison'}
          onClick={(e) => { e.stopPropagation(); onCompare(m.bioguideId); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onCompare(m.bioguideId); } }}
        >
          {inCompare ? '✓' : '+'}
        </span>
      )}
      {m.trades?.chamber === 'House' && (m.trades.ptrCount || 0) > 0 && (
        <span className="trade-badge" title="Periodic transaction reports filed this Congress">
          {m.trades.ptrCount} trade {m.trades.ptrCount === 1 ? 'report' : 'reports'}
        </span>
      )}
      <div className="mcard-stats">
        <div className="mstat">
          <span className="mstat-num">{m.termsServed ?? '—'}</span>
          <span className="mstat-label">{m.termsServed === 1 ? 'term' : 'terms'}</span>
        </div>
        <div className="mstat">
          <span className="mstat-num">{m.nextElection || '—'}</span>
          <span className="mstat-label">on ballot</span>
        </div>
        <div className="mstat">
          <span className="mstat-num">{pl != null ? `${pl}%` : '—'}</span>
          <span className="mstat-label">party line</span>
          {pl != null && (
            <span className="mini-bar" aria-hidden="true">
              <span className="mini-fill partyline" style={{ width: `${pl}%` }} />
            </span>
          )}
        </div>
        <div className="mstat">
          <span className="mstat-num">{pac != null ? `${pac}%` : '—'}</span>
          <span className="mstat-label">PAC money</span>
          {pac != null && (
            <span className="mini-bar" aria-hidden="true">
              <span
                className={`mini-fill ${pac >= 50 ? 'high' : pac >= 25 ? 'mid' : 'low'}`}
                style={{ width: `${pac}%` }}
              />
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

// Full profile for one member: a slide-over panel. Everything we know, in
// one place, every figure linked to its source. Neutral by design.
function MemberProfile({ member: m, onClose, onCompare, inCompare }) {
  const seat =
    m.chamber === 'House' && m.district != null
      ? `${m.state} · District ${m.district}`
      : `${m.state} · ${m.chamber}`;
  const bills = m.bills || [];
  const comms = m.committees || [];
  const shareUrl = `${window.location.origin}${window.location.pathname}#${m.bioguideId}`;
  const [copied, setCopied] = useState(false);

  const [sharing, setSharing] = useState(false);
  const shareCard = async () => {
    setSharing(true);
    try {
      const blob = await renderShareCard(m, document.documentElement.dataset.theme);
      const file = new File([blob], `${m.bioguideId}.png`, { type: 'image/png' });
      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: m.name, text: shareUrl, url: shareUrl });
      } else {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${m.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-congress-tracker.png`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      }
    } catch (e) {
      console.error('share failed', e);
    } finally {
      setSharing(false);
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable; the URL is still in the address bar */
    }
  };

  return (
    <div className="profile-backdrop" onClick={onClose} role="presentation">
      <aside
        className="profile"
        role="dialog"
        aria-modal="true"
        aria-label={`${m.name} profile`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="profile-top">
          <button type="button" className="profile-close" onClick={onClose} aria-label="Close">
            ×
          </button>
          <MemberPhoto member={m} size="lg" />
          <div className="profile-ident">
            <p className="masthead-eyebrow">{seat}</p>
            <h2 className="profile-name">{m.name}</h2>
            <span className={`party-tag ${partyClass(m.party)}`}>
              <span className="party-dot" aria-hidden="true" />
              {m.party}
            </span>
            <div className="profile-links">
              <a href={m.sourceUrl} target="_blank" rel="noopener noreferrer" className="source-link">
                Congress.gov ↗
              </a>
              {m.website && (
                <a href={m.website} target="_blank" rel="noopener noreferrer" className="source-link">
                  Official site ↗
                </a>
              )}
              <button type="button" className="pill pill-sm" onClick={copyLink}>
                {copied ? 'Link copied' : 'Copy link'}
              </button>
              <button type="button" className="pill pill-sm" onClick={shareCard} disabled={sharing}>
                {sharing ? 'Preparing…' : 'Share card'}
              </button>
              {onCompare && (
                <button
                  type="button"
                  className={`pill pill-sm ${inCompare ? 'active' : ''}`}
                  onClick={() => onCompare(m.bioguideId)}
                >
                  {inCompare ? 'In comparison ✓' : 'Compare'}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* headline facts */}
        <div className="finance-grid profile-facts">
          <div className="finance-stat">
            <span className="finance-num">{m.termsServed ?? '—'}</span>
            <span className="finance-label">
              {m.termsServed === 1 ? 'term' : 'terms'} · since {m.firstYearServed || '—'}
            </span>
          </div>
          {ageOf(m.birthday) != null && (
            <div className="finance-stat">
              <span className="finance-num">{ageOf(m.birthday)}</span>
              <span className="finance-label">years old</span>
            </div>
          )}
          <div className="finance-stat">
            <span className="finance-num">{m.nextElection || '—'}</span>
            <span className="finance-label">next on the ballot</span>
          </div>
          {m.lawsEnacted > 0 && (
            <div className="finance-stat">
              <span className="finance-num">{m.lawsEnacted}</span>
              <span className="finance-label">
                {m.lawsEnacted === 1 ? 'law enacted' : 'laws enacted'} this Congress
              </span>
            </div>
          )}
          {m.voting?.partyLinePct != null && (
            <div className="finance-stat">
              <span className="finance-num">{m.voting.partyLinePct}%</span>
              <span className="finance-label">votes with party (House)</span>
            </div>
          )}
          {m.finance?.pacPct != null && (
            <div className="finance-stat">
              <span className="finance-num">{m.finance.pacPct}%</span>
              <span className="finance-label">of money from PACs</span>
            </div>
          )}
        </div>

        {/* committees */}
        {comms.length > 0 && (
          <section className="profile-section">
            <p className="bill-panel-title">Committees</p>
            <ul className="comm-list">
              {comms.map((c) => (
                <li key={c.id} className="comm-item">
                  <div className="comm-head">
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noopener noreferrer" className="comm-name">
                        {c.name}
                      </a>
                    ) : (
                      <span className="comm-name">{c.name}</span>
                    )}
                    <span className={`comm-role ${c.role !== 'Member' ? 'lead' : ''}`}>
                      {c.role}
                    </span>
                  </div>
                  {c.subcommittees?.length > 0 && (
                    <p className="comm-subs">{c.subcommittees.join(' · ')}</p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* stock trade disclosures */}
        {m.trades && (
          <section className="profile-section">
            <p className="bill-panel-title">Stock trade disclosures</p>
            {m.trades.chamber === 'House' ? (
              <>
                <div className="finance-grid">
                  <div className="finance-stat">
                    <span className="finance-num">{m.trades.ptrCount ?? 0}</span>
                    <span className="finance-label">
                      {m.trades.ptrCount === 1 ? 'trade report' : 'trade reports'} this Congress
                    </span>
                  </div>
                  {m.trades.latestFilingDate && (
                    <div className="finance-stat">
                      <span className="finance-num">{fmtDate(m.trades.latestFilingDate)}</span>
                      <span className="finance-label">most recent filing</span>
                    </div>
                  )}
                </div>
                {m.trades.filings?.length > 0 ? (
                  <div className="filing-list">
                    {m.trades.filings.map((f, i) => (
                      <a
                        key={f.docId || i}
                        href={f.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="filing-chip"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {f.date ? new Date(`${f.date}T00:00:00Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : 'Filing'} ↗
                      </a>
                    ))}
                    {m.trades.ptrCount > m.trades.filings.length && (
                      <span className="filing-more">+{m.trades.ptrCount - m.trades.filings.length} more</span>
                    )}
                  </div>
                ) : (
                  <p className="scope-note" style={{ margin: 0 }}>
                    No periodic transaction reports on file this Congress.
                  </p>
                )}
                <p className="scope-note" style={{ marginTop: '0.75rem', marginBottom: '0.5rem' }}>
                  {m.trades.note}
                </p>
              </>
            ) : (
              <p className="scope-note" style={{ margin: '0 0 0.5rem' }}>{m.trades.note}</p>
            )}
            {m.trades.sourceUrl && (
              <a href={m.trades.sourceUrl} target="_blank" rel="noopener noreferrer" className="source-link finance-source">
                {m.trades.chamber === 'House' ? 'House Clerk disclosures ↗' : 'Search Senate disclosures ↗'}
              </a>
            )}
          </section>
        )}

        {/* money */}
        {m.finance && (
          <section className="profile-section">
            <p className="bill-panel-title">
              Campaign finance{m.finance.financeCycle ? ` · ${m.finance.financeCycle} cycle` : ''}
            </p>
            <div className="finance-grid">
              <div className="finance-stat">
                <span className="finance-num">{fmtMoney(m.finance.totalRaised)}</span>
                <span className="finance-label">total raised</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{fmtMoney(m.finance.fromPacs)}</span>
                <span className="finance-label">from PACs ({m.finance.pacPct ?? '—'}%)</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{fmtMoney(m.finance.fromIndividuals)}</span>
                <span className="finance-label">from individuals ({m.finance.individualPct ?? '—'}%)</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{fmtMoney(m.finance.cashOnHand)}</span>
                <span className="finance-label">cash on hand</span>
              </div>
            </div>
            {m.finance.financeSourceUrl && (
              <a href={m.finance.financeSourceUrl} target="_blank" rel="noopener noreferrer" className="source-link finance-source">
                Full FEC filings ↗
              </a>
            )}
          </section>
        )}

        {/* votes */}
        {m.voting && (
          <section className="profile-section">
            <p className="bill-panel-title">Voting record · House · last {m.voting.votesTotal} roll calls</p>
            <div className="finance-grid">
              <div className="finance-stat">
                <span className="finance-num">{m.voting.partyLinePct ?? '—'}%</span>
                <span className="finance-label">with their party</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{m.voting.missedPct ?? '—'}%</span>
                <span className="finance-label">votes missed</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{m.voting.votesAgainstParty ?? '—'}</span>
                <span className="finance-label">broke with party</span>
              </div>
            </div>
            {m.voting.recentVotes?.length > 0 && (
              <div className="vote-list">
                {m.voting.recentVotes.map((rv, i) => (
                  <div key={i} className="vote-row">
                    <span className={`vote-pos vote-${(rv.position || '').toLowerCase().replace(/[^a-z]/g, '')}`}>
                      {rv.position}
                    </span>
                    <span className="vote-desc">
                      {rv.bill ? `${rv.bill} — ` : ''}
                      {voteText(rv)}
                    </span>
                    <span className="vote-date">{rv.date}</span>
                    {rv.billUrl && (
                      <a href={rv.billUrl} target="_blank" rel="noopener noreferrer" className="source-link vote-link">
                        bill ↗
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
        {!m.voting && m.chamber === 'Senate' && (
          <section className="profile-section">
            <p className="bill-panel-title">Voting record</p>
            <p className="scope-note" style={{ margin: 0 }}>
              Senate roll-call votes aren&rsquo;t yet available through the
              Congress.gov API. This will fill in automatically when they are.
            </p>
          </section>
        )}

        {/* bills */}
        {bills.length > 0 && (
          <section className="profile-section">
            <p className="bill-panel-title">
              {m.billsTotal && m.billsTotal > bills.length
                ? `${bills.length} most recent of ${m.billsTotal} sponsored`
                : 'Sponsored legislation'}
            </p>
            <div className="bill-grid">
              {bills.map((bill, idx) => (
                <article key={idx} className="bill-card">
                  <p className="bill-number">{bill.billNumber}</p>
                  <h3 className="bill-title">{bill.title || 'Untitled measure'}</h3>
                  {bill.latestAction && <p className="bill-action">{bill.latestAction}</p>}
                  <div className="bill-foot">
                    {bill.introducedDate && (
                      <span className="bill-date">Introduced {fmtDate(bill.introducedDate)}</span>
                    )}
                    {bill.sourceUrl && (
                      <a href={bill.sourceUrl} target="_blank" rel="noopener noreferrer" className="source-link">
                        Full text ↗
                      </a>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}
      </aside>
    </div>
  );
}


// "How well do you know Congress?" — a short quiz generated from the live
// data. It tests the reader's *knowledge of the record*, never ranks members,
// and every answer reveals the sourced fact. Questions are built fresh each
// time from a random sample so it stays interesting.
function CongressQuiz({ data, onOpenProfile }) {
  const [open, setOpen] = useState(false);
  const [qs, setQs] = useState([]);
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState(null);
  const [score, setScore] = useState(0);

  const pick = (arr, n) => [...arr].sort(() => Math.random() - 0.5).slice(0, n);

  const build = () => {
    const pool = data.filter((m) => m.name && m.party);
    const withPL = pool.filter((m) => m.voting?.partyLinePct != null);
    const withPac = pool.filter((m) => m.finance?.pacPct != null);
    const out = [];

    // Q type 1: which state does X represent?
    for (const m of pick(pool, 2)) {
      const wrong = pick([...new Set(pool.map((x) => x.state))].filter((st) => st !== m.state), 3);
      out.push({ kind: 'state', m, prompt: `Which state does ${m.name} represent?`,
        options: pick([m.state, ...wrong], 4), answer: m.state,
        reveal: `${m.name} represents ${m.state} in the ${m.chamber}.` });
    }
    // Q type 2: who has served longer?
    const [a, b] = pick(pool.filter((m) => m.termsServed), 2);
    if (a && b && a.termsServed !== b.termsServed) {
      const w = a.termsServed > b.termsServed ? a : b; const l = w === a ? b : a;
      out.push({ kind: 'tenure', m: w, prompt: 'Who has served more terms in Congress?',
        options: [a.name, b.name], answer: w.name,
        reveal: `${w.name}: ${w.termsServed} terms (since ${w.firstYearServed}). ${l.name}: ${l.termsServed} (since ${l.firstYearServed}).` });
    }
    // Q type 3: party-line guess (bucketed)
    if (withPL.length) {
      const m = pick(withPL, 1)[0];
      const v = m.voting.partyLinePct;
      const bucket = v >= 95 ? '95–100%' : v >= 85 ? '85–94%' : v >= 70 ? '70–84%' : 'Under 70%';
      out.push({ kind: 'pl', m, prompt: `How often does ${m.name} vote with their party on House roll calls?`,
        options: ['Under 70%', '70–84%', '85–94%', '95–100%'], answer: bucket,
        reveal: `${m.name} voted with the ${m.party} majority ${v}% of the time across the last ${m.voting.votesTotal} House roll calls.` });
    }
    // Q type 4: PAC share guess
    if (withPac.length) {
      const m = pick(withPac, 1)[0];
      const v = m.finance.pacPct;
      const bucket = v >= 50 ? 'Half or more' : v >= 25 ? 'About a quarter to half' : v > 0 ? 'Some, under a quarter' : 'None';
      out.push({ kind: 'pac', m, prompt: `How much of ${m.name}'s campaign money comes from PACs?`,
        options: ['None', 'Some, under a quarter', 'About a quarter to half', 'Half or more'], answer: bucket,
        reveal: `${v}% of ${m.name}'s ${m.finance.financeCycle || ''} cycle money came from PACs (${fmtMoney(m.finance.fromPacs)} of ${fmtMoney(m.finance.totalRaised)} raised).` });
    }
    // Q type 4b: who is older?
    const withAge = pool.filter((m) => ageOf(m.birthday) != null);
    const [p1, p2] = pick(withAge, 2);
    if (p1 && p2 && ageOf(p1.birthday) !== ageOf(p2.birthday)) {
      const older = ageOf(p1.birthday) > ageOf(p2.birthday) ? p1 : p2; const younger = older === p1 ? p2 : p1;
      out.push({ kind: 'age', m: older, prompt: 'Who is older?',
        options: [p1.name, p2.name], answer: older.name,
        reveal: `${older.name} is ${ageOf(older.birthday)}; ${younger.name} is ${ageOf(younger.birthday)}.` });
    }
    // Q type 5: how many members are on the ballot next?
    const yrs = data.map((m) => parseInt(m.nextElection, 10)).filter((y) => !isNaN(y) && y % 2 === 0);
    if (yrs.length) {
      const ny = Math.min(...yrs);
      const n = data.filter((m) => parseInt(m.nextElection, 10) === ny).length;
      const opts = pick([n, Math.round(n * 0.5), Math.round(n * 0.75), Math.min(537, Math.round(n * 1.15))].map(String), 4);
      out.push({ kind: 'ballot', prompt: `How many members of Congress are on the ballot in ${ny}?`,
        options: opts.includes(String(n)) ? opts : [String(n), ...opts.slice(0, 3)], answer: String(n),
        reveal: `${n} of ${data.length} members face voters in ${ny}: the whole House plus a third of the Senate.` });
    }
    return pick(out, Math.min(5, out.length));
  };

  const start = () => { setQs(build()); setI(0); setPicked(null); setScore(0); setOpen(true); };
  const q = qs[i];
  const done = open && qs.length > 0 && i >= qs.length;

  return (
    <section className="quiz" aria-label="How well do you know Congress">
      {!open ? (
        <div className="quiz-intro">
          <div>
            <h2 className="compare-title">How well do you know Congress?</h2>
            <p className="compare-sub">Five quick questions, built from the live record. Every answer shows the source.</p>
          </div>
          <button type="button" className="pill active" onClick={start} disabled={!data.length}>Start</button>
        </div>
      ) : done ? (
        <div className="quiz-intro">
          <div>
            <h2 className="compare-title">You got {score} of {qs.length}</h2>
            <p className="compare-sub">
              {score === qs.length ? 'Perfect. You should probably run for something.' :
               score >= qs.length - 1 ? 'Sharp. The record has few surprises for you.' :
               'The record is full of surprises. That is rather the point.'}
            </p>
          </div>
          <div className="compare2-actions">
            <button type="button" className="pill active" onClick={start}>Play again</button>
            <button type="button" className="pill" onClick={() => setOpen(false)}>Close</button>
          </div>
        </div>
      ) : q ? (
        <div className="quiz-q">
          <p className="masthead-eyebrow">Question {i + 1} of {qs.length}</p>
          <h3 className="quiz-prompt">{q.prompt}</h3>
          <div className="quiz-opts">
            {q.options.map((o) => {
              const state = picked == null ? '' : o === q.answer ? 'right' : o === picked ? 'wrong' : 'dim';
              return (
                <button key={o} type="button" className={`quiz-opt ${state}`} disabled={picked != null}
                  onClick={() => { setPicked(o); if (o === q.answer) setScore((s) => s + 1); }}>
                  {o}
                </button>
              );
            })}
          </div>
          {picked != null && (
            <div className="quiz-reveal">
              <p>{q.reveal}</p>
              <div className="compare2-actions">
                {q.m && <button type="button" className="pill pill-sm" onClick={() => onOpenProfile(q.m)}>See the record</button>}
                <button type="button" className="pill pill-sm active" onClick={() => { setI(i + 1); setPicked(null); }}>
                  {i + 1 < qs.length ? 'Next' : 'Finish'}
                </button>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

export default function CongressTable() {
  const [data, setData] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [lawsByParty, setLawsByParty] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [globalFilter, setGlobalFilter] = useState('');
  const [partyFilter, setPartyFilter] = useState('');
  const [chamberFilter, setChamberFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [viewMode, setViewMode] = useState('cards'); // 'cards' | 'table'
  const [theme, setTheme] = useState(() => {
    try {
      const saved = localStorage.getItem('ct-theme');
      if (saved === 'dark' || saved === 'light') return saved;
    } catch { /* private mode etc. */ }
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('ct-theme', theme); } catch { /* ignore */ }
  }, [theme]);

  const [myState, setMyState] = useState('');
  const [myDistrict, setMyDistrict] = useState('');
  // Profile panel. Synced to the URL hash (#S000148) so any member's page is
  // linkable and shareable — the foundation for share cards later.
  const [selectedId, setSelectedId] = useState(() =>
    (window.location.hash || '').replace(/^#/, '') || null
  );

  useEffect(() => {
    const onHash = () =>
      setSelectedId((window.location.hash || '').replace(/^#/, '') || null);
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // Compare two members. Kept in the URL (?compare=ID,ID) so it's shareable.
  const [compareIds, setCompareIds] = useState(() => {
    const q = new URLSearchParams(window.location.search).get('compare') || '';
    return q.split(',').map((x) => x.trim()).filter(Boolean).slice(0, 2);
  });
  useEffect(() => {
    const url = new URL(window.location.href);
    if (compareIds.length) url.searchParams.set('compare', compareIds.join(','));
    else url.searchParams.delete('compare');
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }, [compareIds]);
  const toggleCompare = (id) =>
    setCompareIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev.slice(-1), id]
    );
  const compareMembers = useMemo(
    () => compareIds.map((id) => data.find((m) => m.bioguideId === id)).filter(Boolean),
    [compareIds, data]
  );

  const openProfile = (m) => {
    window.location.hash = m.bioguideId;
  };
  const closeProfile = () => {
    // Clear the hash without leaving a "#" in the URL.
    history.replaceState(null, '', window.location.pathname + window.location.search);
    setSelectedId(null);
  };

  useEffect(() => {
    if (!selectedId) return;
    const onKey = (e) => e.key === 'Escape' && closeProfile();
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [selectedId]);
  const [expanded, setExpanded] = useState(() => new Set());

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        // Cache-bust with a coarse timestamp (changes hourly) so an updated
        // congress_data.json isn't masked by a stale browser/CDN copy.
        const bust = Math.floor(Date.now() / 3_600_000);
        const response = await fetch(
          `${import.meta.env.BASE_URL}congress_data.json?v=${bust}`
        );
        if (!response.ok) {
          throw new Error(
            `Could not load congress_data.json (HTTP ${response.status}). ` +
            `The data file may not exist yet — check the "Update Congressional Data" ` +
            `workflow in the Actions tab.`
          );
        }
        const json = await response.json();
        setData(json.members || []);
        setLastUpdated(json.lastUpdated || null);
        setLawsByParty(json.lawsByParty || null);
      } catch (err) {
        setError(err.message);
        console.error('Error fetching congressional data:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const toggleRow = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // ---- headline stats, computed from the live data ----
  const stats = useMemo(() => {
    const total = data.length;
    const byParty = {};
    let upNext = 0;
    let nextYear = null;

    for (const m of data) {
      byParty[m.party] = (byParty[m.party] || 0) + 1;
      const y = parseInt(m.nextElection, 10);
      // Skip odd years — federal general elections are even years; an odd year
      // catches only a few special elections and misleads (showed "2").
      if (!isNaN(y) && y % 2 === 0) {
        if (nextYear === null || y < nextYear) nextYear = y;
      }
    }
    if (nextYear !== null) {
      upNext = data.filter((m) => parseInt(m.nextElection, 10) === nextYear).length;
    }

    const senate = data.filter((m) => m.chamber === 'Senate').length;
    const house = data.filter((m) => m.chamber === 'House').length;

    return { total, byParty, upNext, nextYear, senate, house };
  }, [data]);

  // Side-by-side party comparison. All neutral facts computed from the data
  // we already hold; laws-enacted arrives from the payload when available.
  const partyCompare = useMemo(() => {
    const parties = ['Democratic', 'Republican'];
    const groups = Object.fromEntries(parties.map((p) => [p, data.filter((m) => m.party === p)]));
    const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);

    const row = (label, fmt, pick, note) => ({
      label,
      note,
      values: Object.fromEntries(parties.map((p) => [p, pick(groups[p])])),
      fmt,
    });

    const rows = [
      row('Seats held', (v) => v, (g) => g.length),
      row('On the ballot in 2026', (v) => v,
        (g) => g.filter((m) => m.nextElection === '2026').length),
      row('Avg. votes with party (House)', (v) => (v == null ? '—' : `${Math.round(v)}%`),
        (g) => avg(g.filter((m) => m.voting?.partyLinePct != null).map((m) => m.voting.partyLinePct)),
        'House roll calls only'),
      row('Share of money from PACs', (v) => (v == null ? '—' : `${Math.round(v)}%`),
        (g) => {
          const pac = g.reduce((a, m) => a + (m.finance?.fromPacs || 0), 0);
          const ind = g.reduce((a, m) => a + (m.finance?.fromIndividuals || 0), 0);
          return pac + ind ? (pac / (pac + ind)) * 100 : null;
        }),
      row('Avg. terms served', (v) => (v == null ? '—' : v.toFixed(1)),
        (g) => avg(g.filter((m) => m.termsServed).map((m) => m.termsServed))),
      row('Avg. age', (v) => (v == null ? '—' : v.toFixed(1)),
        (g) => avg(g.map((m) => ageOf(m.birthday)).filter((a) => a != null))),
      row('First-term members', (v) => v,
        (g) => g.filter((m) => m.termsServed === 1).length),
      row('Avg. votes missed (House)', (v) => (v == null ? '—' : `${v.toFixed(1)}%`),
        (g) => avg(g.filter((m) => m.voting?.missedPct != null).map((m) => m.voting.missedPct)),
        'House roll calls only — Senate attendance is not yet in the Congress.gov API'),
      row('Members missing 10%+ of votes (House)', (v) => v,
        (g) => g.filter((m) => m.voting?.missedPct != null && m.voting.missedPct >= 10).length,
        'House only'),
      row('Members taking zero PAC money', (v) => v,
        (g) => g.filter((m) => m.finance?.pacPct === 0).length),
      row('Total raised this cycle', (v) => (v == null ? '—' : fmtMoney(v)),
        (g) => g.reduce((a, m) => a + (m.finance?.totalRaised || 0), 0) || null),
    ];

    const anyTrades = data.some((m) => m.trades?.chamber === 'House');
    if (anyTrades) {
      rows.push(
        row('House members disclosing stock trades', (v) => v,
          (g) => g.filter((m) => m.trades?.chamber === 'House' && (m.trades.ptrCount || 0) > 0).length,
          'This Congress, per House Clerk filings. Senate not automatable.')
      );
    }

    if (lawsByParty && lawsByParty.total) {
      rows.push(
        row('Laws enacted this Congress', (v) => v,
          (g) => (g.length ? lawsByParty[g[0].party] ?? 0 : 0),
          'By sponsor party. The majority party structurally passes more; some laws are ceremonial.')
      );
    }
    return { parties, rows };
  }, [data, lawsByParty]);

  const columns = useMemo(
    () => [
      columnHelper.accessor('name', {
        id: 'member',
        header: 'Member',
        cell: (info) => {
          const m = info.row.original;
          const seat =
            m.chamber === 'House' && m.district != null
              ? `${m.state} · District ${m.district}`
              : `${m.state} · ${m.chamber}`;
          return (
            <div className="member-cell">
              <MemberPhoto member={m} size="sm" />
              <div className="member-ident">
                <button
                  type="button"
                  className="member-name member-link"
                  onClick={(e) => {
                    e.stopPropagation();
                    openProfile(m);
                  }}
                >
                  {info.getValue()}
                </button>
                <span className="member-seat">{seat}</span>
              </div>
            </div>
          );
        },
      }),
      columnHelper.accessor('party', {
        header: 'Party',
        cell: (info) => {
          const party = info.getValue() || '';
          return (
            <span className={`party-tag ${partyClass(party)}`}>
              <span className="party-dot" aria-hidden="true" />
              {party || '—'}
            </span>
          );
        },
        filterFn: 'equalsString',
      }),
      columnHelper.accessor('chamber', {
        header: 'Chamber',
        cell: (info) => info.getValue() || '—',
        filterFn: 'equalsString',
      }),
      columnHelper.accessor('termsServed', {
        id: 'tenure',
        header: 'Tenure',
        cell: (info) => {
          const m = info.row.original;
          const terms = info.getValue();
          return (
            <div className="num-cell">
              <span className="num-main">
                {terms ?? '—'}
                <span className="num-unit"> {terms === 1 ? 'term' : 'terms'}</span>
              </span>
              {m.firstYearServed && (
                <span className="num-sub">since {m.firstYearServed}</span>
              )}
            </div>
          );
        },
      }),
      columnHelper.accessor((row) => row.nextElection || '', {
        id: 'term',
        header: 'Term',
        cell: (info) => {
          const m = info.row.original;
          return (
            <div className="num-cell">
              <span className="num-main">{fmtDate(m.termStart) || '—'}</span>
              {m.nextElection && (
                <span className="num-sub">on ballot {m.nextElection}</span>
              )}
            </div>
          );
        },
      }),
      columnHelper.accessor('bills', {
        header: 'Bills',
        enableSorting: false,
        cell: (info) => {
          const m = info.row.original;
          const bills = info.getValue() || [];
          if (bills.length === 0) {
            return <span className="bills-none">None on file</span>;
          }
          const isOpen = expanded.has(m.bioguideId);
          // Show the true total when we have it; "15+" style is misleading, so
          // if the total exceeds what we display we show the real number.
          const total = m.billsTotal;
          const label =
            total && total > bills.length
              ? `${total} bills`
              : `${bills.length} ${bills.length === 1 ? 'bill' : 'bills'}`;
          return (
            <button
              type="button"
              className={`bills-toggle ${isOpen ? 'open' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                toggleRow(m.bioguideId);
              }}
              aria-expanded={isOpen}
            >
              {label}
              <span className="chevron" aria-hidden="true">
                {isOpen ? '▴' : '▾'}
              </span>
            </button>
          );
        },
      }),
      columnHelper.accessor((row) => row.voting?.partyLinePct ?? -1, {
        id: 'partyline',
        header: () => (
          <span className="th-with-note">
            Party Line
            <span className="th-note">House only</span>
          </span>
        ),
        cell: (info) => {
          const v = info.row.original.voting;
          if (!v || v.partyLinePct == null) {
            return <span className="bills-none">—</span>;
          }
          return (
            <div
              className="fund-cell"
              title={`Votes with own party ${v.partyLinePct}% of the time · missed ${v.missedPct ?? 0}%`}
            >
              <div className="fund-bar" aria-hidden="true">
                <div
                  className="fund-fill partyline"
                  style={{ width: `${v.partyLinePct}%` }}
                />
              </div>
              <span className="fund-pct">{v.partyLinePct}%</span>
            </div>
          );
        },
      }),
      columnHelper.accessor((row) => row.finance?.pacPct ?? -1, {
        id: 'funding',
        header: 'PAC money',
        cell: (info) => {
          const f = info.row.original.finance;
          if (!f || f.pacPct == null) {
            return <span className="bills-none">—</span>;
          }
          // A quick visual read: how much of their money is PAC money.
          const level =
            f.pacPct >= 50 ? 'high' : f.pacPct >= 25 ? 'mid' : 'low';
          return (
            <div className="fund-cell" title={`${f.pacPct}% from PACs, ${f.individualPct}% from individuals`}>
              <div className="fund-bar" aria-hidden="true">
                <div
                  className={`fund-fill ${level}`}
                  style={{ width: `${f.pacPct}%` }}
                />
              </div>
              <span className="fund-pct">{f.pacPct}%</span>
            </div>
          );
        },
      }),
      columnHelper.accessor('sourceUrl', {
        header: 'Record',
        enableSorting: false,
        cell: (info) =>
          info.getValue() ? (
            <a
              href={info.getValue()}
              target="_blank"
              rel="noopener noreferrer"
              className="source-link"
              title="View on Congress.gov"
              onClick={(e) => e.stopPropagation()}
            >
              View ↗
            </a>
          ) : (
            '—'
          ),
      }),
    ],
    [expanded]
  );

  const columnFilters = useMemo(() => {
    const f = [];
    if (partyFilter) f.push({ id: 'party', value: partyFilter });
    if (chamberFilter) f.push({ id: 'chamber', value: chamberFilter });
    return f;
  }, [partyFilter, chamberFilter]);

  // State filtering is applied to the data itself (simplest correct approach,
  // since the state now lives inside the composite Member cell).
  const filteredData = useMemo(
    () => (stateFilter ? data.filter((m) => m.state === stateFilter) : data),
    [data, stateFilter]
  );

  // "Find my reps": given a state (and optional House district), pull the
  // user's own delegation — both senators plus their one representative.
  const myReps = useMemo(() => {
    if (!myState) return [];
    return data
      .filter((m) => m.state === myState)
      .filter((m) => {
        if (m.chamber === 'Senate') return true;
        if (!myDistrict) return true; // show all House members until district picked
        return String(m.district) === String(myDistrict);
      })
      .sort((a, b) => (a.chamber === 'Senate' ? -1 : 1));
  }, [data, myState, myDistrict]);

  const selectedMember = useMemo(
    () => (selectedId ? data.find((m) => m.bioguideId === selectedId) || null : null),
    [data, selectedId]
  );

  const myDistricts = useMemo(() => {
    if (!myState) return [];
    return [
      ...new Set(
        data
          .filter((m) => m.state === myState && m.chamber === 'House')
          .map((m) => m.district)
      ),
    ]
      .filter((d) => d != null)
      .sort((a, b) => a - b);
  }, [data, myState]);

  const table = useReactTable({
    data: filteredData,
    columns,
    state: {
      globalFilter,
      columnFilters,
    },
    onGlobalFilterChange: setGlobalFilter,
    getFilteredRowModel: getFilteredRowModel(),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: { pageSize: 25 },
      // Chamber now appears in the Member seat line; hide the column to
      // save width. The Senate/House pills still filter on it.
      columnVisibility: { chamber: false },
    },
  });

  const parties = useMemo(
    () => [...new Set(data.map((d) => d.party))].filter(Boolean).sort(),
    [data]
  );
  const states = useMemo(
    () => [...new Set(data.map((d) => d.state))].filter(Boolean).sort(),
    [data]
  );

  const colCount = columns.length;

  if (loading) {
    return (
      <div className="ct-shell">
        <div className="ct-status">Loading the record…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="ct-shell">
        <div className="ct-status ct-error">{error}</div>
      </div>
    );
  }

  return (
    <div className="ct-shell">
      {/* ---------- masthead ---------- */}
      <button
        type="button"
        className="theme-toggle"
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      >
        {theme === 'dark' ? (
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <circle cx="12" cy="12" r="4" fill="currentColor" />
            <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="12" y1="2" x2="12" y2="5" /><line x1="12" y1="19" x2="12" y2="22" />
              <line x1="2" y1="12" x2="5" y2="12" /><line x1="19" y1="12" x2="22" y2="12" />
              <line x1="4.9" y1="4.9" x2="7" y2="7" /><line x1="17" y1="17" x2="19.1" y2="19.1" />
              <line x1="4.9" y1="19.1" x2="7" y2="17" /><line x1="17" y1="7" x2="19.1" y2="4.9" />
            </g>
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" fill="currentColor" />
          </svg>
        )}
        <span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
      </button>

      <header className="masthead">
        <p className="masthead-eyebrow">The Public Record</p>
        <h1 className="masthead-title">Who&rsquo;s serving you in Congress?</h1>
        <p className="masthead-dek">
          Every current member — their party, their tenure, what they&rsquo;ve
          sponsored, and when they&rsquo;re next on your ballot. Every number
          links back to the official record.
        </p>
        {lastUpdated && (
          <p className="record-stamp">
            Record current as of{' '}
            {new Date(lastUpdated).toLocaleDateString(undefined, {
              month: 'long',
              day: 'numeric',
              year: 'numeric',
            })}
          </p>
        )}
      </header>

      {/* ---------- chamber split + stat strip ---------- */}
      <section className="scoreboard" aria-label="Congress at a glance">
        <div className="split-bar" role="img" aria-label="Party split of Congress">
          {parties.map((p) => {
            const n = stats.byParty[p] || 0;
            if (!n) return null;
            return (
              <div
                key={p}
                className={`split-seg ${partyClass(p)}`}
                style={{ width: `${(n / stats.total) * 100}%` }}
                title={`${p}: ${n}`}
              />
            );
          })}
        </div>
        <div className="split-legend">
          {parties.map((p) => (
            <span key={p} className={`legend-item ${partyClass(p)}`}>
              <span className="party-dot" aria-hidden="true" />
              {p} <strong>{stats.byParty[p] || 0}</strong>
            </span>
          ))}
        </div>

        <div className="stat-strip">
          <div className="stat">
            <span className="stat-num">{stats.total}</span>
            <span className="stat-label">members</span>
          </div>
          <div className="stat">
            <span className="stat-num">{stats.senate}</span>
            <span className="stat-label">senators</span>
          </div>
          <div className="stat">
            <span className="stat-num">{stats.house}</span>
            <span className="stat-label">representatives</span>
          </div>
          {stats.nextYear && (
            <div className="stat stat-accent">
              <span className="stat-num">{stats.upNext}</span>
              <span className="stat-label">on the ballot in {stats.nextYear}</span>
            </div>
          )}
        </div>
      </section>

      {/* ---------- party comparison ---------- */}
      {data.length > 0 && (
        <section className="compare" aria-label="How the parties compare">
          <div className="compare-head">
            <h2 className="compare-title">How the parties compare</h2>
            <p className="compare-sub">
              Same facts, side by side. No scores — just the record.
            </p>
          </div>
          <div className="compare-cols">
            <span className="compare-col democratic">
              <span className="party-dot" aria-hidden="true" /> Democrats
            </span>
            <span />
            <span className="compare-col republican">
              Republicans <span className="party-dot" aria-hidden="true" />
            </span>
          </div>
          {partyCompare.rows.map((r) => {
            const d = r.values.Democratic;
            const rp = r.values.Republican;
            const dn = typeof d === 'number' ? d : 0;
            const rn = typeof rp === 'number' ? rp : 0;
            const tot = dn + rn || 1;
            return (
              <div key={r.label} className="compare-row">
                <span className="compare-val democratic">{r.fmt(d)}</span>
                <div className="compare-mid">
                  <span className="compare-label">{r.label}</span>
                  <span className="compare-bar" aria-hidden="true">
                    <span className="compare-fill democratic" style={{ width: `${(dn / tot) * 100}%` }} />
                    <span className="compare-fill republican" style={{ width: `${(rn / tot) * 100}%` }} />
                  </span>
                  {r.note && <span className="compare-note">{r.note}</span>}
                </div>
                <span className="compare-val republican">{r.fmt(rp)}</span>
              </div>
            );
          })}
          {lawsByParty?.sourceUrl && (
            <p className="compare-foot">
              Laws enacted:{' '}
              <a href={lawsByParty.sourceUrl} target="_blank" rel="noopener noreferrer">
                Congress.gov public laws, {lawsByParty.congress}th Congress ↗
              </a>
              {lawsByParty.Independent ? ` · ${lawsByParty.Independent} sponsored by Independents` : ''}
              {lawsByParty.Unknown ? ` · ${lawsByParty.Unknown} by former members` : ''}
            </p>
          )}
        </section>
      )}

      {/* ---------- find my reps ---------- */}
      <section className="findreps" aria-label="Find your representatives">
        <div className="findreps-head">
          <h2 className="findreps-title">Find your representatives</h2>
          <p className="findreps-sub">
            Pick your state — and your House district — to see the three people
            who represent you in Washington.
          </p>
        </div>
        <div className="findreps-controls">
          <select
            className="state-select"
            value={myState}
            onChange={(e) => {
              setMyState(e.target.value);
              setMyDistrict('');
            }}
            aria-label="Your state"
          >
            <option value="">Choose your state…</option>
            {states.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {myState && myDistricts.length > 0 && (
            <select
              className="state-select"
              value={myDistrict}
              onChange={(e) => setMyDistrict(e.target.value)}
              aria-label="Your House district"
            >
              <option value="">All districts</option>
              {myDistricts.map((d) => (
                <option key={d} value={d}>
                  District {d}
                </option>
              ))}
            </select>
          )}
          {myState && (
            <button
              type="button"
              className="pill"
              onClick={() => {
                setMyState('');
                setMyDistrict('');
              }}
            >
              Clear
            </button>
          )}
        </div>
        {myReps.length > 0 && (
          <div className="reps-grid">
            {myReps.map((m) => (
              <MemberCard
                key={m.bioguideId}
                member={m}
                onOpen={openProfile}
              />
            ))}
          </div>
        )}
      </section>

      {/* ---------- filters ---------- */}
      <section className="toolbar" aria-label="Filter members">
        <input
          type="search"
          className="search-input"
          placeholder="Search by name…"
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          aria-label="Search members by name"
        />

        <div className="pill-group" role="group" aria-label="Filter by party">
          <button
            type="button"
            className={`pill ${partyFilter === '' ? 'active' : ''}`}
            onClick={() => setPartyFilter('')}
          >
            All parties
          </button>
          {parties.map((p) => (
            <button
              key={p}
              type="button"
              className={`pill pill-${partyClass(p)} ${partyFilter === p ? 'active' : ''}`}
              onClick={() => setPartyFilter(partyFilter === p ? '' : p)}
            >
              {p}
            </button>
          ))}
        </div>

        <div className="pill-group" role="group" aria-label="Filter by chamber">
          {['Senate', 'House'].map((c) => (
            <button
              key={c}
              type="button"
              className={`pill ${chamberFilter === c ? 'active' : ''}`}
              onClick={() => setChamberFilter(chamberFilter === c ? '' : c)}
            >
              {c}
            </button>
          ))}
        </div>

        <select
          className="state-select"
          value={stateFilter}
          onChange={(e) => setStateFilter(e.target.value)}
          aria-label="Filter by state"
        >
          <option value="">All states</option>
          {states.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <div className="view-toggle" role="group" aria-label="View mode">
          <button
            type="button"
            className={`pill ${viewMode === 'table' ? 'active' : ''}`}
            onClick={() => setViewMode('table')}
          >
            Table
          </button>
          <button
            type="button"
            className={`pill ${viewMode === 'cards' ? 'active' : ''}`}
            onClick={() => setViewMode('cards')}
          >
            Cards
          </button>
        </div>

        <span className="result-count">
          {table.getFilteredRowModel().rows.length} of {data.length}
        </span>
      </section>

      {/* ---------- card grid view ---------- */}
      {viewMode === 'cards' && (
        <div className="cards-grid">
          {table.getRowModel().rows.map((row, i) => (
            <MemberCard
              key={row.id}
              member={row.original}
              onOpen={openProfile}
              index={i}
              onCompare={toggleCompare}
              inCompare={compareIds.includes(row.original.bioguideId)}
            />
          ))}
        </div>
      )}

      {/* ---------- ledger ---------- */}
      {viewMode === 'table' && (
      <div className="ledger-wrap">
        <table className="ledger">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className={header.column.getCanSort() ? 'sortable' : ''}
                    aria-sort={
                      header.column.getIsSorted() === 'asc'
                        ? 'ascending'
                        : header.column.getIsSorted() === 'desc'
                        ? 'descending'
                        : 'none'
                    }
                  >
                    <span className="th-inner">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getCanSort() && (
                        <span
                          className={`sort-mark ${
                            header.column.getIsSorted() ? 'on' : ''
                          }`}
                          aria-hidden="true"
                        >
                          {header.column.getIsSorted() === 'desc' ? '↓' : '↑'}
                        </span>
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const m = row.original;
              const isOpen = expanded.has(m.bioguideId);
              const bills = m.bills || [];
              const hasDetail = bills.length > 0 || !!m.finance || !!m.voting;
              return (
                <React.Fragment key={row.id}>
                  <tr
                    className={`ledger-row ${isOpen ? 'is-open' : ''}`}
                    onClick={() => hasDetail && toggleRow(m.bioguideId)}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                  {isOpen && (bills.length > 0 || m.finance || m.voting) && (
                    <tr className="detail-row">
                      <td colSpan={colCount}>
                        <div className="bill-panel">
                          {m.voting && (
                            <div className="finance-block">
                              <p className="bill-panel-title">
                                Voting record · House · last {m.voting.votesTotal} roll calls
                              </p>
                              <p className="scope-note">
                                Party-line and attendance reflect recent House
                                floor votes. Senate roll-call data isn&rsquo;t yet
                                available in the Congress.gov API.
                              </p>
                              <div className="finance-grid">
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {m.voting.partyLinePct ?? '—'}%
                                  </span>
                                  <span className="finance-label">
                                    votes with their party
                                  </span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {m.voting.missedPct ?? '—'}%
                                  </span>
                                  <span className="finance-label">votes missed</span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {m.voting.votesAgainstParty ?? '—'}
                                  </span>
                                  <span className="finance-label">
                                    times broke with party
                                  </span>
                                </div>
                              </div>
                              {m.voting.recentVotes &&
                                m.voting.recentVotes.length > 0 && (
                                  <div className="vote-list">
                                    {m.voting.recentVotes.map((rv, i) => (
                                      <div key={i} className="vote-row">
                                        <span
                                          className={`vote-pos vote-${(rv.position || '')
                                            .toLowerCase()
                                            .replace(/[^a-z]/g, '')}`}
                                        >
                                          {rv.position}
                                        </span>
                                        <span className="vote-desc">
                                          {rv.bill ? `${rv.bill} — ` : ''}
                                          {voteText(rv)}
                                        </span>
                                        <span className="vote-date">{rv.date}</span>
                                        {rv.billUrl && (
                                          <a
                                            href={rv.billUrl}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="source-link vote-link"
                                            onClick={(e) => e.stopPropagation()}
                                          >
                                            bill ↗
                                          </a>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              {m.voting.sourceUrl && (
                                <a
                                  href={m.voting.sourceUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="source-link finance-source"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  Full voting record ↗
                                </a>
                              )}
                            </div>
                          )}

                          {m.finance && (
                            <div className="finance-block">
                              <p className="bill-panel-title">
                                Campaign finance · {m.finance.financeCycle} cycle
                              </p>
                              <div className="finance-grid">
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {fmtMoney(m.finance.totalRaised)}
                                  </span>
                                  <span className="finance-label">total raised</span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {fmtMoney(m.finance.fromPacs)}
                                  </span>
                                  <span className="finance-label">
                                    from PACs ({m.finance.pacPct ?? '—'}%)
                                  </span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {fmtMoney(m.finance.fromIndividuals)}
                                  </span>
                                  <span className="finance-label">
                                    from individuals ({m.finance.individualPct ?? '—'}%)
                                  </span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {fmtMoney(m.finance.cashOnHand)}
                                  </span>
                                  <span className="finance-label">cash on hand</span>
                                </div>
                              </div>
                              {m.finance.financeSourceUrl && (
                                <a
                                  href={m.finance.financeSourceUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="source-link finance-source"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  Full FEC filings ↗
                                </a>
                              )}
                            </div>
                          )}

                          {bills.length > 0 && (
                            <>
                              <p className="bill-panel-title">
                                {m.billsTotal && m.billsTotal > bills.length
                                  ? `${bills.length} most recent of ${m.billsTotal} sponsored`
                                  : 'Sponsored legislation'}
                              </p>
                              <div className="bill-grid">
                                {bills.map((bill, idx) => (
                                  <article key={idx} className="bill-card">
                                    <p className="bill-number">{bill.billNumber}</p>
                                    <h3 className="bill-title">
                                      {bill.title || 'Untitled measure'}
                                    </h3>
                                    {bill.latestAction && (
                                      <p className="bill-action">{bill.latestAction}</p>
                                    )}
                                    <div className="bill-foot">
                                      {bill.introducedDate && (
                                        <span className="bill-date">
                                          Introduced {fmtDate(bill.introducedDate)}
                                        </span>
                                      )}
                                      {bill.sourceUrl && (
                                        <a
                                          href={bill.sourceUrl}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="source-link"
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          Full text ↗
                                        </a>
                                      )}
                                    </div>
                                  </article>
                                ))}
                              </div>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      )}

      {/* ---------- pagination ---------- */}
      <div className="pager">
        <button
          type="button"
          onClick={() => table.previousPage()}
          disabled={!table.getCanPreviousPage()}
        >
          ← Previous
        </button>
        <span className="pager-info">
          Page {table.getState().pagination.pageIndex + 1} of{' '}
          {table.getPageCount() || 1}
        </span>
        <button
          type="button"
          onClick={() => table.nextPage()}
          disabled={!table.getCanNextPage()}
        >
          Next →
        </button>
        <select
          value={table.getState().pagination.pageSize}
          onChange={(e) => table.setPageSize(Number(e.target.value))}
          aria-label="Rows per page"
        >
          {[25, 50, 100].map((n) => (
            <option key={n} value={n}>
              {n} per page
            </option>
          ))}
        </select>
      </div>

      {data.length > 0 && <CongressQuiz data={data} onOpenProfile={openProfile} />}

      {/* ---------- compare two ---------- */}
      {compareMembers.length > 0 && (
        <section className="compare2" aria-label="Compare two members">
          <div className="compare2-head">
            <h2 className="compare-title">
              {compareMembers.length === 2 ? 'Side by side' : 'Pick one more to compare'}
            </h2>
            <div className="compare2-actions">
              {compareMembers.length === 2 && (
                <button
                  type="button"
                  className="pill pill-sm"
                  onClick={async () => {
                    try { await navigator.clipboard.writeText(window.location.href); } catch {}
                  }}
                >
                  Copy comparison link
                </button>
              )}
              <button type="button" className="pill pill-sm" onClick={() => setCompareIds([])}>
                Clear
              </button>
            </div>
          </div>
          <div className={`compare2-grid ${compareMembers.length === 2 ? 'two' : ''}`}>
            {compareMembers.map((m) => (
              <div key={m.bioguideId} className={`compare2-card ${partyClass(m.party)}`}>
                <div className="mcard-head">
                  <MemberPhoto member={m} size="lg" />
                  <div className="mcard-ident">
                    <button type="button" className="mcard-name member-link" onClick={() => openProfile(m)}>
                      {m.name}
                    </button>
                    <span className="mcard-seat">
                      {m.chamber === 'House' && m.district != null ? `${m.state} · District ${m.district}` : `${m.state} · ${m.chamber}`}
                    </span>
                    <span className={`party-tag ${partyClass(m.party)}`}>
                      <span className="party-dot" aria-hidden="true" />{m.party}
                    </span>
                  </div>
                  <button type="button" className="compare2-remove" aria-label="Remove" onClick={() => toggleCompare(m.bioguideId)}>×</button>
                </div>
                <dl className="compare2-facts">
                  <div><dt>Terms served</dt><dd>{m.termsServed ?? '—'} <small>since {m.firstYearServed || '—'}</small></dd></div>
                  <div><dt>Age</dt><dd>{ageOf(m.birthday) ?? '—'}</dd></div>
                  <div><dt>Next election</dt><dd>{m.nextElection || '—'}</dd></div>
                  <div><dt>Votes with party</dt><dd>{m.voting?.partyLinePct != null ? `${m.voting.partyLinePct}%` : <small>Senate n/a</small>}</dd></div>
                  <div><dt>Votes missed</dt><dd>{m.voting?.missedPct != null ? `${m.voting.missedPct}%` : <small>—</small>}</dd></div>
                  <div><dt>Money from PACs</dt><dd>{m.finance?.pacPct != null ? `${m.finance.pacPct}%` : '—'}</dd></div>
                  <div><dt>Total raised</dt><dd>{m.finance ? fmtMoney(m.finance.totalRaised) : '—'}</dd></div>
                  <div><dt>Bills sponsored</dt><dd>{m.billsTotal ?? (m.bills?.length || 0)}</dd></div>
                  <div><dt>Laws enacted</dt><dd>{m.lawsEnacted ?? 0}</dd></div>
                  <div><dt>Trade reports</dt><dd>{m.trades?.chamber === 'House' ? (m.trades.ptrCount ?? 0) : <small>Senate n/a</small>}</dd></div>
                  <div><dt>Committees</dt><dd>{m.committees?.length || 0}</dd></div>
                </dl>
              </div>
            ))}
          </div>
        </section>
      )}

      <footer className="colophon">
        <p>
          Member data:{' '}
          <a
            href="https://github.com/unitedstates/congress-legislators"
            target="_blank"
            rel="noopener noreferrer"
          >
            unitedstates/congress-legislators
          </a>{' '}
          (public domain) · Bills:{' '}
          <a href="https://api.congress.gov" target="_blank" rel="noopener noreferrer">
            Congress.gov API
          </a>{' '}
          · Updated nightly
        </p>
        <p className="colophon-note">
          Terms are counted one per elected term. &ldquo;On ballot&rdquo; is the
          November before the current term ends. For official records, always
          verify at Congress.gov.
        </p>
      </footer>

      {selectedMember && (
        <MemberProfile
          member={selectedMember}
          onClose={closeProfile}
          onCompare={toggleCompare}
          inCompare={compareIds.includes(selectedMember.bioguideId)}
        />
      )}
    </div>
  );
}
