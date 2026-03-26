Create new Jira tasks through Tempoy for the current project.

Use the Tempoy MCP server tools to interact with Jira. Follow this workflow:

## Steps

1. **Gather Context**: Read the codebase to understand the project. Use `list_projects` to find the target Jira project. Use `search_tickets` to check for existing related work. Ask the user which project to target if not obvious.

2. **Scope the Work**: Based on the user's request below, determine if this requires a single task or an epic with child tickets. Interview the user if the requirements are unclear.

3. **Validate Each Ticket**: Before creating each ticket, thoroughly review the specification. If available, suggest the user run the **tempoy-review-task** agent for a formal assessment. Otherwise, check:
   - Is the goal unambiguous?
   - Are acceptance criteria defined and measurable?
   - Is the scope clear — what is included AND what is excluded?
   - Is it technically feasible based on the codebase?
   - Are edge cases and error handling addressed?

4. **Create Tickets**: Use `get_project_create_schema` to understand available fields. Create tickets one at a time with `create_ticket` — always preview first, then apply with confirmation. For epics, create the parent first, then link children via `parent_key`.

5. **Summarize**: List all created tickets with their keys and summaries.

## Rules

- Always preview before creating — confirm with the user before applying
- Write descriptions in standard markdown (headings, bold, italic, lists, tables, code blocks, links) — Tempoy converts to Jira's format automatically, never use Jira wiki markup
- Write implementation-aware descriptions using codebase context
- Include clear acceptance criteria in every ticket
- Use specific, actionable language in summaries
- Check for duplicate tickets before creating new ones
- Only use Tempoy MCP tools for Jira operations — do not modify any project files

User request: $ARGUMENTS
