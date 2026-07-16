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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [globalFilter, setGlobalFilter] = useState('');
  const [partyFilter, setPartyFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');

  // Fetch congressional data on mount
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        // This path assumes congress_data.json is in public folder
        const response = await fetch('/congress_data.json');
        if (!response.ok) throw new Error('Failed to fetch data');
        
        const json = await response.json();
        setData(json.members || []);
      } catch (err) {
        setError(err.message);
        console.error('Error fetching congressional data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  // Define columns
  const columns = [
    columnHelper.accessor('name', {
      header: 'Name',
      cell: (info) => <strong>{info.getValue()}</strong>,
    }),
    columnHelper.accessor('state', {
      header: 'State',
      cell: (info) => info.getValue() || '-',
    }),
    columnHelper.accessor('chamber', {
      header: 'Chamber',
      cell: (info) => {
        const chamber = info.getValue();
        return <span className={`chamber ${chamber?.toLowerCase()}`}>{chamber}</span>;
      },
    }),
    columnHelper.accessor('party', {
      header: 'Party',
      cell: (info) => {
        const party = info.getValue();
        return <span className={`party ${party?.toLowerCase()}`}>{party}</span>;
      },
    }),
    columnHelper.accessor('district', {
      header: 'District',
      cell: (info) => info.getValue() || '-',
    }),
    columnHelper.accessor('termStart', {
      header: 'Term Start',
      cell: (info) => {
        const date = info.getValue();
        return date ? new Date(date).toLocaleDateString() : '-';
      },
    }),
    columnHelper.accessor('termEnd', {
      header: 'Term End',
      cell: (info) => {
        const date = info.getValue();
        return date ? new Date(date).toLocaleDateString() : '-';
      },
    }),
    columnHelper.accessor('bills', {
      header: 'Bills Sponsored',
      cell: (info) => {
        const bills = info.getValue() || [];
        return (
          <details className="bills-summary">
            <summary>{bills.length} bills</summary>
            {bills.length > 0 && (
              <ul className="bills-list">
                {bills.slice(0, 5).map((bill, idx) => (
                  <li key={idx}>
                    <strong>{bill.billNumber}:</strong> {bill.title.substring(0, 60)}...
                    <br />
                    <small>{bill.summary.substring(0, 80)}...</small>
                    <br />
                    <a href={bill.sourceUrl} target="_blank" rel="noopener noreferrer" className="source-link">
                      View on Congress.gov
                    </a>
                  </li>
                ))}
                {bills.length > 5 && <li className="more-indicator">+ {bills.length - 5} more</li>}
              </ul>
            )}
          </details>
        );
      },
    }),
    columnHelper.accessor('website', {
      header: 'Contact',
      cell: (info) => {
        const url = info.getValue();
        return url ? (
          <a href={url} target="_blank" rel="noopener noreferrer" className="source-link">
            Website
          </a>
        ) : (
          '-'
        );
      },
    }),
    columnHelper.accessor('sourceUrl', {
      header: 'Source',
      cell: (info) => (
        <a href={info.getValue()} target="_blank" rel="noopener noreferrer" className="source-link">
          Congress.gov
        </a>
      ),
    }),
  ];

  // Initialize table
  const table = useReactTable({
    data,
    columns,
    state: {
      globalFilter,
      columnFilters: [
        { id: 'party', value: partyFilter },
        { id: 'state', value: stateFilter },
      ],
    },
    onGlobalFilterChange: setGlobalFilter,
    getFilteredRowModel: getFilteredRowModel(),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  // Get unique values for filter dropdowns
  const parties = [...new Set(data.map((d) => d.party))].filter(Boolean).sort();
  const states = [...new Set(data.map((d) => d.state))].filter(Boolean).sort();

  if (loading) {
    return (
      <div className="congress-container">
        <div className="loading">Loading congressional data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="congress-container">
        <div className="error">Error: {error}</div>
      </div>
    );
  }

  return (
    <div className="congress-container">
      <header className="header">
        <h1>U.S. Federal Politicians Tracker</h1>
        <p>Track bills, voting records, and more for current members of Congress</p>
        <p className="data-attribution">
          Data sourced from{' '}
          <a href="https://api.congress.gov" target="_blank" rel="noopener noreferrer">
            Congress.gov API
          </a>
          {' '}| Last updated: {data.length > 0 ? new Date().toLocaleDateString() : 'N/A'}
        </p>
      </header>

      <div className="filters">
        <div className="filter-group">
          <label htmlFor="search">Search Name/State:</label>
          <input
            id="search"
            type="text"
            placeholder="Search by name or state..."
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="filter-input"
          />
        </div>

        <div className="filter-group">
          <label htmlFor="party-filter">Party:</label>
          <select
            id="party-filter"
            value={partyFilter}
            onChange={(e) => setPartyFilter(e.target.value)}
            className="filter-select"
          >
            <option value="">All Parties</option>
            {parties.map((party) => (
              <option key={party} value={party}>
                {party}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="state-filter">State:</label>
          <select
            id="state-filter"
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            className="filter-select"
          >
            <option value="">All States</option>
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
                      <span className="sort-indicator">
                        {header.column.getIsSorted()
                          ? header.column.getIsSorted() === 'desc'
                            ? ' ↓'
                            : ' ↑'
                          : ' ↕'}
                      </span>
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
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
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
          Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
        </span>
        <button onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
          Next →
        </button>
        <select
          value={table.getState().pagination.pageSize}
          onChange={(e) => table.setPageSize(Number(e.target.value))}
          className="page-size-select"
        >
          {[10, 25, 50].map((pageSize) => (
            <option key={pageSize} value={pageSize}>
              Show {pageSize}
            </option>
          ))}
        </select>
      </div>

      <footer className="footer">
        <p>
          <strong>Data Sources:</strong> Congress.gov API | <strong>Update Frequency:</strong> Nightly
        </p>
        <p className="disclaimer">
          This tool aggregates publicly available data. For official records, always refer to{' '}
          <a href="https://www.congress.gov" target="_blank" rel="noopener noreferrer">
            Congress.gov
          </a>
          .
        </p>
      </footer>
    </div>
  );
}
