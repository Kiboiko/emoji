import React, { useState } from 'react';

export interface ChartPoint {
    label: string;
    value: number;
    /** Вторая величина для подписи — например число заказов рядом с выручкой */
    secondary?: number;
}

interface BarChartProps {
    points: ChartPoint[];
    formatValue?: (v: number) => string;
    formatSecondary?: (v: number) => string;
    height?: number;
}

/**
 * Столбчатый график на SVG.
 *
 * Своя реализация вместо библиотеки: recharts с зависимостями весит больше,
 * чем весь текущий бандл админки, ради одного графика на одном экране.
 */
export const BarChart: React.FC<BarChartProps> = ({
    points, formatValue = (v) => String(v), formatSecondary, height = 180,
}) => {
    const [hover, setHover] = useState<number | null>(null);

    if (points.length === 0) {
        return <div className="text-gray-500 text-sm py-8 text-center">Нет данных</div>;
    }

    const max = Math.max(...points.map((p) => p.value));
    // Пустой период не должен делить на ноль и рисовать столбцы во всю высоту
    const scale = max > 0 ? max : 1;

    // Подписи по оси X прореживаем: на 30 днях они сливаются в кашу
    const labelStep = Math.ceil(points.length / 8);

    return (
        <div>
            <div className="flex items-end gap-[2px]" style={{ height }}>
                {points.map((point, index) => {
                    const ratio = point.value / scale;
                    const active = hover === index;

                    return (
                        <div
                            key={index}
                            className="flex-1 min-w-0 h-full flex items-end relative"
                            onMouseEnter={() => setHover(index)}
                            onMouseLeave={() => setHover(null)}
                        >
                            <div
                                className={`w-full rounded-t transition-colors ${
                                    active ? 'bg-blue-400' : 'bg-blue-600/70'
                                }`}
                                style={{
                                    // Ненулевые значения показываем хотя бы полоской:
                                    // иначе день с маленькой продажей неотличим от пустого
                                    height: point.value > 0
                                        ? `${Math.max(ratio * 100, 2)}%`
                                        : '1px',
                                    backgroundColor: point.value > 0 ? undefined : 'rgb(55 65 81)',
                                }}
                            />

                            {active && (
                                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-10 whitespace-nowrap bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white shadow-lg">
                                    <div className="font-medium">{formatValue(point.value)}</div>
                                    {point.secondary !== undefined && formatSecondary && (
                                        <div className="text-gray-400">
                                            {formatSecondary(point.secondary)}
                                        </div>
                                    )}
                                    <div className="text-gray-500">{point.label}</div>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>

            <div className="flex gap-[2px] mt-2">
                {points.map((point, index) => (
                    <div key={index} className="flex-1 min-w-0 text-center">
                        {index % labelStep === 0 && (
                            <span className="text-[10px] text-gray-500">
                                {point.label.slice(5)}
                            </span>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
};
