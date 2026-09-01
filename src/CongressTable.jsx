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
      className={`member-photo ph-${size}`}
      src={url}
      alt={member.name}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

function MemberCard({ member, onOpen }) {
  const m = member;
  const seat =
    m.chamber === 'House' && m.district != null
      ? `${m.state} · District ${m.district}`
      : m.state;
  return (
    <button type="button" className="mcard" onClick={() => onOpen && onOpen(m)}>
      <MemberPhoto member={m} size="lg" />
      <div className="mcard-body">
        <span className="mcard-name">{m.name}</span>
        <span className="mcard-seat">{seat}</span>
        <span className={`party-tag ${partyClass(m.party)}`}>
          <span className="party-dot" aria-hidden="true" />
          {m.party}
        </span>
        <div className="mcard-stats">
          <span>
            <strong>{m.termsServed ?? '—'}</strong>{' '}
            {m.termsServed === 1 ? 'term' : 'terms'}
          </span>
          {m.voting?.partyLinePct != null && (
            <span>
              <strong>{m.voting.partyLinePct}%</strong> party line
            </span>
          )}
          {m.finance?.pacPct != null && (
            <span>
              <strong>{m.finance.pacPct}%</strong> PAC
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

export default function CongressTable() {
  const [data, setData] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [globalFilter, setGlobalFilter] = useState('');
  const [partyFilter, setPartyFilter] = useState('');
  const [chamberFilter, setChamberFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [viewMode, setViewMode] = useState('table'); // 'table' | 'cards'
  const [myState, setMyState] = useState('');
  const [myDistrict, setMyDistrict] = useState('');
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
              : m.state;
          return (
            <div className="member-cell">
              <MemberPhoto member={m} size="sm" />
              <div className="member-ident">
                <span className="member-name">{info.getValue()}</span>
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
        header: 'Current Term',
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
        header: 'Recent Bills',
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
        header: 'PAC-Funded',
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
              onClick={(e) => e.stopPropagation()}
            >
              Congress.gov ↗
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
    initialState: { pagination: { pageSize: 25 } },
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
                onOpen={(mem) => {
                  if (mem.bills?.length || mem.finance || mem.voting) {
                    toggleRow(mem.bioguideId);
                    setViewMode('table');
                    setGlobalFilter(mem.name);
                  }
                }}
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
          {table.getRowModel().rows.map((row) => (
            <MemberCard
              key={row.id}
              member={row.original}
              onOpen={(m) => {
                setViewMode('table');
                setGlobalFilter(m.name);
                if (m.bills?.length || m.finance || m.voting) {
                  toggleRow(m.bioguideId);
                }
              }}
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
                                          {rv.question || rv.result}
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
    </div>
  );
}
