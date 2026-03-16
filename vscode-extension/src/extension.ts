import * as vscode from 'vscode';
import { registerTempoyCommands } from './commands';
import { registerTempoyMcpProvider } from './tempoyMcpProvider';
import { createTempoyStatusBar } from './statusBar';

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(registerTempoyMcpProvider(context));
  context.subscriptions.push(...registerTempoyCommands(context));
  context.subscriptions.push(createTempoyStatusBar(context));
}

export function deactivate(): void {
  // No-op. The MCP server process lifecycle is managed by VS Code.
}
