// Requires the isolated verify_up stage after HTTP acceptance; API is real, wallet metadata is mocked.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {createHmac,randomUUID}=require('node:crypto');
const assert=require('node:assert/strict');
const base=process.env.VERIFY_BASE || 'http://127.0.0.1:18084';
if(!/^http:\/\/(127[.]0[.]0[.]1|localhost):[0-9]+$/.test(base))throw new Error('Use the local isolated-stage tunnel');
const botToken='111111111:ACCfakeTokenFakeTokenFakeTokenFake12'; // isolated stage only
(async()=>{
 const browser=await chromium.launch({...(process.env.BROWSER_CHANNEL ? {channel:process.env.BROWSER_CHANNEL} : {}),headless:true});
 try{
  const context=await browser.newContext({viewport:{width:390,height:844}});const errors=[];
  const probe=await context.request.get(base+'/health');assert.equal(probe.status(),200);
  const paymentConfig=await (await context.request.get(base+'/api/payments/config')).json();
  assert.equal(paymentConfig.network,'testnet');assert(paymentConfig.manifest_url.startsWith('https://acc.example'));
  const date=new Date(probe.headers().date).getTime();
  const user={id:7_500_000_000+Math.floor(Math.random()*100_000_000),first_name:'Browser',username:'browser_'+randomUUID().slice(0,8),language_code:'ru'};
  const fields={auth_date:String(Math.floor(date/1000)),query_id:'browser-verify',signature:'stage-placeholder',user:JSON.stringify(user)};
  const secret=createHmac('sha256','WebAppData').update(botToken).digest();
  fields.hash=createHmac('sha256',secret).update(Object.entries(fields).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>k+'='+v).join('\n')).digest('hex');
  const hash='#tgWebAppData='+encodeURIComponent(new URLSearchParams(fields).toString())+'&tgWebAppVersion=8.0&tgWebAppPlatform=android';
  const page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
  // Wallet metadata is external to this acceptance; application API is real.
  await context.route('https://*',r=>r.fulfill({contentType:'application/json',body:'[]'}));
  await page.goto(base+'/my/listings'+hash);
  await page.getByLabel('Название маркета',{exact:true}).fill('Magazin_'+randomUUID().slice(0,7));
  await page.locator('.seller-check input').check();await page.getByRole('button',{name:'Стать продавцом',exact:true}).click();
  await page.locator('.seller-brand-name').waitFor();
  assert((await page.locator('.seller-brand-name').innerText()).startsWith('Magazin_'));
  await page.screenshot({path:'.tmp/real-seller.png',fullPage:true});
  for(const path of ['/','/rankings','/giveaways','/sales','/cart','/profile','/my/channels','/my/deals']){
   await page.goto(base+path+hash);await page.waitForTimeout(700);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+path);
   assert.deepEqual(errors,[],'runtime '+path);
  }
  await context.close();
  const admin=await browser.newContext({viewport:{width:1280,height:900}});
  const response=await admin.request.post(base+'/api/admin/auth/login',{data:{username:process.env.VERIFY_ADMIN_USER || 'acc_admin',password:process.env.VERIFY_ADMIN_PASSWORD || 'Brand-New-Admin-Pass-9'}});assert.equal(response.status(),200);
  const cookie=response.headers()['set-cookie'].match(/admin_refresh_token=([^;]+)/)[1];
  // Local HTTP tunnel only. Production Secure cookie flags are verified in HTTP suite.
  await admin.addCookies([{name:'admin_refresh_token',value:cookie,domain:'127.0.0.1',path:'/',httpOnly:true,secure:false,sameSite:'Lax'}]);
  const ap=await admin.newPage();ap.setDefaultTimeout(15000);ap.on('pageerror',e=>errors.push(e.message));
  for(const [path,title] of [['market-ranking','Рейтинг маркетов'],['publications','Крупные сделки'],['giveaways','Розыгрыши подарков'],['categories','Категории'],['products','Товары']]){
   await ap.goto(base+'/admin/'+path);await ap.getByRole('heading',{name:title,exact:true}).first().waitFor();assert.deepEqual(errors,[],'admin '+path);
  }
  await ap.screenshot({path:'.tmp/real-admin.png',fullPage:true});await admin.close();
  console.log('Real candidate browser passed: signed stage Telegram login -> transliterated seller registration; 8 public/private pages at390px; 5 admin screens with real API; no page errors or horizontal overflow. Wallet metadata mocked, no real Telegram login/payment.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
