# Setup Wizard

The nine saved steps are Welcome, System, Model Provider, GitHub App, Sandbox, Repository, Optional Services, Diagnostics, and Ready. A language switch on the welcome page changes the entire wizard immediately and persists across refresh and login.

A usable instance needs a model, GitHub App, Sandbox, Runtime, and at least one repository. Sandbox can use Local or Shipyard Neo. SMTP is optional. Diagnostics must validate Database, Model, GitHub, Sandbox, Runtime, and Repository before Ready.

For failures, verify the provider base URL and model ID, GitHub installation and permissions, Sandbox write access, `pip check`, and repository default branch and test command. An HTTP 200 alone does not prove the WebUI loaded; verify visible controls and browser Console/Network.
