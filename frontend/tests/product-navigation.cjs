// Run with node tests/product-navigation.cjs. No Telegram messages are sent.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToString } = require('react-dom/server');
const { MemoryRouter } = require('react-router-dom');

function compile(source, resolve, globals = {}) {
    const module = {exports:{}};
    const code = ts.transpileModule(source.replaceAll('import.meta.env.VITE_BOT_USERNAME', '"SafeDeal_app_Bot"'), {
        compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true},
    }).outputText;
    vm.runInNewContext(code,{module,exports:module.exports,console,require:resolve,...globals});
    return module.exports;
}
const read = name => fs.readFileSync(path.join(__dirname,'../src',name),'utf8');
const links = compile(read('lib/productLink.ts'),require);
const gate = compile(read('components/StartLinkGate/StartLinkGate.tsx'), name => name === '@/lib/productLink' ? links : require(name)).StartLinkGate;
const id = 'f976bdf3-9c98-44fc-a25e-9d8ed6b9a5f1';
const start = 'product_' + id.replaceAll('-','');
const share = links.productShareLink(id);
assert.equal(links.productStartId(new URL(share).searchParams.get('startapp')),id);
console.log('PASS shared URL resolves to the same product');

for (const param of [start,'giveaway_'+id.replaceAll('-','')]) {
    let mounted = 0;
    const catalog = () => {mounted++;return React.createElement('p',null,'CATALOG');};
    const html = renderToString(React.createElement(MemoryRouter,{initialEntries:['/']},
        React.createElement(gate,{startParam:param},React.createElement(catalog))));
    assert.equal(mounted,0);
    assert(!html.includes('CATALOG'));
}
console.log('PASS cold product/giveaway links do not mount the catalog before redirect');

for (const [param,route] of [[start,'/product/'+id],[null,'/'],['invalid','/']]) {
    const html = renderToString(React.createElement(MemoryRouter,{initialEntries:[route]},
        React.createElement(gate,{startParam:param},React.createElement('p',null,'CONTENT'))));
    assert(html.includes('CONTENT'));
}
console.log('PASS resolved links and normal launch render their destination');

const app = read('App.tsx');
const overlaySource = app.slice(app.indexOf('const HomeWithProductOverlay:'),app.indexOf('const NavigationWrapper:'));
let catalogs = 0, details = 0, animation;
const Overlay = compile(`import React,{useEffect} from 'react';import {useLocation} from 'react-router-dom';import {motion,AnimatePresence} from 'framer-motion';import {Home} from './Home';import {ProductDetails} from './Details';${overlaySource}\nexport {HomeWithProductOverlay};`, name => {
    if (name === './Home') return {Home:() => {catalogs++;return React.createElement('p',null,'CATALOG');}};
    if (name === './Details') return {ProductDetails:() => {details++;return React.createElement('p',null,'PRODUCT');}};
    if (name === 'framer-motion') return {AnimatePresence:({children})=>children,motion:{div:({children,initial})=>{animation=initial;return React.createElement('div',null,children);}}};
    return require(name);
}).HomeWithProductOverlay;
renderToString(React.createElement(MemoryRouter,{initialEntries:['/product/'+id]},React.createElement(Overlay)));
assert.equal(catalogs,0);assert.equal(details,1);assert.equal(animation,false);
renderToString(React.createElement(MemoryRouter,{initialEntries:['/']},React.createElement(Overlay)));
assert.equal(catalogs,1);
console.log('PASS direct product entry skips catalog requests and the catalog-revealing slide');

function nodes(element) {
    if (!element || typeof element !== 'object') return [];
    const children = element.props?.children;
    return [element,...(Array.isArray(children)?children:[children]).flatMap(nodes)];
}
for (const [index,loading,product] of [[0,true,null],[0,false,null],[undefined,false,{id,name:'Product',price_usdt:10,type:'digital',stock:1}],[2,false,{id,name:'Product',price_usdt:10,type:'digital',stock:1}]]) {
    let state = 0;
    const navigation = [];
    const noOp = () => {};
    const fakeReact = {...React,useEffect:noOp,useRef:value=>({current:value}),useState:initial=>{
        const slot=state++;return [slot===0?product:slot===1?loading:initial,noOp];
    }};
    const component = compile(read('pages/ProductDetails/ProductDetails.tsx'),name => {
        if (name === 'react') return fakeReact;
        if (name === 'react-router-dom') return {useParams:()=>({id}),useNavigate:()=> (...args)=>navigation.push(args)};
        if (name === '@/lib/productLink') return links;
        if (name === '@/lib/image') return {webImage:value=>value};
        if (name === '@/store/authStore') return {useAuthStore:()=>({language:'ru',user:null})};
        if (name === '@/store/cartStore') return {useCartStore:()=>({cart:null,setCart:noOp})};
        if (name === '@/store/toastStore') return {useToastStore:()=>noOp};
        if (name === '@/hooks/useTelegram') return {useTelegram:()=>({haptic:{impact:noOp}})};
        if (name === '@/hooks/useWebSocket') return {useWebSocket:noOp};
        if (name === 'react/jsx-runtime') return require(name);
        if (name === 'framer-motion') return {motion:{div:'div'}};
        return new Proxy({}, {get:()=>noOp});
    },{window:{history:{state:{idx:index}}}}).ProductDetails;
    const tree=component();
    const back=nodes(tree).find(node => ['back-button','btn-notfound'].includes(node.props?.className));
    assert(back,'Back must be available while loading, missing, and loaded');
    back.props.onClick();
    assert.equal(navigation[0][0],index>0?-1:'/');
    if (!(index>0)) assert.equal(navigation[0][1].replace,true);
}
console.log('PASS Back reaches catalog on cold entry and preserves navigation history inside the app');

async function checkDelayedProductResponses() {
    const states=[], refs=[], effects=[], pending=[], requests=[];
    let stateCursor=0, refCursor=0, effectCursor=0, currentId='first';
    const noOp=()=>{};
    const fakeReact={...React,
        useState(initial) {
            const slot=stateCursor++;
            if (!(slot in states)) states[slot]=initial;
            return [states[slot],value=>{states[slot]=typeof value==='function'?value(states[slot]):value;}];
        },
        useRef(initial) {const slot=refCursor++;return refs[slot]??(refs[slot]={current:initial});},
        useEffect(callback,deps) {
            const slot=effectCursor++, previous=effects[slot];
            if (!previous || deps.some((value,index)=>!Object.is(value,previous.deps[index]))) {
                effects[slot]={deps,cleanup:previous?.cleanup};
                pending.push(()=>{effects[slot].cleanup?.();effects[slot].cleanup=callback();});
            }
        },
    };
    const component=compile(read('pages/ProductDetails/ProductDetails.tsx'),name=>{
        if (name==='react') return fakeReact;
        if (name==='react-router-dom') return {useParams:()=>({id:currentId}),useNavigate:()=>noOp};
        if (name==='@/lib/productLink') return links;
        if (name==='@/lib/image') return {webImage:value=>value};
        if (name==='@/store/authStore') return {useAuthStore:()=>({language:'ru',user:null})};
        if (name==='@/store/cartStore') return {useCartStore:()=>({cart:null,setCart:noOp})};
        if (name==='@/store/toastStore') return {useToastStore:()=>noOp};
        if (name==='@/hooks/useTelegram') return {useTelegram:()=>({haptic:{impact:noOp}})};
        if (name==='@/hooks/useWebSocket') return {useWebSocket:noOp};
        if (name==='@/api/client') return {
            productsApi:{getProduct:(id,language,signal)=>new Promise((resolve,reject)=>requests.push({id,language,signal,resolve,reject}))},
            reviewsApi:{getReviews:async()=>[]},
        };
        if (name==='react/jsx-runtime') return require(name);
        if (name==='framer-motion') return {motion:{div:'div'}};
        return new Proxy({}, {get:()=>noOp});
    },{window:{history:{state:{idx:0}}},AbortController}).ProductDetails;
    const render=()=>{stateCursor=refCursor=effectCursor=0;const tree=component();while(pending.length)pending.shift()();return tree;};
    const settle=()=>new Promise(resolve=>setImmediate(resolve));
    const product=(id)=>({id,name:id,price_usdt:10,type:'digital',stock:1});
    render();
    currentId='second';render();
    assert.equal(requests[0].signal.aborted,true);
    requests[1].resolve(product('second'));await settle();render();
    requests[0].resolve(product('first'));await settle();render();
    assert.equal(states[0].id,'second','late product response must not replace the current product');
    console.log('PASS changing product cancels the previous request and ignores late responses');

    currentId='offline';render();
    requests[2].reject(new Error('network timeout'));await settle();
    let tree=render();
    assert(nodes(tree).some(node=>node.props?.role==='alert'));
    const retry=nodes(tree).find(node=>node.type==='button'&&node.props.children==='Повторить загрузку');
    assert(retry,'network failure needs a retry button');
    retry.props.onClick();render();
    requests[3].resolve(product('offline'));await settle();render();
    assert.equal(states[0].id,'offline');
    console.log('PASS network error offers retry and a successful retry restores the product');

    currentId='missing';render();
    requests[4].reject({response:{status:404}});await settle();tree=render();
    assert(!nodes(tree).some(node=>node.props?.role==='alert'));
    assert(nodes(tree).some(node=>node.type==='p'&&node.props.children==='Товар не найден'));
    console.log('PASS actual 404 stays distinct from a connection failure');
}
checkDelayedProductResponses().catch(error=>{console.error(error);process.exitCode=1;});
