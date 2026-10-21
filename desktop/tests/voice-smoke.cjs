// Synthetic MediaStream exercises Chromium AudioWorklet and playback; physical echo is separate.
const { _electron: electron } = require('playwright');
const { waitFor } = require('./wait-for.cjs');
const assert = require('node:assert/strict');
const { resolve } = require('node:path');
const { readFileSync, mkdtempSync, rmSync, mkdirSync, writeFileSync, cpSync } = require('node:fs');
const { execFileSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const { resourceVerdict } = require('./runtime-evidence.cjs');
const { tmpdir } = require('node:os');
(async () => {
  const root = resolve(__dirname, '../..');
  const original = readFileSync(resolve(__dirname, 'fixtures/voice-greeting.wav'));
  const profile = mkdtempSync(resolve(tmpdir(), 'lobuddy-voice-profile-'));
  const soakSeconds = Number(process.env.LOBUDDY_VOICE_SOAK_SECONDS || 0);
  const burstMs = Number(process.env.LOBUDDY_VOICE_BURST_MS || 0);
  assert.ok(Number.isFinite(burstMs) && burstMs >= 0 && burstMs <= 800);
  assert.ok(Number.isFinite(soakSeconds) && (soakSeconds === 0 || soakSeconds >= 60 && soakSeconds <= 14400));
  const isolated = mkdtempSync(resolve(tmpdir(), 'lobuddy-ts-voice-'));
  const data = resolve(isolated,'data');
  const workspace = resolve(isolated,'workspace');
  if (isolated) {
    mkdirSync(resolve(data,'voice-models/onnx-small'),{recursive:true}); mkdirSync(workspace);
    cpSync(resolve(root,'.local-upgrade/ts-assets/whisper-small'),resolve(data,'voice-models/onnx-small/whisper-small'),{recursive:true});
    cpSync(resolve(root,'.local-upgrade/ts-assets/silero.onnx'),resolve(data,'voice-models/onnx-small/silero.onnx'));
    writeFileSync(resolve(workspace,'soak-note.txt'),'决定：保留来源。\n待办：检查连续语音资源。');
  }
  const reportPath = resolve(root,process.env.LOBUDDY_VOICE_SOAK_REPORT || `reports/2026-10-21_t9_voice_soak-${Date.now()}.json`);
  const report = soakSeconds ? {status:'running',started_at:new Date().toISOString(),required_seconds:soakSeconds,distribution:process.env.LOBUDDY_PACKAGE?'relocated-package':'development-build',scope:'synthetic continuous MediaStream, real local ASR/DSH/fixed Fish free voice, periodic background verified tasks; transparent noninteractive test windows, hidden Dock entry and muted output; no physical microphone',samples:[],tasks:0} : null;
  const save = () => { if(report) writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n'); };
  if(report) writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
  const owned = new Set();
  const processes = () => execFileSync('ps',['-axo','pid=,ppid=,rss='],{encoding:'utf8'}).trim().split('\n').map(line=>line.trim().split(/\s+/).map(Number));
  let application;
  const args = [...(process.env.LOBUDDY_PACKAGE ? [] : [resolve(__dirname, '..')]), '--use-fake-device-for-media-stream', `--user-data-dir=${profile}`];
  try {
    application = await electron.launch({ args, executablePath: process.env.LOBUDDY_PACKAGE || undefined, env: { ...process.env, LOBUDDY_DATA_DIR: data, LOBUDDY_WORKSPACE: workspace } });
    owned.add(application.process().pid);
    if(report) await application.evaluate(({app,BrowserWindow,powerMonitor})=>{
      app.dock?.hide();
      const events=[]; const record=(kind,details={})=>{events.push({at:new Date().toISOString(),kind,...details});if(events.length>64)events.shift();};
      globalThis.voiceSoakEvents=events;
      const observe=window=>{
        window.setOpacity(0); window.setFocusable(false); window.setIgnoreMouseEvents(true);
        window.webContents.setAudioMuted(true); // Synthetic playback scheduling, not physical audibility.
        for(const kind of ['hide','show','close'])window.on(kind,()=>record(kind,{quick:window.webContents.getURL().includes('surface=quick')}));
        window.webContents.on('render-process-gone',(_event,info)=>record('renderer-gone',{reason:info.reason}));
      };
      BrowserWindow.getAllWindows().forEach(observe);app.on('browser-window-created',(_event,window)=>observe(window));
      for(const kind of ['suspend','resume'])powerMonitor.on(kind,()=>record(kind));
    });
    const page = await application.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor(); await page.bringToFront();
    if(report) await page.evaluate(()=>window.lobuddy.request('learning.configure',{enabled:false},crypto.randomUUID()));
    await application.evaluate(({ systemPreferences }) => { systemPreferences.askForMediaAccess = async () => true; }); // Fake device only; OS grant is a separate manual check.
    await page.locator('button.new-chat').click();
    await page.evaluate(() => window.lobuddy.windowAction('chat'));
    let quick;
    const windowDeadline = Date.now() + 20000;
    while (Date.now() < windowDeadline) {
      quick = application.windows().find(window => window.url().includes('surface=quick'));
      if (quick) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(quick, 'Quick chat window must load'); quick.setDefaultTimeout(30000);
    await quick.evaluate(({pcm,repeatSeconds}) => {
      window.fixtureEvents=[];
      const record=kind=>{window.fixtureEvents.push({at:new Date().toISOString(),kind});if(window.fixtureEvents.length>64)window.fixtureEvents.shift();};
      window.lobuddy.onVoiceStop(()=>record('main-requested-stop'));
      window.addEventListener('pagehide',()=>record('pagehide'));
      window.addEventListener('storage',event=>{if(event.key==='lobuddy-session')record('shared-session-changed');});
      document.addEventListener('click',event=>{const button=event.target.closest?.('.voice-controls button');if(button)record('voice-control:'+button.textContent);},true);
      window.testTracks = []; window.captureFrames = 0; window.capturePeak = 0; window.audioContexts = [];
      const Worklet = window.AudioWorkletNode, Context = window.AudioContext;
      window.AudioContext = class extends Context { constructor(...args) { super(...args); window.audioContexts.push(this); } };
      window.AudioWorkletNode = class extends Worklet { constructor(...args) { super(...args); this.port.addEventListener('message', event => { window.captureFrames++; for (const n of new Int16Array(event.data)) window.capturePeak = Math.max(window.capturePeak, Math.abs(n)); }); this.port.start(); } };
      window.playbackStarts = 0; window.playbackStops = 0; window.stopTimes = [];
      const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async constraints => {
        const fakeDevice = await capture(constraints); fakeDevice.getTracks().forEach(track => track.stop());
        const context = new Context({ sampleRate: 16000 }); await context.resume();
        const destination = context.createMediaStreamDestination();
        const buffer = context.createBuffer(1, pcm.length + 16000 * repeatSeconds, 16000);
        buffer.getChannelData(0).set(pcm.map(value => value / 32768));
        const source = context.createBufferSource(); source.buffer = buffer; source.loop = true; source.connect(destination);
        start.call(source);
        window.injectSpeech = () => {
          const extra = context.createBufferSource();
          const speech = context.createBuffer(1, pcm.length, 16000);
          speech.getChannelData(0).set(pcm.map(value => value / 32768));
          extra.buffer = speech; extra.connect(destination);
          extra.onended = () => extra.disconnect();
          window.bargeStart = performance.now(); start.call(extra);
        };
        for (const track of destination.stream.getTracks()) {
          const stopTrack = track.stop.bind(track);
          track.stop = () => { stopTrack(); stop.call(source); source.disconnect(); void context.close(); };
        }
        window.testTracks.push(...destination.stream.getTracks());
        return destination.stream;
      };
      const start = AudioBufferSourceNode.prototype.start, stop = AudioBufferSourceNode.prototype.stop;
      AudioBufferSourceNode.prototype.start = function(...args) { window.playbackStarts++; return start.apply(this, args); };
      AudioBufferSourceNode.prototype.stop = function(...args) { window.playbackStops++; window.stopTimes.push(performance.now()); return stop.apply(this, args); };
    }, {pcm:Array.from(new Int16Array(original.buffer.slice(original.byteOffset + 44, original.byteOffset + original.length))),repeatSeconds:soakSeconds ? 600 : 30});
    await quick.bringToFront();
    await quick.getByRole('button', { name: '开启语音陪伴', exact: true }).click();
    await quick.getByRole('button', { name: '结束语音', exact: true }).waitFor({ timeout: 15000 }).catch(async error => { console.log(await quick.locator('.voice-controls').innerText()); throw error; });
    await waitFor(quick, async () => {
      const alert = document.querySelector('.voice-controls [role=alert]'); if (alert?.textContent) throw Error(alert.textContent);
      const state = await window.lobuddy.request('voice.get', {}, crypto.randomUUID());
      if (state.error) throw Error(state.error);
      return window.playbackStarts > 0;
    }, null, { timeout: 45000 });
    try{await quick.screenshot({path:'/tmp/lobuddy-ts-voice.png',timeout:5000});}catch{console.log('Screenshot unavailable; voice assertions still run.');}
    await quick.evaluate(() => window.injectSpeech());
    await waitFor(quick, () => window.stopTimes.some(time => time > window.bargeStart), null, { timeout: 10000 });
    const interruption = await quick.evaluate(() => window.stopTimes.find(time => time > window.bargeStart) - window.bargeStart);
    console.log('Synthetic onset-to-playback-stop ms:', Math.round(interruption));
    assert.ok(interruption <= 300, 'Playback must stop within 300 ms of synthetic speech onset');
    await quick.getByRole('button', { name: '静音', exact: true }).click();
    await quick.getByText('麦克风已关闭', { exact: true }).waitFor();
    assert.equal(await quick.evaluate(() => window.testTracks.every(track => track.readyState === 'ended')), true);
    assert.ok(await quick.evaluate(() => window.playbackStops > 0));
    await quick.getByRole('button', { name: '恢复麦克风', exact: true }).click();
    await waitFor(quick, () => window.testTracks.filter(track => track.readyState === 'live').length === 1, null, { timeout: 40000 });
    if(report) {
      await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().filter(w=>w.webContents.getURL().includes('surface=quick')).forEach(w=>w.setAlwaysOnTop(false)));
      const started = performance.now();
      const sessionId = await quick.evaluate(async()=> (await window.lobuddy.request('voice.get',{},crypto.randomUUID())).session_id);
      let previousFrames = -1, burstInjected = false;
      const voiceTurns = new Set();
      const background = await page.evaluate(()=>window.lobuddy.request('session.create',{title:'连续语音资源检查'},crypto.randomUUID()));
      while((performance.now()-started)/1000 < soakSeconds) {
        if(burstMs && !burstInjected && performance.now()-started>5000){
          await quick.evaluate(ms=>{const until=performance.now()+ms;while(performance.now()<until){}},burstMs);
          report.renderer_pause_ms=burstMs;burstInjected=true;
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
        const state = await quick.evaluate(async()=>({voice:await window.lobuddy.request('voice.get',{},crypto.randomUUID()),frames:window.captureFrames,tracks:window.testTracks.filter(t=>t.readyState==='live').length,contexts:window.audioContexts.filter(c=>c.state!=='closed').length,visibility:document.visibilityState,alert:document.querySelector('.voice-controls [role=alert]')?.textContent||''}));
        report.native_events=await application.evaluate(()=>globalThis.voiceSoakEvents);
        report.renderer_events=await quick.evaluate(()=>window.fixtureEvents);
        report.selection_matches_voice=await quick.evaluate(id=>localStorage.getItem('lobuddy-session')===id,sessionId);
        report.last_voice_state={state:state.voice.state,error:state.voice.error,alert:state.alert,visibility:state.visibility,frames:state.frames,tracks:state.tracks,contexts:state.contexts};save();
        assert.ok(!['off','error','muted'].includes(state.voice.state));
        assert.equal(state.tracks,1); assert.equal(state.contexts,1); assert.ok(state.frames>previousFrames); previousFrames=state.frames;
        const turn = await page.evaluate(id=>window.lobuddy.request('turn.send',{session_id:id,text:'归纳长稳测试资料',lane:'background',workflow_id:'source-digest',workflow_input:{sources:['soak-note.txt']}},crypto.randomUUID()),background.id);
        await waitFor(page,async id=>(await window.lobuddy.request('task.get',{turn_id:id},crypto.randomUUID())).status==='completed',turn.turn_id);
        assert.equal(await page.evaluate(async id=>(await window.lobuddy.request('task.outcome',{turn_id:id},crypto.randomUUID())).verdict,turn.turn_id),'verified');
        report.tasks++;
        const recent = await page.evaluate(()=>window.lobuddy.request('task.list',{},crypto.randomUUID()));
        for(const task of recent)if(task.session_id===sessionId&&task.lane==='foreground'&&task.status==='completed')voiceTurns.add(task.turn_id);
        report.completed_voice_turns=voiceTurns.size;
        const rows=processes(), ids=new Set([application.process().pid]); let added=true;
        while(added){added=false;for(const [id,parent] of rows)if(ids.has(parent)&&!ids.has(id)){ids.add(id);added=true;}}
        const tree=rows.filter(row=>ids.has(row[0])); tree.forEach(row=>owned.add(row[0]));
        report.elapsed_seconds=(performance.now()-started)/1000;
        report.samples.push({seconds:report.elapsed_seconds,rss_kib:tree.reduce((sum,row)=>sum+row[2],0),processes:tree.length,capture_frames:state.frames,live_tracks:state.tracks,open_audio_contexts:state.contexts}); save();
        if(report.tasks%20===0)console.log(`VOICE SOAK ${Math.round(report.elapsed_seconds)}s / ${report.tasks} verified background tasks`);
        await new Promise(resolve=>setTimeout(resolve,Math.min(30000,soakSeconds*250,Math.max(1,soakSeconds*1000-(performance.now()-started)))));
      }
      report.elapsed_seconds=(performance.now()-started)/1000;
      report.completed_voice_turns=voiceTurns.size;
      assert.ok(report.completed_voice_turns >= (soakSeconds>=7200?10:1));
      report.resources=resourceVerdict(report.samples,report.elapsed_seconds,soakSeconds);
      assert.ok(report.resources.passed,report.resources.reason);
      report.status=soakSeconds>=7200?'passed':'short_check_passed';save();
    }
    await quick.getByRole('button', { name: '结束语音', exact: true }).click();
    await quick.getByRole('button', { name: '开启语音陪伴', exact: true }).waitFor();
    assert.equal(await quick.evaluate(() => window.testTracks.every(track => track.readyState === 'ended')), true);
    const history = await quick.evaluate(async () => { const tasks = await window.lobuddy.request('task.list', {}, crypto.randomUUID()); return tasks.find(task => task.lane === 'foreground'); });
    assert.match(history.input_text, /你好|回答|我在/);
    assert.equal(history.lane, 'foreground');
    console.log('PASS: Chromium synthetic MediaStream → local ASR → DSH → fixed Fish voice playback; mute stops tracks/playback, resume reacquires, end releases');
  } catch(error) {if(report){report.status='failed';report.error_category='voice_or_lifecycle_assertion';save();}throw error;}
  finally {
    if(application) await application.close();
    if(report){await new Promise(resolve=>setTimeout(resolve,1000));const alive=new Set(processes().map(row=>row[0]));report.orphans=[...owned].filter(id=>alive.has(id));if(report.orphans.length)report.status='failed';report.ended_at=new Date().toISOString();save();}
    rmSync(profile, { recursive: true, force: true }); if(isolated)rmSync(isolated,{recursive:true,force:true});
    if(report?.status==='failed')process.exitCode=1;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
