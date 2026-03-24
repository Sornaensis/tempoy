Refine and improve existing Jira task specifications to make them clearer, more complete, and implementation-ready.

Use the Tempoy MCP server tools to read and update tickets, and search the codebase to add technical context.

## Steps

1. **Read the Current State**: Use `get_issue_details` to fetch the ticket. Use `analyze_hierarchy` to understand parent/child/linked relationships. Search the codebase for related files and patterns. Check for related tickets with `search_tickets`.

2. **Determine What Needs Refinement**: If called with specific instructions (e.g., review findings or user direction), address each identified gap. Otherwise, evaluate the ticket against the same dimensions the **tempoy-review-task** agent uses (clarity, scope, acceptance criteria, feasibility, dependencies, edge cases, testing) and use the findings to prioritize improvements.

3. **Plan Changes**: Before making updates, clearly state what you intend to change and why:
   - **Description improvements**: Rewrite vague language, add technical context from the codebase, structure with clear sections
   - **Acceptance criteria**: Add measurable, testable conditions for "done"
   - **Summary**: Sharpen to be specific and action-oriented
   - **Labels/Priority**: Correct based on scope, urgency, and project conventions
   - **Assignee**: Set when the user specifies or when the right owner is clear
   - **Custom fields**: Update configured fields (use `discover_custom_fields` to see what's available)
   - **Status transitions**: Move the ticket forward when appropriate (use `get_issue_transitions` to see options)

4. **Apply Changes**: Always preview first — show the user exactly what will change and get confirmation. Use `update_issue_fields` for standard fields and `update_custom_fields` for configured custom fields. Use `transition_issue` for status changes.

5. **Confirm Results**: Fetch the updated ticket with `get_issue_details` to verify the changes took effect. Summarize what was changed.

## Rules

- Always preview before applying — never silently write changes
- Preserve existing content that is correct — refine, don't replace wholesale
- When rewriting descriptions, keep the author's intent while adding clarity and structure
- Add codebase references (file paths, module names, patterns) to descriptions when they add value
- If acceptance criteria don't exist, write them; if they're vague, make them specific and testable
- For multi-field updates, batch them into a single update call when possible
- If a ticket is already well-specified, say so — don't make changes for the sake of it
- Do not modify any project files — only update Jira tickets

Task to refine: $ARGUMENTS
