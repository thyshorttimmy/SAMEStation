# SAMEStation

SAMEStation is a local NOAA Weather Radio `S.A.M.E.` decoder and alert capture project with a split `Server` and `Client` product model.

This entire project is AI-generated with Codex GPT-5.4.

## ⚠️ Disclaimer

SAMEStation is provided as-is for monitoring and experimentation purposes. It is not a certified alerting device and should not be relied on for emergency notifications.  
Always use an official NOAA weather radio or other trusted alerting system for safety-critical alerts.

The author assumes no responsibility for any damages or missed alerts resulting from use of this software.

## Product Split

### SAMEStation Server

- Installed product for the machine that does the decoding work
- Keeps the current web admin console
- Owns server-side audio device monitoring, Icecast monitoring, recordings, RSS, ntfy, and saved server settings
- Supports custom server misc-data and recordings paths through the installer
- Can be configured to launch automatically at sign-in

### SAMEStation Client

- Separate installed desktop product
- Native client app for alerts, recordings playback, server health, RSS visibility, and connection management
- Connects to an existing SAMEStation server over the network
- Supports LAN discovery plus manual server URL entry
- Keeps a saved manual server URL as a fallback

## Installer-First Releases

Public release pages are intended to expose only:

- `SAMEStation Server Installer.exe`
- `SAMEStation Client Installer.exe`

The installers are responsible for resolving and installing the real app payloads for the selected product and channel.

## Release Channels

Both installed products support:

- `Stable`
- `Nightly`

The installer shows the currently installed version for that product, the available payload version for the selected channel, and then installs or updates that product only.

## Server Features

- Decodes `S.A.M.E.` headers from local audio files
- Decodes from direct audio-file links and live stream URLs
- Monitors a server-side audio input device continuously
- Monitors an Icecast stream on the server side
- Resolves SAME and FIPS location codes to real county and location names
- Detects repeated header bursts and `NNNN` end-of-message bursts
- Records alerts with configurable pre-roll
- Publishes alerts immediately and updates them when the recording finishes
- Generates an RSS feed for captured alerts
- Sends free phone alerts through `ntfy`

## Client Features

- Connects to a SAMEStation server and shows current alerts
- Shows alert details, detection source, and saved recordings
- Plays finished recordings directly from the server
- Shows current server monitor status and source information
- Shows RSS feed availability and ntfy status
- Supports LAN discovery and manual connection entry

## Server Installer Flow

The server installer uses a 4-step flow:

1. Welcome
2. Server Setup
3. Review
4. Install / Finish

Server setup includes:

- branch channel selection
- install location
- sign-in launch option
- post-install start option
- optional browser-open behavior
- optional monitor auto-start
- misc-data path
- recordings path

Default server storage behavior:

- misc data defaults to a folder with the installed app
- recordings default to the user `Documents` folder

## Client Installer Flow

The client installer uses a matching 4-step flow:

1. Welcome
2. Client Setup
3. Review
4. Install / Finish

Client setup includes:

- branch channel selection
- install location
- sign-in launch option
- post-install start option
- preferred server URL

## Internal Payload Source

The installer-first model separates:

- public installer releases
- internal app payload releases

The installer resolves:

- product role
- release channel
- matching internal payload

This keeps the public release page focused on the installers instead of exposing the raw installed app binaries there.
