import React from 'react';
import { Star } from 'lucide-react';
import './Stars.css';

interface StarsProps {
    /** Оценка от 0 до 5 */
    value: number;
    size?: number;
}

const FIVE = [0, 1, 2, 3, 4];

/**
 * Пять звёзд, залитых по величине оценки.
 *
 * Заливка дробная, а не по округлению: 4.8 — это четыре полных звезды и
 * хвост пятой. При округлении 4.6 и 5.0 выглядели бы одинаково, а разница
 * между ними для покупателя как раз существенная.
 *
 * Сделано наложением: снизу пять контурных звёзд, сверху пять залитых в
 * блоке, обрезанном по ширине. Рисовать половинку звезды отдельной иконкой
 * пришлось бы для каждой доли, а так работает любая.
 */
export const Stars: React.FC<StarsProps> = ({ value, size = 12 }) => {
    const percent = Math.max(0, Math.min(100, (value / 5) * 100));

    return (
        <span
            className="stars"
            role="img"
            aria-label={`Оценка ${value} из 5`}
        >
            <span className="stars-row stars-empty" aria-hidden="true">
                {FIVE.map((i) => (
                    <Star key={i} size={size} />
                ))}
            </span>

            <span
                className="stars-row stars-fill"
                style={{ width: `${percent}%` }}
                aria-hidden="true"
            >
                {FIVE.map((i) => (
                    <Star key={i} size={size} fill="currentColor" />
                ))}
            </span>
        </span>
    );
};
