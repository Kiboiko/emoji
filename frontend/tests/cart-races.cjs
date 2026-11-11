// Run with node tests/cart-races.cjs. Exercise the real store with delayed HTTP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const row = (id, quantity = 1) => ({ id, product_id:id, quantity, price_usdt:0.1, subtotal_usdt:0.1 * quantity, max_quantity:10 });
const cart = items => ({ items:structuredClone(items), total_usdt:items.reduce((sum,item) => sum + item.quantity * 10,0)/100 });

async function scenario(name, run) {
    let server = [row('a'), row('b')];
    const calls = [];
    let failId;
    let readStarted;
    const api = {
        async getCart() {
            calls.push(['GET']);
            const snapshot = cart(server);
            readStarted?.();
            await delay(70);
            return snapshot;
        },
        async updateCartItem(id, quantity) {
            calls.push(['PUT',id,quantity]);
            await delay(40);
            if (id === failId) throw new Error('offline');
            server.find(item => item.id === id).quantity = quantity;
        },
        async removeFromCart(id) {
            calls.push(['DELETE',id]);
            await delay(40);
            server = server.filter(item => item.id !== id);
        },
    };
    const module = { exports:{} };
    const source = fs.readFileSync(path.join(__dirname,'../src/store/cartStore.ts'),'utf8');
    const code = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    vm.runInNewContext(code, {
        module, exports:module.exports, console, setTimeout, clearTimeout,
        require(name) {
            if (name === 'zustand') return require('zustand');
            if (name === '@/api/client') return {cartApi:api};
            if (name === './authStore') return {useAuthStore:{getState:()=>({language:'ru'})}};
            if (name === './toastStore') return {errorText:()=> 'offline', useToastStore:{getState:()=>({show(){}})}};
            throw new Error(name);
        },
    });
    const store = module.exports.useCartStore;
    store.getState().setCart(cart(server));
    await run({store,calls,api,fail:id=>{failId=id;},onRead:fn=>{readStarted=fn;}});
    for (let attempt=0;store.getState().isSaving && attempt<100;attempt++) await delay(20);
    assert.equal(store.getState().isSaving,false,'writes must settle');
    assert.equal(JSON.stringify(store.getState().cart),JSON.stringify(cart(server)),'UI must match server');
    console.log('PASS',name,JSON.stringify(calls));
}

(async () => {
    await scenario('rapid taps coalesce',async ({store,calls}) => {
        for (const quantity of [2,3,4]) store.getState().updateQuantity('a',quantity);
        assert.equal(store.getState().cart.items[0].quantity,4);
        assert.equal(store.getState().cart.total_usdt,0.5);
        await delay(310);
        assert.equal(calls.filter(call=>call[0]==='PUT').length,1);
        assert.equal(calls.filter(call=>call[0]==='GET').length,1);
    });
    await scenario('delete during in-flight quantity change',async ({store}) => {
        store.getState().updateQuantity('a',2);
        await delay(165);
        store.getState().removeItem('a');
        store.getState().updateQuantity('b',3);
    });
    await scenario('stale initial read cannot overwrite taps',async ({store}) => {
        const read = store.getState().fetchCart();
        store.getState().updateQuantity('a',4);
        await read;
        assert.equal(store.getState().cart.items[0].quantity,4);
    });
    await scenario('tap during final refresh',async ({store,onRead}) => {
        let once = false;
        onRead(()=> {if (!once) {once=true;store.getState().updateQuantity('a',5);}});
        store.getState().updateQuantity('a',2);
    });
    await scenario('failed row preserves other changes',async ({store,fail}) => {
        fail('a');
        store.getState().updateQuantity('a',4);
        store.getState().updateQuantity('b',3);
    });
})().catch(error=>{console.error(error);process.exitCode=1;});
