# Changelog

## v0.1.1 - 2026-04-20

### Added

- Added launcher argument support for `--server`, `--client`, `--both`, `--server-url`, `--port`, and monitor auto-start options.
- Added launcher state saving so the desktop app remembers the last selected mode and launch settings.
- Added a launcher checkbox to enable SAMEStation startup at Windows sign-in.
- Added server-side importing for browser offline decodes so file and URL decodes now post into the main alert history.
- Added `Detected Via` metadata to alerts and RSS items so the app shows whether an alert came from the server device, an uploaded file, a remote file URL, or a browser live stream.
- Added YouTube link support for URL decoding through the server proxy.
- Added inline URL status text in the web app so URL decode progress and failures show directly under the URL box.

### Changed

- Rebuilt the Windows desktop executable with the latest launcher, offline alert import flow, and YouTube URL support.
- Updated the README to cover the current desktop launch behavior and arguments.

### Removed

- Removed the local alert transcription feature and its UI for now.
