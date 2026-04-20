# SAMECode

SAMECode is a local NOAA Weather Radio `S.A.M.E.` decoder and alert capture app.

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
- `Client` mode opens the SAMECode app against an existing SAMECode server
- `Both` mode runs the local server, shows the server console, and opens the client window

## Server Console

- Shows live server and monitor log output
- Supports built-in commands like `help`, `status`, `devices`, `settings`, `alerts`, `start`, `stop`, `clear`, `open`, and `shutdown`
- Lets you control the server monitor without opening a separate terminal
