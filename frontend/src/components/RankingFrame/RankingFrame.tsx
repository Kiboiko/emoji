import type { ReactNode } from 'react';
import { useAuthStore } from '@/store/authStore';
import gold from './gold.svg';
import silver from './silver.svg';
import bronze from './bronze.svg';
import './RankingFrame.css';

const medals = {
    gold: { rank: 1, image: gold },
    silver: { rank: 2, image: silver },
    bronze: { rank: 3, image: bronze },
};
type Medal = keyof typeof medals;
const medalsByPlace = ['gold', 'silver', 'bronze'] as const;

export function RankingFrame({ medal, rank: place, children, className = '' }: {
    medal?: Medal | null; rank?: number | null; children: ReactNode; className?: string;
}) {
    const language = useAuthStore(state => state.language);
    const award = medal ?? medalsByPlace[(place ?? 0) - 1];
    const ornament = award && medals[award];
    return (
        <span className={`ranking-frame ${award ? `medal-${award}` : 'medal-none'} ${className}`}>
            <span className="ranking-frame-portrait">{children}</span>
            {ornament && (
                <>
                    <span className="visually-hidden">{language === 'ru'
                        ? `${ornament.rank}-е место в рейтинге. ` : `Rank ${ornament.rank}. `}</span>
                    <img className="ranking-frame-ornament" src={ornament.image} alt="" aria-hidden="true" />
                </>
            )}
        </span>
    );
}
