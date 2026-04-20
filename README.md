# SAMECode

SAMECode is a local web app that decodes NOAA Weather Radio `S.A.M.E.` headers from:

- Local audio files your browser can decode
- Direct links to audio files
- Live stream URLs
- A server-side audio input device that can run continuously

The server-side device monitor can:

- Listen on a chosen Windows audio input device all the time
- Keep a configurable pre-roll buffer, defaulting to `10` seconds
- Start recording when a SAME header is detected
- Stop on detected `NNNN` EOM bursts or a configurable timeout
- Save `.wav` recordings under [data/recordings](C:/Users/tyler/Desktop/SAMECODE/data/recordings)
- Publish captured alerts with recording enclosures through [alerts.xml](http://127.0.0.1:8000/alerts.xml)
- Push free phone notifications through `ntfy`

## Install

The bundled runtime already has `numpy`, but the always-on server monitor needs `sounddevice`:

```powershell
& "C:\Users\tyler\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pip install -r requirements.txt
```

## Run

```powershell
& "C:\Users\tyler\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## CLI

While the server is running, the terminal now shows timestamped logs and accepts commands:

```text
help
status
devices
settings
alerts 10
start 3 10 180
stop
clear
open
shutdown
```

Notes:

- `start <deviceId> [preRoll] [maxRecord]` starts the always-on device monitor from the terminal.
- `devices` lists available server-side input devices and their numeric IDs.
- `shutdown` cleanly stops the web server and monitor.

## ntfy Phone Alerts

To get push notifications on your phone for detected alerts:

1. Install the `ntfy` app on your phone.
2. Subscribe to a topic name you choose, such as `my-private-same-topic`.
3. In the SAMECode web console, open `ntfy Phone Alerts`.
4. Set:
   - `Server URL` to `https://ntfy.sh` unless you self-host ntfy
   - `Topic` to the topic you subscribed to
   - optionally `Click URL` to the reachable URL of this SAMECode server, for example `http://192.168.1.50:8000`
5. Enable notifications and choose whether to notify on first detection, recording completion, or both.

Notes:

- Topics on public `ntfy.sh` are effectively secret-by-name unless you reserve them, so pick something hard to guess.
- If you self-host ntfy, put that base URL in `Server URL` instead.
- If `Click URL` is set, tapping the phone notification can take you to the SAMECode console or recording link.

## Test

Browser decoder tests:

```powershell
& "C:\Users\tyler\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --test
```

Python backend decoder tests:

```powershell
& "C:\Users\tyler\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -p "test_*.py"
```

## Notes

- The browser still handles local file decode and browser-playable URL/live-stream decode.
- The audio-device list and device capture are now server-side, not browser-side.
- SAME `+TTTT` is a purge/valid time, not the guaranteed voice-message length, so the recording timeout is configurable instead of derived from the header.
- Captured alerts are persisted in [data/alerts.json](C:/Users/tyler/Desktop/SAMECODE/data/alerts.json).
