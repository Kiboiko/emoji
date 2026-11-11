import { useState } from 'react';
import { UserRound } from 'lucide-react';
import './ChatAvatar.css';

export function ChatAvatar({ src, className = '' }: { src?: string | null; className?: string }) {
    const [failed, setFailed] = useState<string | null>(null);
    return <span className={`chat-avatar ${className}`} aria-hidden="true">
        {src && failed !== src
            ? <img src={src} alt="" referrerPolicy="no-referrer" onError={() => setFailed(src)} />
            : <UserRound size={20} />}
    </span>;
}
