import { useRef, useState } from 'react';

/*
 * DistrictFinder — "I don't know my district."
 *
 * Two easy paths, no full address required:
 *  1) "Use my location": browser geolocation -> Census geocoder -> exact
 *     current districts. One tap.
 *  2) Type anything (zip, city, or address): OpenStreetMap's Nominatim
 *     resolves it to a point, the Census geocoder resolves the point to
 *     districts. Coarse inputs (zip/city) are honestly labeled approximate,
 *     because zips and cities can span district lines.
 *
 * Privacy: location/text goes only to OpenStreetMap (for text lookups) and
 * the U.S. Census Bureau (for district boundaries), directly from the
 * visitor's browser. This site never sees or stores it. No API keys.
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

const PRECISE_OSM_TYPES = new Set(['house', 'building', 'residential', 'address']);

function jsonp(url, timeoutMs = 12000) {
  return new Promise((resolve, reject) => {
    const cb = `__censusCb${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
    const script = document.createElement('script');
    const timer = setTimeout(() => { cleanup(); reject(new Error('timeout')); }, timeoutMs);
    function cleanup() { clearTimeout(timer); delete window[cb]; script.remove(); }
    window[cb] = (data) => { cleanup(); resolve(data); };
    script.onerror = () => { cleanup(); reject(new Error('network')); };
    script.src = `${url}&callback=${cb}`;
    document.body.appendChild(script);
  });
}

function findLayer(geographies, keyword) {
  const key = Object.keys(geographies || {}).find((k) => k.includes(keyword));
  return (key && geographies[key] && geographies[key][0]) || null;
}

async function censusDistrictsFromPoint(lat, lon) {
  const layers = encodeURIComponent(
    'Congressional Districts,State Legislative Districts - Upper,State Legislative Districts - Lower'
  );
  const url =
    'https://geocoding.geo.census.gov/geocoder/geographies/coordinates' +
    `?x=${encodeURIComponent(lon)}&y=${encodeURIComponent(lat)}` +
    '&benchmark=Public_AR_Current&vintage=Current_Current' +
    `&layers=${layers}&format=jsonp`;
  const data = await jsonp(url);
  const geo = data?.result?.geographies;
  if (!geo) return null;
  const cd = findLayer(geo, 'Congressional Districts');
  const sldu = findLayer(geo, 'Upper');
  const sldl = findLayer(geo, 'Lower');
  if (!cd && !sldu && !sldl) return null;
  const stateCode = FIPS_TO_STATE[cd?.STATE || sldu?.STATE || ''] || null;
  const cdNum = cd ? parseInt(cd.BASENAME, 10) : null; // "00" = at-large
  return {
    stateCode,
    cdNum: Number.isNaN(cdNum) ? null : cdNum,
    cdName: cd?.NAME || null,
    slduName: sldu?.NAME || null,
    sldlName: sldl?.NAME || null,
  };
}

export default function DistrictFinder({ members }) {
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  function fail(msg) { setError(msg); setResult(null); }

  async function finish(point, placeLabel, approximate) {
    const districts = await censusDistrictsFromPoint(point.lat, point.lon);
    if (!districts || !districts.stateCode) {
      fail('Could not determine districts for that spot. It may be outside the United States.');
      return;
    }
    setResult({ ...districts, placeLabel, approximate });
  }

  async function lookupText() {
    const q = query.trim();
    if (!q) { inputRef.current?.focus(); return; }
    setBusy(true); setError(null); setResult(null);
    try {
      const url =
        'https://nominatim.openstreetmap.org/search' +
        `?q=${encodeURIComponent(q)}&format=json&limit=1&countrycodes=us&addressdetails=0`;
      const resp = await fetch(url, { headers: { Accept: 'application/json' } });
      const hits = await resp.json();
      const hit = Array.isArray(hits) && hits[0];
      if (!hit) {
        fail('No match for that. Try a 5-digit zip, a "City, ST", or a street address.');
        return;
      }
      const approximate = !PRECISE_OSM_TYPES.has(hit.type);
      const label = (hit.display_name || q).split(',').slice(0, 3).join(',');
      await finish({ lat: hit.lat, lon: hit.lon }, label, approximate);
    } catch (e) {
      fail('Lookup failed just now. Please try again in a moment.');
    } finally {
      setBusy(false);
    }
  }

  function lookupMyLocation() {
    if (!navigator.geolocation) {
      fail('Your browser does not support location. Type a zip or city instead.');
      return;
    }
    setBusy(true); setError(null); setResult(null);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await finish(
            { lat: pos.coords.latitude, lon: pos.coords.longitude },
            'your current location',
            false
          );
        } catch (e) {
          fail('Lookup failed just now. Please try again in a moment.');
        } finally {
          setBusy(false);
        }
      },
      () => { setBusy(false); fail('Location was blocked or unavailable. Type a zip or city instead.'); },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
    );
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
        <button type="button" className="pill finder-btn finder-geo" onClick={lookupMyLocation} disabled={busy}>
          {busy ? 'Looking…' : '📍 Use my location'}
        </button>
        <span className="finder-or">or</span>
        <input
          ref={inputRef}
          type="text"
          inputMode="text"
          className="finder-input"
          placeholder="Zip code or city, e.g. 27601 or Raleigh, NC"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') lookupText(); }}
          aria-label="Zip code, city, or address"
        />
        <button type="button" className="pill finder-btn" onClick={lookupText} disabled={busy}>
          Find
        </button>
      </div>
      <p className="finder-privacy">
        Lookups go directly from your browser to OpenStreetMap and the U.S. Census
        Bureau to identify your districts. This site never sees or stores your
        location.
      </p>

      {error && <p className="finder-error">{error}</p>}

      {result && (
        <div className="finder-result">
          <p className="finder-matched">
            {result.approximate ? 'Based on the center of ' : 'Based on '}
            {result.placeLabel}
          </p>
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
          {result.approximate && (
            <p className="finder-approx">
              Zips and cities can span more than one district. For an exact match,
              use the location button or enter a street address.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
