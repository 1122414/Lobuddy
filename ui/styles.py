"""Centralized QSS styles for Lobuddy UI widgets."""

PET_LEVEL_LABEL = "color: #1F2937; font-size: 10px; font-weight: bold;"
PET_EXP_BAR = """
    QProgressBar {
        border: 1px solid #F3D9B1;
        border-radius: 6px;
        background-color: #FFF7ED;
    }
    QProgressBar::chunk {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #F97316, stop:1 #FB923C);
        border-radius: 5px;
    }
"""
PET_TRANSPARENT = "background: transparent; border: none;"
PET_STATUS_LABEL = "color: #F97316; font-size: 11px; font-weight: bold; background: rgba(255,247,237,0.9); padding: 2px 8px; border-radius: 8px;"

TASKPANEL_TRANSPARENT = "background: transparent;"
TASKPANEL_CONTAINER = """
    QWidget#container {
        background-color: #FFFFFF;
        border-radius: 20px;
        border: 1px solid #F3D9B1;
    }
"""
TASKPANEL_HEADER = "background-color: #F97316; border-top-left-radius: 20px; border-top-right-radius: 20px;"
TASKPANEL_TITLE = "color: white;"
TASKPANEL_CLOSE_BTN = (
    "background: rgba(255,255,255,0.3); color: white; border: none; "
    "border-radius: 13px; font-size: 14px; font-weight: bold;"
)
TASKPANEL_HISTORY_BTN = (
    "QPushButton { background: rgba(255,255,255,0.25); color: white; border: none; "
    "border-radius: 13px; font-size: 14px; } "
    "QPushButton:hover { background: rgba(255,255,255,0.4); }"
)
TASKPANEL_NEW_CHAT_BTN = (
    "QPushButton { background: rgba(255,255,255,0.25); color: white; border: none; "
    "border-radius: 13px; font-size: 14px; font-weight: bold; } "
    "QPushButton:hover { background: rgba(255,255,255,0.4); }"
)
TASKPANEL_SCROLL = (
    "QScrollArea { border: none; background: #FFF7ED; } "
    "QScrollBar:vertical { width: 8px; background: transparent; } "
    "QScrollBar::handle:vertical { background: #F3D9B1; border-radius: 4px; min-height: 30px; }"
)
TASKPANEL_CHAT_BG = "background: #FFF7ED;"
TASKPANEL_INPUT_CONTAINER = "background: white; border-bottom-left-radius: 20px; border-bottom-right-radius: 20px;"
TASKPANEL_IMAGE_PREVIEW = "background: #FFF7ED; border-radius: 8px;"
TASKPANEL_IMAGE_BTN = (
    "QPushButton { background: #FFF7ED; border: 1px solid #F3D9B1; border-radius: 18px; font-size: 16px; } "
    "QPushButton:hover { background: #FDE68A; }"
)
TASKPANEL_INPUT = (
    "QLineEdit { background: #FFF7ED; border: 1px solid #F3D9B1; border-radius: 20px; "
    "padding: 8px 16px; font-size: 13px; color: #1F2937; } "
    "QLineEdit:focus { background: #FFFFFF; border-color: #F97316; }"
)
TASKPANEL_SEND_BTN = (
    "QPushButton { background: #F97316; color: white; border: none; border-radius: 18px; "
    "font-size: 13px; font-weight: bold; } "
    "QPushButton:hover { background: #EA580C; } "
    "QPushButton:pressed { background: #C2410C; }"
)
TASKPANEL_USER_MSG = (
    "QLabel { background-color: #F97316; color: white; padding: 10px 14px; "
    "border-radius: 18px; border-bottom-right-radius: 4px; }"
)
TASKPANEL_BOT_MSG = (
    "QLabel { background-color: #FFFFFF; color: #1F2937; padding: 10px 14px; "
    "border-radius: 18px; border-bottom-left-radius: 4px; "
    "border: 1px solid #F3D9B1; }"
)
TASKPANEL_HTML_WRAPPER = 'font-family: "Microsoft YaHei UI", "Segoe UI", Arial, sans-serif; font-size: 13px; line-height: 1.6; color: #1F2937;'

QUICK_MENU_BG = "background: transparent; border: none;"
QUICK_MENU_BTN = (
    "QPushButton { background: #FFFFFF; border: 1px solid #F3D9B1; border-radius: 20px; "
    "font-size: 16px; } "
    "QPushButton:hover { background: #FFF7ED; border-color: #F97316; }"
)
QUICK_MENU_BTN_CLOSE = (
    "QPushButton { background: #FEE2E2; border: 1px solid #FECACA; border-radius: 20px; "
    "font-size: 14px; color: #EF4444; } "
    "QPushButton:hover { background: #FECACA; }"
)

TASKCARD_BG = (
    "background: #FFFFFF; border: 1px solid #F3D9B1; border-radius: 16px;"
)
TASKCARD_TITLE = "color: #1F2937; font-size: 14px; font-weight: bold;"
TASKCARD_STATUS = "color: #F97316; font-size: 13px; font-weight: bold;"
TASKCARD_CLOSE_BTN = (
    "background: transparent; color: #6B7280; border: none; "
    "border-radius: 11px; font-size: 12px; font-weight: bold;"
)
TASKCARD_ACTION_BTN = (
    "QPushButton { background: #FFF7ED; color: #1F2937; border: 1px solid #F3D9B1; "
    "border-radius: 8px; padding: 6px 12px; font-size: 12px; } "
    "QPushButton:hover { background: #FDE68A; }"
)

PET_SETTINGS_PREVIEW = (
    "background: #FFF7ED; border: 1px solid #F3D9B1; border-radius: 16px;"
)
