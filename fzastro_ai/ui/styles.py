def get_main_stylesheet():
    """Return the main application stylesheet."""
    return r"""
            * {
                font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
                outline: none;
            }

            QMainWindow,
            QWidget#main {
                background: #0b0d10;
                color: #e8ebef;
            }

            QLabel,
            QCheckBox,
            QRadioButton {
                color: #e8ebef;
            }

            QWidget#sidebar,
            QWidget#historyPanel {
                background: #101318;
            }

            QWidget#sidebar {
                border-right: 1px solid #242a32;
            }

            QWidget#historyPanel {
                border-left: 1px solid #242a32;
            }

            QFrame#sidebarHeader,
            QFrame#historyHeader {
                background: #14181e;
                border-bottom: 1px solid #242a32;
            }

            QLabel#sidebarBrandMark,
            QLabel#brandMark {
                background: #1d232b;
                color: #f5f7fa;
                border: 1px solid #343c47;
                border-radius: 10px;
                font-size: 12px;
                font-weight: 800;
            }

            QLabel#sidebarTitle,
            QLabel#historyTitle {
                color: #f4f6f8;
                font-size: 18px;
                font-weight: 700;
            }

            QLabel#sidebarSubtitle,
            QLabel#historySubtitle,
            QLabel#sidebarFooter {
                color: #7f8996;
                font-size: 11px;
            }

            QLabel#sidebarFooter {
                background: #0e1115;
                border-top: 1px solid #20262d;
                padding: 10px;
            }

            QScrollArea#sidebarConfigScroll,
            QScrollArea#historyScroll,
            QScrollArea#chatScroll,
            QScrollArea#attachmentScroll {
                background: transparent;
                border: none;
            }

            QWidget#sidebarContent,
            QWidget#historyListSurface,
            QWidget#chatContainer,
            QScrollArea#sidebarConfigScroll QWidget,
            QScrollArea#historyScroll QWidget,
            QScrollArea#chatScroll QWidget,
            QScrollArea#attachmentScroll QWidget {
                background: transparent;
            }

            QFrame#settingsCard,
            QFrame#historyActions {
                background: #15191f;
                border: 1px solid #252c35;
                border-radius: 12px;
            }

            QLabel#settingsCardTitle {
                color: #edf0f3;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#ninaSectionTitle {
                color: #ffcc66;
                font-size: 12px;
                font-weight: 850;
                letter-spacing: 0.8px;
                text-transform: uppercase;
            }

            QToolButton#ninaDrawerHeader {
                background: #1b222b;
                color: #ffcc66;
                border: 1px solid #3c4652;
                border-radius: 8px;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 850;
                letter-spacing: 0.7px;
                text-align: left;
            }

            QLabel#settingsCardSubtitle,
            QLabel#webArticleBody {
                color: #8e98a6;
                font-size: 11px;
            }

            QFrame#inlinePanel {
                background: #0d1218;
                border: 1px solid #243142;
                border-radius: 10px;
            }

            QPlainTextEdit#embeddedClaudeTerminal {
                background: #05080d;
                color: #d6e4f0;
                border: 1px solid #26364a;
                border-radius: 10px;
                padding: 10px 12px;
                font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
                font-size: 12px;
                selection-background-color: #31587d;
                selection-color: #ffffff;
            }

            QPlainTextEdit#embeddedClaudeTerminal:focus {
                border-color: #58a6ff;
                background: #070b12;
            }


            QLabel#documentKnowledgeStatusLabel {
                background: #0f141a;
                color: #a9bdd4;
                border: 1px solid #2b3744;
                border-radius: 8px;
                padding: 7px 9px;
                font-size: 11px;
                font-weight: 600;
            }

            QLabel#fieldCaption,
            QLabel#toolbarCaption {
                color: #76808d;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.7px;
            }

            QLabel#calibrationStatusLabel {
                color: #a9c3e5;
                font-size: 11px;
                font-weight: 650;
            }

            QFrame#topBar,
            QFrame#runtimeBar,
            QFrame#quickActionsBar,
            QFrame#skillsDrawer,
            QFrame#composerShell,
            QFrame#thoughtPanel,
            QFrame#chatSurface {
                background: #11151a;
                border: 1px solid #242b33;
                border-radius: 14px;
            }

            QFrame#chatSurface {
                background: #0d1014;
                border: none;
                border-radius: 0;
            }


            QTabWidget#workspaceTabs {
                background: transparent;
                border: none;
                padding: 0;
            }

            QTabWidget#workspaceTabs::pane {
                background: #0b0f14;
                border: 1px solid #30363d;
                border-radius: 14px;
                top: 0px;
            }

            QTabWidget#workspaceTabs::tab-bar {
                left: 0px;
            }

            QTabWidget#workspaceTabs QTabBar#workspaceTabBar {
                background: transparent;
                border: none;
            }

            QTabWidget#workspaceTabs QTabBar::tab {
                background: #0d1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 19px;
                min-width: 112px;
                min-height: 36px;
                padding: 6px 8px 6px 18px;
                margin: 0 9px 8px 0;
                font-size: 11px;
                font-weight: 800;
            }

            QTabWidget#workspaceTabs QTabBar::tab:selected {
                background: #111827;
                color: #f0f6fc;
                border: 1px solid #58a6ff;
            }

            QTabWidget#workspaceTabs QTabBar::tab:hover:!selected {
                background: #161b22;
                color: #f0f6fc;
                border: 1px solid #3d444d;
            }

            QPushButton#workspaceAppsButton {
                background: #132033;
                color: #e9f2fb;
                border: 1px solid #38506b;
                border-radius: 8px;
                padding: 4px 12px;
                margin: 0 8px 2px 8px;
                font-size: 11px;
                font-weight: 800;
                min-height: 24px;
            }

            QPushButton#workspaceAppsButton:hover {
                background: #18304f;
                border-color: #5f7fa4;
            }

            QPushButton#workspaceAppsButton:pressed,
            QPushButton#workspaceAppsButton:checked {
                background: #1d3b63;
                border-color: #81a6cf;
            }


            QPushButton#workspaceTabCloseButton {
                background: transparent;
                color: #8b949e;
                border: 1px solid transparent;
                border-radius: 10px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
                padding: 0px;
                margin: 0px 2px 0px 5px;
                font-size: 17px;
                font-weight: 500;
            }

            QPushButton#workspaceTabCloseButton:hover {
                background: #21262d;
                color: #f0f6fc;
                border: 1px solid #3d444d;
            }

            QPushButton#workspaceTabCloseButton:pressed {
                background: #3b1f2b;
                color: #ffd8df;
                border: 1px solid #ff7b8a;
            }


            QFrame#skillsDrawer {
                background: #10161d;
                border-color: #2a3540;
            }

            QWidget#emptyStateHolder {
                background: transparent;
            }

            QFrame#emptyState {
                background: #11161b;
                border: 1px solid #252d36;
                border-radius: 16px;
            }

            QLabel#emptyStateMark {
                background: #1c232b;
                color: #f4f6f8;
                border: 1px solid #3b4652;
                border-radius: 13px;
                font-size: 13px;
                font-weight: 800;
            }

            QLabel#emptyStateTitle {
                color: #f0f3f6;
                font-size: 20px;
                font-weight: 750;
            }

            QLabel#emptyStateSubtitle {
                color: #8893a0;
                font-size: 12px;
            }

            QLabel#emptyStateHint {
                background: #181e25;
                color: #8893a0;
                border: 1px solid #2b343e;
                border-radius: 8px;
                padding: 5px 8px;
                font-size: 10px;
            }

            QLabel#header {
                color: #f6f7f9;
                font-size: 17px;
                font-weight: 800;
                letter-spacing: 0.4px;
            }

            QLabel#subtitle {
                color: #7d8794;
                font-size: 10px;
            }

            QFrame#toolbarDivider {
                background: #2b323b;
                border: none;
            }

            QLabel#workspaceContextLabel {
                color: #8f99a7;
                font-size: 11px;
                padding: 0 4px;
            }

            QComboBox#quickModelBox,
            QComboBox#quickWebBox {
                min-height: 0;
                padding: 0 28px 0 10px;
                border-radius: 9px;
                font-size: 11px;
                font-weight: 600;
            }

            QComboBox#quickModelBox {
                color: #b8c7d9;
            }

            QComboBox#quickWebBox {
                color: #d3d9e2;
            }

            QPushButton,
            QToolButton#openclaudeMenuButton {
                background: #1a1f26;
                color: #e6e9ed;
                border: 1px solid #303842;
                border-radius: 9px;
                min-height: 30px;
                padding: 0 11px;
                font-size: 12px;
                font-weight: 650;
            }

            QPushButton:hover,
            QToolButton#openclaudeMenuButton:hover {
                background: #20262e;
                border-color: #414b57;
                color: #ffffff;
            }

            QPushButton:pressed,
            QToolButton#openclaudeMenuButton:pressed,
            QToolButton#openclaudeMenuButton:checked {
                background: #15191f;
                border-color: #566271;
            }

            QPushButton:disabled,
            QToolButton#openclaudeMenuButton:disabled {
                background: #13171c;
                color: #59626d;
                border-color: #222831;
            }

            QToolButton#openclaudeMenuButton {
                background: #121a24;
                border-color: #33445a;
                border-radius: 10px;
                min-width: 92px;
                min-height: 32px;
                padding: 0 13px;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.2px;
            }

            QToolButton#openclaudeMenuButton:hover {
                background: #1b2838;
                border-color: #5f82aa;
            }

            QToolButton#openclaudeMenuButton::menu-indicator {
                image: none;
                width: 0px;
            }

            QMenu {
                background: #111820;
                color: #e6edf5;
                border: 1px solid #303842;
                border-radius: 10px;
                padding: 6px;
            }

            QMenu::item {
                min-height: 24px;
                padding: 5px 18px 5px 10px;
                border-radius: 7px;
                font-size: 11px;
            }

            QMenu::item:selected {
                background: #1d2b3b;
                color: #ffffff;
            }

            QMenu::separator {
                height: 1px;
                background: #2b333d;
                margin: 6px 4px;
            }

            QPushButton#sidebarToggle,
            QPushButton#historyToggle,
            QPushButton#helpButton,
            QPushButton#diagnosticsButton,
            QPushButton#calibrationProfileButton,
            QPushButton#quickRefreshModelsButton {
                padding: 0;
                min-height: 0;
                font-size: 18px;
                border-radius: 10px;
            }

            QPushButton#sidebarToggle:checked,
            QPushButton#historyToggle:checked,
            QPushButton#composerToolButton:checked,
            QPushButton#calibrationProfileButton:checked {
                background: #222a34;
                border-color: #607b9d;
                color: #f7f9fb;
            }

            QPushButton#dailyNewsButton,
            QPushButton#stockPriceButton {
                min-height: 0;
                padding: 0 10px;
            }

            QPushButton#stockPriceButton {
                font-size: 11px;
                font-weight: 750;
            }

            QPushButton#quickRefreshModelsButton {
                font-size: 17px;
                font-weight: 800;
            }

            QPushButton#panelCloseButton {
                padding: 0;
                min-height: 0;
                border-radius: 8px;
                font-size: 18px;
            }

            QPushButton#primaryActionButton {
                background: #222a34;
                border-color: #526983;
            }

            QPushButton#workflowStepButton {
                background: #1d2632;
                border: 1px solid #536f8c;
                border-radius: 14px;
                padding: 12px 14px;
                min-height: 64px;
                font-size: 13px;
                font-weight: 900;
                letter-spacing: 0.6px;
            }

            QPushButton#workflowStepButton:hover {
                background: #243246;
                border-color: #7aa0c8;
            }

            QPushButton#workflowToolButton {
                background: #171d25;
                border: 1px solid #3b4b60;
                border-radius: 12px;
                padding: 9px 12px;
                font-size: 12px;
                font-weight: 850;
                letter-spacing: 0.4px;
            }

            QPushButton#workflowToolButton:hover {
                background: #1f2834;
                border-color: #60768f;
            }

            QPushButton#dangerActionButton {
                background: #22181b;
                border: 1px solid #63373e;
                border-radius: 12px;
                color: #efcfd3;
                padding: 9px 12px;
                font-size: 12px;
                font-weight: 850;
                letter-spacing: 0.4px;
            }

            QPushButton#dangerActionButton:hover {
                background: #2d1e22;
                border-color: #86515a;
            }

            QLabel#workflowStatusStrip {
                background: #10151c;
                color: #a9bdd4;
                border: 1px solid #263342;
                border-radius: 10px;
                padding: 8px 10px;
                font-size: 11px;
            }

            QLabel#workflowHintText {
                color: #8490a0;
                font-size: 11px;
                padding: 2px 4px;
            }

            QLabel#selectionPill {
                background: #1a2027;
                color: #9ea8b5;
                border: 1px solid #303842;
                border-radius: 9px;
                min-width: 64px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 650;
            }

            QFrame#benchmarkControlsCard,
            QFrame#benchmarkTelemetryCard,
            QFrame#benchmarkSetupCard {
                background: #11161c;
                border: 1px solid #26303a;
                border-radius: 13px;
            }

            QComboBox#benchmarkModelBox,
            QComboBox#benchmarkComboBox,
            QSpinBox#benchmarkSpinBox,
            QDoubleSpinBox#benchmarkSpinBox,
            QLineEdit#benchmarkLineEdit {
                background: #0f141a;
                color: #e8ebef;
                border: 1px solid #2d3742;
                border-radius: 9px;
                padding: 8px 10px;
                min-height: 20px;
                selection-background-color: #3d5f86;
                selection-color: #ffffff;
                font-size: 12px;
            }

            QComboBox#benchmarkModelBox:focus,
            QComboBox#benchmarkComboBox:focus,
            QSpinBox#benchmarkSpinBox:focus,
            QDoubleSpinBox#benchmarkSpinBox:focus,
            QLineEdit#benchmarkLineEdit:focus {
                border-color: #607b9d;
                background: #111922;
            }

            QProgressBar#benchmarkProgressBar {
                background: #0d1116;
                color: #b7c2cf;
                border: 1px solid #26313d;
                border-radius: 7px;
                min-height: 14px;
                max-height: 14px;
                text-align: center;
                font-size: 10px;
                font-weight: 650;
            }

            QProgressBar#benchmarkProgressBar::chunk {
                background: #607b9d;
                border-radius: 6px;
            }

            QSplitter#benchmarkRunSetupSplitter::handle,
            QSplitter#benchmarkDashboardSplitter::handle {
                background: #26313d;
                border-radius: 4px;
            }

            QListWidget#benchmarkPromptQueue {
                background: #0f1318;
                color: #dfe5ec;
                border: 1px solid #29313b;
                border-radius: 10px;
                padding: 6px;
                selection-background-color: #23364a;
                selection-color: #ffffff;
                font-size: 12px;
            }

            QTextBrowser#benchmarkSetupBrowser {
                background: #0f1318;
                color: #e8edf2;
                border: 1px solid #29313b;
                border-radius: 10px;
                padding: 10px;
                font-size: 12px;
                line-height: 1.35;
            }

            QTableWidget#benchmarkTable {
                background: #0f1318;
                color: #dfe5ec;
                border: 1px solid #29313b;
                border-radius: 11px;
                gridline-color: #29313b;
                alternate-background-color: #111820;
                selection-background-color: #23364a;
                selection-color: #ffffff;
            }

            QHeaderView::section {
                background: #141a21;
                color: #aab4c1;
                border: none;
                border-bottom: 1px solid #29313b;
                padding: 7px 6px;
                font-size: 10px;
                font-weight: 750;
            }

            QLineEdit,
            QComboBox,
            QSpinBox,
            QDoubleSpinBox,
            QTextEdit#systemPromptBox,
            QListWidget,
            QTextEdit#memorySearchPreview {
                background: #0f1318;
                color: #e8ebef;
                border: 1px solid #2b333d;
                border-radius: 8px;
                padding: 8px 9px;
                selection-background-color: #3d5f86;
                selection-color: #ffffff;
                font-size: 12px;
            }

            QLineEdit:focus,
            QComboBox:focus,
            QSpinBox:focus,
            QDoubleSpinBox:focus,
            QTextEdit#systemPromptBox:focus,
            QListWidget:focus {
                border-color: #607b9d;
                background: #11161c;
            }

            QComboBox::drop-down {
                width: 24px;
                border: none;
            }

            QComboBox QAbstractItemView {
                background: #151a20;
                color: #e8ebef;
                border: 1px solid #343d48;
                selection-background-color: #27313d;
                padding: 4px;
            }

            QFrame#thoughtPanel {
                background: #10151b;
                border-color: #293746;
            }

            QLabel#thoughtIndicator {
                color: #7398c4;
                font-size: 9px;
            }

            QLabel#thoughtTitle {
                color: #a9c3e5;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.8px;
            }

            QLabel#thoughtHint {
                color: #657180;
                font-size: 10px;
            }

            QTextBrowser#thoughtBox {
                background: transparent;
                border: none;
                color: #aeb7c2;
                padding: 0;
                font-size: 11px;
                selection-background-color: #344e69;
            }

            QWidget#messageWidget {
                background: transparent;
            }

            QWidget#messageContentContainer {
                background: #13171c;
                border: 1px solid #252c34;
                border-radius: 13px;
            }

            QWidget#messageContentContainer[messageKind="assistant"] {
                background: #13171c;
                border-color: #252c34;
            }

            QWidget#messageContentContainer[messageKind="user"] {
                background: #17191d;
                border-color: #343941;
            }

            QWidget#messageContentContainer[messageKind="news"] {
                background: #111820;
                border-color: #2a3a4b;
            }

            QWidget#messageContentContainer[messageKind="stock"] {
                background: transparent;
                border: none;
            }

            QWidget#messageContentContainer[messageKind="typing"] {
                background: transparent;
                border: none;
            }

            QLabel#messageRoleBadge {
                background: #1a2027;
                color: #aeb7c2;
                border: 1px solid #303842;
                border-radius: 7px;
                font-size: 9px;
                font-weight: 800;
            }

            QLabel#messageRoleBadge[roleType="user"] {
                background: #211b1d;
                color: #d9b6bb;
                border-color: #49343a;
            }

            QLabel#messageRoleBadge[roleType="news"] {
                background: #142231;
                color: #a8c9ec;
                border-color: #35516d;
            }

            QPushButton#messageOptionsButton {
                background: transparent;
                color: #6f7884;
                border: 1px solid transparent;
                border-radius: 7px;
                padding: 0;
                min-height: 0;
                font-size: 18px;
            }

            QPushButton#messageOptionsButton:hover {
                background: #1d232a;
                color: #ffffff;
                border-color: #343c46;
            }

            QLabel#messageText,
            QTextBrowser#messageText {
                background: transparent;
                color: #e5e8ec;
                border: none;
                font-size: 14px;
                selection-background-color: #3c5e82;
                selection-color: #ffffff;
            }

            QLabel#messageText[messageMode="user"],
            QTextBrowser#messageText[messageMode="user"] {
                color: #eef0f2;
            }

            QWidget#sourceHeader,
            QWidget#newsBriefHeader,
            QWidget#replyTimerFooter {
                background: transparent;
                border: none;
            }

            QWidget#sourceHeader {
                border-bottom: 1px solid #252c34;
            }

            QLabel#sourceHeaderLabel {
                color: #768291;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.4px;
            }

            QLabel#sourceChip {
                background: #1b222b;
                color: #bac4cf;
                border: 1px solid #313a45;
                border-radius: 8px;
                padding: 2px 7px;
                font-size: 10px;
                font-weight: 750;
            }

            QLabel#sourceChip[sourceType="llm"] {
                background: #1d2028;
                color: #c7cbd3;
                border-color: #383e4a;
            }

            QLabel#sourceChip[sourceType="web_search"],
            QLabel#sourceChip[sourceType="web_page"],
            QLabel#sourceChip[sourceType="web_screenshot"],
            QLabel#sourceChip[sourceType="web_image"],
            QLabel#sourceChip[sourceType="web_news"] {
                background: #132432;
                color: #a9d4f4;
                border-color: #2c5270;
            }

            QLabel#sourceChip[sourceType="document_knowledge"] {
                background: #1d261b;
                color: #b8d8ad;
                border-color: #3c5638;
            }

            QLabel#sourceChip[sourceType="persistent_memory"] {
                background: #241f31;
                color: #cdbcf0;
                border-color: #4d4168;
            }

            QLabel#sourceChip[sourceType="market_data"] {
                background: #2b2414;
                color: #e1c689;
                border-color: #5d4a21;
            }

            QLabel#sourceChip[sourceType="attachments"],
            QLabel#sourceChip[sourceType="vision"],
            QLabel#sourceChip[sourceType="app"] {
                background: #261f21;
                color: #d8b4bd;
                border-color: #513941;
            }

            QWidget#newsBriefHeader {
                border-bottom: 1px solid #2a3a4b;
            }

            QWidget#replyTimerFooter {
                border-top: 1px solid #252c34;
            }

            QLabel#newsBriefTitle {
                color: #b8d2ee;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.9px;
            }

            QLabel#newsBriefMeta,
            QLabel#replyTimerLabel,
            QLabel#fileLine {
                color: #75808d;
                font-size: 10px;
            }

            QFrame#composerShell {
                background: #11151a;
            }

            QTextEdit#inputBox {
                background: #0d1115;
                border: 1px solid #2c343e;
                color: #f0f2f4;
                border-radius: 13px;
                padding: 8px 12px;
                font-size: 14px;
                selection-background-color: #3d5f86;
                selection-color: #ffffff;
            }

            QTextEdit#inputBox:focus {
                background: #0f1419;
                border-color: #607b9d;
            }

            QFrame#composerToolbar {
                background: transparent;
                border: none;
            }

            QLabel#composerToolsLabel {
                color: #707a87;
                font-size: 10px;
                font-weight: 750;
                letter-spacing: 0.7px;
                padding: 0 4px 0 2px;
            }

            QPushButton#composerToolButton,
            QPushButton#newChatButton {
                background: #121820;
                color: #aeb8c3;
                border: 1px solid #2a333d;
                border-radius: 8px;
                min-height: 24px;
                max-height: 24px;
                padding: 0 9px;
                font-size: 10px;
                font-weight: 700;
            }

            QPushButton#composerToolButton:hover,
            QPushButton#newChatButton:hover {
                background: #17202a;
                color: #eef4fb;
                border-color: #526983;
            }

            QPushButton#composerToolButton:pressed,
            QPushButton#newChatButton:pressed {
                background: #0f141a;
                border-color: #607b9d;
            }

            QPushButton#composerToolButton:disabled,
            QPushButton#newChatButton:disabled {
                background: #11151a;
                color: #535d68;
                border-color: #20262e;
            }

            QPushButton#attachButton,
            QPushButton#voiceButton,
            QPushButton#sendButton,
            QPushButton#stopButton {
                padding: 0 16px;
                margin: 0;
                min-height: 48px;
                max-height: 48px;
                border-radius: 13px;
                font-size: 12px;
                font-weight: 750;
                letter-spacing: 0.2px;
            }

            QPushButton#attachButton {
                background: #0d1115;
                color: #bac3ce;
                border: 1px solid #2c343e;
            }

            QPushButton#attachButton:hover {
                background: #0f1419;
                color: #f1f4f7;
                border-color: #607b9d;
            }

            QPushButton#attachButton:pressed {
                background: #0a0e12;
                border-color: #536b88;
            }

            QPushButton#voiceButton {
                background: #0d1115;
                color: #f0f3f6;
                border: 1px solid #2c343e;
                min-width: 48px;
                max-width: 48px;
                padding: 0;
            }

            QPushButton#voiceButton:hover {
                background: #111922;
                border-color: #607b9d;
            }

            QPushButton#voiceButton:pressed {
                background: #0a0e12;
                border-color: #536b88;
            }

            QPushButton#voiceButton:checked {
                background: #351c22;
                border-color: #7a404b;
            }

            QPushButton#voiceButton:checked:hover {
                background: #46242c;
                border-color: #9b5260;
            }

            QPushButton#sendButton {
                background: #2d4967;
                color: #f7fbff;
                border: 1px solid #5f7fa3;
            }

            QPushButton#sendButton:hover {
                background: #365878;
                border-color: #7798bd;
            }

            QPushButton#sendButton:pressed {
                background: #243c56;
                border-color: #88a7c9;
            }

            QPushButton#stopButton {
                background: #351c22;
                color: #ffc3cb;
                border: 1px solid #7a404b;
            }

            QPushButton#stopButton:hover {
                background: #46242c;
                color: #ffe6ea;
                border-color: #9b5260;
            }

            QPushButton#stopButton:pressed {
                background: #2b171c;
                border-color: #b56573;
            }

            QPushButton#attachButton:disabled,
            QPushButton#sendButton:disabled,
            QPushButton#stopButton:disabled {
                background: #14181d;
                color: #59636e;
                border-color: #252c34;
            }

            QLabel#timeLabel,
            QLabel#gpuLabel,
            QLabel#systemLabel,
            QLabel#statsLabel {
                color: #707a87;
                font-size: 10px;
                padding: 0 3px;
            }

            QWidget#attachmentChip {
                background: #1b2128;
                border: 1px solid #313a45;
                border-radius: 11px;
            }

            QLabel#attachmentChipLabel {
                color: #d8dde3;
                font-size: 11px;
            }

            QPushButton#removeAttachmentButton {
                background: #2b333d;
                color: #dfe3e8;
                border: none;
                border-radius: 9px;
                padding: 0;
                min-height: 0;
                font-size: 13px;
            }

            QWidget#webArticleCard {
                background: #151a20;
                border: 1px solid #2b343f;
                border-radius: 11px;
            }

            QLabel#webArticleTitle {
                color: #eef1f4;
                font-size: 14px;
                font-weight: 700;
            }

            QLabel#webArticleSource {
                color: #91b6dd;
                font-size: 11px;
            }

            QWidget#codeBlockWidget {
                background: #0b0f13;
                border: 1px solid #28313a;
                border-radius: 11px;
            }

            QWidget#codeBlockHeader {
                background: #131920;
                border-bottom: 1px solid #28313a;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
            }

            QLabel#codeLanguageLabel {
                color: #aeb8c3;
                font-family: "Cascadia Code", Consolas, monospace;
                font-size: 11px;
            }

            QLabel#helpDialogTitle {
                color: #f2f5f8;
                font-size: 20px;
                font-weight: 800;
            }

            QLabel#helpDialogSubtitle {
                color: #9aa5b2;
                font-size: 12px;
            }

            QFrame#astroLookupHeaderCard,
            QFrame#astroLookupTopBarCard,
            QFrame#astroLookupSettingsCard,
            QFrame#astroLookupResultCard,
            QFrame#astroLookupImagePanel {
                background: #11161c;
                border: 1px solid #26303a;
                border-radius: 13px;
            }

            QFrame#astroLookupHeaderCard {
                background: #121820;
                border-color: #2f3b49;
            }

            QFrame#astroLookupTopBarCard {
                background: #10161d;
                border-color: #2b3744;
            }

            QPushButton#astroLookupToggleButton {
                background: #151d27;
                color: #cfe1f2;
                border: 1px solid #334254;
                border-radius: 9px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 750;
            }

            QPushButton#astroLookupToggleButton:hover {
                background: #1a2530;
                border-color: #4b6076;
            }

            QSplitter#astroLookupResultSplitter::handle {
                background: #202a35;
                border: 1px solid #2c3947;
                border-radius: 3px;
                margin: 2px 1px;
            }

            QSplitter#astroLookupResultSplitter::handle:hover {
                background: #334559;
            }

            QLabel#astroLookupSectionTitle {
                color: #eef3f8;
                font-size: 12px;
                font-weight: 800;
            }

            QLabel#astroLookupStatusLabel {
                color: #9fb8d4;
                font-size: 11px;
                font-weight: 700;
            }

            QLabel#astroLookupPill {
                background: #0e141a;
                color: #bdd3ea;
                border: 1px solid #2a3744;
                border-radius: 8px;
                padding: 4px 6px;
                font-size: 10px;
                font-weight: 650;
            }

            QLineEdit#astroLookupField,
            QComboBox#astroLookupCombo,
            QDoubleSpinBox#astroLookupSpin {
                background: #0f141a;
                color: #e8ebef;
                border: 1px solid #2d3742;
                border-radius: 9px;
                padding: 5px 8px;
                min-height: 18px;
                selection-background-color: #3d5f86;
                selection-color: #ffffff;
                font-size: 11px;
            }

            QLineEdit#astroLookupField:focus,
            QComboBox#astroLookupCombo:focus,
            QDoubleSpinBox#astroLookupSpin:focus {
                border-color: #5d7fa4;
                background: #121922;
            }

            QTextBrowser#astroLookupResultBrowser {
                background: #0f1318;
                color: #e8edf2;
                border: 1px solid #29313b;
                border-radius: 12px;
                padding: 5px;
                font-size: 10px;
            }

            QTabWidget#astroLookupDetailsTabs::pane {
                background: #0f1318;
                border: 1px solid #29313b;
                border-radius: 12px;
                top: -1px;
            }

            QTabWidget#astroLookupDetailsTabs QTabBar::tab {
                background: #101720;
                color: #9fb2c8;
                border: 1px solid #29313b;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 5px 9px;
                margin-right: 2px;
                font-size: 10px;
                font-weight: 750;
            }

            QTabWidget#astroLookupDetailsTabs QTabBar::tab:selected {
                background: #151f2b;
                color: #f2f7fc;
                border-color: #3a4959;
            }

            QLabel#astroLookupImageSetupStrip {
                background: #0e141a;
                color: #c2d6ea;
                border: 1px solid #2a3744;
                border-radius: 9px;
                padding: 4px 7px;
                font-size: 10px;
                font-weight: 700;
            }

            QLabel#astroLookupImagePreview {
                background: #0d1116;
                color: #8f9ba8;
                border: 1px solid #2b3540;
                border-radius: 12px;
                padding: 3px;
                font-size: 10px;
            }

            QLabel#targetPreviewMetaLabel {
                background: #0f151b;
                color: #bdd0e3;
                border: 1px solid #2b3540;
                border-radius: 9px;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 650;
            }

            QProgressBar#astroLookupProgress {
                background: #0d1116;
                border: 1px solid #26313d;
                border-radius: 7px;
                min-height: 9px;
                max-height: 9px;
            }

            QProgressBar#astroLookupProgress::chunk {
                background: #607b9d;
                border-radius: 6px;
            }

            QTableWidget#seeingForecastTable {
                background: #0f1318;
                color: #e8edf2;
                border: 1px solid #29313b;
                border-radius: 10px;
                gridline-color: #26313d;
                alternate-background-color: #121820;
                selection-background-color: #28435f;
                selection-color: #ffffff;
                font-size: 11px;
            }

            QTableWidget#seeingForecastTable::item {
                padding: 4px 6px;
                border: none;
            }

            QLabel#seeingSkyQualityCard,
            QLabel#seeingScoreCard {
                background: #101820;
                color: #e8edf2;
                border: 1px solid #2b3744;
                border-radius: 12px;
                padding: 8px 10px;
            }

            QLabel#seeingSkyQualityCard {
                background: #0f1f17;
                border-color: #24633a;
            }

            QScrollArea#seeingPlannerScroll {
                background: transparent;
                border: none;
            }

            QScrollArea#seeingPlannerScroll QWidget {
                background: transparent;
            }

            QWidget#seeingCloudTimeline,
            QWidget#seeing24HourGraph,
            QWidget#seeingNightPlanner {
                background: #0f1318;
                border: 1px solid #29313b;
                border-radius: 10px;
            }

            QHeaderView::section {
                background: #17202a;
                color: #eef3f8;
                border: none;
                border-right: 1px solid #293545;
                border-bottom: 1px solid #293545;
                padding: 5px 7px;
                font-size: 10px;
                font-weight: 800;
            }

            QTextBrowser#helpCheatSheetBrowser {
                background: #0f1318;
                color: #e8edf2;
                border: 1px solid #29313b;
                border-radius: 12px;
                padding: 14px;
                font-size: 13px;
                line-height: 1.45;
            }

            QTextBrowser#codeView {
                background: #0b0f13;
                color: #dde3ea;
                border: none;
                padding: 13px;
                font-family: "Cascadia Code", Consolas, monospace;
                font-size: 12px;
                selection-background-color: #304d6a;
            }

            QPushButton#codeCopyButton,
            QPushButton#codeRunButton {
                background: transparent;
                border: none;
                padding: 3px 7px;
                min-height: 0;
                font-size: 11px;
            }

            QPushButton#codeRunButton {
                color: #8fd0ff;
                font-weight: 750;
            }

            QPushButton#codeRunButton:hover {
                color: #ffffff;
                background: #172435;
                border-radius: 7px;
            }

            QLabel#imagePreview {
                background: #11161b;
                border: 1px solid #2c353f;
                border-radius: 9px;
                padding: 4px;
            }

            QFrame#historyItemCard {
                background: #11161b;
                border: 1px solid #27303a;
                border-radius: 10px;
            }

            QFrame#historyItemCard[selected="true"] {
                background: #131d27;
                border-color: #4c6f94;
            }

            QFrame#historyItemCard[pinned="true"] {
                border-color: #465361;
            }

            QPushButton#historySelectButton {
                background: #151a20;
                color: #b9c2cc;
                border: 1px solid #3a4551;
                border-radius: 8px;
                padding: 0 7px;
                text-align: center;
                font-size: 10px;
                font-weight: 750;
            }

            QPushButton#historySelectButton:hover {
                background: #1c222a;
                color: #ffffff;
                border-color: #607b9d;
            }

            QPushButton#historySelectButton:checked {
                background: #2d4967;
                color: #ffffff;
                border-color: #7798bd;
            }

            QPushButton#historySelectButton:disabled {
                background: #14181d;
                color: #59636e;
                border-color: #252c34;
            }

            QPushButton#historyButton {
                background: transparent;
                color: #eef1f4;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 0 8px;
                text-align: left;
                font-size: 12px;
                font-weight: 650;
            }

            QPushButton#historyActionButton,
            QPushButton#historyMoreButton {
                background: #151a20;
                color: #c7ced6;
                border: 1px solid #29313b;
                border-radius: 7px;
                padding: 0 7px;
                text-align: center;
                font-size: 10px;
                font-weight: 650;
            }

            QPushButton#historyButton:hover,
            QPushButton#historyActionButton:hover,
            QPushButton#historyMoreButton:hover {
                background: #1c222a;
                color: #ffffff;
                border-color: #465361;
            }

            QPushButton#historyMoreButton::menu-indicator {
                image: none;
                width: 0;
            }

            QDialog,
            QMessageBox {
                background: #101318;
                color: #e8ebef;
            }

            QMenu {
                background: #15191f;
                color: #e8ebef;
                border: 1px solid #323a45;
                border-radius: 8px;
                padding: 5px;
            }

            QMenu::item {
                padding: 7px 24px 7px 10px;
                border-radius: 5px;
            }

            QMenu::item:selected {
                background: #242c35;
            }

            QMenu QLabel#skillMenuSectionTitle {
                color: #f2cc60;
                background: #0d1117;
                border: 1px solid #30363d;
                border-left: 3px solid #f2cc60;
                border-radius: 5px;
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 1.0px;
                padding: 4px 8px 4px 7px;
                margin: 3px 2px 2px 2px;
            }

            QToolTip {
                background: #1b2027;
                color: #eef1f4;
                border: 1px solid #3a444f;
                padding: 5px 7px;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 9px;
                margin: 2px;
            }

            QScrollBar::handle:vertical {
                background: #39424d;
                min-height: 32px;
                border-radius: 4px;
            }

            QScrollBar::handle:vertical:hover {
                background: #53606e;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                height: 0;
            }

            QScrollBar:horizontal {
                background: transparent;
                height: 8px;
            }

            QScrollBar::handle:horizontal {
                background: #39424d;
                min-width: 30px;
                border-radius: 4px;
            }

            /* Premium cockpit polish for the command surfaces. */
            QFrame#runtimeBar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0f1721, stop:0.58 #0c1118, stop:1 #101824);
                border: 1px solid #2d4056;
                border-radius: 15px;
            }

            QFrame#skillsDrawer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #101824, stop:0.54 #0e141d, stop:1 #121a25);
                border: 1px solid #314258;
                border-radius: 16px;
            }

            QFrame#cockpitSkillsGroup,
            QFrame#cockpitRuntimeGroup,
            QFrame#cockpitWebGroup,
            QFrame#cockpitModeGroup,
            QFrame#cockpitSystemGroup {
                background: rgba(9, 13, 18, 158);
                border: 1px solid #263447;
                border-radius: 13px;
            }

            QFrame#cockpitRuntimeGroup,
            QFrame#cockpitWebGroup,
            QFrame#cockpitModeGroup,
            QFrame#cockpitSystemGroup {
                border-color: #30435b;
            }

            QFrame#cockpitModeGroup,
            QFrame#cockpitSystemGroup {
                background: rgba(10, 14, 20, 172);
            }

            QLabel#cockpitGroupTitle {
                color: #8fa0b4;
                font-size: 10px;
                font-weight: 850;
                letter-spacing: 1.1px;
                padding: 0 4px;
            }

            QPushButton#cockpitSkillButton,
            QPushButton#cockpitWebButton,
            QPushButton#cockpitSystemMenuButton {
                background: #151d27;
                color: #dce6f2;
                border: 1px solid #33445a;
                border-radius: 11px;
                min-height: 34px;
                max-height: 34px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 780;
            }

            QPushButton#cockpitSkillButton:hover,
            QPushButton#cockpitWebButton:hover,
            QPushButton#cockpitSystemMenuButton:hover {
                background: #1a2634;
                color: #ffffff;
                border-color: #5f82aa;
            }

            QPushButton#cockpitSkillButton:pressed,
            QPushButton#cockpitWebButton:pressed,
            QPushButton#cockpitSystemMenuButton:pressed {
                background: #111820;
                border-color: #77a1cf;
            }

            QPushButton#cockpitSkillButton[accent="true"] {
                background: #203752;
                color: #ffffff;
                border-color: #6f97c5;
            }

            QPushButton#cockpitSkillButton[accent="true"]:hover {
                background: #274464;
                border-color: #90b7e2;
            }

            QPushButton#cockpitSkillButton::menu-indicator,
            QPushButton#cockpitWebButton::menu-indicator,
            QPushButton#cockpitSystemMenuButton::menu-indicator,
            QPushButton#composerToolButton::menu-indicator,
            QPushButton#newChatButton::menu-indicator,
            QPushButton#composerAstroButton::menu-indicator {
                image: none;
                width: 0;
            }

            QPushButton#quickRefreshModelsButton,
            QPushButton#quickRestartOllamaButton {
                background: #111923;
                color: #d9e5f2;
                border: 1px solid #31435a;
                border-radius: 11px;
                min-height: 34px;
                max-height: 34px;
                min-width: 34px;
                max-width: 34px;
                padding: 0;
            }

            QPushButton#quickRefreshModelsButton:hover,
            QPushButton#quickRestartOllamaButton:hover {
                background: #182536;
                border-color: #6f97c5;
                color: #ffffff;
            }

            QPushButton#quickRestartOllamaButton[ollamaState="on"],
            QPushButton#ollamaPowerButton[ollamaState="on"] {
                background: #12351f;
                border-color: #22c55e;
                color: #bbf7d0;
            }

            QPushButton#quickRestartOllamaButton[ollamaState="on"]:hover,
            QPushButton#ollamaPowerButton[ollamaState="on"]:hover {
                background: #16452a;
                border-color: #4ade80;
                color: #ecfdf5;
            }

            QPushButton#quickRestartOllamaButton[ollamaState="off"],
            QPushButton#ollamaPowerButton[ollamaState="off"] {
                background: #3a1518;
                border-color: #ef4444;
                color: #fecaca;
            }

            QPushButton#quickRestartOllamaButton[ollamaState="off"]:hover,
            QPushButton#ollamaPowerButton[ollamaState="off"]:hover {
                background: #4a1b20;
                border-color: #f87171;
                color: #fff1f2;
            }

            QPushButton#quickRestartOllamaButton[ollamaState="checking"],
            QPushButton#ollamaPowerButton[ollamaState="checking"] {
                background: #332713;
                border-color: #f59e0b;
                color: #fde68a;
            }

            QPushButton#quickRestartOllamaButton[ollamaState="unavailable"],
            QPushButton#ollamaPowerButton[ollamaState="unavailable"] {
                background: #171923;
                border-color: #475569;
                color: #94a3b8;
            }

            QComboBox#quickModelBox,
            QComboBox#quickWebBox {
                background: #0c1219;
                color: #dce8f6;
                border: 1px solid #32445b;
                border-radius: 11px;
                min-height: 34px;
                max-height: 34px;
                padding: 0 28px 0 12px;
                font-size: 11px;
                font-weight: 700;
            }

            QComboBox#quickModelBox:hover,
            QComboBox#quickWebBox:hover,
            QComboBox#quickModelBox:focus,
            QComboBox#quickWebBox:focus {
                background: #111a24;
                border-color: #668bb4;
            }

            QComboBox#quickModelBox QAbstractItemView {
                min-width: 185px;
                max-width: 185px;
            }

            QFrame#composerShell {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #10151d, stop:0.56 #0d1117, stop:1 #111923);
                border: 1px solid #2d3b4c;
                border-radius: 17px;
            }

            QFrame#composerToolbar {
                background: rgba(8, 12, 17, 138);
                border: 1px solid #243143;
                border-radius: 12px;
                padding: 2px;
            }

            QLabel#composerToolsLabel {
                color: #8fa0b4;
                font-size: 10px;
                font-weight: 850;
                letter-spacing: 1.1px;
                padding: 0 6px 0 4px;
            }

            QPushButton#composerToolButton,
            QPushButton#newChatButton {
                background: #121a24;
                color: #c6d1de;
                border: 1px solid #2b3a4d;
                border-radius: 9px;
                min-height: 26px;
                max-height: 26px;
                padding: 0 10px;
                font-size: 10px;
                font-weight: 760;
            }

            QPushButton#composerToolButton:hover,
            QPushButton#newChatButton:hover {
                background: #192535;
                color: #ffffff;
                border-color: #668bb4;
            }

            QPushButton#newChatButton {
                min-height: 24px;
                max-height: 24px;
                padding: 0 7px;
                font-size: 9px;
                font-weight: 720;
            }

            QPushButton#composerAstroButton {
                background: #17253a;
                color: #e8f3ff;
                border: 1px solid #416486;
                border-radius: 9px;
                min-height: 26px;
                max-height: 26px;
                padding: 0 12px;
                font-size: 10px;
                font-weight: 820;
            }

            QPushButton#composerAstroButton:hover {
                background: #1e3350;
                color: #ffffff;
                border-color: #7ba7d4;
            }

            QPushButton#composerAstroButton:pressed {
                background: #122033;
                border-color: #97c2eb;
            }

            QPushButton#composerAstroButton::menu-indicator {
                image: none;
                width: 0;
            }

            QTextEdit#inputBox {
                background: #0b1016;
                border: 1px solid #334052;
                color: #f3f7fb;
                border-radius: 15px;
                padding: 9px 13px;
                font-size: 14px;
                selection-background-color: #42658a;
                selection-color: #ffffff;
            }

            QTextEdit#inputBox:focus {
                background: #0e151d;
                border-color: #80a9d4;
            }

            QPushButton#attachButton,
            QPushButton#voiceButton {
                background: #0b1016;
                color: #d4dde8;
                border: 1px solid #334052;
                border-radius: 15px;
            }

            QPushButton#attachButton:hover,
            QPushButton#voiceButton:hover {
                background: #111a24;
                color: #ffffff;
                border-color: #80a9d4;
            }

            QPushButton#sendButton {
                background: #2c5278;
                color: #ffffff;
                border: 1px solid #79a5d3;
                border-radius: 15px;
                font-weight: 850;
                letter-spacing: 0.35px;
            }

            QPushButton#sendButton:hover {
                background: #376491;
                border-color: #a0c5ea;
            }

            QPushButton#sendButton:pressed {
                background: #244762;
                border-color: #6d94bb;
            }

            QPushButton#stopButton {
                border-radius: 15px;
                font-weight: 850;
            }

            QFrame#statusRow {
                background: transparent;
                border: none;
            }

            QLabel#timeLabel,
            QLabel#gpuLabel,
            QLabel#systemLabel,
            QLabel#statsLabel {
                background: rgba(10, 15, 21, 128);
                color: #8797aa;
                border: 1px solid #243246;
                border-radius: 8px;
                padding: 2px 7px;
                font-size: 10px;
                font-weight: 650;
            }

            QLabel#gpuLabel {
                color: #9eb8d4;
            }

            QLabel#systemLabel,
            QLabel#statsLabel {
                color: #94a4b7;
            }


            /* Codex dark overlay (FZAstro) */
            QMainWindow,
            QWidget#main {
                background: #0b0f14;
                color: #e6edf3;
            }

            QWidget#sidebar,
            QWidget#historyPanel {
                background: #0d1117;
            }

            QFrame#sidebarHeader,
            QFrame#historyHeader,
            QFrame#topBar,
            QFrame#runtimeBar,
            QFrame#quickActionsBar,
            QFrame#skillsDrawer,
            QFrame#composerShell,
            QFrame#thoughtPanel {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 14px;
            }

            QFrame#chatSurface,
            QScrollArea#chatScroll,
            QScrollArea#chatScroll QWidget,
            QWidget#chatContainer {
                background: #0b0f14;
                border: none;
                border-radius: 0px;
            }

            QFrame#cockpitSkillsGroup,
            QFrame#cockpitRuntimeGroup,
            QFrame#cockpitWebGroup,
            QFrame#cockpitModeGroup,
            QFrame#cockpitSystemGroup {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 14px;
            }

            QLabel#cockpitGroupTitle,
            QLabel#subtitle,
            QLabel#workspaceContextLabel,
            QLabel#timeLabel,
            QLabel#gpuLabel,
            QLabel#systemLabel,
            QLabel#statsLabel,
            QLabel#toolbarCaption,
            QLabel#fieldCaption {
                color: #8b949e;
            }

            QComboBox#quickModelBox,
            QComboBox#quickWebBox,
            QLineEdit,
            QComboBox,
            QSpinBox,
            QDoubleSpinBox,
            QTextEdit#systemPromptBox,
            QListWidget,
            QTextEdit#memorySearchPreview,
            QTextEdit#inputBox {
                background: #0b0f14;
                color: #e6edf3;
                border: 1px solid #30363d;
                selection-background-color: #1f6feb;
                selection-color: #ffffff;
            }

            QComboBox#quickModelBox:hover,
            QComboBox#quickWebBox:hover,
            QComboBox#quickModelBox:focus,
            QComboBox#quickWebBox:focus,
            QLineEdit:focus,
            QComboBox:focus,
            QSpinBox:focus,
            QDoubleSpinBox:focus,
            QTextEdit#inputBox:focus {
                background: #0d1117;
                border-color: #58a6ff;
            }

            QPushButton,
            QToolButton,
            QPushButton#cockpitSkillButton,
            QPushButton#cockpitWebButton,
            QPushButton#cockpitModeButton,
            QPushButton#cockpitSystemMenuButton,
            QPushButton#composerToolButton,
            QPushButton#newChatButton,
            QPushButton#attachButton,
            QPushButton#voiceButton,
            QPushButton#workspaceAppsButton {
                background: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
            }

            QPushButton:hover,
            QToolButton:hover,
            QPushButton#cockpitSkillButton:hover,
            QPushButton#cockpitWebButton:hover,
            QPushButton#cockpitModeButton:hover,
            QPushButton#cockpitSystemMenuButton:hover,
            QPushButton#composerToolButton:hover,
            QPushButton#newChatButton:hover,
            QPushButton#attachButton:hover,
            QPushButton#voiceButton:hover,
            QPushButton#workspaceAppsButton:hover {
                background: #21262d;
                color: #f0f6fc;
                border-color: #58a6ff;
            }

            QPushButton#sendButton {
                background: #1f6feb;
                color: #ffffff;
                border: 1px solid #388bfd;
            }

            QPushButton#sendButton:hover {
                background: #388bfd;
                border-color: #79c0ff;
            }

            QWidget#messageContentContainer,
            QWidget#messageContentContainer[messageKind="assistant"] {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 16px;
            }

            QWidget#messageContentContainer[messageKind="user"] {
                background: #161b22;
                border-color: #30363d;
                border-radius: 18px;
            }

            QWidget#messageContentContainer[messageKind="news"] {
                background: #0d1117;
                border-color: #30363d;
            }

            QLabel#messageText,
            QTextBrowser#messageText,
            QTextBrowser#thoughtBox,
            QTextBrowser#codeView,
            QTextBrowser#helpCheatSheetBrowser {
                color: #e6edf3;
                selection-background-color: #1f6feb;
                selection-color: #ffffff;
            }

            QMenu {
                background: #161b22;
                color: #e6edf3;
                border: 1px solid #30363d;
            }

            QMenu::item:selected {
                background: #21262d;
            }

            QMenu QLabel#skillMenuSectionTitle {
                color: #f2cc60;
                background: #0d1117;
                border: 1px solid #30363d;
                border-left: 3px solid #f2cc60;
                border-radius: 5px;
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 1.0px;
                padding: 4px 8px 4px 7px;
                margin: 3px 2px 2px 2px;
            }

            QScrollBar::handle:vertical,
            QScrollBar::handle:horizontal {
                background: #30363d;
                border-radius: 4px;
            }

            QScrollBar::handle:vertical:hover,
            QScrollBar::handle:horizontal:hover {
                background: #484f58;
            }

            QFrame#topBar,
            QFrame#runtimeBar,
            QFrame#quickActionsBar,
            QFrame#skillsDrawer,
            QFrame#composerShell,
            QFrame#thoughtPanel {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 8px;
            }

            QFrame#cockpitSkillsGroup,
            QFrame#cockpitRuntimeGroup,
            QFrame#cockpitWebGroup,
            QFrame#cockpitModeGroup,
            QFrame#cockpitSystemGroup,
            QFrame#composerToolbar {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 8px;
            }

            QFrame#chatSurface,
            QScrollArea#chatScroll,
            QScrollArea#chatScroll QWidget,
            QWidget#chatContainer {
                background: #0d1117;
                border: none;
            }

            QLabel#brandMark,
            QLabel#sidebarBrandMark {
                background: #161b22;
                color: #f0f6fc;
                border: 1px solid #30363d;
                border-radius: 8px;
            }

            QLabel#thoughtIndicator {
                color: #58a6ff;
            }

            QLabel#thoughtTitle {
                color: #c9d1d9;
            }

            QLabel#thoughtHint {
                color: #8b949e;
            }

            QTextBrowser#thoughtBox {
                background: #0d1117;
                color: #c9d1d9;
                border: none;
            }

            QTabWidget#workspaceTabs {
                background: #0d1117;
                border: none;
                padding: 0px;
            }

            QTabWidget#workspaceTabs::pane {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 8px;
                top: 0px;
            }

            QTabWidget#workspaceTabs::tab-bar {
                left: 0px;
            }

            QTabWidget#workspaceTabs QTabBar#workspaceTabBar {
                background: transparent;
                border: none;
            }

            QTabWidget#workspaceTabs QTabBar::tab {
                background: #0d1117;
                color: #8b949e;
                border: 1px solid #30363d;
                border-radius: 8px;
                min-width: 86px;
                min-height: 24px;
                padding: 3px 10px 3px 12px;
                margin: 0px 6px 4px 0px;
                font-size: 11px;
                font-weight: 700;
            }

            QTabWidget#workspaceTabs QTabBar::tab:selected {
                background: #161b22;
                color: #f0f6fc;
                border-color: #58a6ff;
            }

            QTabWidget#workspaceTabs QTabBar::tab:hover:!selected {
                background: #161b22;
                color: #c9d1d9;
                border-color: #484f58;
            }

            QPushButton#workspaceAppsButton {
                background: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 2px 18px 2px 10px;
                margin: 0px;
                min-width: 76px;
                max-width: 76px;
                min-height: 26px;
                max-height: 26px;
            }

            QPushButton#workspaceAppsButton:hover {
                background: #21262d;
                color: #f0f6fc;
                border-color: #58a6ff;
            }

            QPushButton#workspaceAppsButton::menu-indicator {
                subcontrol-origin: padding;
                subcontrol-position: right center;
                width: 8px;
                height: 8px;
                right: 7px;
            }

            QPushButton#workspaceTabCloseButton,
            QToolButton#workspaceTabCloseButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                min-width: 16px;
                max-width: 16px;
                min-height: 16px;
                max-height: 16px;
                padding: 0px;
                margin: 0px;
            }

            QPushButton#workspaceTabCloseButton:hover,
            QToolButton#workspaceTabCloseButton:hover {
                background: #21262d;
                border-color: #484f58;
            }

            QPushButton#workspaceTabCloseButton:pressed,
            QToolButton#workspaceTabCloseButton:pressed {
                background: #30363d;
                border-color: #58a6ff;
            }

            QWidget#messageContentContainer,
            QWidget#messageContentContainer[messageKind="assistant"],
            QWidget#messageContentContainer[messageKind="news"] {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 10px;
            }

            QWidget#messageContentContainer[messageKind="user"] {
                background: #10151c;
                border: 1px solid #30363d;
                border-radius: 10px;
            }

            QLabel#messageRoleBadge {
                background: transparent;
                color: #8b949e;
                border: none;
                border-radius: 0px;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.4px;
            }

            QLabel#messageRoleBadge[roleType="user"] {
                color: #f0b7c0;
            }

            QLabel#messageRoleBadge[roleType="news"] {
                color: #79c0ff;
            }

            QWidget#sourceHeader,
            QWidget#newsBriefHeader,
            QWidget#replyTimerFooter {
                background: transparent;
                border: none;
            }

            QWidget#sourceHeader {
                border-bottom: none;
                margin-bottom: 2px;
            }

            QLabel#sourceHeaderLabel {
                color: #8b949e;
                font-size: 10px;
                font-weight: 700;
            }

            QLabel#sourceChip {
                background: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 750;
            }

            QWidget#replyTimerFooter {
                margin-top: 2px;
            }

            QLabel#replyTimerLabel {
                color: #8b949e;
                font-size: 10px;
                padding: 0px;
            }

            QPushButton#messageOptionsButton {
                background: transparent;
                color: #8b949e;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 0px;
                font-size: 16px;
            }

            QPushButton#messageOptionsButton:hover {
                background: #21262d;
                color: #f0f6fc;
                border-color: #30363d;
            }

            QTextEdit#inputBox {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 8px;
                color: #e6edf3;
            }

            QTextEdit#inputBox:focus {
                background: #0d1117;
                border-color: #58a6ff;
            }


            QPushButton#cockpitWebButton[webState="on"],
            QPushButton[webState="on"] {
                background: #12351f;
                border-color: #22c55e;
                color: #bbf7d0;
            }

            QPushButton#cockpitWebButton[webState="on"]:hover,
            QPushButton[webState="on"]:hover {
                background: #16452a;
                border-color: #4ade80;
                color: #ecfdf5;
            }

            QPushButton#cockpitWebButton[webState="on"]:disabled,
            QPushButton[webState="on"]:disabled {
                background: #12351f;
                border-color: #22c55e;
                color: #bbf7d0;
            }

            QPushButton#cockpitWebButton[webState="off"],
            QPushButton[webState="off"] {
                background: #3a1518;
                border-color: #ef4444;
                color: #fecaca;
            }

            QPushButton#cockpitWebButton[webState="off"]:hover,
            QPushButton[webState="off"]:hover {
                background: #4a1b20;
                border-color: #f87171;
                color: #fff1f2;
            }

            QPushButton#cockpitWebButton[webState="checking"],
            QPushButton#cockpitWebButton[webState="external"],
            QPushButton[webState="checking"],
            QPushButton[webState="external"] {
                background: #332713;
                border-color: #f59e0b;
                color: #fde68a;
            }

            QPushButton#cockpitWebButton[webState="checking"]:hover,
            QPushButton#cockpitWebButton[webState="external"]:hover,
            QPushButton[webState="checking"]:hover,
            QPushButton[webState="external"]:hover {
                background: #433414;
                border-color: #fbbf24;
                color: #fffbeb;
            }

            QLabel#webArticleBody[webState="on"] {
                background: #0b2515;
                color: #bbf7d0;
                border: 1px solid #22c55e;
                border-radius: 8px;
                padding: 8px 10px;
            }

            QLabel#webArticleBody[webState="off"] {
                background: #2a1114;
                color: #fecaca;
                border: 1px solid #ef4444;
                border-radius: 8px;
                padding: 8px 10px;
            }

            QLabel#webArticleBody[webState="checking"],
            QLabel#webArticleBody[webState="external"] {
                background: #261d0d;
                color: #fde68a;
                border: 1px solid #f59e0b;
                border-radius: 8px;
                padding: 8px 10px;
            }



            /* Composer / top app bar button standardization (v2.4.3). */
            QPushButton#composerToolButton,
            QPushButton#composerAstroButton,
            QPushButton#composerClaudeButton,
            QPushButton#newChatButton {
                min-height: 34px;
                max-height: 34px;
                padding: 0 12px;
                border-radius: 10px;
                font-size: 11px;
                font-weight: 760;
                letter-spacing: 0.1px;
            }

            QPushButton#composerToolButton,
            QPushButton#newChatButton {
                background: #121a24;
                color: #c6d1de;
                border: 1px solid #2b3a4d;
            }

            QPushButton#composerToolButton:hover,
            QPushButton#newChatButton:hover {
                background: #192535;
                color: #ffffff;
                border-color: #668bb4;
            }

            QPushButton#composerToolButton:pressed,
            QPushButton#newChatButton:pressed {
                background: #0e151f;
                border-color: #8ab8e3;
            }

            QPushButton#composerAstroButton {
                background: #17253a;
                color: #e8f3ff;
                border: 1px solid #416486;
            }

            QPushButton#composerAstroButton:hover {
                background: #1e3350;
                color: #ffffff;
                border-color: #7ba7d4;
            }

            QPushButton#composerClaudeButton {
                background: #182438;
                color: #f4f0ff;
                border: 1px solid #6d5fa8;
                font-weight: 820;
            }

            QPushButton#composerClaudeButton:hover {
                background: #243457;
                color: #ffffff;
                border-color: #9c8df0;
            }

            QPushButton#composerClaudeButton:pressed {
                background: #121b2e;
                border-color: #b9adff;
            }

            QPushButton#composerToolButton::menu-indicator,
            QPushButton#composerAstroButton::menu-indicator,
            QPushButton#composerClaudeButton::menu-indicator {
                image: none;
                width: 0;
            }

            QPushButton#cockpitTopMenuButton,
            QPushButton#cockpitSystemMenuButton,
            QPushButton#cockpitProfileMenuButton {
                background: #151d27;
                color: #dce6f2;
                border: 1px solid #33445a;
                border-radius: 11px;
                min-height: 34px;
                max-height: 34px;
                padding: 0 12px;
                font-size: 11px;
                font-weight: 780;
            }

            QPushButton#cockpitTopMenuButton:hover,
            QPushButton#cockpitSystemMenuButton:hover,
            QPushButton#cockpitProfileMenuButton:hover {
                background: #1a2634;
                color: #ffffff;
                border-color: #5f82aa;
            }

            QPushButton#cockpitTopMenuButton:pressed,
            QPushButton#cockpitSystemMenuButton:pressed,
            QPushButton#cockpitProfileMenuButton:pressed {
                background: #111820;
                border-color: #77a1cf;
            }

            QPushButton#cockpitTopMenuButton::menu-indicator,
            QPushButton#cockpitSystemMenuButton::menu-indicator,
            QPushButton#cockpitProfileMenuButton::menu-indicator {
                image: none;
                width: 0;
            }

            /* End Codex dark overlay (FZAstro) */


        """
