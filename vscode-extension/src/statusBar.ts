import * as vscode from 'vscode';
import { getExtensionConfig } from './config';

const POLL_INTERVAL_MS = 30_000;

export function createTempoyStatusBar(context: vscode.ExtensionContext): vscode.Disposable {
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
  item.command = 'tempoy.showConnectionStatus';
  item.name = 'Tempoy Status';
  setDisconnected(item);
  item.show();

  const poll = async () => {
    const config = getExtensionConfig(context);
    try {
      const response = await fetch(`${config.apiBaseUrl}/health`, {
        headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(5000)
      });
      if (response.ok) {
        const payload = await response.json() as { status?: string; mode?: string };
        setConnected(item, payload.mode ?? 'unknown');
      } else {
        setDisconnected(item);
      }
    } catch {
      setDisconnected(item);
    }
  };

  void poll();
  const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);

  return new vscode.Disposable(() => {
    clearInterval(timer);
    item.dispose();
  });
}

function setConnected(item: vscode.StatusBarItem, mode: string): void {
  item.text = `$(check) Tempoy: ${mode}`;
  item.tooltip = `Tempoy API connected (${mode} mode). Click to show details.`;
  item.backgroundColor = undefined;
}

function setDisconnected(item: vscode.StatusBarItem): void {
  item.text = '$(warning) Tempoy: offline';
  item.tooltip = 'Tempoy API not reachable. Click to diagnose.';
  item.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
}
