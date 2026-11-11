import type { Category } from '@/types';
export function categoryOptions(categories: Category[]) {
 return categories.filter(c => !c.parent_id).flatMap(root => [{...root, label: root.name}, ...categories.filter(c => c.parent_id === root.id).map(c => ({...c, label: `${root.name} / ${c.name}`}))]);
}
