import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PaginationProps {
    total: number;
    skip: number;
    limit: number;
    onChange: (skip: number) => void;
}

export const Pagination: React.FC<PaginationProps> = ({ total, skip, limit, onChange }) => {
    if (total <= limit) return null;

    const page = Math.floor(skip / limit) + 1;
    const pages = Math.ceil(total / limit);
    const from = skip + 1;
    const to = Math.min(skip + limit, total);

    return (
        <div className="flex items-center justify-between mt-4 text-sm text-gray-400">
            <span>
                {from}–{to} из {total}
            </span>

            <div className="flex items-center gap-2">
                <button
                    disabled={page <= 1}
                    onClick={() => onChange(Math.max(0, skip - limit))}
                    className="p-2 rounded-lg bg-gray-800 border border-gray-700 disabled:opacity-40 hover:bg-gray-700 transition-colors"
                >
                    <ChevronLeft size={16} />
                </button>

                <span className="px-2">
                    {page} / {pages}
                </span>

                <button
                    disabled={page >= pages}
                    onClick={() => onChange(skip + limit)}
                    className="p-2 rounded-lg bg-gray-800 border border-gray-700 disabled:opacity-40 hover:bg-gray-700 transition-colors"
                >
                    <ChevronRight size={16} />
                </button>
            </div>
        </div>
    );
};
