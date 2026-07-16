import React, { useEffect, useState } from 'react';
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

export default function CongressTable() {
  const [data, setData] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [globalFilter, setGlobalFilter] = useState('');
  const [partyFilter, setPartyFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${import.meta.env.BASE_URL}congress_data.json`);
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

  const columns = [
    columnHelper.accessor('name', {
      header: 'Name',
      cell: (info) => <strong>{info.getValue()}</strong>,
    }),
    columnHelper.accessor('state', {
      header: 'State',
      cell: (info) => info.getValue() || '-',
      filterFn: 'equalsString',
    }),
    columnHelper.accessor('chamber', {
      header: 'Chamber',
      cell: (info) => {
        const chamber = info.getValue() || '';
        const cls = chamber.toLowerCase().includes('senate') ? 'senate' : 'house';
        return chamber ? <span className={`chamber ${cls}`}>{chamber}</span> : '-';
      },
    }),
    columnHelper.accessor('party', {
      header: 'Party',
      cell: (info) => {
        const party = info.getValue() || '';
        const cls = party.toLowerCase().replace(/[^a-z]/g, '-');
        return party ? <span className={`party ${cls}`}>{party}</span> : '-';
      },
      filterFn: 'equalsString',
    }),
    columnHelper.accessor('district', {
      header: 'District',
      cell: (info) => {
        const d = info.getValue();
        return d === null || d === undefined ? '-' : d;
      },
    }),
    columnHelper.accessor('termStart', {
      header: 'Current Term Began',
      cell: (info) => {
        const v = info.getValue();
        if (!v) return '-';
        // Parse as UTC so the date doesn't shift a day in western timezones.
        const d = new Date(`${v}T00:00:00Z`);
        return isNaN(d) ? v : d.toLocaleDateString(undefined, { timeZone: 'UTC' });
      },
    }),
    columnHelper.accessor('firstYearServed', {
      header: 'In Office Since',
      cell: (info) => info.getValue() || '-',
    }),
    columnHelper.accessor('termsServed', {
      header: 'Terms Served',
      cell: (info) => info.getValue() ?? '-',
    }),
    columnHelper.accessor('nextElection', {
      header: 'Next Election',
      cell: (info) => info.getValue() || '-',
    }),
    columnHelper.accessor('bills', {
      header: 'Bills Sponsored',
      enableSorting: false,
      cell: (info) => {
        const bills = info.getValue() || [];
        if (bills.length === 0) return <span className="more-indicator">None found</span>;
        return (
          <details className="bills-summary">
            <summary>{bills.length} bills</summary>
            <ul className="bills-list">
              {bills.slice(0, 5).map((bill, idx) => (
                <li key={idx}>
                  <strong>{bill.billNumber}</strong>
                  {bill.title ? `: ${bill.title.substring(0, 70)}` : ''}
                  {bill.title && bill.title.length > 70 ? '…' : ''}
                  {bill.latestAction && (
                    <>
                      <br />
                      <small>{bill.latestAction.substring(0, 90)}</small>
                    </>
                  )}
                  {bill.sourceUrl && (
                    <>
                      <br />
                      <a
                        href={bill.sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="source-link"
                      >
                        View on Congress.gov
                      </a>
                    </>
                  )}
                </li>
              ))}
              {bills.length > 5 && (
                <li className="more-indicator">+ {bills.length - 5} more</li>
              )}
            </ul>
          </details>
        );
      },
    }),
    columnHelper.accessor('sourceUrl', {
      header: 'Source',
      enableSorting: false,
      cell: (info) =>
        info.getValue() ? (
          <a
            href={info.getValue()}
            target="_blank"
            rel="noopener noreferrer"
            className="source-link"
          >
            Congress.gov
          </a>
        ) : (
          '-'
        ),
    }),
  ];

  const columnFilters = [];
  if (partyFilter) columnFilters.push({ id: 'party', value: partyFilter });
  if (stateFilter) columnFilters.push({ id: 'state', value: stateFilter });

  const table = useReactTable({
    data,
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

  const parties = [...new Set(data.map((d) => d.party))].filter(Boolean).sort();
  const states = [...new Set(data.map((d) => d.state))].filter(Boolean).sort();

  if (loading) {
    return (
      <div className="congress-container">
        <div className="loading">Loading congressional data…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="congress-container">
        <div className="error">{error}</div>
      </div>
    );
  }

  return (
    <div className="congress-container">
      <header className="header">
        <h1>U.S. Federal Politicians Tracker</h1>
        <p>Bills, terms, and party data for current members of Congress</p>
        <p className="data-attribution">
          Data from{' '}
          <a href="https://api.congress.gov" target="_blank" rel="noopener noreferrer">
            the Congress.gov API
          </a>
          {lastUpdated && ` · Last updated: ${new Date(lastUpdated).toLocaleString()}`}
        </p>
      </header>

      <div className="filters">
        <div className="filter-group">
          <label htmlFor="search">Search</label>
          <input
            id="search"
            type="text"
            placeholder="Name, state, party…"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="filter-input"
          />
        </div>

        <div className="filter-group">
          <label htmlFor="party-filter">Party</label>
          <select
            id="party-filter"
            value={partyFilter}
            onChange={(e) => setPartyFilter(e.target.value)}
            className="filter-select"
          >
            <option value="">All parties</option>
            {parties.map((party) => (
              <option key={party} value={party}>
                {party}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="state-filter">State</label>
          <select
            id="state-filter"
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            className="filter-select"
          >
            <option value="">All states</option>
            {states.map((state) => (
              <option key={state} value={state}>
                {state}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group info">
          Showing {table.getRowModel().rows.length} of {data.length} members
        </div>
      </div>

      <div className="table-wrapper">
        <table className="congress-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} onClick={header.column.getToggleSortingHandler()}>
                    <div className="header-cell">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getCanSort() && (
                        <span className="sort-indicator">
                          {header.column.getIsSorted() === 'desc'
                            ? ' ↓'
                            : header.column.getIsSorted() === 'asc'
                            ? ' ↑'
                            : ' ↕'}
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="pagination">
        <button onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
          ← Previous
        </button>
        <span className="page-info">
          Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount() || 1}
        </span>
        <button onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
          Next →
        </button>
        <select
          value={table.getState().pagination.pageSize}
          onChange={(e) => table.setPageSize(Number(e.target.value))}
          className="page-size-select"
        >
          {[10, 25, 50, 100].map((pageSize) => (
            <option key={pageSize} value={pageSize}>
              Show {pageSize}
            </option>
          ))}
        </select>
      </div>

      <footer className="footer">
        <p>
          <strong>Source:</strong> Congress.gov API · <strong>Updates:</strong> nightly
        </p>
        <p className="disclaimer">
          Terms are counted as one per Congress served. Next election is derived from the
          current term's end year. This tool aggregates publicly available data — for
          official records, refer to{' '}
          <a href="https://www.congress.gov" target="_blank" rel="noopener noreferrer">
            Congress.gov
          </a>
          .
        </p>
      </footer>
    </div>
  );
}
