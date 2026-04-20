<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" indent="yes" encoding="UTF-8"/>

  <xsl:template match="/">
    <html lang="en">
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>SAMECode Alert Feed</title>
        <style>
          :root {
            --bg: #08131f;
            --panel: rgba(10, 24, 38, 0.88);
            --panel-border: rgba(170, 206, 233, 0.16);
            --text: #eff6fb;
            --muted: #9ab1c4;
            --accent: #ffd772;
            --success: #88e4ae;
            --shadow: 0 22px 60px rgba(0, 0, 0, 0.28);
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            color: var(--text);
            font-family: "Segoe UI", "Trebuchet MS", sans-serif;
            background:
              radial-gradient(circle at top left, rgba(244, 185, 66, 0.14), transparent 32%),
              radial-gradient(circle at 85% 18%, rgba(66, 169, 244, 0.12), transparent 28%),
              linear-gradient(180deg, #08131f 0%, #102133 48%, #06111a 100%);
          }
          .shell {
            width: min(1100px, calc(100vw - 32px));
            margin: 0 auto;
            padding: 36px 0 48px;
          }
          .topbar, .alert-card {
            background: var(--panel);
            border: 1px solid var(--panel-border);
            border-radius: 24px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(16px);
          }
          .topbar {
            padding: 14px 18px;
            margin-bottom: 20px;
          }
          .topbar a {
            color: #041219;
            background: linear-gradient(135deg, #f4b942 0%, #ffd772 100%);
            text-decoration: none;
            padding: 10px 14px;
            border-radius: 999px;
            font-weight: 700;
          }
          .feed {
            display: grid;
            gap: 16px;
            margin-top: 20px;
          }
          .alert-card {
            padding: 20px;
            display: grid;
            gap: 12px;
          }
          .alert-meta,
          .alert-grid,
          .muted,
          .recording-status {
            color: var(--muted);
            line-height: 1.55;
          }
          .alert-head {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            justify-content: space-between;
            gap: 10px;
          }
          .alert-title {
            font-size: 1.12rem;
            font-weight: 700;
          }
          .alert-grid {
            display: grid;
            gap: 8px;
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
          .alert-grid span,
          .recording-block span {
            display: block;
            font-size: 0.8rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--accent);
            margin-bottom: 4px;
          }
          .recording-block {
            display: grid;
            gap: 8px;
          }
          .recording-block audio {
            width: 100%;
            min-height: 42px;
            border-radius: 12px;
            background: rgba(4, 11, 18, 0.78);
          }
          .recording-status {
            padding: 12px;
            border-radius: 14px;
            background: rgba(4, 11, 18, 0.72);
          }
          .raw-header {
            padding: 12px;
            border-radius: 14px;
            background: rgba(4, 11, 18, 0.72);
            color: #d8edf9;
            overflow-wrap: anywhere;
            font-family: "Cascadia Code", Consolas, monospace;
            font-size: 0.92rem;
          }
          .pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            border-radius: 999px;
            background: rgba(136, 228, 174, 0.12);
            color: var(--success);
            font-size: 0.8rem;
            font-weight: 700;
          }
          .pill.warn {
            background: rgba(244, 185, 66, 0.12);
            color: var(--accent);
          }
          @media (max-width: 720px) {
            .shell {
              width: min(100vw - 20px, 100%);
              padding-top: 18px;
            }
            .topbar, .alert-card {
              padding: 18px;
              border-radius: 18px;
            }
            .alert-grid {
              grid-template-columns: 1fr;
            }
          }
        </style>
      </head>
      <body>
        <main class="shell">
          <section class="topbar">
            <a href="{rss/channel/link}">Open SAMECode Console</a>
          </section>

          <section class="feed">
            <xsl:for-each select="rss/channel/item">
              <xsl:value-of select="description" disable-output-escaping="yes"/>
            </xsl:for-each>
          </section>
        </main>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
