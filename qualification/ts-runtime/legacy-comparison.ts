// Development-only oracle. T9 removes this adapter together with the old runtime.
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';

const [python, model, corpus, manifest, output] = process.argv.slice(2);
if (!python || !model || !corpus || !manifest || !output) throw new Error('Expected PYTHON MODEL CORPUS MANIFEST OUTPUT');
const source = `
import hashlib,json,time,wave,sys
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel
model_path,corpus_path,manifest_path,output_path=sys.argv[1:]
manifest_bytes=Path(manifest_path).read_bytes()
manifest=json.loads(manifest_bytes)
model=WhisperModel(model_path,device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
def audio(item):
    path=Path(corpus_path)/item['file']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
    with wave.open(str(path),'rb') as stream:
        assert stream.getframerate()==16000 and stream.getnchannels()==1 and stream.getsampwidth()==2
        return np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
def transcribe(samples):
    segments,_=model.transcribe(samples,beam_size=1,language='zh',condition_on_previous_text=False,vad_filter=False,temperature=0,no_speech_threshold=0.6)
    return ''.join(s.text for s in segments if s.avg_logprob > -1).strip()
transcribe(audio(manifest['cases'][0]))
results=[]
for item in manifest['cases']:
    samples=audio(item)
    started=time.perf_counter()
    text=transcribe(samples)
    results.append({'id':item['id'],'text':text,'ms':(time.perf_counter()-started)*1000})
    if len(results)%20==0: print('Legacy corpus:',len(results),flush=True)
Path(output_path).write_text(json.dumps({'engine':'faster-whisper-small-int8','threads':4,'corpusSha256':hashlib.sha256(manifest_bytes).hexdigest(),'results':results},ensure_ascii=False,indent=2)+'\\n')
`;
await new Promise<void>((done, reject) => {
  const child = spawn(resolve(python), ['-c', source, ...[model, corpus, manifest, output].map(path => resolve(path))], {
    stdio: ['ignore', 'inherit', 'inherit'], env: { PATH: '/usr/bin:/bin', HOME: process.env.HOME,
      HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1' },
  });
  child.once('error', reject);
  child.once('exit', code => code === 0 ? done() : reject(new Error(`Legacy comparison exited ${code}`)));
});
