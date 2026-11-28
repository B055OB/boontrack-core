# Railway OAuth Connectivity Diagnostic (Google Antigravity on Windows)

**Date:** 2026-11-12  
**Target Environment:** Google Antigravity IDE (`2.6.0` / VS Code `1.107.0`) + `agy.exe` (`1.5.4`) on Windows (`10.0.26100`)  
**Workspace:** `c:\boontrack-core`  
**Mode:** STRICT READ-ONLY DIAGNOSTIC  
**Status:** Complete — awaiting CTO authorization before any corrective changes

---

## Executive Summary

Clicking **Sign in** for Railway inside Google Antigravity IDE does not fail because `railway` or `railway_mcp` is missing, nor because `mcp.railway.com` is unreachable. Both are installed, enabled, and reaching `https://mcp.railway.com` (receiving an expected HTTP `401 Unauthorized` + valid PKCE OAuth authorization metadata for `https://backboard.railway.com/oauth/auth?[REDACTED_QUERY]`).

Instead, the diagnostic uncovered **four concrete, interacting failure/anomaly vectors**:

1. **Category A — Antigravity Sign-In Launch Path & Unresponsive Renderer Window (`workbench.desktop.main.js` / `out/main.js` / `main.log`):**
   - Unlike Google Account login (which emits `ANTIGRAVITY_OPEN_URL:` -> `vscode.env.openExternal` and logs `[LAUNCH] Intercepted auth URL` / errors), MCP plugin **Sign in** (`te()` in `workbench.desktop.main.js`, identical handler in `jetskiAgent/main.js`) calls raw DOM `window.open(authUrl, "_blank", "noopener,noreferrer")`. Electron's `setWindowOpenHandler` (`out/main.js`) immediately returns `{action: "deny"}` and invokes `nativeHostMainService?.openExternal(void 0, a.url)` without `await` and logs only at `trace` level (suppressed in default `info` logs).
   - Simultaneously, clicking **Sign in** unconditionally flips UI state into `"Restart sign-in"` + `"Paste the code shown after you sign in"` (`X9o` / `H9o`), masking whether the browser launch actually occurred.
   - Compounding this, `main.log` recorded **`CodeWindow: detected unresponsive` for 61 minutes 52 seconds (`2026-11-12 06:41:29.221` to `07:43:21.898`)**, spanning almost the entire interval after `railway` was installed (`06:31:05`).
2. **Category B — Windows Legacy HTTP/HTTPS Protocol Corruption + Antigravity Deep-Link Split:**
   - While Windows 11 `UserChoice`, `UserChoiceLatest\ProgId`, COM `IApplicationAssociationRegistration`, and `AssocQueryString("https")` resolve to `ChromeHTML` -> `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`, legacy **`HKCU\Software\Classes\{http,https}\shell\open\command`**, **`HKEY_CLASSES_ROOT\{http,https}\shell\open\command`**, and **`HKCU\Software\Clients\StartMenuInternet`** still point to a **deleted browser (`360 Extreme Browser` / `360extremebrowser.exe`, `MISSING` on disk)**. Any Windows API or launcher consulting `HKCR\{http,https}\shell\open\command` or `StartMenuInternet` instead of `UserChoice` fails against a non-existent binary.
   - Separately, **`antigravity://`** in Windows Registry launches the dormant **`Antigravity.exe` (`2.11.0.0`)** rather than the running **`Antigravity IDE.exe` (`2.6.0`, registered under `antigravity-ide://`)**.
3. **Category C & E — Pending MCP OAuth State + Failed Token Exchange (`invalid_grant`):**
   - `C:\Users\Alldy\.gemini\antigravity\plugin_data\railway` is empty (`0` files), and `railway_mcp` remains in `MCP_SERVER_STATUS_ERROR` (`calling "initialize": sending "initialize": Unauthorized`).
   - At `2026-11-12 07:31:41.359`, `c:\boontrack-core`'s `agy.exe` hub (`cli-20261110_130220.log`) recorded `/exa.language_server_pb.LanguageServerService/CompleteMcpOAuth` failing with `"invalid_grant" "grant request is invalid"` (consistent with submitting an empty/invalid/stale code into the `H9o` paste box or replaying an expired grant).

---

## Phase 1 — Plugin Installation & Railway MCP Registration State

| Check | Observed Value | Evidence Reference |
| :--- | :--- | :--- |
| Plugin installed | Yes (`railway`) | `agy.exe plugin list`, `search_marketplace` (`"installed": true`) |
| Plugin enabled | Yes (`enabled`, global scope) | `C:\Users\Alldy\.gemini\config\config.json`, `GetAllPlugins` RPC (`isGlobal: true`) |
| Version & source | `1.7.0` from `antigravity-plugins-partners` (`antigravity-plugins-partners/plugin/railway`) | [plugin.json](file:///C:/Users/Alldy/.gemini/config/plugins/railway/plugin.json), `agy.exe plugin list` |
| Plugin components | `1` skill (`use-railway`), `1` MCP server (`railway-mcp` / registered as `railway_mcp`) | [mcp_config.json](file:///C:/Users/Alldy/.gemini/config/plugins/railway/mcp_config.json), [SKILL.md](file:///C:/Users/Alldy/.gemini/config/plugins/railway/skills/use-railway/SKILL.md) |
| Duplicate user MCP config | None (`mcp_config.json` has no `mcpServers`; `~/.gemini/antigravity/mcp_config.json` not present) | `C:\Users\Alldy\.gemini\config\mcp_config.json`, direct filesystem check |
| `plugin_auth_providers` | Empty (`list_plugin_accounts` reports none declared; Railway uses MCP OAuth instead) | `list_plugin_accounts` tool output |
| MCP server registration | Registered as `railway_mcp` (`serverUrl: "https://mcp.railway.com"`) | `GetMcpServerStates` RPC, [mcp_config.json](file:///C:/Users/Alldy/.gemini/config/plugins/railway/mcp_config.json) |
| Current auth / runtime state | **Pending Sign-In** (`status: MCP_SERVER_STATUS_ERROR`, `error: "calling \"initialize\": sending \"initialize\": Unauthorized"`) | `list_plugin_accounts`, `GetMcpServerStates` RPC |
| OAuth metadata issued | `authUrl`: `https://backboard.railway.com/oauth/auth?[REDACTED_QUERY]` (`redirect_uri=https://antigravity.google/oauth-callback`, `client_id=https://antigravity.google/oauth/client-metadata.json`, `resource=https://mcp.railway.com`, `scope=workspace:member`, `code_challenge_method=S256`) | `GetMcpServerStates` RPC (sanitized) |
| Local plugin token/data dir | `C:\Users\Alldy\.gemini\antigravity\plugin_data\railway` (created `2026-11-12 06:31:05`, **empty — 0 files**) | Direct filesystem inspection |

---

## Phase 2 — Windows Browser Launch & Antigravity Environment Diagnostics

### 1. Windows HTTP / HTTPS & Custom Protocol Associations

| Registry / API Check | Observed Value | Status |
| :--- | :--- | :--- |
| `HKCU\...\UrlAssociations\http\UserChoice` | `ProgId = ChromeHTML`, `Hash = 1+81u5pbOsM=` (`UserChoiceLatest\ProgId = ChromeHTML`) | Valid |
| `HKCU\...\UrlAssociations\https\UserChoice` | `ProgId = ChromeHTML`, `Hash = GXdZdTowOz8=` (`UserChoiceLatest\ProgId = ChromeHTML`) | Valid |
| COM `IApplicationAssociationRegistration.QueryCurrentDefault` (`http`, `https`, `AL_EFFECTIVE`) | `ChromeHTML` | Valid |
| `AssocQueryString(https, ASSOCSTR_COMMAND)` | `"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --single-argument %1` | Valid |
| `HKCR\ChromeHTML\shell\open\command` | `"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --single-argument %1` | Valid |
| **`HKCU\Software\Classes\http\shell\open\command`** | `"C:\Users\Alldy\AppData\Local\360extremebrowser\Chrome\Application\360extremebrowser.exe" -- "%1"` | **BROKEN (`MISSING` on disk)** |
| **`HKCU\Software\Classes\https\shell\open\command`** | `"C:\Users\Alldy\AppData\Local\360extremebrowser\Chrome\Application\360extremebrowser.exe" -- "%1"` | **BROKEN (`MISSING` on disk)** |
| **`HKCR\http\shell\open\command`** & **`HKCR\https\shell\open\command`** | Inherits HKCU override -> `"C:\Users\Alldy\AppData\Local\360extremebrowser\Chrome\Application\360extremebrowser.exe" -- "%1"` (plus HKLM `CommandId=IE.Protocol` / `DelegateExecute={17FE9752-0B5A-4665-84CD-569794602F5C}` under `http`) | **BROKEN (`MISSING` on disk)** |
| **`HKCU\Software\Clients\StartMenuInternet`** | `360 Extreme Browser` (subkey `shell\open\command` is `MISSING`) | **BROKEN / Stale** |
| `HKLM\Software\Classes\{http,https}\shell\open\command` | `"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" "%1"` (with Edge `DelegateExecute` on `http`) | Masked by HKCU `360extremebrowser` |
| **`HKCU\Software\Classes\antigravity\shell\open\command`** | `"C:\Users\Alldy\AppData\Local\Programs\antigravity\Antigravity.exe" "%1"` | **MISMATCH (points to dormant `Antigravity.exe` `2.11.0.0`, not active `Antigravity IDE.exe` `2.6.0`)** |
| `HKCU\Software\Classes\antigravity-ide\shell\open\command` | `"C:\Users\Alldy\AppData\Local\Programs\Antigravity IDE\Antigravity IDE.exe" "--open-url" "--" "%1"` | Points to active `Antigravity IDE.exe` |

### 2. Browser, Launcher & IDE Binaries on Disk

| Binary | Presence | Product Version / Runtime State |
| :--- | :--- | :--- |
| `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe` | `EXISTS` | `156.0.8078.81` (running under `PID 21272`, session `console` ID `1`) |
| `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` | `EXISTS` | `157.0.4341.46` (running under `PID 35764`) |
| `C:\WINDOWS\system32\rundll32.exe` | `EXISTS` | `10.0.26100.1` |
| `C:\Users\Alldy\AppData\Local\360extremebrowser\Chrome\Application\360extremebrowser.exe` | **`MISSING`** | Orphaned registry target |
| `C:\Users\Alldy\AppData\Local\Programs\Antigravity IDE\Antigravity IDE.exe` | `EXISTS` | `2.6.0` (VS Code `1.107.0`; active `PID 22812`, extension host `PID 4748`) |
| `C:\Users\Alldy\AppData\Local\Programs\Antigravity\Antigravity.exe` | `EXISTS` | `2.11.0.0` (not running; `AppData\Roaming\Antigravity\credential-user-scope` touched `2026-11-12 06:33:05`) |
| `C:\Users\Alldy\.gemini\bin\agy.exe` | `EXISTS` | `1.5.4` (running for `c:\boontrack-core` as `PID 21328` on `--hub-port=60325`) |

### 3. Antigravity Process Environment & Browser Launch Chain

- **Windows environment variables:** `SYSTEMROOT=C:\WINDOWS`, `WINDIR=C:\WINDOWS`, `COMSPEC=C:\WINDOWS\system32\cmd.exe`, `PATHEXT=.COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.CPL`.
- **Process ancestry & integrity:** `explorer.exe (PID 13960)` -> `Antigravity IDE.exe (PID 14004)` -> `Antigravity IDE.exe (PID 22812)` -> `Antigravity IDE.exe (PID 4748)` -> `agy.exe (PID 21328)` -> child shells. Integrity level is `Medium Mandatory Level` (standard non-elevated user `Alldy`, active `console` session `1`, `rdp-tcp` listening).
- **`PATH` observation:** `%PATH%` contains `C:/Users/Alldy/.gemini/antigravity/bin`, `C:\WINDOWS\system32`, `C:\WINDOWS`, and `C:\Users\Alldy\AppData\Local\Programs\Antigravity IDE\bin`, **but does not include `C:\Users\Alldy\.gemini\bin`** (so bare `agy` is not on `%PATH%` without its full path).
- **IDE `settings.json` browser setting:** [settings.json](file:///C:/Users/Alldy/AppData/Roaming/Antigravity%20IDE/User/settings.json) does **not** set `workbench.externalBrowser`.
- **Exact code path when clicking Railway "Sign in" / "Authenticate":**
  - In [workbench.desktop.main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/vs/workbench/workbench.desktop.main.js) (`$wd`, offset `~12699200`–`12706580`, mirrored in [main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/jetskiAgent/main.js) around `7599491`), the **Accounts** **"Sign in"** handler `te(se.serverName)` looks up `authUrl` in `M`, updates local state to show `"Paste the code shown after you sign in"` + `"Reopen sign-in page"` + `"Paste code"` input (`X9o`/`H9o`), and calls `AB(window, re, "_blank", "noopener,noreferrer")` -> `window.open(...)`. The **MCP** **"Authenticate"** button (`xwd` -> `wpn.handleAuthorize`) likewise calls `AB(window, l, "_blank")`.
  - In Electron main ([main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/main.js) offset `12756590`), `app.on("web-contents-created", ...)` attaches `setWindowOpenHandler`, logs `webContents#setWindowOpenHandler` at `trace` level only, invokes `this.nativeHostMainService?.openExternal(void 0, a.url)` without `await`, and returns `{action: "deny"}`.
  - When `workbench.externalBrowser` is unset, `openExternal` (`out/main.js` offset `869256`) routes `http`/`https` via `openExternalBrowser` -> `doOpenShellExternal` -> `electron.shell.openExternal(url)`. (If `shell.openExternal` throws/rejects, `doOpenShellExternal` opens an error `showMessageBox`; no such error dialog or log occurred.)
  - By contrast, Antigravity's Google login (`2-Antigravity.log`) routes through `ANTIGRAVITY_OPEN_URL:` -> [extension.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/extensions/agy/vscode/extension.js) (`handleInterceptedAuthUrl`, offset `1125186`) -> `vscode.env.openExternal(Uri.parse(a))`, which explicitly logs `[LAUNCH] Intercepted auth URL`, `[LAUNCH WARNING]`, and `[LAUNCH ERROR]`. Agents/Settings webviews in `extensions/agy` also run inside a sandboxed `<iframe sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-popups-to-escape-sandbox">` (`extension.js` offset `3338550`).

### 4. Sanitized Antigravity & Windows Log Excerpts (`2026-11-12`)

- **Plugin installation & RemoteControl state** (`C:\Users\Alldy\.gemini\antigravity\log\cli-20261110_130220.log`, `c:\boontrack-core` hub):
  ```text
  L21997: I1112 06:31:04.261115     274 server.go:4363] [RemoteControl] Subscription callback triggered.
  L21998: I1112 06:31:04.278572     274 server.go:4366] [RemoteControl] RemoteControlEnabled value: false
  L21999: I1112 06:31:04.350087     274 server.go:5455] [RemoteControl] CLI launched without --remote-control, staying disconnected
  ```
- **Prolonged Electron `CodeWindow` UI unresponsiveness** (`C:\Users\Alldy\AppData\Roaming\Antigravity IDE\logs\20261109T193755\main.log`):
  ```text
  L580: 2026-11-12 06:41:29.221 [error] CodeWindow: detected unresponsive
  L581: 2026-11-12 06:41:44.249 [error] CodeWindow unresponsive samples:
  L582-587: <1> at workbench.desktop.main.js:2799:3331 / MessagePort.O (workbench.desktop.main.js:2791:10207) / $ (workbench.desktop.main.js:2791:8445)
  L590: 2026-11-12 07:31:37.261 [warning] [perf] profiling STARTED f3558a9d-ade3-4ef1-a30c-373fa540bba4
  L591: 2026-11-12 07:31:42.306 [warning] [perf] profiling DONE f3558a9d-ade3-4ef1-a30c-373fa540bba4
  L594: 2026-11-12 07:43:21.898 [error] CodeWindow: recovered from unresponsive
  ```
- **Failed `CompleteMcpOAuth` token exchange** (`C:\Users\Alldy\.gemini\antigravity\log\cli-20261110_130220.log`):
  ```text
  L22134: E1112 07:31:41.359766  701044 interceptor.go:70] /exa.language_server_pb.LanguageServerService/CompleteMcpOAuth (unknown): failed to exchange code for token: [REDACTED] "invalid_grant" "grant request is invalid"
  ```
- **Jetski PostMessageTransport errors in renderer logs** (`window2\renderer.log` & `window4\renderer.log`):
  ```text
  window2\renderer.log L801: 2026-11-12 06:31:57.466 [error] [Extension Host] [Jetski] PostMessageTransport error: {"type":"postmessage-rpc","channel":"agy-ext-antigravity-api","requestId":121,"rpcPath":"/gemini_coder.agent_ui_toolkit.iframe.AntigravityApi/SetFileDiffs","error":true,"errorVal":{"message":"Endpoint /gemini_coder.agent_ui_toolkit.iframe.AntigravityApi/SetFileDiffs not implemented","code":5},"source":"antigravity-iframe"}
  window4\renderer.log L2535: 2026-11-12 07:40:07.945 [error] [Extension Host] [Jetski] PostMessageTransport error: {"type":"postmessage-rpc","channel":"agy-ext-antigravity-api","requestId":464,"rpcPath":"/gemini_coder.agent_ui_toolkit.iframe.AntigravityApi/SetFileDiffs",...}
  ```
- **Working Google OAuth baseline (`2-Antigravity.log` in `window4`, sanitized):**
  ```text
  L24: [LAUNCH] Spawning C:\Users\Alldy\.gemini\bin\agy.exe (v1.5.4) --hub --hub-port=60325 --app_data_dir=antigravity --csrf_token=[REDACTED] --add-dir=c:\boontrack-core
  L26: [HUB STDOUT] ANTIGRAVITY_OPEN_URL: https://accounts.google.com/o/oauth2/auth?[REDACTED_QUERY]
  L27: [LAUNCH] Intercepted auth URL: https://accounts.google.com/o/oauth2/auth?[REDACTED_QUERY]
  ```
- **Negative findings (verified absent):**
  - Zero `[LAUNCH ERROR]` or `[LAUNCH WARNING] vscode.env.openExternal returned false` entries in any `2-Antigravity.log` (excluding a harmless startup `SIGTERM` on earlier closed windows).
  - Zero `ExtensionApi/OpenUrl` calls for `backboard.railway.com` in `window1`/`window2`/`window4` `1-Antigravity LS.log` (the only `OpenUrl` calls logged — `window1` `L5791` and `window2` `L1198` — returned `error: false` with empty logged payloads).
  - Zero `webContents#will-navigate` errors, zero Windows WER/CrashDumps for Chrome, Antigravity IDE, or `360extremebrowser.exe` today (`2026-11-12`).

---

## Phase 3 — Safe Alternative Authentication Assessment (`docs.railway.com/ai/antigravity-plugin`)

1. **Official Railway Antigravity docs (`https://docs.railway.com/ai/antigravity-plugin`):**
   - Documents two integration mechanisms: the full Antigravity plugin (`use-railway` skill + hosted `railway-mcp` server via `agy plugin install`) and explicit MCP configuration via Railway CLI (`railway mcp install --agent antigravity`).
   - Also documents that `mcp.railway.com` supports **OAuth Mode** (browser-authorized tokens scoped to selected workspaces) and **CLI Credentials Mode** (delegating through local Railway CLI credentials rather than storing long-lived tokens in editor configs). Note that the local bundled [SKILL.md](file:///C:/Users/Alldy/.gemini/config/plugins/railway/skills/use-railway/SKILL.md) enumerates `claude-code`, `cursor`, `codex`, `opencode`, `copilot`, and `factory-droid` under `railway mcp install` targets rather than explicitly naming `antigravity`.
2. **Antigravity CLI route (`agy plugin list`):**
   - `C:\Users\Alldy\.gemini\bin\agy.exe` (`1.5.4`) **is present and works**, confirming `railway (enabled, 1.7.0)` is already installed. Re-installing via `agy plugin install` is **not** needed and was **not** executed.
   - Because `C:\Users\Alldy\.gemini\bin` is missing from Windows `%PATH%`, invoking bare `agy` from a default terminal fails (`CommandNotFoundException`) unless called by full path.
3. **Railway CLI route (`railway mcp install --agent antigravity`):**
   - **Not currently available on this host:** standalone `railway.exe` / `@railway/cli` was not found in `%PATH%`, `%APPDATA%\npm`, `%LOCALAPPDATA%\Programs`, WinGet packages, Cargo, Scoop, or `Program Files`. Because Railway CLI is absent and no mutations/logins are permitted in read-only mode, `railway mcp install --agent antigravity` was not executed.

---

## Phase 4 — OAuth Failure Classification

| Category | Status | Evidence & Technical Reasoning |
| :--- | :--- | :--- |
| **A. Browser launch failure** | **Verified Contributing Cause** | Railway MCP **Sign in** relies on raw renderer `window.open(..., "_blank", "noopener,noreferrer")` -> Electron `setWindowOpenHandler` (`{action: "deny"}` + unawaited `shell.openExternal`, `trace`-only logging) rather than `ANTIGRAVITY_OPEN_URL` / `vscode.env.openExternal`. Furthermore, `main.log` shows a **61m52s `CodeWindow: detected unresponsive` state (`06:41:29`–`07:43:21`)**, and `te()` switches UI state to `"Paste code"` even if the browser never opens, producing silent failure with zero error logs. |
| **B. Windows protocol association failure** | **Verified Registry Corruption (Legacy Keys + Deep-Link Split)** | `HKCU\Software\Classes\{http,https}\shell\open\command`, `HKCR\{http,https}\shell\open\command`, and `HKCU\Software\Clients\StartMenuInternet` point to **non-existent `360extremebrowser.exe`** (`MISSING`), creating a split against valid `UserChoice`/`ChromeHTML` (`chrome.exe`). Additionally, `antigravity://` launches dormant `Antigravity.exe` (`2.11.0.0`) instead of running `Antigravity IDE.exe` (`2.6.0`, registered only as `antigravity-ide://`). |
| **C. Antigravity plugin authentication state failure** | **Verified Present** | `railway` v`1.7.0` is enabled globally, `plugin_data\railway` is empty (`0` files), `list_plugin_accounts` reports no plugin auth providers, and `railway_mcp` sits in pending-auth error state. |
| **D. Railway MCP server connection failure** | **Ruled Out as Root Cause** | `railway_mcp` (`https://mcp.railway.com`) connects cleanly and receives a valid `401 Unauthorized` + `authUrl` from `https://backboard.railway.com/oauth/auth?[REDACTED_QUERY]`. |
| **E. OAuth callback failure** | **Verified Event Observed** | `cli-20261110_130220.log` `L22134` (`07:31:41.359`) records `/exa.language_server_pb.LanguageServerService/CompleteMcpOAuth` failing with `"invalid_grant" "grant request is invalid"`. Because `redirect_uri` uses `https://antigravity.google/oauth-callback` and the UI immediately reveals the `"Paste code"` box upon clicking **Sign in**, submitting an invalid/stale/manual value (or an `antigravity://` callback misrouted to `Antigravity.exe` `2.11.0.0`) explains the `"invalid_grant"` rejection. |
| **F. Plugin installation / version mismatch** | **Ruled Out (Minor CLI `%PATH%` Gap Only)** | `railway` `1.7.0` manifest, skill, and `mcp_config.json` are intact and uncorrupted without duplicates. Only `C:\Users\Alldy\.gemini\bin` is absent from Windows `%PATH%`, and standalone `railway` CLI is not installed. |
| **G. Not verifiable (read-only boundary)** | **Bounded Unknowns** | (1) Live runtime behavior of `electron.shell.openExternal("https://...")` / `ShellExecuteExW` / `rundll32 url.dll,FileProtocolHandler` was not tested to avoid launching a browser window or altering state; (2) `setWindowOpenHandler` `trace` events are unlogged at default `info` level; (3) the Founder's exact remote-access transport outside Antigravity IDE (`CLI --remote-control` was disconnected) is not directly visible in Antigravity logs. |

---

## Phase 5 — Recommended Minimal Next Action (Pending CTO Authorization)

When the CTO / Founder authorizes next steps, execute **only the minimal set needed** in order:

1. **Test / Restart UI & Configure Explicit Browser Launch Target (Safest Zero-Registry-Risk Action in Antigravity IDE):**
   - Reload or restart the recovered Antigravity IDE window (`CodeWindow` had a 62-minute unresponsive stall), OR explicitly set `"workbench.externalBrowser": "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"` in `%APPDATA%\Antigravity IDE\User\settings.json`.
   - Why this helps immediately: `out/main.js` (`openExternalBrowser`) checks `workbench.externalBrowser` **first** and launches that exact binary directly via Node's `open` package (PowerShell `Start-Process` with explicit executable path), completely bypassing Electron `shell.openExternal`, `HKCR\https\shell\open\command`, and `StartMenuInternet`.
2. **Interactive Founder OAuth Completion (Manual Paste Fallback Supported Built-In):**
   - Note that the Antigravity MCP Sign-In UI (`X9o` / `H9o`) already exposes `"Reopen sign-in page"` (copyable link) and `"Paste the code shown after you sign in"` (`Submit` -> `CompleteMcpOAuth`). Once the Founder authorizes `railway_mcp` interactively in Chrome on their trusted session and pastes the resulting authorization code (or completes callback), `CompleteMcpOAuth` stores credentials in `plugin_data\railway` without modifying any Railway config or project source.
3. **Optional Windows Hygiene Cleanup (Separate Approval):**
   - Remove orphaned `360extremebrowser.exe` overrides under `HKCU\Software\Classes\{http,https}` and `HKCU\Software\Clients\StartMenuInternet` via Windows **Default Apps** (re-apply Chrome as default HTTP/HTTPS handler), and reconcile the `antigravity://` protocol target vs `Antigravity IDE.exe`.
   - Optionally install `@railway/cli` or add `C:\Users\Alldy\.gemini\bin` to user `%PATH%` only if CLI-based Railway workflows (`railway mcp install --agent antigravity`) are desired.

