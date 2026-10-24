# Jarvis Assistant Setup

Jarvis runs as a local web dashboard backed by a Python service. It supports
local commands without an API key; general AI responses require a Groq API key.

## Windows setup

1. Install Python 3.10 or newer and ensure Python is available in `PATH`.
2. Run `install.bat`.
3. The installer creates a virtual environment, installs the project
   requirements, and starts the dashboard at `http://127.0.0.1:8765`.
4. Press `Ctrl+C` in the terminal to stop the service.

To enable AI conversations, open **AI CONVERSATION · GROQ** under the dashboard
chat, enter your Groq API key, and choose **CONNECT**. The dashboard saves it to
`%USERPROFILE%\.openjarvis\free.key` on this computer. Use **REMOVE** to delete
the saved key, then use **TEST CONNECTION** to verify it and select an available
chat model. Keys configured as the `GROQ_API_KEY` environment variable take
precedence over a saved dashboard key.

Alternatively, set `GROQ_API_KEY` in PowerShell before launching:

```powershell
$env:GROQ_API_KEY = "your-key"
.\.venv\Scripts\python.exe .\jarvis_server.py
```

## Supported commands

- Open installed apps or supported websites.
- Search Google or YouTube.
- Get the current time or date.
- Adjust system volume on Windows and macOS.
- Ask for public market summaries.
- Use the browser microphone button for speech-to-text when supported.
- Ask general questions when a Groq API key is configured.

Jarvis does not connect to your email or send WhatsApp messages. It can open
Gmail or WhatsApp Web, and WhatsApp message drafts must be reviewed and sent by
you. Market data and technical indicators are informational, not financial
advice. Browser speech recognition may send audio to your browser's speech
provider; check its privacy settings before using the microphone.
Conversation prompts are sent to Groq when cloud AI is enabled. The saved API
key is stored locally in your user profile and is not encrypted; protect access
to your account.

## Troubleshooting

- **Port is already in use:** stop the other process or start with
  `python jarvis_server.py --port 8766`.
- **Voice input is unavailable:** allow microphone access and use a browser
  supporting the Web Speech API, or type in the chat box.
- **General questions do not get AI answers:** check that `GROQ_API_KEY` is set
  in the same terminal used to start Jarvis.
- **App cannot be found:** install it or confirm its command is in `PATH` or its
  shortcut is in the Windows Start Menu.

See [README.md](README.md) for quick-start details and privacy notes.
