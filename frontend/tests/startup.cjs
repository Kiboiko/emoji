const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');

function startup(ImageClass=class {}) {
    const module={exports:{}};
    const source=fs.readFileSync(path.join(__dirname,'../src/store/startupStore.ts'),'utf8');
    const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    vm.runInNewContext(code,{module,exports:module.exports,require,Image:ImageClass,setTimeout,clearTimeout,console});
    return module.exports;
}
const markAll=api=>['app','telegram','auth','categories','stores','products','images','intro'].forEach(api.markStartup);

(async()=>{
    let api=startup(),store=api.useStartupStore;
    assert.equal(store.getState().progress,0);
    ['app','telegram','auth','categories','stores','products'].forEach(api.markStartup);
    assert.equal(store.getState().dataProgress,90);
    assert.equal(store.getState().progress,0);
    api.advanceStartupIntro(35);
    assert.equal(store.getState().progress,35);
    store.getState().dismiss();assert.equal(store.getState().active,true);
    api.markStartup('products');assert.equal(store.getState().progress,35);
    api.markStartup('images');assert.equal(store.getState().dataProgress,100);
    assert.equal(store.getState().progress,35,'fast data must not park at 90 before animation');
    api.advanceStartupIntro(70);assert.equal(store.getState().progress,70);
    api.advanceStartupIntro(99);assert.equal(store.getState().progress,99);
    store.getState().dismiss();assert.equal(store.getState().active,true);
    api.markStartup('intro');assert.equal(store.getState().progress,100);
    store.getState().dismiss();assert.equal(store.getState().active,false);
    api.failStartup('late error',()=>{});assert.equal(store.getState().error,null);
    console.log('PASS data and animation progress together without a separate 90-percent phase');

    api=startup();store=api.useStartupStore;
    api.markStartup('app');api.markStartup('telegram');api.markStartup('intro');api.finishStartupData();
    assert.equal(store.getState().progress,80);
    store.getState().dismiss();assert.equal(store.getState().active,true);
    api.failStartup('offline',()=>api.markStartup('auth'));
    assert.equal(store.getState().error,'offline');
    store.getState().retry();
    assert.equal(store.getState().error,null);assert.equal(store.getState().progress,100);
    console.log('PASS a failed sign-in cannot become a completed launch; Retry resumes it');

    const seen=[];
    class LoadedImage {
        complete=false;
        set src(url){seen.push(url);queueMicrotask(()=>url==='broken'?this.onerror?.():this.onload?.());}
    }
    api=startup(LoadedImage);
    ['app','telegram','auth','categories','stores','products','intro'].forEach(api.markStartup);
    await api.readyStartupImages(['photo','photo','broken','not-visible']);
    assert.deepEqual(seen,['photo','broken']);
    assert.equal(api.useStartupStore.getState().progress,100);
    console.log('PASS only two unique visible photos are awaited; an unavailable photo does not trap launch');

    api=startup();markAll(api);api.failStartup('temporary',()=>{});
    api.useStartupStore.getState().dismiss();assert.equal(api.useStartupStore.getState().active,true);
    api.useStartupStore.getState().retry();api.useStartupStore.getState().dismiss();
    assert.equal(api.useStartupStore.getState().active,false);
    console.log('PASS an outstanding error keeps Retry visible until acknowledged');
})().catch(error=>{console.error(error);process.exitCode=1;});
