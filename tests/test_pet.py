# 1.测试宠物的基本属性
# from core.storage.db import get_database
# from core.storage.pet_repo import PetRepository
# db = get_database()
# repo = PetRepository(db)
# pet = repo.get_pet('default')
# print(f'宠物名称: {pet.name}')
# print(f'等级: {pet.level}')
# print(f'经验: {pet.exp}')
# print(f'进化阶段: {pet.evolution_stage}')

# 2. 宠物经验增加与升级
# from core.storage.pet_repo import PetRepository
# from core.storage.db import get_database
# db = get_database()
# repo = PetRepository(db)
# pet = repo.get_pet('default')
# print(f'初始状态: Lv{pet.level}, EXP: {pet.exp}')
# # 增加 60 经验（足够从 Lv1 升级到 Lv2）
# level_up = pet.add_exp(60)
# print(f'增加 60 EXP 后: Lv{pet.level}, EXP: {pet.exp}')
# print(f'是否升级: {level_up}')
# # 保存到数据库
# repo.save_pet(pet)
# # 重新读取验证持久化
# pet2 = repo.get_pet('default')
# print(f'从数据库读取: Lv{pet2.level}, EXP: {pet2.exp}')

# 3. 三阶段进化
# from core.storage.pet_repo import PetRepository
# from core.storage.db import get_database
# from core.models.pet import EvolutionStage
# db = get_database()
# repo = PetRepository(db)
# pet = repo.get_or_create_pet()
# # 测试各等级对应的进化阶段
# test_levels = [1, 3, 4, 7, 8, 10]
# for level in test_levels:
#     stage = pet.get_evolution_stage_for_level(level)
#     print(f'Lv{level} -> Stage {stage.value}')

# 4. 任务创建与存储
# from core.storage.task_repo import TaskRepository
# from core.storage.db import get_database
# from core.models.pet import TaskRecord, TaskDifficulty
# import uuid
# db = get_database()
# repo = TaskRepository(db)
# # 创建任务
# task = TaskRecord(
#     id=str(uuid.uuid4()),
#     input_text='帮我写一段Python代码',
#     difficulty=TaskDifficulty.MEDIUM,
#     reward_exp=15
# )
# repo.create_task(task)
# print(f'任务创建成功: {task.id}')
# print(f'任务内容: {task.input_text}')
# print(f'难度: {task.difficulty}')
# print(f'奖励经验: {task.reward_exp}')
# # 从数据库读取
# retrieved = repo.get_task(task.id)
# print(f'从数据库读取: {retrieved.input_text}')
# print(f'状态: {retrieved.status}')

# 5. 任务状态流转
# from core.storage.task_repo import TaskRepository
# from core.storage.db import get_database
# from core.models.pet import TaskRecord, TaskStatus
# import uuid
# from datetime import datetime
# db = get_database()
# repo = TaskRepository(db)
# # 创建任务
# task_id = str(uuid.uuid4())
# task = TaskRecord(id=task_id, input_text='测试任务')
# repo.create_task(task)
# # 验证初始状态
# t = repo.get_task(task_id)
# print(f'初始状态: {t.status}')
# # 开始执行
# repo.update_task_status(task_id, TaskStatus.RUNNING, started_at=datetime.now())
# t = repo.get_task(task_id)
# print(f'开始执行: {t.status}, 开始时间: {t.started_at}')
# # 完成执行
# repo.update_task_status(task_id, TaskStatus.SUCCESS, finished_at=datetime.now())
# t = repo.get_task(task_id)
# print(f'执行完成: {t.status}, 结束时间: {t.finished_at}')

# 6. 任务结果保存
# from core.storage.task_repo import TaskRepository
# from core.storage.db import get_database
# from core.models.pet import TaskResult
# import uuid
# db = get_database()
# repo = TaskRepository(db)
# # 创建任务
# task_id = str(uuid.uuid4())
# from core.models.pet import TaskRecord
# task = TaskRecord(id=task_id, input_text='测试任务')
# repo.create_task(task)
# # 保存结果
# result = TaskResult(
#     task_id=task_id,
#     success=True,
#     raw_result='这是一个很长的执行结果...' * 10,
#     summary='执行成功，已完成'
# )
# repo.save_task_result(result)
# # 读取结果
# retrieved = repo.get_task_result(task_id)
# print(f'任务成功: {retrieved.success}')
# print(f'摘要: {retrieved.summary}')
# print(f'原始结果长度: {len(retrieved.raw_result)}')

# 7. 最近任务查询
# from core.storage.task_repo import TaskRepository
# from core.storage.db import get_database
# from core.models.pet import TaskRecord
# import uuid
# db = get_database()
# repo = TaskRepository(db)
# # 创建多个任务
# for i in range(5):
#     task = TaskRecord(
#         id=str(uuid.uuid4()),
#         input_text=f'任务 {i+1}'
#     )
#     repo.create_task(task)
# # 查询最近3个任务
# recent = repo.get_recent_tasks(limit=3)
# print(f'最近任务数: {len(recent)}')
# for task in recent:
#     print(f'  - {task.input_text} ({task.created_at})')

# 8. 设置持久化
# from core.storage.settings_repo import SettingsRepository
# from core.storage.db import get_database
# db = get_database()
# repo = SettingsRepository(db)
# # 保存设置
# repo.set_setting('pet_name', 'MyBuddy')
# repo.set_setting('theme', 'dark')
# # 读取设置
# name = repo.get_setting('pet_name')
# theme = repo.get_setting('theme')
# print(f'宠物名称: {name}')
# print(f'主题: {theme}')
# # 保存 JSON 设置
# import json
# config = {'timeout': 120, 'notifications': True}
# repo.set_json_setting('app_config', config)
# # 读取 JSON 设置
# retrieved = repo.get_json_setting('app_config')
# print(f'配置: {retrieved}')

# 9.数据重启后保持
from core.storage.pet_repo import PetRepository
from core.storage.db import get_database
db = get_database()
repo = PetRepository(db)
pet = repo.get_or_create_pet()
pet.name = 'TestPet'
pet.level = 5
pet.exp = 100
repo.save_pet(pet)
print('数据已保存')

from core.storage.pet_repo import PetRepository
from core.storage.db import get_database, init_database
from app.config import get_settings
# 重新初始化
settings = get_settings()
init_database(settings)
db = get_database()
repo = PetRepository(db)
pet = repo.get_pet('default')
print(f'重启后读取: {pet.name} (Lv{pet.level}, EXP: {pet.exp})')