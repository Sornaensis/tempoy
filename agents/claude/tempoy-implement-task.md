Implement a Jira task end-to-end: create a branch, write code, run tests, push, and open a pull request.

Use the Tempoy MCP server tools for Jira operations and standard tools for coding.

## Steps

1. **Understand the Task**: Use `get_issue_details` to read the ticket. Use `analyze_hierarchy` for parent/sibling context. Read the relevant codebase to understand architecture and conventions.

2. **Set Up Branch**: Determine the base branch (usually main or develop) from git config and conventions. Create a feature branch: `git checkout -b <issue-key>-<short-description>`. Use `transition_issue` to move the ticket to "In Progress" — preview first, then apply.

3. **Plan**: Break the task into ordered implementation phases. Each phase should be a buildable, testable increment. Identify files to create or modify, and test files to update.

4. **Implement Iteratively**: For each phase:
   - Write the code changes
   - Run the project's build/compile commands
   - Run the test suite
   - Fix any failures before proceeding

   Detect tooling from: package.json (npm), Makefile, pyproject.toml/pytest.ini (pytest), Cargo.toml (cargo), go.mod (go), *.sln/*.csproj (dotnet), build.gradle/pom.xml (gradle/maven).

5. **Push**: Review changes for consistency. Commit with a conventional commit message referencing the issue key: `feat(scope): description [ISSUE-KEY]`. Push the branch: `git push -u origin <branch-name>`.

6. **Open PR**: Use `gh pr create` if GitHub CLI is available. Include the ticket key and link in the PR description. Set the base branch appropriately. If `gh` is unavailable, provide the URL for manual creation.

7. **Update Ticket**: Use `update_issue_fields` to update the ticket if the implementation changed scope.

## Rules

- Never commit directly to main/develop — always use a feature branch
- Run tests after each significant change, not just at the end
- Follow existing code style and conventions in the repository
- Write or update tests for all new functionality
- Keep commits focused and atomic
- If blocked, stop and clearly describe what help is needed

Ticket to implement: $ARGUMENTS
