/**
 * DataTable — consistent table component for ORBIT.
 * 
 * Usage:
 *   <DataTable
 *     columns={[
 *       { key: 'name', label: 'Customer', width: '200px' },
 *       { key: 'premium', label: 'Premium', align: 'right', render: (v) => `$${v}` },
 *     ]}
 *     data={reshops}
 *     onRowClick={(row) => openDetail(row.id)}
 *     emptyMessage="No reshops found"
 *   />
 */

import React from 'react';
import { EmptyState, TableLoader } from './LoadingStates';
import { Inbox } from 'lucide-react';

interface Column {
  key: string;
  label: string;
  width?: string;
  align?: 'left' | 'center' | 'right';
  render?: (value: any, row: any) => React.ReactNode;
  sortable?: boolean;
}

interface DataTableProps {
  columns: Column[];
  data: any[];
  loading?: boolean;
  onRowClick?: (row: any) => void;
  emptyMessage?: string;
  emptyDescription?: string;
  emptyAction?: () => void;
  emptyActionLabel?: string;
  maxHeight?: string;
}

export default function DataTable({
  columns,
  data,
  loading,
  onRowClick,
  emptyMessage = 'No data',
  emptyDescription,
  emptyAction,
  emptyActionLabel,
  maxHeight,
}: DataTableProps) {
  if (loading) {
    return <TableLoader rows={6} cols={columns.length} />;
  }

  if (data.length === 0) {
    return (
      <EmptyState
        icon={<Inbox size={40} />}
        title={emptyMessage}
        description={emptyDescription}
        action={emptyAction}
        actionLabel={emptyActionLabel}
      />
    );
  }

  return (
    <div style={{
      borderRadius: '12px',
      border: '1px solid rgba(255,255,255,0.06)',
      overflow: 'hidden',
      ...(maxHeight ? { maxHeight, overflowY: 'auto' as const } : {}),
    }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  padding: '12px 16px',
                  fontSize: '11px',
                  fontWeight: 600,
                  color: '#64748b',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  textAlign: col.align || 'left',
                  width: col.width,
                  position: 'sticky',
                  top: 0,
                  background: 'rgba(15,23,42,0.95)',
                  backdropFilter: 'blur(8px)',
                  zIndex: 1,
                }}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIdx) => (
            <tr
              key={row.id || rowIdx}
              onClick={() => onRowClick?.(row)}
              style={{
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                cursor: onRowClick ? 'pointer' : 'default',
                transition: 'background 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent';
              }}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  style={{
                    padding: '12px 16px',
                    fontSize: '14px',
                    color: '#e2e8f0',
                    textAlign: col.align || 'left',
                  }}
                >
                  {col.render ? col.render(row[col.key], row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
