# Medral — Discord Music Bot

A Discord music bot with a real-time PyQt6 desktop client.  
Multiple users can connect to the same server and control playback together.

## Architecture

```
bot/
├── bot.py          Discord bot (py-cord, slash commands)
├── audio.py        Audio engine (yt-dlp streaming + FFmpeg)
├── api.py          FastAPI server — REST + WebSocket
└── run_server.bat  One-click server startup

client/
├── main.py         PyQt6 desktop client entry point
├── ui/             UI components (panels)
├── requirements.txt
└── build.bat       PyInstaller packaging → .exe

.env.example        Environment variable template
requirements.txt    Server dependencies
```

## Requirements

- **Python 3.10+**
- **FFmpeg** — must be on `PATH`  
  Download: https://ffmpeg.org/download.html  
  Windows: extract and add the `bin/` folder to your system PATH.
- A **Discord bot token** with the following intents enabled in the Developer Portal:
  - `GUILDS`
  - `GUILD_VOICE_STATES`

---

## Running the server

### 1. Create your `.env` file

```bash
cp .env.example .env
```

Edit `.env` and fill in your token:

```
DISCORD_TOKEN=your_actual_token_here
API_HOST=0.0.0.0
API_PORT=8000
```

### 2. Start

Double-click **`bot/run_server.bat`**  
(or run manually):

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cd bot
uvicorn api:app --host 0.0.0.0 --port 8000
```

The script creates the venv and installs dependencies automatically on first run.

---

## Building the desktop client (.exe)

```bash
client\build.bat
```

The resulting executable will be at `dist\MedralPlayer.exe`.  
No Python installation required on the target machine.

To run the client from source:

```bash
pip install -r client\requirements.txt
python client\main.py
```

---

## Bot slash commands

| Command | Description |
|---------|-------------|
| `/join [channel]` | Connect bot to a voice channel |
| `/play <query>` | Play a track or add to queue |
| `/search <query>` | Show top-5 search results |
| `/skip` | Skip current track |
| `/previous` | Go back to previous track |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/stop` | Stop and clear queue |
| `/leave` | Disconnect bot |
| `/queue` | Show current queue |
| `/volume <0-100>` | Set volume |

---

## Notes

- Audio is streamed directly — no files are downloaded to disk.
- All connected desktop clients receive real-time updates via WebSocket.
- The desktop client connects to the server by IP:PORT (entered on first launch).
- Never commit your `.env` file — it is in `.gitignore`.
