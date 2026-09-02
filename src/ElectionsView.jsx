import React, { useEffect, useMemo, useState } from 'react';

const partyClass = (p) => (p || '').toLowerCase().replace(/[^a-z]/g, '-');

const fmtMoney = (n) => {
  if (n == null || isNaN(n)) return 'n/a';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${Math.round(n / 1_000)}K`;
  return `$${n}`;
};

function Initials({ name, party, size = 'lg' }) {
  const initials = (name || '').split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join('').toUpperCase();
  return <div className={`member-photo ph-${size} ph-fallback ${partyClass(party)}`}>{initials}</div>;
}

function CandidatePhoto({ c }) {
  const [failed, setFailed] = useState(false);
  if (!c.photo?.url || failed) return <Initials name={c.name} party={c.party} />;
  return (
    <img
      className={`member-photo ph-lg ${partyClass(c.party)}`}
      src={c.photo.url}
      alt={`Portrait of ${c.name}`}
      title={`Photo: ${c.photo.credit}`}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

function CandidateCard({ c, onOpenState }) {
  const f = c.finance || {};
  return (
    <div className={`compare2-card ${partyClass(c.party)}`}>
      <div className="mcard-head">
        <CandidatePhoto c={c} />
        <div className="mcard-ident">
          <span className="mcard-name">{c.name}</span>
          <span className="mcard-seat">{c.currentOffice}</span>
          <span className={`party-tag ${partyClass(c.party)}`}>
            <span className="party-dot" aria-hidden="true" />{c.party}
          </span>
        </div>
      </div>

      <p className="election-bg">
        {c.background}{' '}
        {c.backgroundSourceUrl && (
          <a href={c.backgroundSourceUrl} target="_blank" rel="noopener noreferrer" className="source-link">source ↗</a>
        )}
      </p>

      {c.facts?.length > 0 && (
        <ul className="fact-list">
          {c.facts.map((f, i) => (
            <li key={i} className="fact-row">
              <span className="fact-label">{f.label}</span>
              <span className="fact-value">{f.value}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="election-links">
        {c.campaignSiteUrl && (
          <a href={c.campaignSiteUrl} target="_blank" rel="noopener noreferrer" className="pill pill-sm">
            Campaign site &amp; issues ↗
          </a>
        )}
        {c.stateProfile && (
          <button type="button" className="pill pill-sm" onClick={() => onOpenState(c.stateProfile)}>
            See {c.stateProfile.code} legislative record →
          </button>
        )}
      </div>

      <div className="finance-grid" style={{ marginTop: '1rem' }}>
        <div className="finance-stat">
          <span className="finance-num">{f.available ? fmtMoney(f.totalRaised) : 'n/a'}</span>
          <span className="finance-label">total raised{f.cycle ? ` · ${f.cycle} cycle` : ''}</span>
        </div>
        {f.available && (
          <>
            <div className="finance-stat">
              <span className="finance-num">{f.pacPct ?? 'n/a'}%</span>
              <span className="finance-label">from PACs</span>
            </div>
            <div className="finance-stat">
              <span className="finance-num">{fmtMoney(f.cashOnHand)}</span>
              <span className="finance-label">cash on hand</span>
            </div>
          </>
        )}
      </div>

      {c.topPacDonors?.length > 0 && (
        <div className="donor-list">
          <span className="donor-label">Named PAC donors on record:</span>
          {c.topPacDonors.map((d, i) =>
            d.fecUrl ? (
              <a
                key={i}
                href={d.fecUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="donor-chip donor-chip-link"
                title="View this committee's profile on fec.gov"
              >
                {d.name}
                {d.kind && <span className="donor-kind">{d.kind}</span>}
                <strong>{fmtMoney(d.amount)}</strong> <span aria-hidden="true">↗</span>
              </a>
            ) : (
              <span key={i} className="donor-chip">
                {d.name}
                {d.kind && <span className="donor-kind">{d.kind}</span>}
                <strong>{fmtMoney(d.amount)}</strong>
              </span>
            )
          )}
        </div>
      )}

      {c.financeUrl && (
        <a href={c.financeUrl} target="_blank" rel="noopener noreferrer" className="source-link finance-source">
          Full FEC filings ↗
        </a>
      )}
    </div>
  );
}

export default function ElectionsView({ onOpenStateProfile }) {
  const [payload, setPayload] = useState(null);
  const [raceId, setRaceId] = useState(() => new URLSearchParams(window.location.search).get('race') || '');
  const [race, setRace] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${import.meta.env.BASE_URL}elections/index.json`, { cache: 'no-cache' });
        if (!r.ok) throw new Error(`No elections data yet (HTTP ${r.status}).`);
        const j = await r.json();
        setPayload(j);
        if (!raceId && j.races?.[0]) setRaceId(j.races[0].id);
      } catch (e) { setError(e.message); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!raceId) return;
    (async () => {
      try {
        const r = await fetch(`${import.meta.env.BASE_URL}elections/${raceId}.json`, { cache: 'no-cache' });
        if (!r.ok) throw new Error(`Could not load race ${raceId}.`);
        setRace(await r.json());
      } catch (e) { setError(e.message); }
    })();
  }, [raceId]);

  const daysOut = useMemo(() => {
    if (!race?.electionDate) return null;
    const d = Math.ceil((new Date(`${race.electionDate}T00:00:00`) - new Date()) / 86400000);
    return d;
  }, [race]);

  if (error) return <div className="ct-status ct-error">{error}</div>;
  if (!payload || !race) return <div className="ct-status">Loading race data...</div>;

  return (
    <div className="elections-view">
      {payload.races?.length > 1 && (
        <nav className="race-switch" aria-label="Choose a race">
          {payload.races.map((r) => (
            <button
              key={r.id}
              type="button"
              className={`pill pill-sm ${r.id === raceId ? 'active' : ''}`}
              onClick={() => {
                if (r.id === raceId) return;
                setRace(null);
                setRaceId(r.id);
                const url = new URL(window.location.href);
                url.searchParams.set('race', r.id);
                history.replaceState(null, '', url.pathname + url.search + url.hash);
              }}
            >
              {r.state}
            </button>
          ))}
        </nav>
      )}
      <div className="hero">
        <header className="masthead">
          <p className="masthead-eyebrow">Upcoming Race &middot; Preview</p>
          <h1 className="masthead-title">{race.office}, {race.state}</h1>
          <p className="masthead-dek">
            Candidate facts, not recommendations. Party, background, and campaign
            money for each candidate, every claim sourced. What you make of it is
            up to you.
          </p>
          <p className="record-stamp">
            Election day {new Date(`${race.electionDate}T00:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })}
            {daysOut != null && daysOut >= 0 ? ` · ${daysOut} days away` : ''}
          </p>
        </header>
      </div>

      {race.seatNote && (
        <p className="scope-note" style={{ margin: '0 0 1.25rem' }}>
          {race.seatNote}{' '}
          {race.sourceUrl && <a href={race.sourceUrl} target="_blank" rel="noopener noreferrer">source ↗</a>}
        </p>
      )}

      <section className="compare2" aria-label="Candidates" style={{ margin: 0 }}>
        <div className={`compare2-grid ${race.candidates.length === 2 ? 'two' : ''}`}>
          {race.candidates.map((c) => (
            <CandidateCard key={c.fecId} c={c} onOpenState={onOpenStateProfile} />
          ))}
        </div>
      </section>

      <footer className="colophon">
        <p>Candidate finance: <a href="https://www.fec.gov" target="_blank" rel="noopener noreferrer">FEC</a> · Background: Ballotpedia (linked per candidate) · Updated daily</p>
        {race.candidates.some((c) => c.photo) && (
          <p className="colophon-note">
            Photos:{' '}
            {race.candidates.filter((c) => c.photo).map((c, i, arr) => (
              <span key={c.fecId || c.name}>
                {c.name} — <a href={c.photo.sourceUrl} target="_blank" rel="noopener noreferrer">{c.photo.credit}</a>
                {i < arr.length - 1 ? ' · ' : ''}
              </span>
            ))}
          </p>
        )}
        <p className="colophon-note">
          This page is a preview build being tested with a small group before wider release.
          It shows facts only: no ratings, scores, or endorsements of any candidate.
        </p>
      </footer>
    </div>
  );
}
