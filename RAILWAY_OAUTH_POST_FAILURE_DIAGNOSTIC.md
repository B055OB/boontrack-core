# Railway OAuth Post-Failure Diagnostic (`c:\boontrack-core`)

**Date:** 2026-11-12  
**Mode:** STRICT READ-ONLY  
**Target:** Google Antigravity IDE `2.6.0` (VS Code `1.107.0`) / Railway Plugin `v1.7.0`  
**Workspace:** `c:\boontrack-core`

---

## Executive Verdict

| Metric | Finding |
| :--- | :--- |
| **Exact Failure Stage (Post-`08:23:15` Browser Fix)** | **Stage 1 / Pre-Launch & Window Reload (`CodeWindow: failed to load`, `code: -3` at `08:36:01.874` + zero Chrome navigation + zero `CompleteMcpOAuth` calls)** |
| **Previous Logged Failure Stage (Pre-Fix)** | **Stage 5 — Authorization Code Exchange (`CompleteMcpOAuth`)** at **`2026-11-12 07:31:41.359766+07:00`** (`oauth2: "invalid_grant" "grant request is invalid"`) |
| **Current Resulting State (`09:33:13+07:00`)** | **Stage 6 — MCP Initialization Pending Auth (`railway_mcp` waiting on sign-in; `plugin_data\railway` empty)** |
| **Error Category** | Pre-Launch / Silent Browser-Launch & Incomplete IDE Reload (`code: -3` `ERR_ABORTED`, Windows `stderr` suppression `Kr \|\| o.stderr`) + Prior Token-Exchange `invalid_grant` |
| **Sanitized Error Messages** | 1. `2026-11-12 07:31:41.359766`: `failed to exchange code for token: oauth2: "invalid_grant" "grant request is invalid"`<br>2. `2026-11-12 08:36:01.874`: `CodeWindow: failed to load (reason: <unknown>, code: -3)`<br>3. `list_plugin_accounts` (`09:33:13`): `railway_mcp: The plugin "railway" needs the user to sign in.` |
| **Browser Launch Occurred?** | **No evidence in browser history or logs** (`0` Chrome/Edge/Brave/Firefox/Opera visits to Railway OAuth or callback URLs on `2026-11-12`; silent Windows `stderr` gap documented below) |
| **Callback Received (`oauth-callback`)?** | **No** (`0` visits to `https://antigravity.google/oauth-callback` in any browser profile on `2026-11-12`) |
| **Code Exchange Occurred?** | **Pre-fix (`07:31:41`): Yes (rejected `invalid_grant`)** / **Post-fix (`08:23:15`–`09:33`): No (`0` `CompleteMcpOAuth` calls)** |
| **Confidence Level** | **High** (for non-reachability of Chrome OAuth URL, absence of post-`08:23` `CompleteMcpOAuth` RPCs, and IDE/Windows code paths); **Medium** only on whether the Founder clicked **Sign in** inside an incognito session or whether `open` PowerShell launch failed silently after `08:23:15` (unlogged because `Kr = true` on Windows). |

---

## Stage-by-Stage Breakdown (Phase A)

| OAuth Stage | Status (`2026-11-12`) | Exact Evidence |
| :--- | :--- | :--- |
| **1. IDE Reload & Browser Launch (`workbench.externalBrowser`)** | **FAILED / NOT REACHED POST-FIX** | After `settings.json` was updated at `08:23:15`, IDE session folder remained `20261109T193755`; none of `window1`/`window2`/`window4` restarted `exthost.log`; `main.log` `L605` recorded `08:36:01.874 [error] CodeWindow: failed to load (reason: <unknown>, code: -3)`. Chrome `History` across all profiles contains `0` Railway OAuth visits. |
| **2. Authorization Endpoint (`https://backboard.railway.com/oauth/auth`)** | **NOT REACHED IN BROWSER** | Server discovery works (`mcp.railway.com` returns `401 Unauthorized` + PKCE `authUrl` targeting `backboard.railway.com/oauth/auth?[REDACTED]`), but **zero** browser requests loaded `backboard.railway.com/oauth/auth` or `railway.com/authorize` in Chrome, Edge, Brave, Firefox, or Opera today. |
| **3. User Consent** | **NOT COMPLETED** | Active Chrome `Profile 29` visited Railway dashboard pages (`07:25:37`–`07:39:48`) but never loaded `/oauth/auth` or granted workspace consent. |
| **4. Callback / Redirect (`https://antigravity.google/oauth-callback`)** | **NOT REACHED / NOT RECEIVED** | `0` visits to `https://antigravity.google/oauth-callback` across all browsers. Code analysis confirms Antigravity MCP OAuth (`H` / `zln` / `jln` in [jetskiAgent/main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/jetskiAgent/main.js), `te` / `X9o` / `H9o` in [workbench.desktop.main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/vs/workbench/workbench.desktop.main.js)) relies on **copying/pasting the code shown on `antigravity.google/oauth-callback`**, while [extension.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/extensions/agy/vscode/extension.js) `handleUri` handles only `/oauth-success`, `/auth-success`, and `/open-conversation`. |
| **5. Authorization Code Exchange (`CompleteMcpOAuth`)** | **FAILED PRE-FIX (`07:31:41`); NOT INVOKED POST-FIX (`08:23:15`–`09:33`)** | [cli-20261110_130220.log](file:///C:/Users/Alldy/.gemini/antigravity/log/cli-20261110_130220.log) `L22134` (`07:31:41.359766`) logged the single `/exa.language_server_pb.LanguageServerService/CompleteMcpOAuth (unknown)` call, rejected with `oauth2: "invalid_grant" "grant request is invalid"`. Zero calls occurred after `08:23:15`. |
| **6. MCP Initialization (`railway_mcp`)** | **FAILED (`Unauthorized` / Pending Sign-In)** | `list_plugin_accounts` (`09:33:13`) reports `railway_mcp: The plugin "railway" needs the user to sign in.`, and [plugin_data/railway](file:///C:/Users/Alldy/.gemini/antigravity/plugin_data/railway) remains empty (`0` files). |

---

## Detailed Evidence & Timeline (`2026-11-12`, UTC+7)

### 1. Plugin & `list_plugin_accounts` State
- **`list_plugin_accounts` (`09:33:13+07:00`):**
  ```text
  No installed plugins declare account sign-ins.
  Plugin MCP servers waiting on a sign-in:
  - railway_mcp: The plugin "railway" needs the user to sign in. Put <plugin-card catalog-id="railway"></plugin-card> on its own line so they can sign in from the chat, then stop: the conversation continues once they sign in. Do not work around it.
  ```
- **Plugin manifest & MCP registration:**
  - [config.json](file:///C:/Users/Alldy/.gemini/config/config.json): `railway` installed (`antigravity-plugins-partners/plugin/railway`, `version: "1.7.0"`).
  - [plugin.json](file:///C:/Users/Alldy/.gemini/config/plugins/railway/plugin.json) & [mcp_config.json](file:///C:/Users/Alldy/.gemini/config/plugins/railway/mcp_config.json): `version: "1.7.0"`, `mcpServers.mcp.serverUrl: "https://mcp.railway.com"`.
  - [plugin_data/railway](file:///C:/Users/Alldy/.gemini/antigravity/plugin_data/railway): exists (`mtime 2026-11-12 06:31:05`), **`0` files** stored.

### 2. Chronological Log & Browser Forensics
- **`06:31:04`–`06:31:05`:** Railway plugin v`1.7.0` installed (`config.json`, `plugin_data\railway` created).
- **`06:33:05`:** `AppData\Roaming\Antigravity\credential-user-scope` touched (associated with the separate `Antigravity.exe` `2.11.0.0` installation registered on `antigravity://`, whereas active `Antigravity IDE.exe` `2.6.0` is registered on `antigravity-ide://`). Note `AppData\Roaming\Antigravity\logs` contains no `2026-11-12` log files.
- **`06:41:29.221`–`07:43:21.898`:** [main.log](file:///C:/Users/Alldy/AppData/Roaming/Antigravity%20IDE/logs/20261109T193755/main.log) `L580`–`L594` logged `CodeWindow: detected unresponsive` -> `recovered from unresponsive`.
- **`07:25:37`–`07:39:48`:** Chrome `Profile 29` (`C:\Users\Alldy\AppData\Local\Google\Chrome\User Data\Profile 29\History`) shows manual visits to `https://railway.com/dashboard` and `https://railway.com/project/[REDACTED]/settings` (`/tokens`, `/usage`, `/members`, `/observability`), with **zero** `/oauth/auth` or `antigravity.google/oauth-callback` visits.
- **`07:31:41.359766`:** [cli-20261110_130220.log](file:///C:/Users/Alldy/.gemini/antigravity/log/cli-20261110_130220.log) `L22134` (`c:\boontrack-core` hub):
  ```text
  L22134: E1112 07:31:41.359766  701044 interceptor.go:70] /exa.language_server_pb.LanguageServerService/CompleteMcpOAuth (unknown): failed to exchange code for token: oauth2: "invalid_grant" "grant request is invalid"
  ```
- **`07:59:00.550020`:** [cli-20261110_130220.log](file:///C:/Users/Alldy/.gemini/antigravity/log/cli-20261110_130220.log) `L22565` recorded the diagnostic `GetMcpServerStates` check (which showed `calling "initialize": sending "initialize": Unauthorized` and valid PKCE `authUrl` targeting `https://backboard.railway.com/oauth/auth?[REDACTED]`).
- **`08:23:15`:** Phases 1–2 of the minimal browser fix created [settings.json.bak.20261112_0823](file:///C:/Users/Alldy/AppData/Roaming/Antigravity%20IDE/User/settings.json.bak.20261112_0823) and set `"workbench.externalBrowser": "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"` in [settings.json](file:///C:/Users/Alldy/AppData/Roaming/Antigravity%20IDE/User/settings.json).
- **`08:36:01.874`:** [main.log](file:///C:/Users/Alldy/AppData/Roaming/Antigravity%20IDE/logs/20261109T193755/main.log) `L605` recorded:
  ```text
  L605: 2026-11-12 08:36:01.874 [error] CodeWindow: failed to load (reason: <unknown>, code: -3)
  ```
  - Source mapping in [main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/main.js) (`@1018212`): emitted by `this._win.webContents.on("did-fail-load", ...)` -> `onWindowError(3, ...)` (`code: -3` = Chromium `ERR_ABORTED`).
  - **Crucial window/host finding:** No new Antigravity session folder was created after `20261109T193755`, none of `window1`, `window2`, or `window4` restarted `exthost.log` (`mtime`s remained `2026-11-11 10:03:13`, `2026-11-12 04:31:29`, `2026-11-11 16:01:34`), and `agy.exe` (`cli-20261110_130220.log`) did not restart.
- **`08:23:15`–`09:33` Log Verification Across All IDE/CLI Logs:**
  - **`cli-*.log` (`cli-20261109_193932.log`, `cli-20261109_194010.log`, `cli-20261110_130220.log`):** **Zero** `/CompleteMcpOAuth` calls, **zero** `invalid_grant` errors, **zero** `GetMcpServerStates` calls, and **zero** `backboard.railway.com` / `antigravity.google` events after `07:59:00`.
  - **`main.log` & `auth.log`:** `auth.log` was not modified on `2026-11-12` (`mtime 2026-11-11 03:48:02`). `main.log` has **zero** `openExternalBrowser`, `Configured external browser path does not exist`, `Error openening external URL`, `Unable to open external URL`, or `will-navigate` errors.
  - **`1-Antigravity LS.log` (`window1`, `window2`, `window4`):** In `window4` (`c:\boontrack-core`, `895` lines), `[settings]` logged `OnWebviewFocused` (`L867`–`L872`), with **zero** `ExtensionApi/OpenUrl` calls. (`window1` `L5791` and `window2` `L1198` `OpenUrl` entries occurred in unrelated workspace sessions with empty logged payloads.)
  - **Unrelated periodic noise ruled out:** `renderer.log` in `window1` (`L2007`/`L2010`), `window2` (`L843`/`L846`), and `window4` (`L2538` at `08:18:08`, `L2547`/`L2550` at `09:13:10`–`09:13:12`) logged `command 'antigravity.handleAuthRefresh' not found` alongside scheduled 5-minute `cloudcode.log` token/model calls (`v1internal:loadCodeAssist`), confirming this is Antigravity's periodic Google CloudCode refresh rather than Railway MCP OAuth.
  - **Windows Defender & Crash Logs (`>= 07:20`):** Windows Defender Operational event log shows **zero** detections or blocked child processes; Windows Error Reporting (`Application`) shows zero crashes for `Antigravity IDE.exe`, `chrome.exe`, `powershell.exe`, or `agy.exe` (only queued pre-existing `11/03`–`11/05` BlueScreen reports at `07:57:56`).
- **Browser History Across All Detected Profiles (`2026-11-12`):**
  - Chrome `Profile 29`: active during `08:36:24`–`09:14:02` (`chatgpt.com`), `0` Railway OAuth or `antigravity.google/oauth-callback` visits.
  - Chrome `Profile 48` (`05:00`–`09:12`, Docs/Gemini), `Profile 52` (`03:38`–`06:19`, `dashboard.localhost:3000`), `Profile 53` (`03:37`, `console.cloud.google.com`): `0` Railway or OAuth callback visits; no other Chrome profile (`Default`, `Guest Profile`, or remaining `Profile *`) had `History` modified on `2026-11-12`.
  - Edge `Default` (`07:57:15`, Instagram only); Brave, Firefox, Opera: `0` visits on `2026-11-12`. `360Chrome` directory does not exist; `360extremebrowser.exe` does not exist on disk.

---

## Code-Level Root Cause Analysis (Why Browser Launch Fails Silently on Windows)

Inspection of Antigravity IDE's bundled runtime clarifies why **clicking "Sign in" can leave the UI appearing to wait while Chrome never opens and no error is logged**:

1. **Unawaited `window.open` + Blind State Transition:**
   - In [jetskiAgent/main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/jetskiAgent/main.js) (`H(K.serverName)`) and [workbench.desktop.main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/vs/workbench/workbench.desktop.main.js) (`te(se.serverName)`), clicking MCP **Sign in** synchronously caches `authUrl` into the pending-paste map (`y(...)` / `N`) — immediately showing `"Paste the code shown after you sign in."`, `"Reopen sign-in page"`, and the `"Paste code"` input (`zln`/`jln` & `X9o`/`H9o`) — and calls `tA(window, Q, "_blank", "noopener,noreferrer")` (`window.open`), **regardless of whether the external browser actually spawns**.
   - In Electron main ([main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/main.js) `@12756590`), `webContents#setWindowOpenHandler` denies the popup (`{action: "deny"}`), logs only at `trace` level (hidden in default `info` `main.log`), and invokes `this.nativeHostMainService?.openExternal(void 0, a.url)` **without `await`**.

2. **Windows `stderr` Suppression Bug in `openExternalBrowser` (`out/main.js`):**
   - In [main.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/out/main.js) (`@869256`–`869696`), `openExternalBrowser` reads `workbench.externalBrowser` dynamically (`this.configurationService.getValue("workbench.externalBrowser")`), spawns Node's `open` package (`open(url, { app: { name: ... } })`), and checks:
     ```js
     Kr||o.stderr?.once("data",l=>(this.logService.error(`Error openening external URL '${n}' using browser '${i}': ${l.toString()}`),this.doOpenShellExternal(t,n)))
     ```
   - Directly verified at `@317799` (`NM = Jp.platform === "win32"`, `Kr = NM`): **`Kr` is `isWindows` (`true`)**. Because `Kr || ...` short-circuits on Windows, **Electron never attaches the `stderr` listener**, **never logs subprocess errors from PowerShell/`Start-Process`**, and **never falls back to `doOpenShellExternal`** on Windows!
   - Meanwhile, [node_modules/open/index.js](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/node_modules/open/index.js) (`L216–257`) handles `win32` + explicit `app` by spawning `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand` running `Start "\`"${app}\`"" -ArgumentList "\`"${url}\`""`. Any failure in that detached PowerShell spawn is completely unlogged on Windows due to `Kr || ...`.

---

## Phase B — Safe Configuration & Binary Verification

| Check | Verified Value | Status |
| :--- | :--- | :--- |
| **IDE Product Version** | `version: "1.107.0"`, `ideVersion: "2.6.0"`, `urlProtocol: "antigravity-ide"` ([product.json](file:///C:/Users/Alldy/AppData/Local/Programs/Antigravity%20IDE/resources/app/product.json)) | Valid (`Antigravity IDE 2.6.0`) |
| **`workbench.externalBrowser`** | `"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"` ([settings.json](file:///C:/Users/Alldy/AppData/Roaming/Antigravity%20IDE/User/settings.json)) | Valid JSON; target binary exists (`True`) |
| **Settings Backup** | [settings.json.bak.20261112_0823](file:///C:/Users/Alldy/AppData/Roaming/Antigravity%20IDE/User/settings.json.bak.20261112_0823) | Present & intact outside Git |
| **Railway Plugin Version** | `1.7.0` (`antigravity-plugins-partners/plugin/railway`) | Installed & enabled |
| **`plugin_data\railway`** | `0` files | Empty (no stored OAuth credentials) |

---

## Recommended Minimal Next Action (Read-Only Report — No Changes Made)

1. **Minimal Zero-Code, Zero-Config Workaround (Founder Interactive Step):**
   - Because Antigravity's MCP Sign-In UI **always renders the `"Reopen sign-in page"` link (`<a href={authUrl} target="_blank">`) and `"Paste code"` box** (`X9o` / `H9o` / `zln` / `jln`) after clicking **Sign in**, and because Antigravity MCP OAuth expects a **fresh code copy/pasted from `https://antigravity.google/oauth-callback`** rather than a local callback listener:
     1. **Fully restart Antigravity IDE** (close and reopen `Antigravity IDE.exe` `2.6.0` cleanly, since the earlier reload left `CodeWindow` `-3` / un-restarted `exthost`), or open the Railway MCP Sign-In UI.
     2. Click **Sign in** once.
     3. If Chrome still does not open automatically, **right-click `"Reopen sign-in page"` -> Copy link address** (without sharing the URL), paste/open it directly in **Chrome `Profile 29`** (already signed into Railway), approve access on Railway's consent page, wait for `https://antigravity.google/oauth-callback` to display the fresh authorization code, and paste that fresh code immediately into Antigravity's **`"Paste code"`** box -> **Submit**.

2. **Secondary Browser-Launch Check (Pending Separate Authorization):**
   - If Chrome fails to open specifically when `workbench.externalBrowser` is set to the full path `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe` (vs `"chrome"` alias or unset/OS `UserChoice`), note that Windows `UserChoice` already resolves `https` -> `ChromeHTML` -> `chrome.exe`; reverting `workbench.externalBrowser` to `settings.json.bak.20261112_0823` or testing `"chrome"` would require separate authorization.

