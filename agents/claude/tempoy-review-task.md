Review and validate a Jira task specification for completeness and implementability.

Use the Tempoy MCP server tools to read ticket details, and search the codebase to verify feasibility.

## Steps

1. **Read the Specification**: If given an issue key, use `get_issue_details` to fetch it. Otherwise, review the specification text provided below.

2. **Research Feasibility**: Search the codebase for files and patterns related to the task. Use `search_tickets` and `analyze_hierarchy` to understand context and related work.

3. **Evaluate Quality** across these dimensions:
   - **Clarity**: Could two developers interpret this differently?
   - **Scope**: Are boundaries well-defined? Is it clear what is NOT included?
   - **Acceptance criteria**: Are there measurable conditions for "done"?
   - **Technical feasibility**: Is this achievable given the current codebase?
   - **Dependencies**: Are prerequisite tasks or external systems identified?
   - **Edge cases**: Are error handling and boundary conditions addressed?
   - **Testing**: Are test expectations clear or inferable?

4. **Report**: Provide a structured review:
   - Overall rating: **Ready** / **Needs Work** / **Underspecified**
   - Specific issues with suggested improvements
   - Questions to strengthen the specification
   - Distinguish between blocking issues (must fix) and suggestions (nice to have)

## Rules

- Be constructive — suggest specific improvements, not vague criticism
- Reference actual code paths and file names from the codebase
- If the spec is already well-defined, confirm it is ready
- Do not create or modify any tickets or project files — advisory only
- When issues are found, suggest the user run the **tempoy-refine-task** agent to apply improvements

Task to review: $ARGUMENTS
