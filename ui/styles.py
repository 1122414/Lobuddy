"""Centralized QSS styles for Lobuddy UI widgets."""

# PetWindow styles
PET_LEVEL_LABEL = "color: white; font-size: 10px; font-weight: bold;"
PET_EXP_BAR = """
    QProgressBar {
        border: 1px solid #555;
        border-radius: 6px;
        background-color: #2a2a2a;
    }
    QProgressBar::chunk {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #4a9eff, stop:1 #7ec8ff);
        border-radius: 5px;
    }
"""
PET_TRANSPARENT = "background: transparent; border: none;"

# TaskPanel styles
TASKPANEL_TRANSPARENT = "background: transparent;"
TASKPANEL_CONTAINER = """
    QWidget#container {
        background-color: #ffffff;
        border-radius: 16px;
        border: none;
    }
"""
TASKPANEL_SIDEBAR = "background-color: #f5f5f5; border-top-left-radius: 16px; border-bottom-left-radius: 16px;"
TASKPANEL_NEW_CHAT_BTN = (
    "background: #4CAF50; color: white; border: none; border-radius: 8px; "
    "padding: 10px; font-size: 13px; font-weight: bold;"
)
TASKPANEL_HISTORY_LABEL = "color: #666; margin-top: 10px;"
TASKPANEL_SESSION_LIST = """
    QListWidget { background: transparent; border: none; outline: none; }
    QListWidget::item { background: transparent; padding: 8px; border-radius: 6px; margin: 2px 0; }
    QListWidget::item:selected { background: #4CAF50; color: white; }
    QListWidget::item:hover { background: #e0e0e0; }
    QListWidget::item:selected:hover { background: #45a049; }
"""
TASKPANEL_DELETE_BTN = (
    "background: #f44336; color: white; border: none; border-radius: 6px; "
    "padding: 8px; font-size: 12px;"
)
TASKPANEL_HEADER = "background-color: #4CAF50; border-top-right-radius: 16px;"
TASKPANEL_TITLE = "color: white;"
TASKPANEL_CLOSE_BTN = (
    "background: rgba(255,255,255,0.25); color: white; border: none; "
    "border-radius: 13px; font-size: 14px; font-weight: bold;"
)
TASKPANEL_SCROLL = (
    "QScrollArea { border: none; background: #f8f9fa; } "
    "QScrollBar:vertical { width: 8px; background: transparent; } "
    "QScrollBar::handle:vertical { background: #c1c1c1; border-radius: 4px; min-height: 30px; }"
)
TASKPANEL_CHAT_BG = "background: #f8f9fa;"
TASKPANEL_INPUT_CONTAINER = "background: white; border-bottom-right-radius: 16px;"
TASKPANEL_IMAGE_PREVIEW = "background: #f0f0f0; border-radius: 8px;"
TASKPANEL_IMAGE_BTN = (
    "QPushButton { background: #f0f0f0; border: none; border-radius: 18px; font-size: 16px; } "
    "QPushButton:hover { background: #e0e0e0; }"
)
TASKPANEL_INPUT = (
    "QLineEdit { background: #f0f0f0; border: none; border-radius: 20px; "
    "padding: 8px 16px; font-size: 13px; color: #333; } "
    "QLineEdit:focus { background: #e8e8e8; }"
)
TASKPANEL_SEND_BTN = (
    "QPushButton { background: #4CAF50; color: white; border: none; border-radius: 18px; "
    "font-size: 13px; font-weight: bold; } "
    "QPushButton:hover { background: #45a049; } "
    "QPushButton:pressed { background: #3d8b40; }"
)
TASKPANEL_USER_MSG = (
    "QLabel { background-color: #4CAF50; color: white; padding: 10px 14px; "
    "border-radius: 18px; border-bottom-right-radius: 4px; }"
)
TASKPANEL_BOT_MSG = (
    "QLabel { background-color: #e9ecef; color: #333; padding: 10px 14px; "
    "border-radius: 18px; border-bottom-left-radius: 4px; }"
)
TASKPANEL_IMG_LABEL = "background: #e0e0e0; border-radius: 8px;"
TASKPANEL_HTML_WRAPPER = 'font-family: "Microsoft YaHei"; font-size: 13px; line-height: 1.6; color: #333;'
