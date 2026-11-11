export function productStartId(value?: string | null): string | null {
 const match = /^product_([a-f0-9]{32})$/i.exec(value ?? '');
 if (!match) return null;
 const h = match[1]!.toLowerCase();
 return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
export function productShareLink(id: string): string | null {
 const bot = (import.meta.env.VITE_BOT_USERNAME ?? '').replace(/^@/, '');
 if (!/^[a-z0-9_]{5,32}$/i.test(bot) || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id)) return null;
 return `https://t.me/${bot}?startapp=product_${id.replaceAll('-', '')}`;
}

export function giveawayStartId(value?: string | null): string | null {
 const match = /^giveaway_([a-f0-9]{32})$/i.exec(value ?? '');
 if (!match) return null;
 const h = match[1]!.toLowerCase();
 return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
