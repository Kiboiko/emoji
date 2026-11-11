// Repeatable baseline/candidate workload for the isolated 1000-product copy.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

const fixture = JSON.parse(open('/outbox/fixture.json'));
const base = __ENV.BASE;
if (base !== 'http://gram-perf-nginx') throw new Error('Isolated performance stage required');
const latency = new Trend('endpoint_ms', true);
const failures = new Counter('failed_responses');
const imageBytes = new Trend('image_bytes');
const stages = [
    { name: 'clients25', clients: 25, start: '0s', duration: '30s' },
    { name: 'clients50', clients: 50, start: '35s', duration: '30s' },
    { name: 'clients100', clients: 100, start: '70s', duration: '60s' },
];
export const options = {
    scenarios: Object.fromEntries(stages.map(stage => [stage.name, {
        executor: 'constant-vus', vus: stage.clients, duration: stage.duration,
        startTime: stage.start, gracefulStop: '10s', tags: { clients: String(stage.clients) },
    }])),
    thresholds: {
        failed_responses: ['count==0'],
        'http_req_failed{scenario:clients100}': ['rate<0.001'],
        'endpoint_ms{endpoint:catalog}': ['p(95)<300'],
        'endpoint_ms{endpoint:search}': ['p(95)<500'],
        'endpoint_ms{endpoint:chat}': ['p(95)<500'],
        ...Object.fromEntries(['catalog', 'search', 'category', 'product', 'chat', 'chat_list', 'cart', 'image'].map(endpoint => [
            `endpoint_ms{endpoint:${endpoint},clients:100}`, ['p(95)<1000'],
        ])),
    },
    summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
};

function record(response, endpoint) {
    latency.add(response.timings.duration, { endpoint });
    const valid = check(response, { 'status is 200': r => r.status === 200 }, { endpoint });
    if (!valid) failures.add(1, { endpoint, status: String(response.status) });
    if (endpoint === 'image') imageBytes.add(response.body ? response.body.byteLength : 0);
    return response;
}

export default function () {
    if (__ITER === 0) sleep((__VU % 10) / 10);
    const headers = { Authorization: `Bearer ${fixture.tokens[(__VU - 1) % 100]}` };
    const request = (path, endpoint) => record(http.get(base + path, { headers, tags: { name: endpoint } }), endpoint);
    // Deterministic per-user action sequence makes before/after comparable.
    const index = (__VU * 37 + __ITER * 17) % 1000;
    const action = __ITER % 6;
    if (action === 0) {
        const response = request(`/api/products?limit=40&lang=ru&skip=${Math.floor(index / 40) * 40}`, 'catalog');
        const products = response.status === 200 ? response.json() : [];
        const requests = products.slice(0, 6).map(product => ({
            method: 'GET', url: base + product.image_url + '?size=thumb', params: { responseType: 'binary', tags: { name: 'image' } },
        }));
        http.batch(requests).forEach(response => record(response, 'image'));
    } else if (action === 1) {
        request('/api/products?limit=40&lang=ru&search=' + encodeURIComponent('Нагрузка ' + (index + 1)), 'search');
    } else if (action === 2) {
        request('/api/products?limit=40&category_id=' + fixture.categories[index % fixture.categories.length], 'category');
    } else if (action === 3) {
        const response = request('/api/products/' + fixture.products[index] + '?lang=ru', 'product');
        if (response.status === 200) record(http.get(base + response.json().image_url, { responseType: 'binary', tags: { name: 'image' } }), 'image');
    } else if (action === 4) {
        request('/api/inquiries/store/' + fixture.stores[(__VU + 1) % fixture.stores.length], 'chat');
    } else {
        request('/api/cart', 'cart');
        request('/api/inquiries', 'chat_list');
    }
    sleep(1.5 + ((__VU * 13 + __ITER * 7) % 35) / 10);
}

export function handleSummary(data) {
    const output = {};
    output['/outbox/' + (__ENV.RESULT_NAME || 'baseline') + '.json'] = JSON.stringify(data, null, 2);
    return output;
}
