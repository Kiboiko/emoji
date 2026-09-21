import { AnimatePresence, motion } from 'framer-motion';
import { useToastStore } from '../../store/toastStore';
import './Toast.css';

/**
 * Монтируется один раз в App и показывает очередь уведомлений.
 * Позиция — над нижней навигацией, с учётом safe-area у телефонов
 * с жестовой полосой.
 */
export const ToastHost = () => {
    const toasts = useToastStore((s) => s.toasts);
    const dismiss = useToastStore((s) => s.dismiss);

    return (
        <div className="toast-host" role="status" aria-live="polite">
            <AnimatePresence initial={false}>
                {toasts.map((toast) => (
                    <motion.button
                        key={toast.id}
                        type="button"
                        className={`toast toast--${toast.kind}`}
                        onClick={() => dismiss(toast.id)}
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 12 }}
                        transition={{ duration: 0.18 }}
                    >
                        {toast.text}
                    </motion.button>
                ))}
            </AnimatePresence>
        </div>
    );
};
