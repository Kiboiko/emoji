import React from 'react';
import { Loader2, Inbox } from 'lucide-react';

export interface Column<T> {
    key: string;
    /** Подпись колонки. Она же ярлык рядом со значением в карточке. */
    title: string;
    /**
     * Шапка, когда одного текста мало — например, со значком сортировки.
     * В карточке на телефоне всё равно используется title: значок
     * сортировки рядом со значением ничего не означает.
     */
    header?: React.ReactNode;
    onHeaderClick?: () => void;
    /** Как отрисовать ячейку. По умолчанию — значение поля key как текст. */
    render?: (row: T) => React.ReactNode;
    className?: string;
    /**
     * Показывать на телефоне отдельной строкой во всю ширину, без подписи.
     * Для заголовка записи и для колонки с кнопками: подпись «Действие»
     * рядом с кнопкой ничего не добавляет.
     */
    wide?: boolean;
    /** Не показывать на телефоне вовсе — для служебных колонок вроде id */
    hideOnMobile?: boolean;
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
 *
 * На телефоне таблицы нет вовсе: строка превращается в карточку с парами
 * «подпись — значение». Горизонтальная прокрутка формально работала, но
 * читать таблицу из шести колонок на экране в 390 точек, возя её пальцем
 * вбок, нельзя — видно одну колонку за раз и не с чем сопоставить.
 */
export function DataTable<T>({
    columns, rows, rowKey, loading, error, emptyText = 'Пусто', onRowClick,
}: DataTableProps<T>) {
    const state = loading ? 'loading'
        : error ? 'error'
            : rows.length === 0 ? 'empty'
                : 'rows';

    // Одна и та же заглушка на оба вида: раньше пустое состояние в таблице и
    // в списке пришлось бы держать в двух местах и они бы разошлись
    const placeholder = (
        <>
            {state === 'loading' && (
                <div className="px-4 py-12 text-center text-gray-400">
                    <Loader2 size={22} className="animate-spin inline-block" />
                </div>
            )}
            {state === 'error' && (
                <div className="px-4 py-10 text-center text-red-400">{error}</div>
            )}
            {state === 'empty' && (
                <div className="px-4 py-12 text-center text-gray-500">
                    <Inbox size={22} className="inline-block mb-2" />
                    <div className="text-sm">{emptyText}</div>
                </div>
            )}
        </>
    );

    const cell = (column: Column<T>, row: T) => (column.render
        ? column.render(row)
        : String((row as any)[column.key] ?? ''));

    return (
        <div className="bg-gray-800 rounded-xl overflow-hidden shadow-lg border border-gray-700">
            {/* --- Телефон: карточки --- */}
            <div className="md:hidden">
                {state !== 'rows' ? placeholder : (
                    <div className="divide-y divide-gray-700">
                        {rows.map((row) => (
                            <div
                                key={rowKey(row)}
                                onClick={onRowClick ? () => onRowClick(row) : undefined}
                                className={`p-4 space-y-2 ${onRowClick ? 'cursor-pointer active:bg-gray-700/40' : ''}`}
                            >
                                {columns.filter((column) => !column.hideOnMobile).map((column) => (
                                    column.wide || !column.title ? (
                                        <div key={column.key} className="text-sm text-gray-200 break-words">
                                            {cell(column, row)}
                                        </div>
                                    ) : (
                                        <div key={column.key} className="flex items-start justify-between gap-3">
                                            <span className="shrink-0 text-xs text-gray-400 pt-0.5">
                                                {column.title}
                                            </span>
                                            {/* min-w-0 обязателен: без него длинный адрес
                                                кошелька распирает карточку и появляется
                                                горизонтальная прокрутка страницы */}
                                            <span className="min-w-0 text-sm text-gray-200 text-right break-words">
                                                {cell(column, row)}
                                            </span>
                                        </div>
                                    )
                                ))}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* --- Экран пошире: обычная таблица --- */}
            <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-left">
                    <thead className="bg-gray-700/50">
                        <tr>
                            {columns.map((column) => (
                                <th
                                    key={column.key}
                                    onClick={column.onHeaderClick}
                                    className={`px-4 py-3 text-gray-400 font-medium text-sm whitespace-nowrap ${column.onHeaderClick ? 'cursor-pointer select-none hover:bg-gray-700/60' : ''} ${column.className ?? ''}`}
                                >
                                    {column.header ?? column.title}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                        {state !== 'rows' ? (
                            <tr>
                                <td colSpan={columns.length} className="p-0">{placeholder}</td>
                            </tr>
                        ) : rows.map((row) => (
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
                                        {cell(column, row)}
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
