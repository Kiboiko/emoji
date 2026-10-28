// Нагрузочные испытания (k6). Одна итерация — один запрос по весам реального трафика.
//   real300  — 300 живых пользователей с паузами 1,5–5 с между действиями
//   stress150 — 150 пользователей без пауз (предел при закрытой модели)
//   rate500/1000/2000 — фиксированный поток запросов в секунду: ищем, где ломается
import http from 'k6/http';
import { sleep } from 'k6';

const BASE = __ENV.BASE;
const TOKENS = (__ENV.TOKENS || '').split(',').filter(Boolean);
const CATS = (__ENV.CATS || '').split(',').filter(Boolean);
const PRODS = (__ENV.PRODS || '').split(',').filter(Boolean);

function r(n) { return Math.floor(Math.random() * n); }
function auth() { return { Authorization: 'Bearer ' + TOKENS[r(TOKENS.length)] }; }

function act() {
  const x = Math.random();
  if (x < 0.38) return http.get(`${BASE}/api/products?limit=40&lang=ru&skip=${r(122) * 40}`, { headers: auth(), tags: { name: 'catalog' } });
  if (x < 0.50) return http.get(`${BASE}/api/products?limit=40&lang=ru&category_id=${CATS[r(CATS.length)]}`, { headers: auth(), tags: { name: 'category' } });
  if (x < 0.58) return http.get(`${BASE}/api/products?lang=ru&search=${encodeURIComponent('Нагрузка ' + (1 + r(5000)))}`, { headers: auth(), tags: { name: 'search' } });
  if (x < 0.68) return http.get(`${BASE}/api/products/${PRODS[r(PRODS.length)]}?lang=ru`, { headers: auth(), tags: { name: 'card' } });
  if (x < 0.75) return http.get(`${BASE}/api/categories?lang=ru`, { headers: auth(), tags: { name: 'categories' } });
  if (x < 0.81) return http.get(`${BASE}/api/stores`, { headers: auth(), tags: { name: 'stores' } });
  if (x < 0.92) return http.get(`${BASE}/api/cart`, { headers: auth(), tags: { name: 'cart_private' } });
  if (x < 0.96) return http.get(`${BASE}/`, { tags: { name: 'home_page' } });
  return http.get(`${BASE}/api/settings/public`, { headers: auth(), tags: { name: 'settings' } });
}

// Живые люди приходят вразнобой: первое действие каждого — со случайной задержкой до 10 с
export function real() {
  if (__ITER === 0) sleep(Math.random() * 10);
  act();
  sleep(1.5 + Math.random() * 3.5);
}
// Все сразу, одним мигом (пост в канале): 300 человек открывают приложение и делают по одному действию
export function burst() { act(); }
export function stress() { act(); }

const arrival = (rate, start) => ({
  executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration: '15s',
  preAllocatedVUs: 300, maxVUs: 2500, startTime: start, exec: 'stress',
});

export const options = {
  discardResponseBodies: true,
  scenarios: {
    real300: { executor: 'constant-vus', vus: 300, duration: '55s', exec: 'real' },
    burst300: { executor: 'shared-iterations', vus: 300, iterations: 300, maxDuration: '20s', startTime: '60s', exec: 'burst' },
    stress150: { executor: 'constant-vus', vus: 150, duration: '30s', startTime: '85s', exec: 'stress' },
    rate500: arrival(500, '125s'),
    rate1000: arrival(1000, '145s'),
    rate2000: arrival(2000, '165s'),
  },
  thresholds: {
    'http_req_failed{scenario:real300}': ['rate<0.001'],
    'http_req_duration{scenario:real300}': ['p(95)<300', 'p(99)<1000'],
    'http_req_duration{name:catalog,scenario:real300}': ['p(95)<200'],
    'http_req_duration{name:search,scenario:real300}': ['p(95)<500'],
    'http_req_duration{name:cart_private,scenario:real300}': ['p(95)<500'],
    'http_req_failed{scenario:burst300}': ['rate<0.001'],
    'http_req_duration{scenario:burst300}': ['p(95)<2000'],
    'http_req_failed{scenario:stress150}': ['rate<0.001'],
    'http_req_failed{scenario:rate500}': ['rate<0.001'],
    'http_req_failed{scenario:rate1000}': ['rate<0.001'],
    'http_req_failed{scenario:rate2000}': ['rate<0.001'],
  },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
};
