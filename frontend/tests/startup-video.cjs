const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const React=require('react');
function load(file,resolve,extra={}){
    const module={exports:{}};
    const source=fs.readFileSync(path.join(__dirname,'../src',file),'utf8');
    const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
    vm.runInNewContext(code,{module,exports:module.exports,require:resolve,console,...extra});
    return module.exports;
}
function setup(reduced=false){
    const api=load('store/startupStore.ts',require);
    let staticLogo;
    const effects=[];
    const storeHook=Object.assign(()=>api.useStartupStore.getState(),{getState:api.useStartupStore.getState});
    const component=load('components/StartupScreen/StartupScreen.tsx',name=>{
        if(name==='react')return {...React,useEffect:fn=>effects.push(fn),useState:initial=>{
            if(staticLogo===undefined)staticLogo=initial();return [staticLogo,value=>{staticLogo=value;}];
        }};
        if(name==='@/store/startupStore')return {...api,useStartupStore:storeHook};
        if(name==='@/store/authStore')return {useAuthStore:select=>select({language:'ru'})};
        if(name==='react-router-dom')return {useLocation:()=>({pathname:'/'})};
        if(name.endsWith('.css'))return {};
        return require(name);
    },{window:{matchMedia:()=>({matches:reduced,addEventListener(){},removeEventListener(){}})},setTimeout:()=>1,clearTimeout(){}}).StartupScreen;
    return {api,render:()=>component(),flush:()=>{while(effects.length)effects.shift()();}};
}
function nodes(element){
    if(!element||typeof element!=='object')return [];
    const c=element.props?.children;
    return [element,...(Array.isArray(c)?c:[c]).flatMap(nodes)];
}
const dataReady=api=>['app','telegram','auth','categories','stores','products','images'].forEach(api.markStartup);
let test=setup();dataReady(test.api);
let tree=test.render(),video=nodes(tree).find(n=>n.type==='video');
assert(video);assert.equal(nodes(tree).filter(n=>n.type==='img').length,0,'a static image must not cover the animation');
assert.equal(video.props.loop,undefined,'native loop prevents the first-cycle completion event');
assert.equal(nodes(video).find(n=>n.type==='source').props.src,'/launch/safedeal-v3.mp4');
assert.equal(test.api.useStartupStore.getState().dataProgress,100);
assert.equal(test.api.useStartupStore.getState().progress,0);
video.props.onTimeUpdate({currentTarget:{currentTime:.5,duration:2}});
assert.equal(test.api.useStartupStore.getState().progress,25);
video.props.onTimeUpdate({currentTarget:{currentTime:1.5,duration:2}});
assert.equal(test.api.useStartupStore.getState().progress,75);
let replays=0;
video.props.onEnded({currentTarget:{play:()=>{replays++;return Promise.resolve();}}});
assert.equal(test.api.useStartupStore.getState().progress,100);assert.equal(replays,0);
assert(test.render().props.className.includes('startup-complete'));
console.log('PASS the animation and percentage advance together even when data is already ready');

test=setup();['app','telegram','auth','categories','stores'].forEach(test.api.markStartup);
video=nodes(test.render()).find(n=>n.type==='video');
video.props.onTimeUpdate({currentTarget:{currentTime:1,duration:2}});
assert.equal(test.api.useStartupStore.getState().progress,50);
video.props.onEnded({currentTarget:{play:()=>{replays++;return Promise.resolve();}}});
assert.equal(replays,1);assert(!test.render().props.className.includes('startup-complete'));
assert.equal(test.api.useStartupStore.getState().progress,60);
video.props.onTimeUpdate({currentTarget:{currentTime:.1,duration:2}});
assert.equal(test.api.useStartupStore.getState().progress,60,'looping the video must not reset overall progress');
dataReady(test.api);assert.equal(test.api.useStartupStore.getState().progress,100);
console.log('PASS slower data keeps the animation playing without marking loading complete');

test=setup();test.api.captureStartupIntro({currentTime:.75,ended:false});
video=nodes(test.render()).find(n=>n.type==='video');
const player={currentTime:0,duration:2.15};video.props.onLoadedMetadata({currentTarget:player});
assert.equal(player.currentTime,.75);
test.api.captureStartupIntro({currentTime:2.15,ended:true});
assert.equal(test.api.useStartupStore.getState().completed.intro,true);
console.log('PASS React resumes the visible HTML animation without restarting it');

test=setup();test.api.captureStartupIntro({currentTime:2.15,ended:true},true);
assert.equal(test.api.useStartupStore.getState().introOffset,0);
assert.equal(test.api.useStartupStore.getState().completed.intro,undefined);
dataReady(test.api);assert.equal(test.api.useStartupStore.getState().progress,0);
test.api.advanceStartupIntro(40);assert.equal(test.api.useStartupStore.getState().progress,40);
console.log('PASS Telegram always gets a full visible intro even if HTML video ended beneath its native loader');

test=setup(true);dataReady(test.api);tree=test.render();test.flush();
assert.equal(nodes(tree).filter(n=>n.type==='video').length,0);assert.equal(nodes(tree).filter(n=>n.type==='img').length,1);
assert.equal(test.api.useStartupStore.getState().progress,100);
test=setup();dataReady(test.api);video=nodes(test.render()).find(n=>n.type==='video');
video.props.onError();tree=test.render();test.flush();
assert.equal(nodes(tree).filter(n=>n.type==='img').length,1);assert.equal(test.api.useStartupStore.getState().progress,100);
console.log('PASS reduced motion and a failed player use the fallback without trapping launch');
