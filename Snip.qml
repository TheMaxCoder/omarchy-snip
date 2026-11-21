import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui

Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property string homePath: Quickshell.env("HOME")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property bool searchMode: false
  property string searchText: ""
  property int currentTab: 0
  property int selectedIndex: 0
  property bool cursorActive: true
  property var categories: []
  property var savedItems: []
  property var inboxItems: []
  property bool savePickerOpen: false
  property int saveCategoryIndex: 0
  property bool categoryInputOpen: false
  property bool categoryInputForSave: false
  property string categoryInput: ""
  property string statusText: ""
  property string statusTone: "accent"
  property int deleteArmedId: -1
  property int deleteArmedCategoryId: -1
  property string pendingAction: ""
  property string processOutput: ""
  property string processError: ""

  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color border: Color.menu.border
  property var borderSpec: Border.surfaceSpec("menu", "border", border, Math.max(1, Style.space(2)))
  property color scrim: Color.menu.scrim
  property color selectedBackground: Color.menu.selectedBackground
  property color selectedText: Color.menu.selectedText
  property color accent: Color.accent
  property color urgent: Color.urgent
  property color muted: Color.muted
  property color success: Color.accent
  property color warning: Color.accent
  property color danger: Color.urgent
  property color info: Color.accent
  property color navigation: Color.accent
  property color navigationBackground: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.16)
  property color navigationTabBackground: navigationRowBackground
  property color navigationRowBackground: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.05)
  property color navigationBorder: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.12)
  readonly property color statusColor: statusTone === "success" ? success
    : (statusTone === "warning" ? warning : (statusTone === "danger" ? danger : accent))
  readonly property color translucentBackground: background
  readonly property int cornerRadius: Style.cornerRadius
  property string fontFamily: Style.font.menuFamily
  property int contentMargin: Style.spacing.panelPadding
  property int contentSpacing: Style.spacing.md
  property int cardWidth: Math.min(Style.space(1040), panel.width - Style.gapsOut * 2)
  property int cardHeight: Math.min(Style.space(650), panel.height - Style.gapsOut * 2)
  property int headerHeight: Math.max(Style.space(40), Style.font.title + Style.spacing.controlPaddingY * 2)
  property int footerHeight: Math.max(Style.space(30), Style.font.caption + Style.spacing.controlPaddingY * 2)
  property int rowHeight: Math.max(Style.space(58), Style.font.body + Style.font.caption + Style.spacing.rowPaddingX * 2)
  property int tabCount: 2 + categories.length

  property var displayRows: []
  property var selectedItem: null
  property bool resetSelectionOnSnapshot: false
  readonly property string previewText: {
    var body = root.selectedItem ? String(root.selectedItem.body || "") : ""
    return body.length > 12000 ? body.slice(0, 12000) + "\n\n[Preview truncated · copy or edit for full text]" : body
  }

  function open(payloadJson) {
    root.searchMode = false
    root.searchText = ""
    root.currentTab = 0
    root.selectedIndex = 0
    root.cursorActive = true
    root.savePickerOpen = false
    root.categoryInputOpen = false
    root.statusText = ""
    root.rebuildDisplay()
    root.resetSelectionOnSnapshot = true
    root.opened = true
    themeColors.reload()
    root.runBackend(["snapshot"], "snapshot")
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.opened = false
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "nox.snip")
  }

  function toggle() {
    if (root.opened) root.dismiss()
    else root.open("{}")
  }

  function runBackend(args, action) {
    if (backend.running) {
      root.status("Still working…", "warning")
      return false
    }
    root.pendingAction = action
    root.processOutput = ""
    root.processError = ""
    backend.command = [root.homePath + "/.local/bin/snip"].concat(args)
    backend.running = true
    return true
  }

  function applySnapshot(raw) {
    try {
      var data = JSON.parse(raw)
      root.categories = data.categories || []
      root.savedItems = data.items || []
      root.inboxItems = data.inbox || []
      if (root.currentTab >= root.tabCount) root.currentTab = Math.max(0, root.tabCount - 1)
    } catch (error) {
      root.status("Could not read Snip data", "danger")
      return
    }
    if (root.resetSelectionOnSnapshot) root.selectedIndex = 0
    root.rebuildDisplay(!root.resetSelectionOnSnapshot)
  }

  function status(message, tone) {
    root.statusText = message
    root.statusTone = tone || "accent"
    statusTimer.restart()
  }

  function loadThemePalette(raw) {
    function namedColor(name, fallback) {
      var expression = new RegExp("^\\s*" + name + "\\s*=\\s*[\\\"']?(#[0-9A-Fa-f]{6})", "m")
      var match = String(raw || "").match(expression)
      return match ? match[1] : fallback
    }
    function hexToRgba(hex, alpha) {
      if (!hex || typeof hex !== "string" || hex.charAt(0) !== "#") return Qt.rgba(0.5, 0.5, 0.5, alpha)
      var r = parseInt(hex.slice(1, 3), 16) / 255
      var g = parseInt(hex.slice(3, 5), 16) / 255
      var b = parseInt(hex.slice(5, 7), 16) / 255
      return Qt.rgba(r, g, b, alpha)
    }
    var fgHex = namedColor("foreground", "#dcd7ba")
    var rawAccent = namedColor("accent", "#7daea3")
    var accentHex = (rawAccent.toLowerCase() === fgHex.toLowerCase())
      ? namedColor("cyan", namedColor("blue", rawAccent))
      : rawAccent
    root.accent = accentHex
    root.success = namedColor("green", accentHex)
    root.warning = namedColor("orange", namedColor("yellow", accentHex))
    root.danger = namedColor("red", root.urgent)
    var infoHex = namedColor("cyan", namedColor("blue", accentHex))
    root.info = infoHex
    root.navigation = accentHex
    root.navigationBackground = hexToRgba(accentHex, 0.16)
    root.navigationTabBackground = hexToRgba(accentHex, 0.05)
    root.navigationRowBackground = hexToRgba(accentHex, 0.05)
    root.navigationBorder = hexToRgba(accentHex, 0.12)
  }

  function inboxRow(entry) {
    return {
      source: "inbox",
      itemId: -1,
      historyIndex: Number(entry.historyIndex),
      categoryId: -1,
      categoryName: "Inbox",
      kind: entry.kind || "text",
      title: entry.title || "Untitled",
      subtitle: entry.subtitle || "",
      body: entry.body || "",
      path: entry.path || "",
      mime: entry.mime || "text/plain",
      pinned: false
    }
  }

  function savedRow(entry) {
    return {
      source: "saved",
      itemId: Number(entry.id),
      historyIndex: -1,
      categoryId: entry.categoryId === null ? -1 : Number(entry.categoryId),
      categoryName: entry.categoryName || "Pinned only",
      kind: entry.kind || "text",
      title: entry.title || "Untitled",
      subtitle: entry.subtitle || entry.categoryName || "",
      body: entry.body || "",
      path: entry.path || "",
      mime: entry.mime || "text/plain",
      pinned: Boolean(entry.pinned)
    }
  }

  function matches(entry, query) {
    var needle = query.toLowerCase()
    return String(entry.title || "").toLowerCase().indexOf(needle) >= 0
      || String(entry.body || "").toLowerCase().indexOf(needle) >= 0
      || String(entry.categoryName || "").toLowerCase().indexOf(needle) >= 0
  }

  function rebuildDisplay(preserveSelection) {
    var previous = preserveSelection ? root.selectedItem : null
    var rows = []
    if (root.searchMode) {
      for (var s = 0; s < root.savedItems.length; s++) {
        if (root.matches(root.savedItems[s], root.searchText)) rows.push(root.savedRow(root.savedItems[s]))
      }
      for (var x = 0; x < root.inboxItems.length; x++) {
        if (root.matches(root.inboxItems[x], root.searchText)) rows.push(root.inboxRow(root.inboxItems[x]))
      }
    } else if (root.currentTab === 0) {
      for (var i = 0; i < root.inboxItems.length; i++) rows.push(root.inboxRow(root.inboxItems[i]))
    } else if (root.currentTab === 1) {
      for (var p = 0; p < root.savedItems.length; p++) {
        if (root.savedItems[p].pinned) rows.push(root.savedRow(root.savedItems[p]))
      }
    } else {
      var category = root.categories[root.currentTab - 2]
      if (category) {
        for (var c = 0; c < root.savedItems.length; c++) {
          if (Number(root.savedItems[c].categoryId) === Number(category.id)) rows.push(root.savedRow(root.savedItems[c]))
        }
      }
    }

    var nextIndex = Math.max(0, Math.min(root.selectedIndex, rows.length - 1))
    if (previous) {
      for (var r = 0; r < rows.length; r++) {
        var row = rows[r]
        if (row.source === previous.source && (row.source === "saved"
            ? row.itemId === previous.itemId
            : row.kind === previous.kind && row.body === previous.body
              && row.path === previous.path && row.mime === previous.mime)) {
          nextIndex = r
          break
        }
      }
    }
    root.displayRows = rows
    root.updateSelection(nextIndex)
    root.cursorActive = rows.length > 0
    Qt.callLater(function() {
      if (root.displayRows.length > 0) resultList.positionViewAtIndex(root.selectedIndex, ListView.Contain)
      preview.contentY = 0
    })
  }

  function tabName(index) {
    if (index === 0) return "Inbox"
    if (index === 1) return "Pinned"
    var category = root.categories[index - 2]
    return category ? category.name : ""
  }

  function switchTab(delta) {
    root.currentTab = (root.currentTab + delta + root.tabCount) % root.tabCount
    root.selectedIndex = 0
    root.deleteArmedId = -1
    root.deleteArmedCategoryId = -1
    root.rebuildDisplay()
  }

  function updateSelection(index) {
    root.resetSelectionOnSnapshot = false
    root.selectedIndex = index
    root.selectedItem = root.displayRows[index] || null
  }

  function select(delta) {
    if (root.displayRows.length === 0) return
    root.updateSelection((root.selectedIndex + delta + root.displayRows.length) % root.displayRows.length)
    root.cursorActive = true
    resultList.positionViewAtIndex(root.selectedIndex, ListView.Contain)
    preview.contentY = 0
  }

  function selectAbsolute(index) {
    if (root.displayRows.length === 0) return
    root.updateSelection(Math.max(0, Math.min(index, root.displayRows.length - 1)))
    root.cursorActive = true
    resultList.positionViewAtIndex(root.selectedIndex, ListView.Contain)
    preview.contentY = 0
  }

  function pasteSelected(copyOnly) {
    var row = root.selectedItem
    if (!row) return
    var command
    if (row.kind === "image") {
      command = [root.omarchyPath + "/bin/omarchy-clipboard-paste-file"]
      if (copyOnly) command.push("--copy-only")
      command.push(row.mime, row.path)
    } else {
      command = [root.omarchyPath + "/bin/omarchy-clipboard-paste-text"]
      if (copyOnly) command.push("--copy-only")
      else command.push("--shift-insert")
      if (row.source === "inbox") command.push("--history-index", String(row.historyIndex))
      else command.push(row.body)
    }

    if (row.source === "saved")
      Quickshell.execDetached([root.homePath + "/.local/bin/snip", "used", String(row.itemId)])
    if (!copyOnly) root.dismiss()
    else root.status("Copied", "success")
    Quickshell.execDetached(command)
  }

  function quickPin() {
    var row = root.selectedItem
    if (!row) return
    if (row.source === "inbox") {
      if (root.runBackend(["pin-inbox", String(row.historyIndex)], "mutate"))
        root.status("Pinned · [s] choose or create a tab", "success")
    } else {
      if (root.runBackend(["toggle-pin", String(row.itemId)], "mutate"))
        root.status(row.pinned ? "Unpinned" : "Pinned", row.pinned ? "warning" : "success")
    }
  }

  function openSavePicker() {
    var row = root.selectedItem
    if (!row || row.source !== "inbox") return
    root.saveCategoryIndex = 0
    root.savePickerOpen = true
  }

  function saveToCategory() {
    var row = root.selectedItem
    if (root.saveCategoryIndex === root.categories.length) {
      root.savePickerOpen = false
      root.categoryInput = ""
      root.categoryInputForSave = true
      root.categoryInputOpen = true
      return
    }
    var category = root.categories[root.saveCategoryIndex]
    if (!row || !category) return
    root.savePickerOpen = false
    if (root.runBackend(["save-inbox", String(row.historyIndex), String(category.id)], "mutate"))
      root.status("Saved to " + category.name, "success")
  }

  function deleteSelected() {
    var row = root.selectedItem
    if (!row || row.source !== "saved") return
    if (root.deleteArmedId !== row.itemId) {
      root.deleteArmedId = row.itemId
      root.status("Press d again to delete", "danger")
      deleteTimer.restart()
      return
    }
    root.deleteArmedId = -1
    root.runBackend(["delete", String(row.itemId)], "mutate")
    root.status("Deleted", "danger")
  }

  function deleteCurrentTab() {
    if (root.currentTab < 2) {
      root.status("Inbox and Pinned are permanent tabs", "warning")
      return
    }
    var category = root.categories[root.currentTab - 2]
    if (!category) return
    if (root.deleteArmedCategoryId !== Number(category.id)) {
      root.deleteArmedCategoryId = Number(category.id)
      root.status("Delete “" + category.name + "”? Press D again · snippets move to Pinned", "danger")
      deleteTimer.restart()
      return
    }
    root.deleteArmedCategoryId = -1
    root.currentTab = 1
    root.selectedIndex = 0
    if (root.runBackend(["delete-category", String(category.id)], "mutate"))
      root.status("Deleted “" + category.name + "” · snippets moved to Pinned", "danger")
  }

  function editSelected() {
    var row = root.selectedItem
    if (!row || row.source !== "saved") {
      root.status("Save this Inbox item before editing", "warning")
      return
    }
    if (row.kind !== "text") {
      root.status("Images cannot be edited as text", "warning")
      return
    }
    root.dismiss()
    Quickshell.execDetached([
      "foot", "--app-id=snip-editor", "--title=Edit Snip", "-e",
      root.homePath + "/.local/bin/snip", "edit", String(row.itemId)
    ])
  }

  function createCategory() {
    var name = root.categoryInput.trim()
    if (!name) return
    var saveAfterCreate = root.categoryInputForSave
    var row = root.selectedItem
    root.categoryInputOpen = false
    root.categoryInputForSave = false
    root.categoryInput = ""
    if (saveAfterCreate && row && row.source === "inbox") {
      if (root.runBackend(["save-inbox-new", String(row.historyIndex), name], "mutate"))
        root.status("Created and saved to " + name, "success")
    } else if (root.runBackend(["create-category", name], "mutate")) {
      root.status("Created " + name, "success")
    }
  }

  Process {
    id: backend
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.processOutput = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.processError = text
    }
    onExited: function(exitCode) {
      var action = root.pendingAction
      root.pendingAction = ""
      if (exitCode !== 0) {
        root.status(root.processError.trim() || "Snip operation failed", "danger")
        return
      }
      if (action === "snapshot") root.applySnapshot(root.processOutput)
      else refreshTimer.restart()
    }
  }

  FileView {
    path: root.homePath + "/.local/state/omarchy/clipboard-history.json"
    watchChanges: true
    printErrors: false
    onFileChanged: if (root.opened) refreshTimer.restart()
  }

  FileView {
    id: themeColors
    path: root.homePath + "/.local/state/omarchy/current/theme/colors.toml"
    watchChanges: true
    printErrors: false
    onLoaded: root.loadThemePalette(text())
    onFileChanged: reload()
  }

  Timer {
    id: refreshTimer
    interval: 80
    onTriggered: root.runBackend(["snapshot"], "snapshot")
  }

  Timer {
    id: statusTimer
    interval: 2200
    onTriggered: {
      root.statusText = ""
      root.statusTone = "accent"
    }
  }

  Timer {
    id: deleteTimer
    interval: 3500
    onTriggered: {
      root.deleteArmedId = -1
      root.deleteArmedCategoryId = -1
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "nox-snip"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      anchors.centerIn: parent
      color: root.translucentBackground
      borderSpec: root.borderSpec
      padding: root.contentMargin

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (root.savePickerOpen) {
            if (event.key === Qt.Key_Escape) root.savePickerOpen = false
            else if (event.key === Qt.Key_Up || event.text === "o" || event.text === "k")
              root.saveCategoryIndex = (root.saveCategoryIndex - 1 + root.categories.length + 1) % (root.categories.length + 1)
            else if (event.key === Qt.Key_Down || event.text === "a" || event.text === "j")
              root.saveCategoryIndex = (root.saveCategoryIndex + 1) % (root.categories.length + 1)
            else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) root.saveToCategory()
            event.accepted = true
            return
          }

          if (root.categoryInputOpen) {
            if (event.key === Qt.Key_Escape) {
              root.categoryInputOpen = false
              root.categoryInputForSave = false
              root.categoryInput = ""
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
              root.createCategory()
            } else if (Util.editsFilter(event, root.categoryInput)) {
              root.categoryInput = Util.editedFilter(event, root.categoryInput)
            } else if (event.text && event.text.length === 1
                       && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
              root.categoryInput += event.text
            }
            event.accepted = true
            return
          }

          if (event.matches(StandardKey.Copy)
              || (event.key === Qt.Key_C && event.modifiers === Qt.MetaModifier)) {
            root.pasteSelected(true)
            event.accepted = true
            return
          }

          if (root.searchMode) {
            if (event.key === Qt.Key_Escape) {
              root.searchMode = false
              root.searchText = ""
              root.selectedIndex = 0
              root.rebuildDisplay()
            } else if (event.key === Qt.Key_Up) {
              root.select(-1)
            } else if (event.key === Qt.Key_Down) {
              root.select(1)
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
              root.pasteSelected(false)
            } else if (Util.editsFilter(event, root.searchText)) {
              root.searchText = Util.editedFilter(event, root.searchText)
              root.selectedIndex = 0
              root.rebuildDisplay()
            } else if (event.text && event.text.length === 1
                       && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
              root.searchText += event.text
              root.selectedIndex = 0
              root.rebuildDisplay()
            }
            event.accepted = true
            return
          }

          if (event.key === Qt.Key_Escape || event.text === "q") root.dismiss()
          else if (event.key === Qt.Key_Right || event.key === Qt.Key_Tab || event.text === "e") root.switchTab(1)
          else if (event.key === Qt.Key_Left || event.key === Qt.Key_Backtab || event.text === "h") root.switchTab(-1)
          else if (event.key === Qt.Key_Up || event.text === "o" || event.text === "k") root.select(-1)
          else if (event.key === Qt.Key_Down || event.text === "a" || event.text === "j") root.select(1)
          else if (event.key === Qt.Key_Home || event.text === "g") root.selectAbsolute(0)
          else if (event.key === Qt.Key_End || event.text === "G") root.selectAbsolute(root.displayRows.length - 1)
          else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.text === "p") root.pasteSelected(false)
          else if (event.text === "y") root.pasteSelected(true)
          else if (event.text === "f") root.quickPin()
          else if (event.text === "s") root.openSavePicker()
          else if (event.text === "d") root.deleteSelected()
          else if (event.text === "D") root.deleteCurrentTab()
          else if (event.text === "i") root.editSelected()
          else if (event.text === "N") {
            root.categoryInput = ""
            root.categoryInputForSave = false
            root.categoryInputOpen = true
          } else if (event.text === "/") {
            root.searchMode = true
            root.searchText = ""
            root.selectedIndex = 0
            root.rebuildDisplay()
          } else if (event.text && /^[0-9]$/.test(event.text)) {
            var tab = Number(event.text)
            if (tab < root.tabCount) {
              root.currentTab = tab
              root.selectedIndex = 0
              root.rebuildDisplay()
            }
          }
          event.accepted = true
        }
      }

      Column {
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: root.contentSpacing

        Item {
          width: parent.width
          height: root.headerHeight

          Row {
            visible: !root.searchMode
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.sm

            Repeater {
              model: root.tabCount
              delegate: Rectangle {
                id: resultRow
                required property int index
                height: root.headerHeight - Style.spacing.sm
                width: tabLabel.implicitWidth + Style.spacing.controlPaddingX * 2
                radius: root.cornerRadius
                color: index === root.currentTab ? root.navigationTabBackground : "transparent"
                border.width: index === root.currentTab ? 1 : 0
                border.color: index === root.currentTab ? root.navigationBorder : "transparent"

                Text {
                  id: tabLabel
                  anchors.centerIn: parent
                  text: index + "  " + root.tabName(index)
                  color: index === root.currentTab
                    ? root.navigation
                    : (index === 1 ? root.success : root.muted)
                  opacity: index === 1 && index !== root.currentTab ? 0.8 : 1
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.weight: index === root.currentTab ? Font.DemiBold : Font.Normal
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    root.currentTab = index
                    root.selectedIndex = 0
                    root.rebuildDisplay()
                  }
                }
              }
            }
          }

          Text {
            visible: root.searchMode
            anchors.left: parent.left
            anchors.right: searchCount.left
            anchors.verticalCenter: parent.verticalCenter
            text: "󰍉  " + (root.searchText || "Search saved snippets and clipboard…") + (root.searchText ? "▍" : "")
            color: root.searchText ? root.foreground : root.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            elide: Text.ElideRight
          }

          Text {
            id: searchCount
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.displayRows.length + (root.displayRows.length === 1 ? " item" : " items")
            color: root.info
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Rectangle {
          width: parent.width
          height: 1
          color: root.muted
          opacity: 0.45
        }

        Item {
          width: parent.width
          height: parent.height - root.headerHeight - root.footerHeight - root.contentSpacing * 4 - 1

          Item {
            id: listPane
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width * 0.38

            ListView {
              id: resultList
              anchors.fill: parent
              anchors.rightMargin: root.contentSpacing
              model: root.displayRows
              clip: true
              spacing: Style.spacing.xs
              boundsBehavior: Flickable.StopAtBounds

              delegate: Rectangle {
                id: snippetRow
                required property int index
                required property var modelData

                readonly property bool hasCursor: root.cursorActive && index === root.selectedIndex
                width: resultList.width
                height: root.rowHeight
                radius: root.cornerRadius
                color: hasCursor ? root.navigationRowBackground : "transparent"
                border.width: hasCursor ? 1 : 0
                border.color: hasCursor ? root.navigationBorder : "transparent"

                Column {
                  anchors.left: parent.left
                  anchors.right: pinIcon.left
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.spacing.rowPaddingX
                  anchors.rightMargin: Style.spacing.sm
                  spacing: Style.spacing.xxs

                  Text {
                    width: parent.width
                    text: snippetRow.modelData.title
                    color: parent.parent.hasCursor ? root.navigation : root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.weight: parent.parent.hasCursor ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    text: root.searchMode ? snippetRow.modelData.categoryName : snippetRow.modelData.subtitle
                    color: root.muted
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }

                Text {
                  id: pinIcon
                  anchors.right: parent.right
                  anchors.rightMargin: Style.spacing.md
                  anchors.verticalCenter: parent.verticalCenter
                  text: snippetRow.modelData.kind === "image" ? "󰋩" : (snippetRow.modelData.pinned ? "󰐃" : "")
                  color: snippetRow.modelData.kind === "image" ? root.info : (snippetRow.modelData.pinned ? root.success : root.muted)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.icon
                }

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onContainsMouseChanged: if (containsMouse) {
                    root.cursorActive = true
                    root.updateSelection(index)
                  }
                  onClicked: {
                    root.updateSelection(index)
                    root.pasteSelected(false)
                  }
                }
              }
            }

            Column {
              anchors.centerIn: parent
              visible: root.displayRows.length === 0
              spacing: Style.spacing.sm

              Text {
                width: parent.width
                text: root.searchMode ? "󰈉" : (root.currentTab === 1 ? "󰐃" : "󰅍")
                color: root.currentTab === 1 ? root.success : root.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.displayLarge
                horizontalAlignment: Text.AlignHCenter
              }

              Text {
                width: parent.width
                text: root.searchMode ? "No matches" : (root.currentTab === 1 ? "Nothing pinned yet" : "No items")
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                horizontalAlignment: Text.AlignHCenter
              }
            }
          }

          Rectangle {
            anchors.left: listPane.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: root.muted
            opacity: 0.4
          }

          Item {
            id: previewPane
            anchors.left: listPane.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: root.contentSpacing * 2

            Flickable {
              id: preview
              anchors.fill: parent
              clip: true
              contentWidth: width
              contentHeight: previewContent.height
              boundsBehavior: Flickable.StopAtBounds

              Column {
                id: previewContent
                width: preview.width
                spacing: Style.spacing.lg

                Image {
                  width: parent.width
                  height: visible ? Math.min(Style.space(430), implicitHeight * width / Math.max(1, implicitWidth)) : 0
                  visible: root.selectedItem !== null && root.selectedItem.kind === "image"
                  source: visible ? Util.fileUrl(root.selectedItem.path) : ""
                  fillMode: Image.PreserveAspectFit
                  asynchronous: true
                  cache: false
                }

                Text {
                  width: parent.width
                  visible: root.selectedItem !== null && root.selectedItem.kind !== "image"
                  text: root.previewText
                  textFormat: Text.PlainText
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  lineHeight: 1.3
                  font.hintingPreference: Font.PreferFullHinting
                  wrapMode: Text.Wrap
                }
              }
            }
          }
        }

        Rectangle {
          width: parent.width
          height: 1
          color: root.muted
          opacity: 0.35
        }

        Item {
          width: parent.width
          height: root.footerHeight

          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: root.statusText || (root.searchMode
              ? "[Esc] navigation   [↑/↓] move   [Enter] paste   [Super+C] copy"
              : "[h/e] tabs   [o/a] move   [f] pin   [s] save   [i] edit   [N/D] tab +/-   [/] search   [p/↵] paste   [y/Super+C] copy   [q] close")
            color: root.statusText ? root.statusColor : root.foreground
            opacity: root.statusText ? 1.0 : 0.65
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.selectedItem && root.selectedItem.source === "saved" && root.selectedItem.pinned ? "󰐃 pinned" : ""
            color: root.success
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      Rectangle {
        anchors.fill: parent
        z: 20
        visible: root.savePickerOpen || root.categoryInputOpen
        radius: root.cornerRadius
        color: Qt.rgba(root.background.r, root.background.g, root.background.b, 0.94)

        Column {
          anchors.centerIn: parent
          width: Math.min(parent.width * 0.5, Style.space(420))
          spacing: Style.spacing.md

          Text {
            width: parent.width
            text: root.categoryInputOpen
              ? (root.categoryInputForSave ? "Create new tab and save" : "New tab")
              : "Save to tab"
            color: root.categoryInputOpen ? root.warning : root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.weight: Font.DemiBold
          }

          Rectangle {
            visible: root.categoryInputOpen
            width: parent.width
            height: root.headerHeight
            radius: root.cornerRadius
            color: root.selectedBackground

            Text {
              anchors.fill: parent
              anchors.margins: Style.spacing.controlPaddingX
              verticalAlignment: Text.AlignVCenter
              text: root.categoryInput ? root.categoryInput + "▍" : "Category name…"
              color: root.categoryInput ? root.foreground : root.selectedText
              opacity: root.categoryInput ? 1 : 0.6
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }

          Repeater {
            visible: root.savePickerOpen
            model: root.categories.length + 1
            delegate: Rectangle {
              required property int index
              visible: root.savePickerOpen
              width: parent.width
              height: visible ? root.headerHeight : 0
              radius: root.cornerRadius
              color: index === root.saveCategoryIndex ? root.selectedBackground : "transparent"

              Text {
                anchors.left: parent.left
                anchors.leftMargin: Style.spacing.controlPaddingX
                anchors.verticalCenter: parent.verticalCenter
                text: index === root.categories.length ? "＋  Create new tab…" : root.categories[index].name
                color: index === root.categories.length
                  ? root.warning
                  : (index === root.saveCategoryIndex ? root.selectedText : root.foreground)
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
            }
          }

          Text {
            width: parent.width
            text: "[Enter] confirm   [Esc] cancel"
            color: root.foreground
            opacity: 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
