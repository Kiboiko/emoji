import React from 'react';
import {
    AlertCircle, AlertTriangle, Check, CheckCheck, Clock, Package, RotateCcw, ShieldCheck,
} from 'lucide-react';
import type { DealMessage } from '@/types';
import { dayLabel, fmtTime, sameDay, splitCode } from './dealFormat';
import { withGram } from '@/components/Gram/Gram';

/** Сообщение в ленте: с сервера или своё, ещё не дошедшее до него */
export interface ChatMessage extends DealMessage {
    localId?: string;
    pending?: 'sending' | 'failed';
    /** Локальное превью фото, пока оно загружается */
    localPhoto?: string;
    /** Файл фото — чтобы повторить отправку, если она не удалась */
    retryFile?: File;
}

type T = (ru: string, en: string) => string;

const SYSTEM_ICON: Record<string, React.ReactNode> = {
    pay: <ShieldCheck size={15} />,
    ship: <Package size={15} />,
    done: <Check size={15} />,
    resolved: <Check size={15} />,
    refund: <RotateCcw size={15} />,
    dispute: <AlertTriangle size={15} />,
};

/** Сообщение площадки на языке приложения; у старых английского нет */
export const systemText = (m: { text: string | null; text_en?: string | null }, language: string) =>
    (language === 'en' && m.text_en) || m.text;

const Tick: React.FC<{ message: ChatMessage }> = ({ message }) => {
    if (message.pending === 'sending') return <Clock size={11} />;
    if (message.pending === 'failed') return <AlertCircle size={13} className="dchat-failed-icon" />;
    if (message.state === 'read') return <CheckCheck size={15} />;
    return <Check size={14} />;
};

const Text: React.FC<{ text: string; onCopy: (value: string) => void; t: T }> = ({ text, onCopy, t }) => (
    <span className="dchat-txt">
        {splitCode(text).map((part, index) => part.code ? (
            <button
                key={index}
                type="button"
                className="dchat-code"
                onClick={() => onCopy(part.value)}
                title={t('Нажмите, чтобы скопировать', 'Tap to copy')}
            >
                {part.value}
            </button>
        ) : (
            <React.Fragment key={index}>{part.value}</React.Fragment>
        ))}
    </span>
);

export const MessageList: React.FC<{
    messages: ChatMessage[];
    language: string;
    t: T;
    onCopy: (value: string) => void;
    onRetry: (message: ChatMessage) => void;
    onOpenPhoto: (url: string) => void;
}> = ({ messages, language, t, onCopy, onRetry, onOpenPhoto }) => {
    const items: React.ReactNode[] = [];

    messages.forEach((message, index) => {
        const prev = messages[index - 1];
        const next = messages[index + 1];
        const key = message.localId ?? message.id;

        if (!prev || !sameDay(prev.created_at, message.created_at)) {
            items.push(
                <div key={`day-${key}`} className="dchat-day">
                    {dayLabel(message.created_at, language, t)}
                </div>,
            );
        }

        const time = fmtTime(message.created_at, language);

        if (message.from === 'system') {
            items.push(
                <div key={key} className={`dchat-sys ${message.kind ?? ''}`}>
                    {SYSTEM_ICON[message.kind ?? ''] ?? <ShieldCheck size={15} />}
                    <span>
                        {withGram(systemText(message, language))} <span className="dchat-sys-time">{time}</span>
                    </span>
                </div>,
            );
            return;
        }

        const dir = message.from === 'me' ? 'out' : message.from === 'moderator' ? 'mod' : 'in';
        const continues = (other?: ChatMessage) =>
            other && other.from === message.from && other.from !== 'system'
            && sameDay(other.created_at, message.created_at);
        const first = !continues(prev);
        const tail = !continues(next);

        const meta = (
            <span className="dchat-meta">
                {time}
                {dir === 'out' && <Tick message={message} />}
            </span>
        );
        const photo = message.localPhoto ?? message.photo_url;

        items.push(
            <div
                key={key}
                className={`dchat-msg ${dir}${first ? ' first' : ''}${tail ? ' tail' : ''}`}
            >
                {photo ? (
                    <div className="dchat-bubble media">
                        <button
                            type="button"
                            className="dchat-shot"
                            onClick={() => message.photo_url && onOpenPhoto(message.photo_url)}
                            aria-label={t('Открыть фото', 'Open photo')}
                        >
                            <img src={photo} alt="" loading="lazy" />
                        </button>
                        {message.text && (
                            <span className="dchat-caption">
                                <Text text={message.text} onCopy={onCopy} t={t} />
                            </span>
                        )}
                        {meta}
                    </div>
                ) : (
                    <div className="dchat-bubble">
                        {dir === 'mod' && first && (
                            <span className="dchat-from">
                                <ShieldCheck size={13} />
                                {t('Модератор', 'Moderator')}
                            </span>
                        )}
                        {message.legacy_media && (
                            <span className={`dchat-legacy${message.text ? '' : ' solo'}`}>
                                {t('Вложение из переписки через бота', 'Attachment sent via the bot')}
                            </span>
                        )}
                        {message.text && <Text text={message.text} onCopy={onCopy} t={t} />}
                        {meta}
                    </div>
                )}

                {message.pending === 'failed' && (
                    <button type="button" className="dchat-retry" onClick={() => onRetry(message)}>
                        {t('Не отправлено. Нажмите, чтобы повторить', 'Not sent. Tap to retry')}
                    </button>
                )}
            </div>,
        );
    });

    return <>{items}</>;
};
