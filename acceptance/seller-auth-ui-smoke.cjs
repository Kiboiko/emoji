// Run from repository root. Local Vite only, all application API calls mocked.
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const server=spawn(process.execPath,['frontend/node_modules/vite/bin/vite.js','frontend','--host','127.0.0.1','--port','4177','--strictPort'],{stdio:'ignore',windowsHide:true});
let browser;
const hash='#tgWebAppData='+encodeURIComponent('user='+encodeURIComponent(JSON.stringify({id:123,first_name:'Test'}))+'&auth_date=1793444641&hash=mock')+'&tgWebAppVersion=8.0&tgWebAppPlatform=android';
(async()=>{
 await new Promise(r=>setTimeout(r,1500));
 browser=await chromium.launch({...(process.env.BROWSER_CHANNEL?{channel:process.env.BROWSER_CHANNEL}:{}),headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844}});const errors=[],early=[],registrations=[];let signedIn=false,registered=false;
 await context.addInitScript(()=>localStorage.setItem('access_token','old-token'));
 await context.route('**/api/**',async route=>{
  const p=new URL(route.request().url()).pathname;if(!p.startsWith('/api/'))return route.continue();let data={};let status=200;
  if(p==='/api/auth/telegram'){
   await new Promise(r=>setTimeout(r,800));signedIn=true;data={access_token:'new-token',user:{id:'user',telegram_id:123,first_name:'Test',app_language:'ru'}};
  }else if(p==='/api/p2p/seller/me'){
   if(!signedIn)early.push(p);
   if(route.request().headers().authorization!=='Bearer new-token'){status=401;data={detail:'Invalid token'};}
   else data=registered?{registered:true,id:'seller',display_name:'Magazin Igrushek',name_locked:true,status:'active',rating:0,review_count:0,total_sales:0}: {registered:false};
  }else if(p==='/api/p2p/seller/register'){
   registrations.push(route.request().postDataJSON());registered=true;data={registered:true,status:'active'};
  }else if(p==='/api/test/delayed-401'){
   await new Promise(r=>setTimeout(r,400));status=401;data={detail:'Expired token'};
  }else if(p==='/api/test/current-401'){status=401;data={detail:'Expired token'};}
  else if(p.includes('/deals/unread'))data={deals:{},total:0};
  else if(p==='/api/cart')data={items:[],total_usdt:0,total_ton:0};
  else if(p.includes('/terms'))data={accepted:true,is_empty:false,text:'Terms',version:'1'};
  else if(p.includes('/listings')||p.includes('/deals'))data=[];
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:4177/my/listings'+hash);await page.getByLabel('Название маркета',{exact:true}).waitFor();
 assert.deepEqual(early,[],'seller profile must wait for Telegram sign-in');
 await page.getByLabel('Название маркета',{exact:true}).fill('Magazin Igrushek');await page.locator('.seller-check input').check();await page.getByRole('button',{name:'Стать продавцом',exact:true}).click();
 await page.locator('.seller-brand-name').getByText('Magazin Igrushek',{exact:true}).waitFor();
 assert.deepEqual(registrations,[{display_name:'Magazin Igrushek',accept_terms:true}]);
 await page.evaluate(async()=>{
  const {apiClient}=await import('/src/api/client.ts');const {useAuthStore}=await import('/src/store/authStore.ts');
  const pending=apiClient.get('/test/delayed-401').catch(()=>{});
  await new Promise(r=>setTimeout(r,50));useAuthStore.getState().setAccessToken('replacement-token');await pending;
 });
 assert.equal(await page.evaluate(()=>localStorage.getItem('access_token')),'replacement-token','late 401 for old token must preserve the new session');
 await page.evaluate(async()=>{const {apiClient}=await import('/src/api/client.ts');await apiClient.get('/test/current-401').catch(()=>{});});
 assert.equal(await page.evaluate(()=>localStorage.getItem('access_token')),null,'401 for the current token must end the session');
 assert.deepEqual(errors,[]);await browser.close();server.kill();
 console.log('Seller/auth UI passed: private page waits for sign-in, transliterated name registration, late stale 401 preserves fresh session, current 401 logs out. API mocked.');
})().catch(async e=>{console.error(e);if(browser)await browser.close();server.kill();process.exitCode=1;});
