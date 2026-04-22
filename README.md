# SAMEStation

SAMEStation is a local NOAA Weather Radio `S.A.M.E.` decoder and alert capture app.

## Important Disclaimer

This entire project is AI-generated with Codex GPT-5.4.

SAMEStation is not meant to be relied on as an actual life-safety alerting program. Use a real NOAA Weather Radio and other official alerting sources for actual emergency warning coverage.

## What The App Does

- Decodes `S.A.M.E.` headers from local audio files
- Decodes from direct audio-file links and live stream URLs
- Monitors a server-side audio input device continuously
- Resolves SAME/FIPS location codes to real county and location names
- Detects repeated header bursts and `NNNN` end-of-message bursts

## Server Audio Monitoring

- Watches a selected Windows audio input device on the server side
- Keeps a configurable pre-alert audio buffer before detection
- Starts recording as soon as an alert is detected
- Stops after the full EOM burst sequence, with timeout fail-safes
- Saves alert audio as `.wav` files
- Supports live listening to the monitored server audio

## Alerts And Recordings

- Publishes alerts immediately when detected, then updates them when recording finishes
- Keeps decoded alert details, raw burst history, and recording status together
- Shows finished recordings with in-app playback
- Stores alert history and server settings locally
- Clears and updates alerts from the server side, not just in the browser

## RSS Feed

- Generates an RSS feed for captured alerts
- Includes the decoded alert details in each feed item
- Adds the recorded audio file to the alert when one is available
- Keeps one feed item per alert and updates it as recording completes

## ntfy Phone Notifications

- Sends free phone alerts through `ntfy`
- Supports separate notifications for first detection and recording completion
- Supports separate click targets for detected alerts and completed alerts
- Can optionally open completed alerts directly on the saved recording
- Lets warnings, watches, advisories, tests, and other alert types use different urgency levels

## Desktop App Modes

- `Server` mode runs the local server and shows a built-in server console
- `Client` mode opens the SAMEStation app against an existing SAMEStation server
- `Both` mode runs the local server, shows the server console, and opens the client window
- The launcher remembers the last mode and launch settings you used
- The launcher can also enable automatic startup at sign-in from a checkbox

## Desktop Launch Arguments

- `SAMEStation.exe --server` launches the local server and server console
- `SAMEStation.exe --client --server-url http://127.0.0.1:8000` launches the client against an existing server
- `SAMEStation.exe --both` launches the local server, server console, and client window together
- `SAMEStation.exe --server --auto-start-monitor` auto-starts the server audio monitor using the saved device and saved timing settings
- `SAMEStation.exe --both --auto-start-monitor --device-id 3 --pre-roll 10 --max-record 180` auto-starts monitoring with explicit values
- `SAMEStation.exe --server --port 8010` starts the local server on a different port

## Server Console

- Shows live server and monitor log output
- Supports built-in commands like `help`, `status`, `devices`, `settings`, `alerts`, `start`, `stop`, `clear`, `open`, and `shutdown`
- Lets you control the server monitor without opening a separate terminal
