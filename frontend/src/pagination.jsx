import React, {useEffect, useMemo, useState} from 'react';

const PAGE_SIZES = [10, 25, 50, 100];

export default function PaginatedRows({rows = [], children}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const rowsKey = rows.map(row => row?.id ?? row?.user_id ?? row?.device_id ?? row?.email ?? '').join('|');
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageRows = useMemo(() => rows.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [rows, currentPage, pageSize]);

  useEffect(() => setPage(1), [rowsKey]);

  return <>
    {children(pageRows)}
    {rows.length > 0 && <Pagination total={rows.length} page={currentPage} pageSize={pageSize}
      onPageChange={setPage} onPageSizeChange={size => {setPageSize(size); setPage(1)}}/>}
  </>;
}

function Pagination({total, page, pageSize, onPageChange, onPageSizeChange}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  const pageItems = totalPages <= 5 ? Array.from({length: totalPages}, (_, index) => index + 1)
    : [...new Set([1, page - 1, page, page + 1, totalPages])]
      .filter(value => value >= 1 && value <= totalPages).sort((a, b) => a - b);
  const buttons = pageItems.flatMap((value, index) => index > 0 && value - pageItems[index - 1] > 1
    ? [{ellipsis: true, key: `ellipsis-${value}`}, {value, key: value}]
    : [{value, key: value}]);
  const sizes = [...new Set([...PAGE_SIZES, ...(total > 100 ? [total] : [])])];

  return <nav className="pagination" aria-label="Table pagination">
    <span className="paginationSummary">Showing {start} to {end} of {total} entries</span>
    <div className="paginationControls">
      <button type="button" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>Prev</button>
      {buttons.map(item => item.ellipsis
        ? <span className="paginationEllipsis" key={item.key} aria-hidden="true">...</span>
        : <button type="button" key={item.key} className={item.value === page ? 'current' : ''}
          aria-current={item.value === page ? 'page' : undefined} aria-label={`Page ${item.value}`}
          onClick={() => onPageChange(item.value)}>{item.value}</button>)}
      <button type="button" onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}>Next</button>
    </div>
    <label className="paginationSize">Show entries<select value={pageSize}
      onChange={event => onPageSizeChange(Number(event.target.value))}>
      {sizes.map(size => <option value={size} key={size}>{size}</option>)}
    </select></label>
  </nav>;
}
