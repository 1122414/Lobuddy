// Standalone macOS arm64 bundle. Dependencies resolve entirely inside Resources/app.
const { cpSync,mkdirSync,writeFileSync,readFileSync,existsSync,renameSync,symlinkSync }=require('node:fs');
const { dirname,join,resolve }=require('node:path');
const { execFileSync }=require('node:child_process');
const { createHash }=require('node:crypto');
const desktop=resolve(__dirname,'..'),root=resolve(desktop,'..');
if(process.platform!=='darwin'||process.arch!=='arm64')throw Error('This package targets macOS arm64');
const native=JSON.parse(readFileSync(join(root,'qualification/ts-runtime/native-manifest.json'),'utf8'));
const assets=join(root,'.local-upgrade/ts-assets');
if(!existsSync(join(assets,'dsh-runtime')))execFileSync(process.execPath,[join(root,'qualification/ts-runtime/dist/download-assets.js'),assets,'--runtime-only'],{stdio:'inherit',cwd:root});
const runtime=readFileSync(join(assets,'dsh-runtime'));
if(runtime.length!==native.dsh.runtimeSize||createHash('sha256').update(runtime).digest('hex')!==native.dsh.runtimeSha256)throw Error('DSH runtime differs from the pinned distribution');
const version=JSON.parse(readFileSync(join(root,'package.json'),'utf8')).version;
const destination=join(desktop,'release',`Lobuddy-${version}-${Date.now()}.app`);
mkdirSync(dirname(destination),{recursive:true});
cpSync(join(dirname(require.resolve('electron/package.json')),'dist/Electron.app'),destination,{recursive:true,verbatimSymlinks:true});
const app=join(destination,'Contents/Resources/app');mkdirSync(app);
for(const folder of ['dist','dist-electron'])cpSync(join(desktop,folder),join(app,folder),{recursive:true});
writeFileSync(join(app,'package.json'),JSON.stringify({name:'lobuddy-desktop',version,main:'dist-electron/desktop/electron/main.js'},null,2));
execFileSync(process.execPath,[join(root,'scripts/ts/copy-runtime-dependencies.mjs'),join(root,'package.json'),'@lobuddy/service,@lobuddy/speech,@lobuddy/contracts,@lobuddy/domain,@deepseek-ai/dsh-llm,zod',join(app,'node_modules')],{stdio:'inherit',cwd:root});
mkdirSync(join(app,'packages'));
// Keep each entry alongside its resolved dependencies, including nested peer versions.
for(const name of ['contracts','domain','service','speech'])symlinkSync(`../node_modules/@lobuddy/${name}`,join(app,'packages',name),'dir');
mkdirSync(join(app,'bridge/dsh'),{recursive:true});
cpSync(join(root,'bridge/dsh/dist'),join(app,'bridge/dsh/dist'),{recursive:true});
cpSync(join(root,'bridge/dsh/package.json'),join(app,'bridge/dsh/package.json'));
mkdirSync(join(app,'assets'));cpSync(join(assets,'dsh-runtime'),join(app,'assets/dsh-runtime'));
cpSync(join(assets,'licenses'),join(app,'assets/licenses'),{recursive:true});
writeFileSync(join(app,'assets/runtime-provenance.json'),JSON.stringify(native.dsh,null,2));
cpSync(join(root,'qualification/ts-runtime/dependency-inventory.json'),join(app,'assets/dependency-inventory.json'));
cpSync(join(root,'qualification/ts-runtime/model-manifest.json'),join(app,'assets/model-manifest.json'));
const plist=join(destination,'Contents/Info.plist');
for(const [key,value] of Object.entries({NSMicrophoneUsageDescription:'开启语音陪伴时在本机识别你的声音，结束后释放麦克风。',CFBundleName:'Lobuddy',CFBundleDisplayName:'Lobuddy',CFBundleIdentifier:'app.lobuddy.desktop',CFBundleExecutable:'Lobuddy',CFBundleShortVersionString:version,LSMinimumSystemVersion:'14.0'}))execFileSync('/usr/bin/plutil',['-replace',key,'-string',value,plist]);
renameSync(join(destination,'Contents/MacOS/Electron'),join(destination,'Contents/MacOS/Lobuddy'));
// Verification must succeed before this build becomes the latest candidate.
execFileSync(process.execPath,[join(root,'scripts/ts/verify-package.mjs'),destination,'--write-manifest'],{stdio:'inherit',cwd:root});
writeFileSync(join(desktop,'release/latest.txt'),destination+'\n');console.log(destination);
