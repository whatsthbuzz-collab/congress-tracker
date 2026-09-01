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
// Decorative party-emblem wreath (OpenClipart, CC0), rendered as a faint
// single-color watermark in the hero on wide screens.
import emblemSvg from './emblem.svg?raw';
import StateView from './StateView';

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
  if (n == null || isNaN(n)) return 'n/a';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${Math.round(n / 1_000)}K`;
  return `$${n}`;
};


// Human text for a vote row. The API list endpoint sometimes lacks a real
// question, and an older fallback stored the bill type ("HR") there, treat
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
    [String(m.termsServed ?? 'n/a'), m.termsServed === 1 ? 'term' : 'terms'],
    [m.nextElection || 'n/a', 'on ballot'],
    [m.voting?.partyLinePct != null ? `${m.voting.partyLinePct}%` : 'n/a', 'party line'],
    [m.finance?.pacPct != null ? `${m.finance.pacPct}%` : 'n/a', 'PAC money'],
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


// Democratic donkey. Source: OpenClipart (public domain, CC0), simplified to a
// single-color silhouette with the stars removed so it reads as an animal,
// not a party logo. Colored via currentColor for light/dark mode.
function DonkeyIcon({ size = 28, className = '' }) {
  return (
    <svg viewBox="0 0 319.7 293.8" width={size} height={size} className={`mascot ${className}`} aria-hidden="true"
         fill="currentColor" stroke="currentColor" strokeWidth="9" strokeLinejoin="round">
      <path d="M 299.66192287253944,159.18550288509883 C 298.5671624255167,193.84567167527695 330.11329815350655,192.8687757590002 307.4953687693296,218.41727928410666 C 305.2391740780115,213.66713765307418 304.0329234765343,208.8002167079143 304.15576522400374,203.81401656100095 C 301.41152163191146,201.30877543343257 301.09736096289294,199.80774642836906 302.9238601717168,199.1849481944557 C 305.8998069085526,195.32251489153413 304.33499608106126,193.8039593034285 302.0767058297672,192.62038922062385 C 301.68475916987086,186.54602507153007 298.5328085733338,181.29078012605035 294.0070532327104,177.51672069397728 C 281.78981084460565,195.70236064505656 298.4740141104444,213.40327478484522 286.61569591758916,235.0214947309231 C 282.393654111469,238.5142037063996 281.3210776508663,242.82125661252468 280.248618856157,247.4906642980509 C 281.904680201234,264.3752798347263 268.7123740499162,287.0225795282859 257.30106407452763,289.4641637774142 C 248.3649159720112,291.3765753674989 227.64132495433705,283.5896833474317 242.51765229878674,272.9095553172636 C 247.37056864932788,270.1086897555752 251.65226985198,266.8443177162379 254.51237928370438,262.9971722759717 C 261.0099702743421,240.02662512710344 268.33668126919315,217.57106343299455 261.02942455313087,193.84800063989033 C 257.31851126162314,184.94000622235112 253.18511119864434,179.54959121797827 256.1799121273625,194.51084996840933 C 263.53482535767444,219.28405316005535 231.73307749437458,214.42001349748153 234.06098164643527,232.48978229121047 C 232.76815158259387,252.03535620005306 226.14702571942053,243.20865623324687 216.99114671748976,262.65765686829246 C 214.76772324391925,267.42435436836274 213.52535690350123,271.42397370977466 211.06791675751094,273.9040297431891 C 205.70112840045738,275.14983499706864 201.46729511194258,274.14931329062557 198.3256699496311,273.6148113359692 C 187.45257960097535,271.81943386313225 182.58645852722566,269.140422908394 200.53847359454517,246.24049496041278 C 212.5408072207906,231.0700278441932 223.93211994190176,221.42924050654034 219.3920782884593,199.28355553666395 C 212.2259247169021,164.39666979160413 198.3879571749219,176.45899242479146 181.89669096515865,178.41257907470464 C 171.07129561402508,179.7745337331474 160.91226111968,176.07164997279145 153.79165458088687,183.2376044465302 C 147.34989418339728,189.59741010247086 138.57510282180635,237.36326411514972 162.6035762676828,249.28001232348282 C 161.8804099508841,252.65591671760416 160.60670908244072,255.4638909157988 159.12040436639143,257.906251104438 C 154.6641865282155,265.2760016822203 148.28928553962487,268.9487615961905 148.41396981026298,272.0842613701747 C 147.1919706028973,274.1727747019966 145.86989383833236,274.55662106266396 144.41263490686856,273.28404634710927 C 139.25071756201078,267.5268913791711 138.0956679461325,270.80100276775573 138.75957663703718,277.91850480499755 C 138.32659253753036,281.38715768033325 137.61676497952647,281.7831246459984 136.91674100426087,282.309758706854 C 126.2297104813938,279.8316611294153 127.40695599763467,284.5614882926941 111.14641065041792,281.7881933190012 C 106.89464767289428,274.9073907071717 121.28614890906181,258.6516664178824 120.90850993205595,248.68031300908945 C 119.18871457152716,242.1952691450972 120.04198574520365,237.23111107910324 122.35839297495261,233.05174144410245 C 125.45685912694216,211.04892531741143 110.98140009192923,170.9118454195705 103.13682738852322,150.07818352107137 C 172.68741656000407,142.34779084670362 236.98737763690542,147.32129248126392 299.66192287253944,159.18550288509883" />
      <path d="M 303.1705391032592,152.19843388976685 C 242.34834383596012,139.54269547328136 185.46974407663788,136.41971381806184 130.79574125759143,140.9220340802045 C 117.63127023763082,142.0524179816376 100.14601504899372,144.64631620405078 100.6792076444599,142.7501448889687 C 49.80106378053199,90.30847319592044 87.52281316229676,142.1346709011287 33.400550912274866,142.2757628564187 C 16.721957836322872,137.95067985064816 18.364376704470487,129.80326073404734 18.51761207898778,121.96386356844866 C 29.43365019891428,80.78442757468706 12.263919635749517,77.60652631940513 24.938017596638247,63.4560428690847 C 26.408878101988194,58.9631006956529 -11.353659513281855,50.49006594679665 11.202584943772194,15.951462312694346 C 28.03995926540381,22.784861390258982 19.915937463923797,36.594064979498924 40.19578773354658,41.189030598704335 C 39.27388599251617,24.799387461043153 41.77523090115051,10.515576077240524 51.702764753104475,4.000000000000028 C 61.93272591675577,14.175597210492697 69.99355837813187,24.375395102099446 68.25536721563583,33.520991391167755 C 65.16456071120786,48.51676346706253 80.94401100873085,43.81898438455981 94.21611109014145,46.61416298869601 C 108.58280157631066,49.63935430076451 121.71788441621572,57.82392538230761 133.56345602007627,65.86776348223306 C 140.31510519298172,74.16538154080894 149.39057002470975,78.07524062881555 159.84503625270202,79.60332828591172 C 209.46618543245324,87.09542839742036 252.08505920492257,47.92183501659386 294.1739887069775,74.9540093533179 C 305.60568764488585,82.29468216941774 313.23853686163466,93.61821950694514 314.38978411103335,108.00593241660357 C 315.4029175233634,120.04624494115296 312.01839490409293,134.62186127939566 303.1705391032592,152.19843388976685 " />
    </svg>
  );
}

// Republican elephant. Source: OpenClipart (public domain, CC0), simplified to a
// single-color silhouette with the stars removed. Colored via currentColor.
function ElephantIcon({ size = 28, className = '' }) {
  return (
    <svg viewBox="0 0 1869.088 1643.136" width={size * 1.1} height={size} className={`mascot ${className}`} aria-hidden="true"
         fill="currentColor" stroke="currentColor" strokeWidth="40" strokeLinejoin="round">
      <path d="M1343.103,1251.966c-17.97-186.704-75.21-144.34-64.254,0v280.533
		c0,33.349-27.068,60.417-60.417,60.417H955.159c-33.349,0-60.417-27.068-60.417-60.417v-264.322
		c-2.384-10.116-9.398-14.547-18.668-16.211H426.117c-10.324,3.258-16.701,11.373-14.762,29.671l-2.156,0.068v250.793
		c0,33.349-27.07,60.417-60.417,60.417H85.506c-33.347,0-60.417-27.068-60.417-60.417V794.477c0-28.587,23.203-51.79,51.792-51.79
		h1454.448c28.589,0,51.792,23.203,51.792,51.79v297.902l0.321-0.104l-4.315,295.637c3.779,45.811,70.958,73.865,92.791-4.315
		l-2.159-79.843c-7.687-29.35-0.69-48.741,43.16-43.16l90.635-2.159c13.867-0.04,27.783-3.493,41.001,43.16
		C1834.885,1768.435,1355.436,1700.821,1343.103,1251.966z" />
      <path d="M810.576,21.934C397.459,28.901-45.063,137.18,33.716,604.578c-6.613,55.768,10.301,80.799,38.842,90.634
		l1467.403,8.633c24.889-7.937,45.632-28.688,47.475-107.899C1582.175,92.005,1197.83,15.402,810.576,21.934z " />
    </svg>
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
      {(m.trades?.ptrCount || 0) > 0 && (
        <span className="trade-badge" title="Periodic transaction reports filed this Congress">
          {m.trades.ptrCount} trade {m.trades.ptrCount === 1 ? 'report' : 'reports'}
        </span>
      )}
      <div className="mcard-stats">
        <div className="mstat">
          <span className="mstat-num">{m.termsServed ?? 'n/a'}</span>
          <span className="mstat-label">{m.termsServed === 1 ? 'term' : 'terms'}</span>
        </div>
        <div className="mstat">
          <span className="mstat-num">{m.nextElection || 'n/a'}</span>
          <span className="mstat-label">on ballot</span>
        </div>
        <div className="mstat">
          <span className="mstat-num">{pl != null ? `${pl}%` : 'n/a'}</span>
          <span className="mstat-label">party line</span>
          {pl != null && (
            <span className="mini-bar" aria-hidden="true">
              <span className="mini-fill partyline" style={{ width: `${pl}%` }} />
            </span>
          )}
        </div>
        <div className="mstat">
          <span className="mstat-num">{pac != null ? `${pac}%` : 'n/a'}</span>
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
            <span className="finance-num">{m.termsServed ?? 'n/a'}</span>
            <span className="finance-label">
              {m.termsServed === 1 ? 'term' : 'terms'} · since {m.firstYearServed || 'n/a'}
            </span>
          </div>
          {ageOf(m.birthday) != null && (
            <div className="finance-stat">
              <span className="finance-num">{ageOf(m.birthday)}</span>
              <span className="finance-label">years old</span>
            </div>
          )}
          <div className="finance-stat">
            <span className="finance-num">{m.nextElection || 'n/a'}</span>
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
              <span className="finance-label">votes with party</span>
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
            {m.trades.ptrCount != null ? (
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
                    No trade reports filed this Congress. No reportable stock
                    transactions on record.
                  </p>
                )}
                {m.trades.annual && (
                  <p className="annual-line">
                    Latest annual financial disclosure:{' '}
                    <a
                      href={m.trades.annual.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="source-link"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {m.trades.annual.title}
                      {m.trades.annual.date ? ` · filed ${fmtDate(m.trades.annual.date)}` : ''} ↗
                    </a>
                    <span className="annual-hint"> (lists assets and holdings)</span>
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
                {m.trades.chamber === 'House' ? 'House Clerk disclosures ↗' : 'Senate eFD disclosures ↗'}
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
                <span className="finance-label">from PACs ({m.finance.pacPct ?? 'n/a'}%)</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{fmtMoney(m.finance.fromIndividuals)}</span>
                <span className="finance-label">from individuals ({m.finance.individualPct ?? 'n/a'}%)</span>
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
            <p className="bill-panel-title">Voting record · {m.voting.chamberScope || m.chamber} · last {m.voting.votesTotal} roll calls</p>
            <div className="finance-grid">
              <div className="finance-stat">
                <span className="finance-num">{m.voting.partyLinePct ?? 'n/a'}%</span>
                <span className="finance-label">with their party</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{m.voting.missedPct ?? 'n/a'}%</span>
                <span className="finance-label">votes missed</span>
              </div>
              <div className="finance-stat">
                <span className="finance-num">{m.voting.votesAgainstParty ?? 'n/a'}</span>
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
                      {rv.bill ? `${rv.bill}: ` : ''}
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
              Senate roll-call data wasn&rsquo;t available on the last update.
              It fills in automatically on the next successful run.
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


// "How well do you know Congress?", a short quiz generated from the live
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
      out.push({ kind: 'pl', m, prompt: `How often does ${m.name} vote with their party on roll-call votes?`,
        options: ['Under 70%', '70–84%', '85–94%', '95–100%'], answer: bucket,
        reveal: `${m.name} voted with the ${m.party} majority ${v}% of the time across the last ${m.voting.votesTotal} ${m.voting.chamberScope || m.chamber} roll calls.` });
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

  const [compareTab, setCompareTab] = useState('overview');
  const [level, setLevel] = useState(() =>
    new URLSearchParams(window.location.search).get('view') === 'state' ? 'state' : 'federal'
  );
  useEffect(() => {
    const url = new URL(window.location.href);
    if (level === 'state') url.searchParams.set('view', 'state');
    else { url.searchParams.delete('view'); url.searchParams.delete('st'); }
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }, [level]);
  const [myState, setMyState] = useState('');
  const [myDistrict, setMyDistrict] = useState('');
  // Profile panel. Synced to the URL hash (#S000148) so any member's page is
  // linkable and shareable, the foundation for share cards later.
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
            `The data file may not exist yet. Check the "Update Congressional Data" ` +
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
      // Skip odd years, federal general elections are even years; an odd year
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

    const houseVotes = data.some((m) => m.chamber === 'House' && m.voting);
    const senateVotes = data.some((m) => m.chamber === 'Senate' && m.voting);
    const voteScopeNote =
      houseVotes && senateVotes ? 'Recent House and Senate roll calls'
      : houseVotes ? 'House roll calls only. Senate data unavailable on last update'
      : senateVotes ? 'Senate roll calls only. House data unavailable on last update'
      : undefined;

    const row = (label, fmt, pick, note, group = 'overview') => ({
      label,
      note,
      group,
      values: Object.fromEntries(parties.map((p) => [p, pick(groups[p])])),
      fmt,
    });

    const rows = [
      row('Seats held', (v) => v, (g) => g.length),
      row('On the ballot in 2026', (v) => v,
        (g) => g.filter((m) => m.nextElection === '2026').length),
      row('Avg. votes with party', (v) => (v == null ? 'n/a' : `${Math.round(v)}%`),
        (g) => avg(g.filter((m) => m.voting?.partyLinePct != null).map((m) => m.voting.partyLinePct)),
        voteScopeNote),
      row('Share of money from PACs', (v) => (v == null ? 'n/a' : `${Math.round(v)}%`),
        (g) => {
          const pac = g.reduce((a, m) => a + (m.finance?.fromPacs || 0), 0);
          const ind = g.reduce((a, m) => a + (m.finance?.fromIndividuals || 0), 0);
          return pac + ind ? (pac / (pac + ind)) * 100 : null;
        }),
      row('Avg. terms served', (v) => (v == null ? 'n/a' : v.toFixed(1)),
        (g) => avg(g.filter((m) => m.termsServed).map((m) => m.termsServed)), undefined, 'people'),
      row('Avg. age', (v) => (v == null ? 'n/a' : v.toFixed(1)),
        (g) => avg(g.map((m) => ageOf(m.birthday)).filter((a) => a != null)), undefined, 'people'),
      row('First-term members', (v) => v,
        (g) => g.filter((m) => m.termsServed === 1).length, undefined, 'people'),
      row('Avg. votes missed', (v) => (v == null ? 'n/a' : `${v.toFixed(1)}%`),
        (g) => avg(g.filter((m) => m.voting?.missedPct != null).map((m) => m.voting.missedPct)),
        voteScopeNote, 'voting'),
      row('Avg. votes with party', (v) => (v == null ? 'n/a' : `${Math.round(v)}%`),
        (g) => avg(g.filter((m) => m.voting?.partyLinePct != null).map((m) => m.voting.partyLinePct)),
        voteScopeNote, 'voting'),
      row('Members missing 10%+ of votes', (v) => v,
        (g) => g.filter((m) => m.voting?.missedPct != null && m.voting.missedPct >= 10).length,
        voteScopeNote, 'voting'),
      row('Share of money from PACs', (v) => (v == null ? 'n/a' : `${Math.round(v)}%`),
        (g) => {
          const pac = g.reduce((a, m) => a + (m.finance?.fromPacs || 0), 0);
          const ind = g.reduce((a, m) => a + (m.finance?.fromIndividuals || 0), 0);
          return pac + ind ? (pac / (pac + ind)) * 100 : null;
        }, undefined, 'money'),
      row('Members taking zero PAC money', (v) => v,
        (g) => g.filter((m) => m.finance?.pacPct === 0).length, undefined, 'money'),
      row('Total raised this cycle', (v) => (v == null ? 'n/a' : fmtMoney(v)),
        (g) => g.reduce((a, m) => a + (m.finance?.totalRaised || 0), 0) || null, undefined, 'money'),
    ];

    const anyTrades = data.some((m) => m.trades?.ptrCount != null);
    if (anyTrades) {
      const senateCovered = data.some((m) => m.chamber === 'Senate' && m.trades?.ptrCount != null);
      rows.push(
        row('Members disclosing stock trades', (v) => v,
          (g) => g.filter((m) => (m.trades?.ptrCount || 0) > 0).length,
          senateCovered
            ? 'This Congress, per House Clerk and Senate eFD filings.'
            : 'This Congress, per House Clerk filings. Senate data unavailable this run.',
          'money')
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
              {party || 'n/a'}
            </span>
          );
        },
        filterFn: 'equalsString',
      }),
      columnHelper.accessor('chamber', {
        header: 'Chamber',
        cell: (info) => info.getValue() || 'n/a',
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
                {terms ?? 'n/a'}
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
              <span className="num-main">{fmtDate(m.termStart) || 'n/a'}</span>
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
        header: 'Party Line',
        cell: (info) => {
          const v = info.row.original.voting;
          if (!v || v.partyLinePct == null) {
            return <span className="bills-none">n/a</span>;
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
            return <span className="bills-none">n/a</span>;
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
            'n/a'
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
  // user's own delegation, both senators plus their one representative.
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

      <nav className="level-switch" aria-label="Federal or state">
        <button type="button" className={`pill ${level === 'federal' ? 'active' : ''}`} onClick={() => setLevel('federal')}>Federal</button>
        <button type="button" className={`pill ${level === 'state' ? 'active' : ''}`} onClick={() => setLevel('state')}>State Legislatures</button>
      </nav>

      {level === 'state' ? (
        <StateView theme={theme} />
      ) : (
      <>

      <div className="hero">
      <header className="masthead">
        <p className="masthead-eyebrow">The Public Record</p>
        <h1 className="masthead-title">Who&rsquo;s serving you in Congress?</h1>
        <p className="masthead-dek">
          Every current member: their party, their tenure, what they&rsquo;ve
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
      <div
        className="hero-emblem"
        aria-hidden="true"
        dangerouslySetInnerHTML={{ __html: emblemSvg }}
      />
      </div>

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
              {p === 'Democratic' ? <DonkeyIcon size={22} /> :
               p === 'Republican' ? <ElephantIcon size={22} /> :
               <span className="party-dot" aria-hidden="true" />}
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
            <div>
              <h2 className="compare-title">How the parties compare</h2>
              <p className="compare-sub">Same facts, side by side. No scores, just the record.</p>
            </div>
            <div className="pill-group compare-tabs" role="tablist" aria-label="Comparison category">
              {[['overview', 'Overview'], ['voting', 'Voting'], ['money', 'Money'], ['people', 'People']].map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  role="tab"
                  aria-selected={compareTab === k}
                  className={`pill pill-sm ${compareTab === k ? 'active' : ''}`}
                  onClick={() => setCompareTab(k)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="compare-cols">
            <span className="compare-col democratic"><DonkeyIcon size={30} /> Democrats</span>
            <span />
            <span className="compare-col republican">Republicans <ElephantIcon size={30} /></span>
          </div>

          {partyCompare.rows.filter((r) => r.group === compareTab).map((r) => {
            const d = r.values.Democratic;
            const rp = r.values.Republican;
            const dn = typeof d === 'number' ? d : 0;
            const rn = typeof rp === 'number' ? rp : 0;
            const tot = dn + rn || 1;
            return (
              <div key={r.label} className="compare-row">
                <span className="compare-label">{r.label}</span>
                <span className="compare-val democratic">{r.fmt(d)}</span>
                <span className="compare-bar" aria-hidden="true">
                  <span className="compare-fill democratic" style={{ width: `${(dn / tot) * 100}%` }} />
                  <span className="compare-fill republican" style={{ width: `${(rn / tot) * 100}%` }} />
                </span>
                <span className="compare-val republican">{r.fmt(rp)}</span>
              </div>
            );
          })}

          {(() => {
            const notes = [...new Set(partyCompare.rows.filter((r) => r.group === compareTab && r.note).map((r) => r.note))];
            const showLaws = compareTab === 'overview' && lawsByParty?.sourceUrl;
            if (!notes.length && !showLaws) return null;
            return (
              <p className="compare-foot">
                {notes.join(' · ')}
                {showLaws && (
                  <>
                    {notes.length ? ' · ' : ''}
                    Laws:{' '}
                    <a href={lawsByParty.sourceUrl} target="_blank" rel="noopener noreferrer">
                      Congress.gov public laws, {lawsByParty.congress}th Congress ↗
                    </a>
                    {lawsByParty.Independent ? ` · ${lawsByParty.Independent} by Independents` : ''}
                    {lawsByParty.Unknown ? ` · ${lawsByParty.Unknown} by former members` : ''}
                  </>
                )}
              </p>
            );
          })()}
        </section>
      )}

      {/* ---------- find my reps ---------- */}
      <section className="findreps" aria-label="Find your representatives">
        <div className="findreps-head">
          <h2 className="findreps-title">Find your representatives</h2>
          <p className="findreps-sub">
            Pick your state and your House district to see the three people
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
              className={`pill pill-${partyClass(p)} pill-mascot ${partyFilter === p ? 'active' : ''}`}
              onClick={() => setPartyFilter(partyFilter === p ? '' : p)}
            >
              {p === 'Democratic' && <DonkeyIcon size={16} />}
              {p === 'Republican' && <ElephantIcon size={16} />}
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
                                Voting record · {m.voting.chamberScope || m.chamber} · last {m.voting.votesTotal} roll calls
                              </p>
                              <div className="finance-grid">
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {m.voting.partyLinePct ?? 'n/a'}%
                                  </span>
                                  <span className="finance-label">
                                    votes with their party
                                  </span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {m.voting.missedPct ?? 'n/a'}%
                                  </span>
                                  <span className="finance-label">votes missed</span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {m.voting.votesAgainstParty ?? 'n/a'}
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
                                          {rv.bill ? `${rv.bill}: ` : ''}
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
                                    from PACs ({m.finance.pacPct ?? 'n/a'}%)
                                  </span>
                                </div>
                                <div className="finance-stat">
                                  <span className="finance-num">
                                    {fmtMoney(m.finance.fromIndividuals)}
                                  </span>
                                  <span className="finance-label">
                                    from individuals ({m.finance.individualPct ?? 'n/a'}%)
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
                  <div><dt>Terms served</dt><dd>{m.termsServed ?? 'n/a'} <small>since {m.firstYearServed || 'n/a'}</small></dd></div>
                  <div><dt>Age</dt><dd>{ageOf(m.birthday) ?? 'n/a'}</dd></div>
                  <div><dt>Next election</dt><dd>{m.nextElection || 'n/a'}</dd></div>
                  <div><dt>Votes with party</dt><dd>{m.voting?.partyLinePct != null ? `${m.voting.partyLinePct}%` : <small>n/a</small>}</dd></div>
                  <div><dt>Votes missed</dt><dd>{m.voting?.missedPct != null ? `${m.voting.missedPct}%` : <small>n/a</small>}</dd></div>
                  <div><dt>Money from PACs</dt><dd>{m.finance?.pacPct != null ? `${m.finance.pacPct}%` : 'n/a'}</dd></div>
                  <div><dt>Total raised</dt><dd>{m.finance ? fmtMoney(m.finance.totalRaised) : 'n/a'}</dd></div>
                  <div><dt>Bills sponsored</dt><dd>{m.billsTotal ?? (m.bills?.length || 0)}</dd></div>
                  <div><dt>Laws enacted</dt><dd>{m.lawsEnacted ?? 0}</dd></div>
                  <div><dt>Trade reports</dt><dd>{m.trades?.ptrCount != null ? m.trades.ptrCount : <small>n/a</small>}</dd></div>
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

      </>
      )}

      {level === 'federal' && selectedMember && (
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
