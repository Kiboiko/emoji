// Run from repository root. Uses local Vite and mocked API; never points at a deployment.
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
require('node:fs').mkdirSync('.tmp', { recursive: true });
const servers=['frontend','admin'].map((app,i)=>spawn(process.execPath,[`${app}/node_modules/vite/bin/vite.js`,app,'--host','127.0.0.1','--port',String(4175+i)],{stdio:'ignore',windowsHide:true}));
let browser;
const sid='11111111-1111-4111-8111-111111111111',gid='22222222-2222-4222-8222-222222222222',pid='33333333-3333-4333-8333-333333333333';
const period={id:pid,start_at:'2026-10-25T21:00:00Z',end_at:'2026-11-01T21:00:00Z',updated_at:new Date().toISOString()};
const rank={period,items:[{id:sid,name:'Первый маркет',rank:1,medal:'gold',rating:4.8,volume_cents:10000,sales_count:2,review_count:1,score:'95'}]};
const giveaway={id:gid,title_ru:'Подарок недели',title_en:'Weekly gift',description_ru:'Бесплатное участие',description_en:'Free entry',prize:'NFT gift',start_at:new Date(Date.now()-86400000).toISOString(),end_at:new Date(Date.now()+86400000).toISOString(),status:'open',participants:1,winner:null,fulfillment_status:'pending',requirements:[{id:'chat',chat_id:'-100123',title:'Обязательный чат',join_link:'https://t.me/required'}]};
const hash='#tgWebAppData='+encodeURIComponent('user='+encodeURIComponent(JSON.stringify({id:123,first_name:'Test'}))+'&auth_date=1793444641&hash=mock')+'&tgWebAppVersion=8.0&tgWebAppPlatform=android';
(async()=>{
 await new Promise(r=>setTimeout(r,1600));browser=await chromium.launch({...(process.env.BROWSER_CHANNEL ? {channel:process.env.BROWSER_CHANNEL} : {}),headless:true});
 for(const [lang,theme] of [['ru','light'],['en','dark']]){
  const context=await browser.newContext({viewport:{width:390,height:844}});const errors=[];let joined=false,finished=false;const calls=[];
  await context.addInitScript(theme=>localStorage.setItem('theme',theme),theme);
  await context.route('**/api/**',async r=>{const p=new URL(r.request().url()).pathname;if(!p.startsWith('/api/'))return r.continue();calls.push([p,r.request().method()]);let data={};
   if(p.includes('/auth/telegram'))data={access_token:'mock',user:{id:'user',telegram_id:123,first_name:'Test',app_language:lang}};
   else if(p==='/api/market-rankings/current'||p===`/api/market-rankings/periods/${pid}`)data=rank;
   else if(p==='/api/market-rankings/periods')data=[period];
   else if(p===`/api/giveaways/${gid}/join`){joined=true;data={joined:true,checks:[{joined:true}],entry_label:'Участник abcdef12'};}
   else if(p.endsWith('/my-entry'))data={joined,entry_label:joined?'Участник abcdef12':null,is_winner:finished};
   else if(p==='/api/giveaways')data=[giveaway];
   else if(p===`/api/giveaways/${gid}`)data={...giveaway,status:finished?'finished':'open',winner:finished?'Участник abcdef12':null};
   else if(p.includes('/terms'))data={accepted:true,version:'1',is_empty:false};
   else if(p.includes('/cart'))data={items:[],total_usdt:0,total_ton:0};
   else if(p.includes('/deals/unread'))data={deals:{},total:0};
   else if(p.includes('/deals')||p.includes('/categories')||p.includes('/products')||p==='/api/stores')data=[];
   await r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:4175/rankings'+hash);
  await page.getByText('Первый маркет',{exact:false}).waitFor();assert.equal(await page.locator('.ranking-frame.medal-gold').count(),1);
  await page.locator('select').selectOption(pid);await page.waitForTimeout(150);assert(calls.some(c=>c[0].endsWith('/periods/'+pid)));
  assert.equal(await page.locator('html').getAttribute('data-theme'),theme);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:`.tmp/stage3-ranking-${lang}-${theme}.png`,fullPage:true});
  await page.goto('http://127.0.0.1:4175/giveaways'+hash);await page.getByText(lang==='ru'?'Подарок недели':'Weekly gift',{exact:true}).click();
  await page.getByRole('button',{name:lang==='ru'?'Участвовать':'Enter',exact:true}).click();
  await page.getByText(lang==='ru'?'Ваша заявка принята:':'Your entry was accepted:',{exact:false}).waitFor();
  assert(calls.some(c=>c[0].endsWith('/join')&&c[1]==='POST'));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:`.tmp/stage3-giveaway-${lang}-${theme}.png`,fullPage:true});
  finished=true;await page.reload();await page.getByText(lang==='ru'?'Вы победили!':'You won!',{exact:false}).waitFor();
  assert.deepEqual(errors,[]);await context.close();
 }
 const context=await browser.newContext({viewport:{width:1280,height:900}});const page=await context.newPage();page.setDefaultTimeout(10000);const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
 const token='x.'+Buffer.from(JSON.stringify({user_id:'mock',sub:'admin',is_admin:true,role:'admin'})).toString('base64')+'.x';let rankingEnabled=false;let rows=[{...giveaway,status:'draft'}];
 await context.route('**/api/**',async r=>{const p=new URL(r.request().url()).pathname;if(!p.startsWith('/api/'))return r.continue();let data=[];const method=r.request().method();if(method!=='GET')writes.push([p,method,r.request().postData()]);
  if(p.endsWith('/refresh'))data={access_token:token};
  else if(p.includes('/market-rankings/sellers/')){rankingEnabled=r.request().postDataJSON().ranking_enabled;data={saved:true};}
  else if(p==='/api/admin/market-rankings')data={ranking:rank,sellers:[{id:sid,name:'Первый маркет',home_visible:true,ranking_enabled:rankingEnabled,is_platform:false}],channels:[]};
  else if(p.endsWith('/publications/config'))data={enabled:false,min_gram:'0',min_nano:'0',chat_id:'',thread_id:null};
  else if(p==='/api/admin/publications')data=[{id:'post',status:'unknown',attempts:1,error_code:'timeout',preview:'Завершена сделка'}];
  else if(p.endsWith('/draw-attempts'))data=[{ordinal:1,entry_label:'Участник abcdef12',status:'eligible',selected_at:new Date().toISOString()}];
  else if(p==='/api/admin/giveaways'){
   if(method==='POST'){const body=r.request().postDataJSON();rows=[{...giveaway,...body,status:'draft'}];data=rows[0];}else data=rows;
  }else if(p.endsWith('/publish')){rows=[{...rows[0],status:'open'}];data=rows[0];}
  await r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto('http://127.0.0.1:4176/admin/market-ranking');await page.getByLabel('Участие в рейтинге').click();await page.waitForTimeout(200);assert(writes.some(w=>w[1]==='PATCH'&&JSON.parse(w[2]).ranking_enabled===true));
 await page.goto('http://127.0.0.1:4176/admin/publications');await page.getByLabel('Порог, Gram').fill('0.300000001');await page.getByRole('button',{name:'Проверить права и сохранить',exact:true}).click();await page.waitForTimeout(200);assert(writes.some(w=>w[1]==='PUT'&&JSON.parse(w[2]).min_nano===300000001));
 await page.goto('http://127.0.0.1:4176/admin/giveaways');await page.getByRole('button',{name:'Новый черновик'}).click();
 for(const [label,value] of [['Название RU','Новый подарок'],['Название EN','New gift'],['NFT / приз','NFT'],['ID чата (отрицательное число)','-100123'],['Название','Чат'],['Ссылка https://t.me/...','https://t.me/required']])await page.getByLabel(label,{exact:true}).fill(value);
 await page.getByRole('button',{name:'Сохранить черновик'}).click();await page.getByRole('heading',{name:'Новый подарок · draft'}).waitFor();
 await page.getByRole('button',{name:'Проверить права и опубликовать'}).click();await page.getByRole('heading',{name:'Новый подарок · open'}).waitFor();assert.equal(await page.getByRole('button',{name:'Редактировать',exact:true}).count(),0);
 await page.getByRole('button',{name:'История выбора',exact:true}).click();await page.getByText('#1 · Участник abcdef12',{exact:false}).waitFor();
 await page.screenshot({path:'.tmp/stage3-admin-giveaway.png',fullPage:true});assert.deepEqual(errors,[]);
 await browser.close();servers.forEach(s=>s.kill());console.log('Stage 3 browser smoke passed: RU/EN, light/dark, 390px layout, ranking/archive/medal, join/restored winner; admin participation, exact threshold, draft/publish/immutable form, draw history. API mocked; no Telegram calls.');
})().catch(async e=>{console.error(e);if(browser)await browser.close();servers.forEach(s=>s.kill());process.exitCode=1;});
