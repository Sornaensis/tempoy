import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

const DEFAULT_PORT = 8765;
const TEMPOY_CONFIG_FILE = path.join(os.homedir(), '.tempoy', 'config.json');

export interface TempoyExtensionConfig {
  apiBaseUrl: string;
  pythonCommand: string;
  clientName: string;
  serverVersion: string;
  repoRoot: string;
}

/**
 * Read the copilot_api_port from ~/.tempoy/config.json.
 * Returns undefined if the file doesn't exist or can't be parsed.
 */
function readTempoyConfigPort(): number | undefined {
  try {
    const raw = fs.readFileSync(TEMPOY_CONFIG_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    const port = Number(parsed?.copilot_api_port);
    if (Number.isInteger(port) && port > 0 && port <= 65535) {
      return port;
    }
  } catch {
    // File doesn't exist or isn't valid JSON — fall through
  }
  return undefined;
}

export function getExtensionConfig(context: vscode.ExtensionContext): TempoyExtensionConfig {
  const configuration = vscode.workspace.getConfiguration('tempoy');
  const configuredPython = configuration.get<string>('mcp.pythonCommand')?.trim();
  const pythonDefaultInterpreter = vscode.workspace.getConfiguration('python').get<string>('defaultInterpreterPath')?.trim();

  const explicitBaseUrl = configuration.get<string>('apiBaseUrl')?.trim();
  let apiBaseUrl: string;
  if (explicitBaseUrl) {
    apiBaseUrl = explicitBaseUrl;
  } else {
    const discoveredPort = readTempoyConfigPort();
    apiBaseUrl = `http://127.0.0.1:${discoveredPort ?? DEFAULT_PORT}`;
  }

  return {
    apiBaseUrl,
    pythonCommand: configuredPython || pythonDefaultInterpreter || 'python',
    clientName: configuration.get<string>('mcp.clientName', 'tempoy-vscode').trim() || 'tempoy-vscode',
    serverVersion: configuration.get<string>('mcp.serverVersion', '0.1.0').trim() || '0.1.0',
    repoRoot: path.resolve(context.extensionPath, '..')
  };
}

export function buildMcpEnvironment(config: TempoyExtensionConfig): Record<string, string> {
  const mergedPythonPath = [
    config.repoRoot,
    process.env.PYTHONPATH || ''
  ].filter(Boolean).join(path.delimiter);

  return {
    ...process.env,
    PYTHONPATH: mergedPythonPath,
    TEMPOY_API_BASE_URL: config.apiBaseUrl,
    TEMPOY_MCP_CLIENT_NAME: config.clientName
  } as Record<string, string>;
}
