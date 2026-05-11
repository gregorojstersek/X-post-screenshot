# X Post Screenshot

A web app that generates clean, styled screenshots from X (Twitter) post URLs — matching the look of native X screenshots with full control over fonts, sizing, and layout.

## Features

- Paste any X / Twitter post URL and get a clean PNG screenshot
- Custom template design (white background, large readable text, profile header)
- Exports at **1536×1536px** (1:1 ratio, retina quality)
- Supports custom local avatars per handle
- One-click download of the generated image

## Setup

### Requirements

- Python 3.10+
- pip

### Install dependencies

```bash
pip3 install flask playwright
python3 -m playwright install chromium
```

### Run the app

```bash
python3 app.py
```

Then open [http://localhost:8080](http://localhost:8080) in your browser.

## Usage

1. Paste an X post URL (e.g. `https://x.com/gregorojstersek/status/...`)
2. Click **Capture**
3. The screenshot appears in the browser — click **Download PNG** to save it

## Custom Avatars

To use a local high-res profile image for a specific handle, add an entry to `CUSTOM_AVATARS` in `app.py`:

```python
CUSTOM_AVATARS = {
    "yourhandle": "/path/to/your/avatar.png",
}
```

## Output Example

- **Size:** 1536×1536px
- **Font:** SF Pro / system sans-serif
- **Content:** Profile header (avatar, name, handle, verified badge) + tweet text with paragraph spacing

## Tech Stack

- [Flask](https://flask.palletsprojects.com/) — web server
- [Playwright](https://playwright.dev/python/) — headless browser for scraping and rendering
- Chromium (via Playwright)
