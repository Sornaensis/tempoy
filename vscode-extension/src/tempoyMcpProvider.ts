import * as vscode from 'vscode';
import { buildMcpEnvironment, getExtensionConfig } from './config';

export function registerTempoyMcpProvider(context: vscode.ExtensionContext): vscode.Disposable {
  return vscode.lm.registerMcpServerDefinitionProvider('tempoy', {
    provideMcpServerDefinitions: async () => {
      const config = getExtensionConfig(context);
      return [
        new vscode.McpStdioServerDefinition(
          'Tempoy MCP Server',
          config.pythonCommand,
          ['-m', 'tempoy_app.mcp_server'],
          buildMcpEnvironment(config),
          config.serverVersion
        )
      ];
    },
    resolveMcpServerDefinition: async (server: vscode.McpStdioServerDefinition) => {
      return server;
    }
  });
}
