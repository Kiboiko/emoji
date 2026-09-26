import { useEffect, useState } from 'react';
import { settingsApi } from '@/api/client';
import type { PublicSettings } from '@/types';

/**
 * Комиссии площадки.
 *
 * Значение одно на всё приложение и меняется раз в полгода, поэтому кэш
 * живёт в модуле: витрина продавца и кабинет каналов спрашивают его
 * независимо, а запрос уходит один.
 *
 * Возвращает null, пока не загрузилось или если запрос не прошёл. Строка
 * с комиссией при этом просто не рисуется — врать про процент нельзя.
 */
let cached: PublicSettings | null = null;
let inflight: Promise<PublicSettings> | null = null;

export const usePublicSettings = (): PublicSettings | null => {
    const [value, setValue] = useState<PublicSettings | null>(cached);

    useEffect(() => {
        if (cached) return;

        let alive = true;
        const request = inflight ?? settingsApi.getPublic();
        inflight = request;

        request
            .then((data) => {
                cached = data;
                if (alive) setValue(data);
            })
            .catch(() => {
                // Даём следующему вызову попробовать снова
                inflight = null;
            });

        return () => { alive = false; };
    }, []);

    return value;
};
