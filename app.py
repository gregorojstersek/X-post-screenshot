import os
import re
import time
import uuid
import base64
import urllib.request
from flask import Flask, render_template, request, jsonify, send_file
from playwright.sync_api import sync_playwright

app = Flask(__name__)
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

CHECKMARK_SVG = """<svg viewBox="0 0 22 22" width="22" height="22" style="display:inline-block;vertical-align:middle;margin-left:4px;position:relative;top:-1px"><g><path d="M20.396 11c-.018-.646-.215-1.275-.57-1.816-.354-.54-.852-.972-1.438-1.246.223-.607.27-1.264.14-1.897-.131-.634-.437-1.218-.882-1.687-.47-.445-1.053-.75-1.687-.882-.633-.13-1.29-.083-1.897.14-.273-.587-.704-1.086-1.245-1.44S11.647 1.62 11 1.604c-.646.017-1.273.213-1.813.568s-.969.854-1.24 1.44c-.608-.223-1.267-.272-1.902-.14-.635.13-1.22.436-1.69.882-.445.47-.749 1.055-.878 1.688-.13.633-.08 1.29.144 1.896-.587.274-1.087.705-1.443 1.245-.356.54-.555 1.17-.574 1.817.02.648.218 1.279.574 1.82.356.541.856.972 1.443 1.245-.224.606-.274 1.263-.144 1.896.13.634.433 1.218.877 1.688.47.443 1.054.747 1.687.878.633.132 1.29.084 1.897-.136.274.586.705 1.084 1.246 1.439.54.354 1.17.551 1.816.569.647-.016 1.276-.213 1.817-.567s.972-.854 1.245-1.44c.604.239 1.266.296 1.903.164.636-.132 1.22-.447 1.68-.907.46-.46.776-1.044.908-1.681s.075-1.299-.165-1.903c.586-.274 1.084-.705 1.439-1.246.354-.54.551-1.17.569-1.816zM9.662 14.85l-3.429-3.428 1.293-1.302 2.072 2.072 4.4-4.794 1.347 1.246z" fill="#1d9bf0"></path></g></svg>"""

CANVAS = 768   # logical px — x2 device scale = 1536px output
PADDING = 64

TWEET_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: {canvas}px;
    height: {canvas}px;
    background: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
                 "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  body {{
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .content {{
    width: {inner}px;
  }}
  .profile {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
  }}
  .avatar {{
    width: 96px;
    height: 96px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
  }}
  .names {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .display-name {{
    font-size: 32px;
    font-weight: 700;
    color: #0f1419;
    display: flex;
    align-items: center;
    line-height: 1.2;
  }}
  .handle {{
    font-size: 32px;
    color: #536471;
    font-weight: 400;
  }}
  .tweet-text p {{
    font-size: 38px;
    font-weight: 400;
    color: #0f1419;
    line-height: 1.3;
    word-break: break-word;
    margin-bottom: 36px;
  }}
  .tweet-text p:last-child {{
    margin-bottom: 0;
  }}
</style>
</head>
<body>
  <div class="content">
    <div class="profile">
      <img class="avatar" src="{avatar_src}" />
      <div class="names">
        <div class="display-name">{display_name}{checkmark}</div>
        <div class="handle">@{handle}</div>
      </div>
    </div>
    <div class="tweet-text">{tweet_paragraphs}</div>
  </div>
</body>
</html>"""


CUSTOM_AVATARS = {
    "gregorojstersek": os.path.join(os.path.dirname(__file__), "assets", "gregorojstersek.png"),
}

def local_image_data_uri(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    ext = path.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def is_valid_x_url(url: str) -> bool:
    pattern = r"^https?://(www\.)?(twitter\.com|x\.com)/\w+/status/\d+"
    return bool(re.match(pattern, url.strip()))


def grey_circle_uri() -> str:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><circle cx="100" cy="100" r="100" fill="#ccc"/></svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def extract_tweet_data(page, tweet_url: str) -> dict:
    """Extract display name, handle, avatar URL, verified status, and text from a loaded tweet page."""
    # Extract handle reliably from the URL itself
    url_handle_match = re.search(r"(?:twitter\.com|x\.com)/(\w+)/status/", tweet_url)
    url_handle = url_handle_match.group(1) if url_handle_match else ""

    data = page.evaluate("""() => {
        const article = document.querySelector("article[data-testid='tweet']");
        if (!article) return null;

        // Avatar — return raw URL, quality upgrade handled in Python
        const avatarImg = article.querySelector("img[src*='profile_images']");
        const avatarUrl = avatarImg ? avatarImg.src : '';

        // Display name — first non-empty leaf span in the User-Name block
        const userNameBlock = article.querySelector("[data-testid='User-Name']");
        let displayName = '';
        let verified = false;
        if (userNameBlock) {
            const spans = userNameBlock.querySelectorAll('span');
            for (const s of spans) {
                const t = s.textContent.trim();
                if (t && s.children.length === 0) {
                    displayName = t;
                    break;
                }
            }
            verified = !!article.querySelector('[data-testid="icon-verified"], svg[aria-label*="erif"], [aria-label="Verified account"]');
        }

        // Tweet text — preserve newlines
        const textEl = article.querySelector("[data-testid='tweetText']");
        let tweetText = '';
        if (textEl) {
            const walk = (node) => {
                if (node.nodeType === Node.TEXT_NODE) return node.textContent;
                if (node.nodeName === 'BR') return '\\n';
                if (node.nodeName === 'IMG') return node.alt || '';
                return Array.from(node.childNodes).map(walk).join('');
            };
            tweetText = walk(textEl);
        }

        return { avatarUrl, displayName, verified, tweetText };
    }""")

    if data:
        data["handle"] = url_handle  # always use URL-derived handle (correct casing)

    # avatarDataUri is set by take_screenshot after extract_tweet_data returns

    return data


def take_screenshot(url: str) -> str:
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(SCREENSHOTS_DIR, filename)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Intercept the first profile_images response and capture its bytes
        captured_avatar: dict = {"bytes": None, "mime": "image/jpeg"}

        def handle_response(response):
            if captured_avatar["bytes"] is None and "profile_images" in response.url:
                try:
                    captured_avatar["bytes"] = response.body()
                    ct = response.headers.get("content-type", "image/jpeg")
                    captured_avatar["mime"] = ct.split(";")[0].strip()
                except Exception:
                    pass

        page.on("response", handle_response)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Dismiss login/signup popups
        for selector in ["[data-testid='BottomBar']", "[aria-label='Close']"]:
            try:
                el = page.query_selector(selector)
                if el:
                    el.click()
                    time.sleep(0.3)
            except Exception:
                pass

        page.wait_for_selector("article[data-testid='tweet']", timeout=15000)
        time.sleep(1)

        data = extract_tweet_data(page, url)

        # Use custom high-res local avatar if available for this handle
        if data and data.get("handle", "").lower() in CUSTOM_AVATARS:
            custom_path = CUSTOM_AVATARS[data["handle"].lower()]
            data["avatarDataUri"] = local_image_data_uri(custom_path)
        elif data and data.get("avatarUrl"):
            # Try to fetch _orig quality via context.request (uses browser cookie jar)
            orig_url = re.sub(
                r'_(normal|bigger|mini|reasonably_small|200x200|400x400)(\.\w+)',
                r'_orig\2',
                data["avatarUrl"]
            )
            avatar_data_uri = None
            for attempt_url in [orig_url, data["avatarUrl"]]:
                try:
                    resp = context.request.get(attempt_url)
                    raw = resp.body()
                    if resp.ok and raw:
                        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                        avatar_data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
                        break
                except Exception:
                    pass

            # Last resort: intercepted bytes from page load
            if not avatar_data_uri and captured_avatar["bytes"]:
                raw = captured_avatar["bytes"]
                mime = captured_avatar["mime"]
                avatar_data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode()}"

            data["avatarDataUri"] = avatar_data_uri or grey_circle_uri()
        elif data:
            data["avatarDataUri"] = grey_circle_uri()

        browser.close()

    if not data:
        raise RuntimeError("Could not extract tweet content.")

    avatar_src = data.get("avatarDataUri") or ""
    checkmark = CHECKMARK_SVG if data.get("verified") else ""

    # Escape HTML special chars in text / name
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    # Split tweet text into paragraphs; single \n within a paragraph becomes <br>
    raw_text = data["tweetText"].strip()
    paragraphs = re.split(r'\n{2,}', raw_text)
    tweet_paragraphs = "".join(
        "<p>" + esc(p.strip()).replace("\n", "<br>") + "</p>"
        for p in paragraphs if p.strip()
    )

    html = TWEET_HTML_TEMPLATE.format(
        canvas=CANVAS,
        inner=CANVAS - PADDING * 2,
        avatar_src=avatar_src,
        display_name=esc(data["displayName"]),
        checkmark=checkmark,
        handle=esc(data["handle"]),
        tweet_paragraphs=tweet_paragraphs,
    )

    # Render the custom HTML and screenshot it — 768x768 logical × 2 = 1536x1536 px
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": CANVAS, "height": CANVAS},
            device_scale_factor=2,
        )
        page = context.new_page()
        # Allow file:// access so the avatar temp file can be loaded
        page.set_content(html, wait_until="load")
        page.screenshot(path=filepath)
        browser.close()

    return filename


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/screenshot", methods=["POST"])
def screenshot():
    data = request.get_json()
    url = (data or {}).get("url", "").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400
    if not is_valid_x_url(url):
        return jsonify({"error": "Please enter a valid X / Twitter post URL."}), 400

    try:
        filename = take_screenshot(url)
        return jsonify({"filename": filename})
    except Exception as e:
        return jsonify({"error": f"Failed to capture screenshot: {str(e)}"}), 500


@app.route("/screenshots/<filename>")
def serve_screenshot(filename):
    filename = os.path.basename(filename)
    filepath = os.path.join(SCREENSHOTS_DIR, filename)
    if not os.path.exists(filepath):
        return "Not found", 404
    return send_file(filepath, mimetype="image/png")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
