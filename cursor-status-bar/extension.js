// FILE: cursor-status-bar/extension.js
// PURPOSE: Нижняя панель Cursor — читает ~/.cursor-limits/cache.json.
// WHY: Токен авторизации остаётся только в Python; расширение не ходит в сеть.
//
// Отображение:
//   ● % · spent $ · ₽ · дни до сброса · токены сегодня
//   цвет ● плавно green→yellow→red по status_bar_color из кэша
//   hover — status_bar_tooltip (дни недели: № · день · tok · $ · ₽)

const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const os = require("os");

/** @type {vscode.StatusBarItem | undefined} */
let statusItem;
/** @type {NodeJS.Timeout | undefined} */
let timer;

/**
 * @param {string} configured
 * @returns {string[]}
 */
function candidateCachePaths(configured) {
  const list = [];
  if (configured && configured.trim()) {
    list.push(configured.trim());
  }
  list.push(path.join(os.homedir(), ".cursor-limits", "cache.json"));
  const folders = vscode.workspace.workspaceFolders || [];
  for (const f of folders) {
    list.push(path.join(f.uri.fsPath, "data", "cache.json"));
  }
  return list;
}

/**
 * @returns {{ file: string, data: any } | null}
 */
function readCache() {
  const cfg = vscode.workspace.getConfiguration("cursorLimitsStatusBar");
  const configured = cfg.get("cachePath", "");
  for (const file of candidateCachePaths(configured)) {
    try {
      if (!fs.existsSync(file)) continue;
      const raw = fs.readFileSync(file, "utf8");
      const data = JSON.parse(raw);
      return { file, data };
    } catch {
      // next
    }
  }
  return null;
}

/**
 * Подставляем цветной ● в начало строки status_bar_text.
 * @param {string} text
 * @param {string} hex
 */
function withColoredDot(text, hex) {
  const body = String(text || "Cursor limits").replace(/^[●🟢🟡🔴⚠]\s*/, "");
  // VS Code status bar принимает color как hex-строку в Electron
  return `● ${body}`;
}

function paint() {
  if (!statusItem) return;
  const hit = readCache();
  if (!hit) {
    statusItem.text = "$(warning) Cursor limits: нет кэша";
    statusItem.tooltip =
      "Запусти трей CursorLimits (python -m src или CursorLimits.exe).\n" +
      "Кэш: %USERPROFILE%\\.cursor-limits\\cache.json";
    statusItem.color = undefined;
    statusItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
    return;
  }

  const { data } = hit;
  const hex = data.status_bar_color || "#22c55e";
  const text = withColoredDot(data.status_bar_text || "Cursor limits", hex);
  statusItem.text = text;

  // Плавный цвет индикатора (foreground status bar item)
  try {
    statusItem.color = hex;
  } catch {
    statusItem.color = undefined;
  }
  statusItem.backgroundColor = undefined;

  const tip = data.status_bar_tooltip || data.tray_title || "";
  const md = new vscode.MarkdownString();
  md.isTrusted = false;
  md.supportHtml = true;
  const safe = String(tip)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const colorSpan = `<span style="color:${hex};">●</span> <b>${Number(data.status_bar_percent || 0).toFixed(0)}%</b>`;
  md.appendMarkdown(`${colorSpan}\n\n`);
  md.appendMarkdown("```\n" + safe + "\n```");
  statusItem.tooltip = md;
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  statusItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusItem.command = "cursorLimitsStatusBar.refresh";
  statusItem.show();
  context.subscriptions.push(statusItem);

  context.subscriptions.push(
    vscode.commands.registerCommand("cursorLimitsStatusBar.refresh", () => {
      paint();
      vscode.window.setStatusBarMessage("Cursor Limits: status bar обновлён", 1500);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("cursorLimitsStatusBar.openCache", async () => {
      const hit = readCache();
      if (!hit) {
        vscode.window.showWarningMessage("cache.json не найден — сначала запусти трей.");
        return;
      }
      const doc = await vscode.workspace.openTextDocument(hit.file);
      await vscode.window.showTextDocument(doc, { preview: true });
    })
  );

  paint();
  const sec = vscode.workspace
    .getConfiguration("cursorLimitsStatusBar")
    .get("refreshIntervalSec", 30);
  timer = setInterval(paint, Math.max(5, Number(sec) || 30) * 1000);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

function deactivate() {
  if (timer) clearInterval(timer);
}

module.exports = { activate, deactivate };
