// Native utility-process/renderer delivery with a prepared synthetic utterance. No model calls.
const {_electron:electron}=require('playwright');
const assert=require('node:assert/strict');
const {mkdtempSync,mkdirSync,rmSync,writeFileSync}=require('node:fs');
const {join,resolve}=require('node:path');const {tmpdir}=require('node:os');const {DatabaseSync}=require('node:sqlite');
const {isolatedDesktopArgs}=require('./isolated-desktop.cjs');
const {waitFor}=require('./wait-for.cjs');
(async()=>{
  const root=mkdtempSync(join(tmpdir(),'lobuddy-care-native-')),data=join(root,'data'),workspace=join(root,'workspace');mkdirSync(workspace);
  const real=process.env.LOBUDDY_CARE_REAL_MODEL==='1';
  const report={kind:real?'native-real-model-care':'native-prepared-care-delivery',model_calls:0,generation_checked:false,started_at:new Date().toISOString(),checks:[],passed:false};let app,provider,phase='seed';
  try{
    if(real){const {evaluationAvailable}=await import('../../qualification/ts-runtime/dist/evaluation-budget.js');
      if(!evaluationAvailable(resolve(__dirname,'../../.local-upgrade/care-model-evaluation.json'),100000,4096,4)){
        phase='evaluation-budget-preflight';report.evaluation_budget_blocked=true;throw Error('evaluation budget unavailable');
      }
      report.evaluation_single_call_output_limit=1024;
    }
    const {Store}=await import('../../packages/service/dist/storage/database.js');
    const {Preferences}=await import('../../packages/service/dist/storage/preferences.js');
    const {ChatRepository}=await import('../../packages/service/dist/storage/chat.js');
    const {KnowledgeService}=await import('../../packages/service/dist/knowledge/service.js');
    const {ProjectService}=await import('../../packages/service/dist/knowledge/projects.js');
    const {CareService}=await import('../../packages/service/dist/companion/care.js');
    const {runtimeSettings}=await import('../../packages/service/dist/config/settings.js');
    const {ChatSessionSchema,ChatMessageSchema,CompanionPolicyStateSchema}=await import('@lobuddy/contracts');
    const store=new Store(join(data,'lobuddy.db'),{create:true}),knowledge=new KnowledgeService(store,()=>runtimeSettings({data,workspace,logs:join(root,'logs')}));
    const projects=new ProjectService(store,knowledge.relationship,new AbortController().signal),chat=new ChatRepository(store),care=new CareService(store,knowledge,projects);
    chat.saveSession(ChatSessionSchema.parse({id:'origin',title:'面试近况'}));chat.saveSession(ChatSessionSchema.parse({id:'other',title:'其他对话'}));
    const text='我最近准备面试，打算先练习项目介绍。',now=Date.now()/1000;
    chat.saveMessage(ChatMessageSchema.parse({id:'user-source',session_id:'origin',role:'user',content:text,created_at:new Date((now-48*3600)*1000).toISOString()}));
    let item=real?undefined:care.admit({source_id:'user-source',subject:'面试',quote:text},'origin');if(!real)assert.ok(item);
    care.configure({...care.policy,start_hour:0,end_hour:24});
    const prefs=new Preferences(store);prefs.set('learning_policy',JSON.stringify({enabled:real,idle_seconds:1,daily_calls:40,daily_input_tokens:160000,daily_output_tokens:20000}));
    prefs.set('companion_policy',JSON.stringify({enabled:true,daily_limit:5,interval_minutes:60}));
    if(real){
      const {LearningRepository}=await import('../../packages/service/dist/storage/learning.js');new LearningRepository(store).enqueue('relationship','user-source',now);
      prefs.set('companion_policy_state',JSON.stringify(CompanionPolicyStateSchema.parse({cooldown_until:now+5})));
      provider=await require('./evaluation-provider.cjs').evaluationProvider();
    }else{
      prefs.set('companion_policy_state',JSON.stringify(CompanionPolicyStateSchema.parse({pending:'care_due',pending_at:now-1,pending_expires:now+1800})));
      store.run('INSERT INTO dialogue_invitation VALUES(?,?,?,?,?,?,?)','offline-prepared','care_due',`care:${item.id}`,item.source_revision,`care:${item.id}`,
        JSON.stringify({opening:'想到你之前说的',closing:'想接着聊时，我在。',start:0,length:[...text].length}),now+1800);
    }store.close();
    const env={...process.env,LOBUDDY_DATA_DIR:data,LOBUDDY_WORKSPACE:workspace,USER_NAME:'合成用户',...(provider?{LLM_BASE_URL:provider.url}:{})};
    const launch=()=>electron.launch({args:isolatedDesktopArgs(root),env,timeout:120000});
    const call=(page,method,params={})=>page.evaluate(({method,params})=>window.lobuddy.request(method,params,crypto.randomUUID()),{method,params});
    phase='launch';app=await launch();let page=await app.firstWindow();await page.getByText('服务已连接',{exact:true}).waitFor({timeout:30000});
    const pet=await find(app,'surface=pet');phase='bubble';await pet.locator('.bubble-content').filter({hasText:'面试'}).waitFor({timeout:real?180000:30000});
    const notice=await call(pet,'companionship.poll');assert.ok(notice);assert.ok(notice.memory_id.startsWith('care:'));if(!real)assert.equal(notice.source,'care_due');
    if(real){item=(await call(page,'care.get')).items.find(item=>`care:${item.id}`===notice.memory_id);assert.ok(item);report.generation_checked=true;report.checks.push('actual-model-extraction-selection-and-review');report.utterance=notice.text;}
    phase='receipt';await call(pet,'companionship.presented',{notice_id:notice.notice_id});await call(pet,'companionship.presented',{notice_id:notice.notice_id});
    assert.equal((await call(page,'care.get')).items[0].unanswered,1);report.checks.push('native-display-receipt-is-idempotent');
    assert.deepEqual(await call(page,'companionship.presented',{notice_id:notice.notice_id}),{accepted:false});
    await assert.rejects(call(page,'companionship.visibility',{visible:true}));report.checks.push('management-cannot-forge-pet-receipts-or-visibility');
    phase='handoff';await pet.locator('.bubble-content').click();const quick=await find(app,'surface=quick');await quick.getByText(notice.text,{exact:true}).waitFor();
    assert.equal(await quick.evaluate(()=>localStorage.getItem('lobuddy-session')),'origin');
    assert.equal((await call(pet,'companionship.accept',{notice_id:notice.notice_id})).session_id,'origin');report.checks.push('click-and-replay-return-to-originating-session');
    if(real){
      phase='model-followup';await quick.getByLabel('消息',{exact:true}).fill('还没开始');await quick.getByRole('button',{name:'发送',exact:true}).click();
      const turn=await waitFor(quick,async()=>{const tasks=await window.lobuddy.request('task.list',{},crypto.randomUUID());return tasks.find(task=>task.session_id==='origin'&&task.input_text==='还没开始'&&!['running','queued'].includes(task.status));},null,{timeout:180000});
      assert.equal(turn.status,'completed');assert.ok(turn.output_text);assert.doesNotMatch(turn.output_text,/已经通过面试|面试已经成功|source_id|memory_id/u);
      assert.equal((await call(page,'care.get')).items[0].unanswered,0);report.reply=turn.output_text;report.checks.push('actual-model-short-followup-without-invented-completion');
      await call(page,'learning.configure',{enabled:false});
    }
    phase='restart';await app.close();app=undefined;
    const db=new DatabaseSync(join(data,'lobuddy.db'));try{
      assert.equal(db.prepare('SELECT count(*) n FROM companion_delivery').get().n,1);
      assert.equal(JSON.parse(db.prepare("SELECT value FROM app_settings WHERE key='companion_policy_state'").get().value).used,1);
    }finally{db.close();}
    app=await launch();page=await app.firstWindow();await page.getByText('服务已连接',{exact:true}).waitFor({timeout:30000});
    assert.equal((await call(page,'care.get')).items[0].unanswered,real?0:1);report.checks.push('restart-retains-presentation-and-unanswered-count');
    phase='forget';await call(page,'memory.delete',{memory_id:item.memory_id});assert.equal((await call(page,'care.get')).items.length,0);
    assert.ok(!(await call(page,'session.history',{session_id:'origin'})).some(message=>message.content===notice.text));
    report.checks.push('forget-removes-followup-and-derived-utterance');report.passed=true;
  }catch(error){report.phase=phase;report.failure=error instanceof assert.AssertionError?error.message:'native_care_check_failed';throw error;}
  finally{if(provider){report.model_calls=provider.calls();report.evaluation_budget_blocked=provider.budgetBlocked();}report.completed_at=new Date().toISOString();if(process.env.LOBUDDY_CARE_REPORT)writeFileSync(process.env.LOBUDDY_CARE_REPORT,JSON.stringify(report,null,2)+'\n');if(app)await app.close();if(provider)await provider.close();rmSync(root,{recursive:true,force:true});}
})().catch(()=>{console.error('Native care check failed; see sanitized report.');process.exitCode=1;});
async function find(app,surface){const until=Date.now()+30000;while(Date.now()<until){const page=app.windows().find(page=>page.url().includes(surface));if(page)return page;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('surface unavailable');}
