# Jarvis AI Assistant

Jarvis is a local browser-based assistant with a holographic dashboard, text chat,
optional browser speech input/output, and a Python command service. Local actions
work without an AI key. General questions use Groq when `GROQ_API_KEY` is set.

## Run on Windows

1. Install Python 3.10 or newer.
2. Double-click `install.bat`, or run it from PowerShell/Command Prompt.
3. The installer creates `.venv`, installs dependencies, and starts Jarvis.
4. The dashboard opens at `http://127.0.0.1:8765`.

To start it later:

```powershell
.\.venv\Scripts\python.exe .\jarvis_server.py
```

Press `Ctrl+C` in the server terminal to stop Jarvis.

## Enable AI answers

Create a Groq API key in your Groq account, open **AI CONVERSATION · GROQ**
under the chat controls, paste the key, and select **CONNECT**. The key is
stored on this computer in `~/.openjarvis/free.key` (on Windows:
`%USERPROFILE%\.openjarvis\free.key`). Select **REMOVE** in the same panel to
delete the saved key. Once saved, select **TEST CONNECTION**. Jarvis checks
Groq's current model catalog and chooses an available chat model. A saved key
is not considered connected until this test succeeds.

Alternatively, set the key in PowerShell before starting Jarvis:

```powershell
$env:GROQ_API_KEY = "your-key"
.\.venv\Scripts\python.exe .\jarvis_server.py
```

An environment key takes precedence over a saved dashboard key. The dashboard
shows when that is the active configuration. Without a key, supported local
commands continue to work and general questions explain that cloud AI is not
configured.

## Try these commands

- `What time is it?`
- `Open VS Code`
- `Search for placement interview tips`
- `Play jazz on YouTube`
- `Check my unread emails` (Jarvis does not access an inbox; it explains this)
- `Stock market update` (fetches public market data when requested)
- `Help`

For WhatsApp, Jarvis opens a prepared message in WhatsApp Web; choose the contact
and review the text yourself before sending. Market summaries are informational,
not financial advice.

Use the dashboard's text box or microphone button. Select **MIC** to record and
**STOP** to send the recording for transcription. Recording requires browser
microphone permission and a configured Groq key. Choose a locally available
browser voice under **SPOKEN VOICE**; Jarvis remembers the selection in this
browser. The Hugging Face recordings are not cloned or used for speech
generation.

## Privacy and safety

- The server binds to `127.0.0.1` and refuses non-local network interfaces.
- API keys are entered through the local dashboard and are never returned by
  the settings API or written to server logs. The key file is stored in your
  user profile; it is not encrypted, so protect access to your Windows account.
- General AI conversation prompts and microphone recordings (after you select
  **STOP**) are sent to Groq when a key is configured. Recording stays in the
  browser until you stop it; audio is limited to 30 seconds and 10 MB for
  transcription.
- Local commands run on this computer. Review messages before sending them.
- Groq transcribes microphone audio using its `whisper-large-v3-turbo` model.
  Groq's speech-to-text API has a 10-second minimum billed length, even for
  shorter recordings.
- Speech output uses the browser's installed voices. The provided voice-sample
  dataset is not cloned or uploaded by Jarvis.
- Email and messaging accounts are not connected or read by Jarvis.

## Files

- `jarvis_server.py` — local dashboard server and command API
- `jarvis_brain.py` — local action routing and optional Groq AI
- `jarvis_actions.py` — app, website, time, volume, and market commands
- `jarvis_market.py` — public Yahoo Finance data helpers
- `jarvis_workplace.html` — dashboard, chat, and browser voice controls
- `jarvis_voice.py` — optional terminal microphone client
