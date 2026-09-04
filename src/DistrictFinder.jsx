import { useRef, useState } from 'react';

/*
 * DistrictFinder — "I don't know my district."
 *
 * Uses the U.S. Census Bureau's free public geocoder, which returns the
 * authoritative CURRENT congressional and state legislative districts for a
 * street address. No API key; boundaries maintained by the Bureau through
 * every redistricting. A street address (not just a zip) is required because
 * thousands of zip codes straddle district lines — a facts site shouldn't
 * guess. Requests go via JSONP (the geocoder supports it explicitly for
 * cross-origin browser use) directly from the visitor's browser to
 * census.gov; this site never sees or stores the address.
 */

const FIPS_TO_STATE = {
  '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA', '08': 'CO',
  '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL', '13': 'GA', '15': 'HI',
  '16': 'ID', '17': 'IL', '18': 'IN', '19': 'IA', '20': 'KS', '21': 'KY',
  '22': 'LA', '23': 'ME', '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN',
  '28': 'MS', '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
  '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND', '39': 'OH',
  '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI', '45': 'SC', '46': 'SD',
  '47': 'TN', '48': 'TX', '49': 'UT', '50': 'VT', '51': 'VA', '53': 'WA',
  '54': 'WV', '55': 'WI', '56': 'WY', '72': 'PR',
};

function jsonp(url, timeoutMs = 12000) {
  return new Promise((resolve, reject) => {
    const cb = `__censusCb${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
    const script = document.createElement('script');
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error('timeout'));
    }, timeoutMs);
    function cleanup() {
      clearTimeout(timer);
      delete window[cb];
      script.remove();
    }
    window[cb] = (data) => { cleanup(); resolve(data); };
    script.onerror = () => { cleanup(); reject(new Error('network')); };
    script.src = `${url}&callback=${cb}`;
    document.body.appendChild(script);
  });
}

function findLayer(geographies, keyword) {
  const key = Object.keys(geographies || {}).find((k) => k.includes(keyword));
  const entry = key && geographies[key] && geographies[key][0];
  return entry || null;
}

export default function DistrictFinder({ members }) {
  const [addr, setAddr] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  async function lookup() {
    const q = addr.trim();
    if (!q) { inputRef.current?.focus(); return; }
    setBusy(true); setError(null); setResult(null);
    try {
      const layers = encodeURIComponent(
        'Congressional Districts,State Legislative Districts - Upper,State Legislative Districts - Lower'
      );
      const url =
        'https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress' +
        `?address=${encodeURIComponent(q)}` +
        '&benchmark=Public_AR_Current&vintage=Current_Current' +
        `&layers=${layers}&format=jsonp`;
      const data = await jsonp(url);
      const match = data?.result?.addressMatches?.[0];
      if (!match) {
        setError('No match for that address. Try adding a city and state, e.g. "123 Main St, Raleigh, NC".');
        return;
      }
      const geo = match.geographies || {};
      const cd = findLayer(geo, 'Congressional Districts');
      const sldu = findLayer(geo, 'Upper');
      const sldl = findLayer(geo, 'Lower');
      const stateCode = FIPS_TO_STATE[cd?.STATE || sldu?.STATE || ''] || null;
      const cdNum = cd ? parseInt(cd.BASENAME, 10) : null; // "00" = at-large
      setResult({
        matched: match.matchedAddress,
        stateCode,
        cdNum: Number.isNaN(cdNum) ? null : cdNum,
        cdName: cd?.NAME || null,
        slduName: sldu?.NAME || null,
        sldlName: sldl?.NAME || null,
      });
    } catch (e) {
      setError('The Census geocoder could not be reached just now. Please try again in a moment.');
    } finally {
      setBusy(false);
    }
  }

  const rep = result && result.stateCode
    ? (members || []).find((m) =>
        m.chamber === 'House' && m.stateCode === result.stateCode &&
        (result.cdNum === 0 || result.cdNum === null
          ? true // at-large states have a single House member
          : Number(m.district) === result.cdNum))
    : null;
  const senators = result && result.stateCode
    ? (members || []).filter((m) => m.chamber === 'Senate' && m.stateCode === result.stateCode)
    : [];

  return (
    <section className="district-finder" aria-label="Find your districts and legislators">
      <p className="donor-label">Find your legislators</p>
      <div className="finder-row">
        <input
          ref={inputRef}
          type="text"
          className="finder-input"
          placeholder='Street address, city, state — e.g. "123 Main St, Raleigh, NC"'
          value={addr}
          onChange={(e) => setAddr(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') lookup(); }}
          aria-label="Your street address"
        />
        <button type="button" className="pill finder-btn" onClick={lookup} disabled={busy}>
          {busy ? 'Looking…' : 'Find my district'}
        </button>
      </div>
      <p className="finder-privacy">
        Your address goes only to the U.S. Census Bureau's public geocoder to
        identify your districts. This site never sees or stores it.
      </p>

      {error && <p className="finder-error">{error}</p>}

      {result && (
        <div className="finder-result">
          <p className="finder-matched">Matched: {result.matched}</p>
          {result.cdName && result.stateCode && (
            <p className="finder-line">
              <strong>
                {result.stateCode}
                {result.cdNum ? `-${String(result.cdNum).padStart(2, '0')}` : ' (at-large)'}
              </strong>
              {rep && <> · Your U.S. House member: <strong>{rep.name}</strong> ({rep.party})</>}
            </p>
          )}
          {senators.length > 0 && (
            <p className="finder-line">
              Your U.S. senators: {senators.map((s, i) => (
                <span key={s.bioguideId || s.name}>
                  <strong>{s.name}</strong> ({s.party}){i < senators.length - 1 ? ' and ' : ''}
                </span>
              ))}
            </p>
          )}
          {(result.slduName || result.sldlName) && (
            <p className="finder-line finder-state-line">
              State districts: {[result.slduName, result.sldlName].filter(Boolean).join(' · ')}
              {' — '}see the State Legislatures tab for those members.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
