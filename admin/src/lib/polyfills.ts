/**
 * Buffer для TON-библиотек в браузере.
 *
 * @ton/core собирает ячейку с комментарием перевода через Buffer — в Node он
 * есть всегда, в браузере нет, а Vite его не подставляет. Без этого файла
 * кнопка «Выплатить» падала бы с ReferenceError при сборке перевода.
 *
 * Импортировать первой строкой в main.tsx, до остальных импортов.
 */
import { Buffer } from 'buffer'

const globalWithBuffer = globalThis as unknown as { Buffer?: typeof Buffer }

if (!globalWithBuffer.Buffer) {
    globalWithBuffer.Buffer = Buffer
}
