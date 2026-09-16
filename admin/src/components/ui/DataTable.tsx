import React from 'react';
import { Loader2, Inbox } from 'lucide-react';

export interface Column<T> {
    key: string;
    title: string;
    /** Как отрисовать ячейку. По умолчанию — значение поля key как текст. */
    render?: (row: T) => React.ReactNode;
    className?: string;
}

interface DataTableProps<T> {
    columns: Column<T>[];
    rows: T[];
    rowKey: (row: T) => string;
    loading?: boolean;
    error?: string | null;
    emptyText?: string;
    onRowClick?: (row: T) => void;
}

/**
 * Таблица админки.
 *
 * Заведена, потому что одна и та же разметка была скопирована на шести
 * страницах, и состояние загрузки в каждой выглядело по-своему: где-то
 * скелетон, где-то текст Loading.
 */
export function DataTable<T>({
    columns, rows, rowKey, loading, error, emptyText = 'Пусто', onRowClick,
}: DataTableProps<T>) {
    return (
        <div className="bg-gray-800 rounded-xl overflow-hidden shadow-lg border border-gray-700">
            <div className="overflow-x-auto">
                <table className="w-full text-left">
                    <thead className="bg-gray-700/50">
                        <tr>
                            {columns.map((column) => (
                                <th
                                    key={column.key}
                                    className={`px-4 py-3 text-gray-400 font-medium text-sm whitespace-nowrap ${column.className ?? ''}`}
                                >
                                    {column.title}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                        {loading && (
                            <tr>
                                <td colSpan={columns.length} className="px-4 py-12 text-center text-gray-400">
                                    <Loader2 size={22} className="animate-spin inline-block" />
                                </td>
                            </tr>
                        )}

                        {!loading && error && (
                            <tr>
                                <td colSpan={columns.length} className="px-4 py-10 text-center text-red-400">
                                    {error}
                                </td>
                            </tr>
                        )}

                        {!loading && !error && rows.length === 0 && (
                            <tr>
                                <td colSpan={columns.length} className="px-4 py-12 text-center text-gray-500">
                                    <Inbox size={22} className="inline-block mb-2" />
                                    <div className="text-sm">{emptyText}</div>
                                </td>
                            </tr>
                        )}

                        {!loading && !error && rows.map((row) => (
                            <tr
                                key={rowKey(row)}
                                onClick={onRowClick ? () => onRowClick(row) : undefined}
                                className={`hover:bg-gray-700/30 transition-colors ${onRowClick ? 'cursor-pointer' : ''}`}
                            >
                                {columns.map((column) => (
                                    <td
                                        key={column.key}
                                        className={`px-4 py-3 text-gray-200 text-sm ${column.className ?? ''}`}
                                    >
                                        {column.render
                                            ? column.render(row)
                                            : String((row as any)[column.key] ?? '')}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
