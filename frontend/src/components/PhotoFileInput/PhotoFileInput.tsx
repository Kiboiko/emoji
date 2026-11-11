import type { ChangeEvent } from 'react';
import './PhotoFileInput.css';

const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const PHOTO_EXTENSIONS = /\.(?:jpe?g|png|webp)$/i;
const MAX_PHOTO_BYTES = 20 * 1024 * 1024;

type Translate = (ru: string, en: string) => string;

export function photoFileError(file: File, t: Translate): string | null {
    if (file.size === 0) return t('Файл пустой', 'The file is empty');
    if (file.size > MAX_PHOTO_BYTES) return t('Файл больше 20 МБ', 'The file exceeds 20 MB');
    if (!PHOTO_TYPES.includes(file.type) && !PHOTO_EXTENSIONS.test(file.name)) {
        return t('Выберите фото в формате JPG, PNG или WebP', 'Choose a JPG, PNG, or WebP photo');
    }
    return null;
}

interface PhotoFileInputProps {
    label: string;
    disabled?: boolean;
    multiple?: boolean;
    onFiles: (files: File[]) => void;
}

export function PhotoFileInput({ label, disabled, multiple, onFiles }: PhotoFileInputProps) {
    const pickFiles = (event: ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(event.currentTarget.files ?? []);
        event.currentTarget.value = '';
        if (files.length) onFiles(files);
    };

    return <input
        className="photo-file-input"
        type="file"
        accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
        aria-label={label}
        disabled={disabled}
        multiple={multiple}
        onChange={pickFiles}
    />;
}
