// Disposable fixture records for native UI acceptance; never open the user's database.
import { mkdir,writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import assert from 'node:assert/strict';
import { ChatSessionSchema,ChatMessageSchema,TurnSendSchema,OutcomeSchema,NotificationViewSchema,JevDecisionSchema } from '@lobuddy/contracts';
import { contextDefinition } from '@lobuddy/domain';
import { createStorageService } from '../../packages/service/dist/storage-service.js';
import { ChatRepository } from '../../packages/service/dist/storage/chat.js';
import { KnowledgeService } from '../../packages/service/dist/knowledge/service.js';
import { TopicService } from '../../packages/service/dist/companion/topics.js';
import { TurnRepository } from '../../packages/service/dist/storage/turns.js';
import { OutcomeRepository } from '../../packages/service/dist/storage/outcomes.js';
import { WorkflowRepository } from '../../packages/service/dist/storage/workflows.js';
import { WorkflowEvolution } from '../../packages/service/dist/knowledge/evolution.js';
import { NotificationRepository } from '../../packages/service/dist/storage/notifications.js';
import { JevRepository } from '../../packages/service/dist/storage/jev.js';
export async function seedFixture(kind,temp){
  const data=join(temp,'data'),workspace=join(temp,'workspace');await mkdir(workspace,{recursive:true});
  const service=createStorageService({data,workspace,logs:join(temp,'logs'),create:true,environment:{}});
  try{
    const {store,settings}=service,chat=new ChatRepository(store),knowledge=new KnowledgeService(store,()=>settings.effective());
    chat.saveSession(ChatSessionSchema.parse({id:'fixture'}));
    if(kind==='relationship'){
      chat.saveMessage(ChatMessageSchema.parse({id:'source',session_id:'fixture',role:'user',content:'请叫我小满。'}));
      assert.ok(knowledge.relationship.immediate('fixture','source','请叫我小满。').length);
    }else if(kind==='topics'){
      knowledge.recordFocus('focus-fixture',25);const topics=new TopicService(store),choice=topics.choose();assert.ok(choice);topics.shown(choice);topics.feedback(choice.topic_id,'never');
    }else if(kind==='outcomes'){
      const turns=new TurnRepository(store),{state}=turns.submit('test-result',TurnSendSchema.parse({session_id:'fixture',text:'合成文件整理验收'}));state.status='completed';turns.save(state);
      new OutcomeRepository(store).save(OutcomeSchema.parse({turn_id:state.turn_id,verdict:'verified',scenario:'organize',criteria:['副本数量与 SHA-256 一致'],reason:'已验证1份测试副本',evidence:[{sha256:'test-only'}]}));
    }else if(kind==='workflows'){
      await mkdir(join(workspace,'input'));await writeFile(join(workspace,'input/a.txt'),'待办：检验副本');
      const evolution=new WorkflowEvolution(new WorkflowRepository(store));const candidate=evolution.propose(contextDefinition('compact'),'合成改进验证',['fixture']);
      assert.equal((await evolution.evaluate(candidate.version_id,new AbortController().signal)).status,'probation');
    }else if(kind==='jev'){
      store.run("INSERT INTO app_settings VALUES('llm_model','','now')");
      new NotificationRepository(store).put(NotificationViewSchema.parse({id:'synthetic',source_id:'synthetic',reason:'task_result',text:'合成演示资料已完成',planned_at:1000,created_at:1000}));
      const decision=JevDecisionSchema.parse({action:'quiet',reason:'内容重复，仅留收件箱（合成演示）',mode:'shadow',status:'decided',created_at:1000,not_before:1600,model:'jev-1.13.0'});
      new JevRepository(store).reserve('synthetic','',decision,1,30,60000);
    }else throw Error('Unknown fixture');
  }finally{service.close();}
}
