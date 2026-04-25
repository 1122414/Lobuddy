# ui-redesign-plan.md

# Lobuddy UI Redesign Plan

## 0. Goal

This plan redesigns Lobuddy from a “chat window with a pet image” into a real desktop pet agent.

The redesign must preserve and improve the core product direction:

- Desktop pet is the visual and interaction center.
- Agent task execution is shown through lightweight task cards, not long log-like chat bubbles.
- Chat is available, but not always the main UI.
- Pet has level, EXP, mood, and task feedback.
- Users can customize the pet appearance by uploading static images and GIFs.
- The first implementation should be incremental and safe. Do not rewrite the whole project.

---

## 1. Current Problems

From the current screenshot, the UI has these issues:

1. Pet, chat, history, and task result are all forced into one large window.
2. The pet looks like a decorative image instead of a desktop companion.
3. The large green/red button style conflicts with the pet’s red/white/black color palette.
4. Chat output is too verbose and looks like an execution log.
5. History is always visible and wastes space.
6. Pet level and EXP exist visually, but they are not connected to task completion feedback.
7. There is no clear entry for pet customization.

---

## 2. New UI Direction

Lobuddy should use this structure:

```text
Desktop Pet Layer
├─ PetWidget
│  ├─ Pet image / GIF / animation
│  ├─ Level + EXP mini bar
│  ├─ Mood / working status
│  └─ Speech bubble
│
Floating Interaction Layer
├─ QuickActionMenu
│  ├─ Chat
│  ├─ Tasks
│  ├─ Memory
│  ├─ Pet
│  └─ Settings
│
Assistant Layer
├─ ChatPanel
│  ├─ Compact chat messages
│  ├─ Input box
│  └─ Optional history drawer
│
Task Layer
├─ TaskCardPanel
│  ├─ Running task
│  ├─ Success / failure state
│  ├─ Tool details
│  └─ Continue action buttons
│
Customization Layer
├─ PetSettingsPanel
│  ├─ Upload image
│  ├─ Upload GIF
│  ├─ Preview pet
│  ├─ Scale / position / opacity
│  └─ Reset to default
```

The default state should only show the desktop pet, its level/EXP, and occasional speech bubble. The full chat panel should appear only when the user opens it.

---

## 3. Design Principles

### 3.1 Pet First

The pet must be the main UI object. Other panels are secondary.

Do:

- Let the pet float independently on the desktop.
- Allow the user to drag the pet.
- Show short speech bubbles near the pet.
- Show task progress as compact cards near the pet.

Avoid:

- Keeping a giant chat window open by default.
- Treating the pet as a sidebar avatar.
- Showing long execution logs directly in the chat bubble.

---

### 3.2 Lightweight by Default

Default UI:

```text
[Pet]
Lv.7  EXP bar
Small speech bubble when needed
```

Expanded UI:

```text
[Pet] + [Quick Action Menu]
[Chat Panel] only after clicking Chat
[Task Cards] only when a task is running or finished
```

---

### 3.3 Task Result Should Be Card-Based

Bad:

```text
Edge browser has successfully opened and accessed Baidu homepage.
Although there are encoding issues...
Explanation:
- Used DrissionPage...
- Browser will remain open...
```

Good:

```text
Pet bubble:
“Edge 已经打开啦，要继续让我搜索什么吗？”

Task card:
✅ 打开 Edge 浏览器
✅ 访问百度首页
⚠️ 控制台编码显示异常，不影响执行

Buttons:
[继续操作] [打开网页] [截图] [查看详情]
```

Long logs should be hidden inside “查看详情”.

---

### 3.4 Custom Pet Appearance Is a Core Feature

Users must be able to customize the pet image.

Supported assets:

- PNG
- JPG / JPEG
- WEBP
- GIF

Initial version does not need advanced Live2D or Spine support. Static image and GIF are enough for MVP.

---

## 4. Target Visual Style

Recommended style: cozy desktop companion.

### 4.1 Color Palette

Avoid the current large green/red admin-style UI.

Recommended colors:

```text
Background:       #FFF7ED
Panel:            #FFFFFF
Panel Transparent:#FFFFFFDD
Primary:          #F97316
Primary Dark:     #EA580C
Accent Red:       #EF4444
Accent Blue:      #60A5FA
Text Main:        #1F2937
Text Muted:       #6B7280
Border:           #F3D9B1
Success:          #22C55E
Warning:          #F59E0B
Error:            #EF4444
```

### 4.2 Component Style

- Rounded corners: 16px to 24px.
- Soft shadow.
- Semi-transparent floating panels.
- Large panels should not appear unless requested.
- Use icon buttons where possible.
- Avoid strong rectangular admin buttons.

### 4.3 Typography

Use system fonts first:

```text
Windows:
Microsoft YaHei UI / Segoe UI

Fallback:
Arial / sans-serif
```

---

## 5. New Main Components

## 5.1 PetWidget

### Purpose

The core desktop pet view.

### Responsibilities

- Render default pet image or user-uploaded image/GIF.
- Show level and EXP mini bar.
- Show current status: idle, thinking, working, success, failed.
- Show short speech bubble.
- Support drag-to-move.
- Support right-click menu.
- Support click-to-open quick action menu.

### Suggested UI

```text
        [speech bubble]
              |
          [pet image/GIF]
       Lv.7 [ EXP bar ]
```

### Required Features

- Transparent background.
- Always-on-top option.
- Drag support.
- Scale support.
- Opacity support.
- Pet asset loading from user settings.
- Fallback to default pet image if custom asset is missing or invalid.

### Acceptance Criteria

- App can start with only the PetWidget visible.
- Pet can be dragged around the desktop.
- Pet image loads from default asset.
- Pet image can be replaced by user-uploaded image.
- GIF animation plays correctly.
- If custom file is deleted, app falls back to default pet.

---

## 5.2 QuickActionMenu

### Purpose

A small radial or floating menu opened by clicking the pet.

### Actions

MVP buttons:

```text
Chat
Task
Pet
Settings
Close
```

Future buttons:

```text
Memory
Browser
Screenshot
Sleep
Feed
```

### Suggested UI

Use small rounded icon buttons around or beside the pet.

Example:

```text
        [Chat]
[Task]  [Pet]  [Settings]
        [Close]
```

### Acceptance Criteria

- Clicking the pet opens/closes the menu.
- Clicking Chat opens ChatPanel.
- Clicking Pet opens PetSettingsPanel.
- Clicking Settings opens AppSettingsPanel.
- Menu closes when clicking outside or selecting an action.

---

## 5.3 ChatPanel

### Purpose

Compact chat interface. It should not dominate the default UI.

### Layout

```text
Header:
Lobuddy Chat        [History] [Settings] [X]

Messages:
User message
Pet reply
Task card reference if needed

Input:
[Type a message...] [Send]
```

### Changes from Current UI

- Remove always-visible History sidebar.
- Move History into a collapsible drawer.
- Shorten assistant replies.
- Use task cards for tool execution results.
- Keep chat bubble width reasonable.
- Do not show raw logs by default.

### Acceptance Criteria

- ChatPanel can be opened and closed without closing the pet.
- User can send messages.
- Assistant responses render in styled bubbles.
- History drawer is hidden by default.
- Delete button is not shown as a large red button in the main layout.
- Long tool details are collapsed.

---

## 5.4 TaskCardPanel

### Purpose

Show Agent execution status in a structured way.

### Task Card Fields

```text
Task title
Status: pending / running / success / warning / failed
Steps
Short result
Action buttons
Details drawer
EXP reward
```

### Example

```text
打开 Edge 浏览器
Status: Success

✅ 启动浏览器
✅ 访问百度首页
⚠️ 控制台编码异常，不影响执行

+15 EXP

[继续操作] [截图] [查看详情]
```

### Acceptance Criteria

- When a browser/tool task starts, a task card appears.
- Running state is visible.
- Success/failure state is visible.
- Long logs are hidden under “查看详情”.
- Task completion can trigger EXP gain animation or message.

---

## 5.5 PetSettingsPanel

### Purpose

Allow users to customize the pet appearance.

This is required by the user.

### Entry Points

Users should be able to open this panel from:

1. Pet right-click menu.
2. QuickActionMenu → Pet.
3. ChatPanel header → Settings → Pet Appearance.

### MVP Features

```text
Pet Appearance
├─ Current preview
├─ Upload image
├─ Upload GIF
├─ Scale slider
├─ Opacity slider
├─ Reset position
├─ Reset to default pet
└─ Save
```

### Supported File Types

```text
.png
.jpg
.jpeg
.webp
.gif
```

### File Handling Rules

When a user uploads a pet asset:

1. Validate file type.
2. Copy the file into the app data directory.
3. Do not depend on the original source path after upload.
4. Store the copied asset path in settings.
5. Reload PetWidget preview immediately.
6. Save settings only after user clicks Save, or auto-save if current app style prefers that.

Recommended app data structure:

```text
data/
├─ user_assets/
│  ├─ pets/
│  │  ├─ custom_pet_001.png
│  │  ├─ custom_pet_002.gif
│  │  └─ ...
│  └─ thumbnails/
├─ settings/
│  └─ ui_settings.json
```

### Settings Schema

Suggested JSON:

```json
{
  "pet": {
    "asset_path": "data/user_assets/pets/custom_pet_001.gif",
    "asset_type": "gif",
    "scale": 1.0,
    "opacity": 1.0,
    "position": {
      "x": 1200,
      "y": 680
    },
    "always_on_top": true,
    "use_default_asset": false
  },
  "ui": {
    "theme": "cozy",
    "chat_panel_collapsed_by_default": true,
    "history_drawer_visible": false
  }
}
```

### Validation

- Reject unsupported file types.
- Reject files larger than a configurable limit.
- Recommended MVP size limit: 20 MB.
- Show friendly error message if file is invalid.
- If GIF is too large, still allow it if performance is acceptable, but warn the user.

### GIF Handling

For PySide6, use `QMovie` for GIF playback.

Expected behavior:

- Static image uses `QPixmap`.
- GIF uses `QMovie`.
- Scaling should apply to both.
- Preview panel and PetWidget should use the same loader logic.

Suggested abstraction:

```text
PetAssetLoader
├─ load_static_image(path) -> QPixmap
├─ load_gif(path) -> QMovie
├─ detect_asset_type(path) -> image/gif/invalid
└─ validate_asset(path) -> ValidationResult
```

### Acceptance Criteria

- User can upload PNG/JPG/WEBP and see the pet update.
- User can upload GIF and see animation play.
- Uploaded asset is copied into app data directory.
- App remembers custom pet after restart.
- User can reset to default pet.
- Invalid files show a readable error instead of crashing.
- Missing custom file falls back to default pet.

---

## 6. Proposed Code Organization

Adjust names based on the current repository structure. Do not force this exact structure if the existing project already has a better layout.

Suggested structure:

```text
lobuddy/
├─ ui/
│  ├─ main_window.py
│  ├─ pet_widget.py
│  ├─ quick_action_menu.py
│  ├─ chat_panel.py
│  ├─ task_card_panel.py
│  ├─ pet_settings_panel.py
│  ├─ app_settings_panel.py
│  └─ styles/
│     ├─ theme.py
│     └─ cozy.qss
│
├─ services/
│  ├─ settings_service.py
│  ├─ pet_asset_service.py
│  └─ task_event_service.py
│
├─ assets/
│  ├─ default_pet.png
│  └─ icons/
│
├─ data/
│  ├─ user_assets/
│  └─ settings/
│
└─ main.py
```

---

## 7. Event Flow

## 7.1 Open Chat

```text
User clicks pet
→ QuickActionMenu opens
→ User clicks Chat
→ ChatPanel opens near pet or center screen
```

## 7.2 Execute Task

```text
User sends: 帮我打开 Edge 浏览器
→ Agent starts task
→ Pet status = working
→ TaskCardPanel shows running card
→ Tool result arrives
→ TaskCardPanel updates status
→ Pet status = success / failed
→ EXP reward displayed if success
→ Pet speech bubble shows short summary
```

## 7.3 Upload Custom Pet

```text
User clicks pet
→ QuickActionMenu
→ Pet
→ PetSettingsPanel
→ Upload Image/GIF
→ Validate file
→ Copy to data/user_assets/pets/
→ Preview updates
→ Save settings
→ PetWidget reloads asset
```

---

## 8. Implementation Phases

# Phase 1: UI Shell Separation

## Goal

Separate the current giant window into pet-first UI components.

## Tasks

1. Identify current UI entry file and widget hierarchy.
2. Extract pet rendering into `PetWidget`.
3. Extract chat area into `ChatPanel`.
4. Hide History by default.
5. Add simple QuickActionMenu.
6. Make PetWidget the default visible surface.

## Do Not Do

- Do not rewrite the Agent backend.
- Do not change task execution logic.
- Do not implement complex animations yet.
- Do not remove existing chat functionality.

## Acceptance Criteria

- App launches with PetWidget visible.
- ChatPanel can be opened from PetWidget.
- Existing chat still works.
- History no longer occupies permanent left sidebar.
- No major backend behavior changes.

---

# Phase 2: Visual Theme Redesign

## Goal

Replace the current admin-like green/red UI with a cozy desktop companion style.

## Tasks

1. Add a central theme file or QSS file.
2. Replace large green header/buttons with warm primary color.
3. Replace large red Delete button with small secondary/danger action.
4. Add rounded cards and soft shadows.
5. Update chat bubble style.
6. Update input box style.
7. Update EXP bar style.

## Acceptance Criteria

- Main UI no longer looks like a raw Qt demo.
- Buttons, panels, chat bubbles, and EXP bar use one consistent visual style.
- Pet colors do not conflict with UI colors.
- Delete action is visually less dominant.

---

# Phase 3: Task Card System

## Goal

Convert tool execution results from long chat text into structured task cards.

## Tasks

1. Create `TaskCardPanel`.
2. Define task status enum:

```text
pending
running
success
warning
failed
```

3. Add task card data model.
4. Render browser/tool execution result as card.
5. Add “查看详情” collapsible section for logs.
6. Add action buttons:

```text
继续操作
截图
打开网页
查看详情
```

7. Connect task success to EXP reward display.

## Acceptance Criteria

- Browser task result appears as a card.
- Long execution details are collapsed by default.
- Pet bubble only shows short human-friendly result.
- EXP gain is shown when task succeeds.

---

# Phase 4: Pet Customization

## Goal

Add user-uploaded pet image/GIF support.

## Tasks

1. Create `PetSettingsPanel`.
2. Add upload button for image/GIF.
3. Add file validation.
4. Add `PetAssetService`.
5. Copy uploaded file into app data directory.
6. Add settings persistence through `SettingsService`.
7. Add static image loading with `QPixmap`.
8. Add GIF loading with `QMovie`.
9. Add preview area.
10. Add scale slider.
11. Add opacity slider.
12. Add reset-to-default button.
13. Reload PetWidget after saving.

## Acceptance Criteria

- User can upload a custom image.
- User can upload a custom GIF.
- GIF animation plays.
- Scale and opacity can be adjusted.
- Custom pet persists after restart.
- Reset to default works.
- Invalid files do not crash the app.

---

# Phase 5: Pet Interaction Polish

## Goal

Make the pet feel alive.

## Tasks

1. Add pet statuses:

```text
idle
thinking
working
success
failed
sleeping
```

2. Add status-specific speech bubble text.
3. Add simple idle animation if using GIF or frame-based image set.
4. Add drag-to-move.
5. Save pet position.
6. Add always-on-top toggle.
7. Add right-click menu.

## Acceptance Criteria

- Pet can be moved and position persists.
- Pet status changes during task execution.
- Pet can show short speech bubble.
- Right-click menu opens Pet / Chat / Settings / Exit.
- Always-on-top can be toggled.

---

# Phase 6: History Drawer

## Goal

Make history useful without making the UI heavy.

## Tasks

1. Remove permanent History sidebar.
2. Add collapsible HistoryDrawer in ChatPanel.
3. Render history as task/chat cards instead of plain text list.
4. Add search/filter later if needed.
5. Move delete action into item menu or drawer footer.

## Acceptance Criteria

- History is hidden by default.
- User can open history manually.
- History items are visually clean.
- Delete is no longer a giant always-visible red button.

---

## 9. Data Models

## 9.1 PetConfig

```python
from dataclasses import dataclass

@dataclass
class PetPosition:
    x: int
    y: int

@dataclass
class PetConfig:
    asset_path: str | None
    asset_type: str  # "default" | "image" | "gif"
    scale: float
    opacity: float
    position: PetPosition
    always_on_top: bool
    use_default_asset: bool
```

## 9.2 TaskCardModel

```python
from dataclasses import dataclass, field
from typing import Literal

TaskStatus = Literal["pending", "running", "success", "warning", "failed"]

@dataclass
class TaskStep:
    text: str
    status: TaskStatus

@dataclass
class TaskCardModel:
    title: str
    status: TaskStatus
    steps: list[TaskStep] = field(default_factory=list)
    short_result: str = ""
    details: str = ""
    exp_reward: int = 0
```

---

## 10. PySide6 Implementation Notes

## 10.1 Transparent Pet Window

Use:

```python
self.setWindowFlags(
    Qt.WindowType.FramelessWindowHint |
    Qt.WindowType.Tool |
    Qt.WindowType.WindowStaysOnTopHint
)
self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
```

## 10.2 Static Image

Use:

```python
pixmap = QPixmap(path)
label.setPixmap(
    pixmap.scaled(
        target_width,
        target_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )
)
```

## 10.3 GIF

Use:

```python
movie = QMovie(path)
label.setMovie(movie)
movie.start()
```

For scale control, either:

- set scaled size on QMovie, or
- update label size based on scale.

## 10.4 File Upload

Use:

```python
QFileDialog.getOpenFileName(
    self,
    "选择宠物图片或 GIF",
    "",
    "Pet Assets (*.png *.jpg *.jpeg *.webp *.gif)"
)
```

---

## 11. Settings Persistence

Implement a simple JSON settings service first.

Suggested file:

```text
data/settings/ui_settings.json
```

Required methods:

```text
SettingsService.load_ui_settings()
SettingsService.save_ui_settings(settings)
SettingsService.get_pet_config()
SettingsService.update_pet_config(config)
```

Rules:

- If settings file does not exist, create default settings.
- If JSON is invalid, back up corrupted file and recreate default settings.
- If pet asset path does not exist, fall back to default pet.
- Never crash on settings loading.

---

## 12. Pet Asset Storage

When uploading:

```text
source file:
C:/Users/user/Desktop/my_pet.gif

copy to:
data/user_assets/pets/pet_20260425_182300.gif
```

Reasons:

- User may delete or move the original file.
- App should own the uploaded copy.
- Future asset library can be built from this directory.

Recommended filename:

```text
pet_YYYYMMDD_HHMMSS.<ext>
```

---

## 13. Testing Checklist

## 13.1 Basic UI

- [ ] App starts normally.
- [ ] PetWidget appears.
- [ ] PetWidget can open ChatPanel.
- [ ] ChatPanel can close without closing app.
- [ ] QuickActionMenu opens and closes.

## 13.2 Pet Customization

- [ ] Upload PNG works.
- [ ] Upload JPG works.
- [ ] Upload WEBP works.
- [ ] Upload GIF works.
- [ ] GIF animates.
- [ ] Scale slider works.
- [ ] Opacity slider works.
- [ ] Reset to default works.
- [ ] Custom pet persists after restart.
- [ ] Invalid file is rejected.
- [ ] Missing asset path falls back to default pet.

## 13.3 Task Cards

- [ ] Running task card appears.
- [ ] Success task card appears.
- [ ] Failed task card appears.
- [ ] Details are collapsed by default.
- [ ] EXP reward appears after success.

## 13.4 Regression

- [ ] Existing chat message sending still works.
- [ ] Existing Agent backend still works.
- [ ] Existing browser-control task still works.
- [ ] No crash when closing panels.
- [ ] No crash when repeatedly opening/closing ChatPanel.

---

## 14. Opencode Execution Rules

When implementing this plan:

1. First inspect the existing UI files and summarize the current structure.
2. Do not rewrite the entire app.
3. Make the smallest viable changes per phase.
4. Preserve existing Agent/backend logic.
5. Prefer extracting components over replacing everything.
6. Add fallback behavior for every file/settings operation.
7. Verify each phase before moving to the next.
8. If current project structure differs from this plan, adapt the file names but keep the component boundaries.
9. Avoid adding heavy UI frameworks.
10. Keep PySide6 as the main UI stack unless the project already uses another stack.

---

## 15. First Milestone

The first milestone should be small and verifiable:

```text
Milestone 1:
- PetWidget extracted.
- ChatPanel can be opened from PetWidget.
- History sidebar hidden by default.
- Pet right-click menu includes:
  - Open Chat
  - Pet Settings
  - Exit
- PetSettingsPanel has placeholder UI but does not need upload logic yet.
```

After Milestone 1 is stable, continue to Pet Customization and TaskCardPanel.

---

## 16. Final Target Experience

Default:

```text
Desktop shows only Lobuddy pet.
Pet has small Lv/EXP bar.
Pet occasionally speaks with short bubble.
```

When user clicks pet:

```text
Small quick menu appears.
User can open chat, task panel, pet settings, or app settings.
```

When user gives a task:

```text
Pet enters working state.
Task card appears.
Long logs are hidden.
Success gives EXP.
Pet reacts emotionally.
```

When user wants custom pet:

```text
Open Pet Settings.
Upload image or GIF.
Preview immediately.
Adjust scale and opacity.
Save.
The custom pet becomes the desktop pet.
```

The final product should feel like:

> A desktop pet that can help with real Agent tasks, not a normal chat app with a pet sticker.
