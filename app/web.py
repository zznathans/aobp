from datetime import UTC, datetime
from html import escape

from app.models.character import CharacterDocument

BASE_STYLE = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background: #0f1115;
    color: #e6e6e6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  a { color: inherit; }
  .btn {
    display: inline-block;
    padding: 0.6rem 1rem;
    border-radius: 8px;
    border: none;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
    box-sizing: border-box;
  }
  .btn-primary { background: #4c8bf5; color: #fff; }
  .btn-primary:hover { background: #3b76e0; }
  .btn-secondary { background: transparent; color: #9aa4b2; border: 1px solid #2a2e37; }
  .btn-secondary:hover { color: #e6e6e6; border-color: #4c8bf5; }
  .navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.75rem 1.5rem;
    background: #14161c;
    border-bottom: 1px solid #2a2e37;
  }
  .navbar .brand {
    font-weight: 700;
    font-size: 1.05rem;
    text-decoration: none;
    flex-shrink: 0;
  }
  .navbar .nav-links {
    display: flex;
    gap: 1.25rem;
    flex: 1;
    font-size: 0.9rem;
  }
  .navbar .nav-links a {
    text-decoration: none;
    color: #9aa4b2;
  }
  .navbar .nav-links a:hover,
  .navbar .nav-links a.active {
    color: #e6e6e6;
  }
  .navbar .nav-user {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-shrink: 0;
  }
  .navbar .nav-avatar {
    width: 2rem;
    height: 2rem;
    border-radius: 50%;
  }
  .navbar .nav-user-name {
    font-size: 0.85rem;
    white-space: nowrap;
  }
  .mini-gauge { display: flex; align-items: center; gap: 0.5rem; min-width: 7rem; }
  .mini-gauge-track {
    flex: 1; height: 5px; border-radius: 3px;
    background: #2a2e37; overflow: hidden;
  }
  .mini-gauge-fill { height: 100%; border-radius: 3px; }
  .mini-gauge-text { font-size: 0.75rem; color: #9aa4b2; min-width: 2.6rem; text-align: right; }
"""


def gauge_color(percentage: float) -> str:
    if percentage >= 100:
        return "#3ddc84"
    if percentage >= 50:
        return "#f5c344"
    return "#f0625a"


def gauge_cell_html(percentage: float, value_text: str | None = None) -> str:
    clamped = min(100.0, max(0.0, percentage))
    color = gauge_color(percentage)
    text = value_text if value_text is not None else f"{percentage:.0f}%"
    return f"""
      <div class="mini-gauge">
        <div class="mini-gauge-track">
          <div class="mini-gauge-fill" style="width: {clamped:.0f}%; background: {color};"></div>
        </div>
        <span class="mini-gauge-text">{text}</span>
      </div>
    """


def icon_url(type_id: int, is_copy: bool = False) -> str:
    variant = "bpc" if is_copy else "bp"
    return f"https://images.evetech.net/types/{type_id}/{variant}"


def humanize_relative_time(target: datetime) -> str:
    seconds = (target - datetime.now(UTC)).total_seconds()
    if seconds <= 0:
        return "any moment"

    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days > 0:
        value, unit = days, "day"
    elif hours > 0:
        value, unit = hours, "hour"
    elif minutes > 0:
        value, unit = minutes, "minute"
    else:
        return "in less than a minute"

    return f"in {value} {unit}{'s' if value != 1 else ''}"


def render_nav(character: CharacterDocument | None) -> str:
    if character is None:
        return """
          <nav class="navbar">
            <a class="brand" href="/">aobp</a>
            <a class="btn btn-primary" href="/auth/login">Log in with EVE Online</a>
          </nav>
        """

    avatar_url = f"https://images.evetech.net/characters/{character.character_id}/portrait?size=64"
    character_name = escape(str(getattr(character, "character_name", "")))
    return f"""
      <nav class="navbar">
        <a class="brand" href="/">aobp</a>
        <div class="nav-links">
          <a href="/">Home</a>
          <a href="/blueprints">Blueprints</a>
        </div>
        <div class="nav-user">
          <img class="nav-avatar" src="{avatar_url}" alt="{escape(character.character_name)}">
          <span class="nav-user-name">{escape(character.character_name)}</span>
          <a class="btn btn-secondary" href="/auth/logout">Log out</a>
        </div>
      </nav>
    """


def render_page(
    title: str,
    body: str,
    extra_style: str = "",
    *,
    character: CharacterDocument | None = None,
) -> str:
    nav = render_nav(character)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>{BASE_STYLE}{extra_style}</style>
</head>
<body>
{nav}
{body}
</body>
</html>"""
