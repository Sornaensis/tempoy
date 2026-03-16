import * as vscode from 'vscode';
import { getExtensionConfig } from './config';

function diagnoseConnectionError(error: unknown, apiBaseUrl: string): string {
  const msg = error instanceof Error ? error.message : String(error);
  if (msg.includes('ECONNREFUSED') || msg.includes('fetch failed')) {
    return [
      `Cannot reach Tempoy API at ${apiBaseUrl}.`,
      'Possible causes:',
      '• Tempoy application is not running',
      '• Tempoy Copilot API is not enabled in settings',
      `• API is running on a different port (check tempoy.apiBaseUrl setting)`,
      '',
      'Start Tempoy and enable the Copilot API, then try again.'
    ].join('\n');
  }
  if (msg.includes('ETIMEDOUT') || msg.includes('timeout')) {
    return `Connection to Tempoy API at ${apiBaseUrl} timed out. Check that the port is correct and not blocked by a firewall.`;
  }
  return `Tempoy API error: ${msg}`;
}

async function fetchJson(url: string, init?: RequestInit): Promise<any> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.headers || {})
    }
  });

  let payload: any = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (!response.ok) {
    const detail = typeof payload?.error === 'string' ? payload.error : `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }

  return payload;
}

export function registerTempoyCommands(context: vscode.ExtensionContext): vscode.Disposable[] {
  const checkApiHealth = vscode.commands.registerCommand('tempoy.checkApiHealth', async () => {
    const config = getExtensionConfig(context);
    try {
      const payload = await fetchJson(`${config.apiBaseUrl}/health`);
      void vscode.window.showInformationMessage(`Tempoy API: ${payload.status} (${payload.mode}) at ${payload.bound_host}:${payload.bound_port}`);
    } catch (error) {
      const guidance = diagnoseConnectionError(error, config.apiBaseUrl);
      void vscode.window.showErrorMessage(`Tempoy API health check failed`, { modal: false, detail: guidance } as vscode.MessageOptions, 'Show Details').then(choice => {
        if (choice === 'Show Details') {
          const channel = vscode.window.createOutputChannel('Tempoy');
          channel.appendLine(guidance);
          channel.show();
        }
      });
    }
  });

  const showConnectionStatus = vscode.commands.registerCommand('tempoy.showConnectionStatus', async () => {
    const config = getExtensionConfig(context);
    try {
      const [health, capabilities] = await Promise.all([
        fetchJson(`${config.apiBaseUrl}/health`),
        fetchJson(`${config.apiBaseUrl}/capabilities`)
      ]);
      const lines = [
        `Tempoy API status: ${health.status}`,
        `Mode: ${health.mode}`,
        `Session active: ${health.session_active ? 'yes' : 'no'}`,
        `Tempoy API base URL: ${config.apiBaseUrl}`,
        `Projects read enabled: ${capabilities.endpoints?.projects_read ? 'yes' : 'no'}`,
        `Issues read enabled: ${capabilities.endpoints?.issues_read ? 'yes' : 'no'}`,
        `Issues refine enabled: ${capabilities.endpoints?.issues_refine ? 'yes' : 'no'}`,
        `Issues create enabled: ${capabilities.endpoints?.issues_create ? 'yes' : 'no'}`
      ];
      const document = await vscode.workspace.openTextDocument({
        language: 'markdown',
        content: `# Tempoy Connection Status\n\n${lines.map((line) => `- ${line}`).join('\n')}\n`
      });
      await vscode.window.showTextDocument(document, { preview: false });
    } catch (error) {
      const guidance = diagnoseConnectionError(error, config.apiBaseUrl);
      void vscode.window.showErrorMessage(`Unable to get Tempoy connection status. ${guidance}`);
    }
  });

  const openMcpConfiguration = vscode.commands.registerCommand('tempoy.openMcpConfiguration', async () => {
    const choice = await vscode.window.showQuickPick(
      [
        { label: 'Workspace MCP Configuration', target: 'workspace' }
      ],
      { placeHolder: 'Open the workspace MCP configuration file?' }
    );

    if (!choice || choice.target !== 'workspace') {
      return;
    }

    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
      void vscode.window.showWarningMessage('Open a workspace folder to create or edit .vscode/mcp.json.');
      return;
    }

    const mcpConfigUri = vscode.Uri.joinPath(workspaceFolder.uri, '.vscode', 'mcp.json');
    try {
      await vscode.workspace.fs.stat(mcpConfigUri);
    } catch {
      const initialContent = JSON.stringify(
        {
          servers: {
            tempoy: {
              type: 'stdio',
              command: 'python',
              args: ['-m', 'tempoy_app.mcp_server'],
              env: {
                PYTHONPATH: '${workspaceFolder}',
                TEMPOY_API_BASE_URL: 'http://127.0.0.1:8765',
                TEMPOY_MCP_CLIENT_NAME: 'tempoy-vscode'
              }
            }
          }
        },
        null,
        2
      );
      await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(workspaceFolder.uri, '.vscode'));
      await vscode.workspace.fs.writeFile(mcpConfigUri, new TextEncoder().encode(initialContent));
    }

    const document = await vscode.workspace.openTextDocument(mcpConfigUri);
    await vscode.window.showTextDocument(document, { preview: false });
  });

  const startMcpSessionTest = vscode.commands.registerCommand('tempoy.startMcpSessionTest', async () => {
    const config = getExtensionConfig(context);
    try {
      const payload = await fetchJson(`${config.apiBaseUrl}/session/start`, {
        method: 'POST',
        body: JSON.stringify({ client_name: 'tempoy-vscode-command' }),
        headers: {
          'Content-Type': 'application/json'
        }
      });
      void vscode.window.showInformationMessage(`Tempoy session started. Mode: ${payload.mode}. Expires at: ${payload.expires_at ?? 'unknown'}`);
    } catch (error) {
      const guidance = diagnoseConnectionError(error, config.apiBaseUrl);
      void vscode.window.showErrorMessage(`Tempoy session test failed. ${guidance}`);
    }
  });

  return [checkApiHealth, showConnectionStatus, openMcpConfiguration, startMcpSessionTest];
}
