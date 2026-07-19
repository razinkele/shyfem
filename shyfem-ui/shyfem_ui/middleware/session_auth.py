"""Session-based authentication middleware for the SHYFEM UI ASGI app.

Reads a ``shyfem_session`` cookie, validates it via :class:`AuthService`,
and gates access to the inner application.  Unauthenticated HTTP requests
are redirected to ``/login``; unauthenticated WebSocket connections are
closed with code 4001.

In *local mode* authentication is bypassed entirely and a synthetic admin
user is injected into every request.
"""

import contextvars
import logging
import secrets
import urllib.parse

from shyfem_ui.middleware.rate_limit import get_client_ip

logger = logging.getLogger(__name__)

# ContextVar holding the authenticated user dict for the current request.
_user_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "current_user", default=None
)

_SYNTHETIC_LOCAL_USER: dict = {
    "id": 0,
    "username": "local",
    "display_name": "Local User",
    "email": None,
    "role": "admin",
    "is_active": True,
}


def get_current_user() -> dict | None:
    """Return the authenticated user dict for the current ASGI scope.

    Returns ``None`` when called outside of an authenticated request context.
    """
    return _user_var.get()


# ------------------------------------------------------------------
# Cookie parsing helper
# ------------------------------------------------------------------


def _parse_cookie(raw: bytes) -> dict[str, str]:
    """Parse a raw ``Cookie`` header value into a ``{name: value}`` dict.

    Handles the common ``name=value; name2=value2`` format.  Cookies
    without a ``=`` are stored with an empty-string value.
    """
    if not raw:
        return {}
    text = raw.decode("latin-1")
    cookies: dict[str, str] = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
        else:
            cookies[part.strip()] = ""
    return cookies


# ------------------------------------------------------------------
# Login page HTML
# ------------------------------------------------------------------

_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SHYFEM Workbench</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Outfit:wght@300;400;500;600&display=swap"
        rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: 'Outfit', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(160deg, #061E2F 0%, #0B3D5B 30%, #1A6B8A 60%, #2D9CBA 100%);
      background-size: 400% 400%;
      animation: gradientShift 18s ease infinite;
      overflow: hidden;
    }}

    @keyframes gradientShift {{
      0%   {{ background-position: 0% 50%; }}
      50%  {{ background-position: 100% 50%; }}
      100% {{ background-position: 0% 50%; }}
    }}

    .login-card {{
      max-width: 440px;
      width: 95%;
      background: rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 16px;
      padding: 40px 36px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
      animation: cardEntrance 600ms ease-out both;
      position: relative;
      z-index: 2;
    }}

    @keyframes cardEntrance {{
      from {{
        opacity: 0;
        transform: translateY(30px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}

    .brand {{
      text-align: center;
      margin-bottom: 8px;
    }}

    .brand svg {{
      width: 48px;
      height: 48px;
      margin-bottom: 12px;
    }}

    .brand h1 {{
      font-family: 'DM Serif Display', Georgia, serif;
      font-size: 1.75rem;
      font-weight: 400;
      color: #fff;
      margin: 0;
      letter-spacing: 0.01em;
    }}

    .brand .tagline {{
      font-size: 0.85rem;
      color: rgba(255, 255, 255, 0.7);
      margin-top: 4px;
      font-weight: 400;
    }}

    .info {{
      background: rgba(255, 255, 255, 0.08);
      border-radius: 10px;
      padding: 14px 18px;
      margin: 20px 0 28px;
      animation: cardEntrance 600ms ease-out 100ms both;
    }}

    .info ul {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}

    .info li {{
      font-size: 0.82rem;
      color: rgba(255, 255, 255, 0.8);
      padding: 3px 0;
    }}

    .info li::before {{
      margin-right: 8px;
      opacity: 0.7;
    }}

    .form-group {{
      margin-bottom: 18px;
      animation: cardEntrance 500ms ease-out both;
    }}

    .form-group:nth-child(1) {{ animation-delay: 150ms; }}
    .form-group:nth-child(2) {{ animation-delay: 250ms; }}
    .form-group.btn-group       {{ animation-delay: 350ms; }}

    label {{
      display: block;
      font-size: 0.8rem;
      font-weight: 500;
      color: rgba(255, 255, 255, 0.85);
      margin-bottom: 6px;
      letter-spacing: 0.01em;
    }}

    input[type="text"],
    input[type="password"] {{
      width: 100%;
      padding: 10px 14px;
      font-size: 0.95rem;
      font-family: inherit;
      background: rgba(255, 255, 255, 0.1);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 8px;
      color: #fff;
      outline: none;
      transition: box-shadow 200ms ease, border-color 200ms ease;
    }}

    input[type="text"]::placeholder,
    input[type="password"]::placeholder {{
      color: rgba(255, 255, 255, 0.4);
    }}

    input[type="text"]:focus,
    input[type="password"]:focus {{
      border-color: #2D9CBA;
      box-shadow: 0 0 0 3px rgba(45, 156, 186, 0.35);
    }}

    .btn-signin {{
      width: 100%;
      padding: 11px;
      font-size: 0.95rem;
      font-weight: 600;
      font-family: inherit;
      color: #fff;
      background: linear-gradient(135deg, #1A6B8A, #2D9CBA);
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: transform 150ms ease, filter 150ms ease;
      letter-spacing: 0.01em;
    }}

    .btn-signin:hover {{
      transform: scale(1.02);
      filter: brightness(1.1);
    }}

    .btn-signin:active {{
      transform: scale(0.99);
    }}

    .error-alert {{
      background: rgba(220, 53, 69, 0.2);
      border: 1px solid rgba(220, 53, 69, 0.5);
      border-radius: 8px;
      color: #ffc9cf;
      padding: 10px 14px;
      font-size: 0.85rem;
      margin-bottom: 18px;
      animation: shake 400ms ease;
    }}

    @keyframes shake {{
      0%, 100% {{ transform: translateX(0); }}
      20%      {{ transform: translateX(-6px); }}
      40%      {{ transform: translateX(6px); }}
      60%      {{ transform: translateX(-4px); }}
      80%      {{ transform: translateX(4px); }}
    }}

    .footer {{
      text-align: center;
      margin-top: 24px;
      font-size: 0.7rem;
      color: rgba(255, 255, 255, 0.4);
      letter-spacing: 0.02em;
    }}

    .footer a {{
      color: rgba(255, 255, 255, 0.55);
      text-decoration: none;
      transition: color 200ms ease;
    }}

    .footer a:hover {{
      color: rgba(255, 255, 255, 0.85);
      text-decoration: underline;
    }}

    /* FEM mesh patchwork — irregular Delaunay triangulation */
    .fem-mesh {{
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 0;
      background-image: url('data:image/svg+xml,%3Csvg%20xmlns=%27http://www.w3.org/2000/svg%27%20width=%27300%27%20height=%27260%27%3E%3Cpolygon%20points=%270,110%200,50%2025,100%27%20fill=%27rgba(60,180,200,0.035)%27/%3E%3Cpolygon%20points=%2730,35%200,50%200,0%27%20fill=%27rgba(45,156,186,0.06)%27/%3E%3Cpolygon%20points=%27118,38%20100,0%20160,0%27%20fill=%27rgba(26,107,138,0.05)%27/%3E%3Cpolygon%20points=%27130,45%20118,38%20160,0%27%20fill=%27rgba(45,156,186,0.06)%27/%3E%3Cpolygon%20points=%27145,230%20205,245%20160,260%27%20fill=%27rgba(60,180,200,0.035)%27/%3E%3Cpolygon%20points=%27265,235%20300,220%20300,260%27%20fill=%27rgba(45,156,186,0.06)%27/%3E%3Cpolygon%20points=%27148,55%20130,45%20160,0%27%20fill=%27rgba(6,30,47,0.08)%27/%3E%3Cpolygon%20points=%2780,95%2090,160%2055,135%27%20fill=%27rgba(6,30,47,0.08)%27/%3E%3Cpolygon%20points=%27148,55%20110,65%20130,45%27%20fill=%27rgba(45,156,186,0.06)%27/%3E%3Cpolygon%20points=%27118,38%20110,65%2088,48%27%20fill=%27rgba(100,200,230,0.04)%27/%3E%3Cpolygon%20points=%27155,175%20100,160%20120,130%27%20fill=%27rgba(26,107,138,0.05)%27/%3E%3Cpolygon%20points=%27100,160%2090,160%20120,130%27%20fill=%27rgba(26,107,138,0.05)%27/%3E%3Cpolygon%20points=%270,220%2030,235%200,260%27%20fill=%27rgba(60,180,200,0.035)%27/%3E%3Cpolygon%20points=%27175,195%20145,230%20155,175%27%20fill=%27rgba(6,30,47,0.08)%27/%3E%3Cpolygon%20points=%27220,0%20260,40%20235,60%27%20fill=%27rgba(6,30,47,0.08)%27/%3E%3Cpolygon%20points=%27260,40%20270,90%20235,60%27%20fill=%27rgba(45,156,186,0.06)%27/%3E%3Cpolygon%20points=%27118,38%2075,25%20100,0%27%20fill=%27rgba(60,180,200,0.035)%27/%3E%3Cpolygon%20points=%27140,110%20110,65%20148,55%27%20fill=%27rgba(26,107,138,0.05)%27/%3E%3Cpolygon%20points=%2730,35%2050,70%200,50%27%20fill=%27rgba(100,200,230,0.04)%27/%3E%3Cpolygon%20points=%27100,160%20115,210%2090,160%27%20fill=%27rgba(26,107,138,0.05)%27/%3E%3Cpolygon%20points=%2785,240%20115,210%20100,260%27%20fill=%27rgba(60,180,200,0.035)%27/%3E%3Cpolygon%20points=%27300,175%20275,175%20300,110%27%20fill=%27rgba(6,30,47,0.08)%27/%3E%3Cpolygon%20points=%27275,175%20300,175%20300,220%27%20fill=%27rgba(100,200,230,0.04)%27/%3E%3Cpolygon%20points=%27245,130%20270,90%20300,110%27%20fill=%27rgba(6,30,47,0.08)%27/%3E%3Cpolygon%20points=%27275,175%20245,130%20300,110%27%20fill=%27rgba(100,200,230,0.04)%27/%3E%3Cpolygon%20points=%27240,210%20220,260%20205,245%27%20fill=%27rgba(26,107,138,0.05)%27/%3E%3Cpolygon%20points=%2790,160%2060,200%2035,170%27%20fill=%27rgba(60,180,200,0.035)%27/%3E%3Cpolygon%20points=%27115,210%2060,200%2090,160%27%20fill=%27rgba(100,200,230,0.04)%27/%3E%3Cpolygon%20points=%27200,100%20165,80%20195,30%27%20fill=%27rgba(45,156,186,0.06)%27/%3E%3Cpolygon%20points=%27210,165%20180,145%20200,100%27%20fill=%27rgba(100,200,230,0.04)%27/%3E%3Cpath%20d=%27M200,100L245,130%20M260,40L270,90%20M80,95L105,85%20M300,260L265,235%20M130,45L110,65%20M100,260L160,260%20M0,50L50,70%20M160,0L130,45%20M245,130L275,175%20M140,110L155,120%20M130,45L118,38%20M210,165L275,175%20M80,95L90,160%20M300,175L300,220%20M100,260L85,240%20M50,70L88,48%20M25,100L55,135%20M0,175L0,220%20M240,210L205,245%20M90,160L115,210%20M160,260L220,260%20M195,30L165,80%20M220,0L195,30%20M110,65L118,38%20M195,30L148,55%20M30,235L85,240%20M260,40L235,60%20M300,50L260,40%20M165,80L148,55%20M300,50L270,90%20M115,210L145,230%20M160,260L145,230%20M0,50L30,35%20M35,170L90,160%20M0,50L25,100%20M155,175L175,195%20M110,65L105,85%20M180,145L210,165%20M80,95L55,135%20M300,50L300,110%20M50,70L25,100%20M165,80L155,120%20M80,95L88,48%20M0,50L0,110%20M75,25L50,70%20M300,0L300,50%20M140,110L120,130%20M145,230L205,245%20M155,175L155,120%20M75,25L88,48%20M0,110L0,175%20M165,80L140,110%20M175,195L240,210%20M45,0L75,25%20M220,260L265,235%20M60,200L85,240%20M35,170L60,200%20M0,260L30,235%20M155,175L145,230%20M55,135L90,160%20M235,60L200,100%20M180,145L175,195%20M270,90L245,130%20M200,100L210,165%20M30,35L75,25%20M88,48L118,38%20M0,220L60,200%20M160,0L195,30%20M120,130L105,85%20M110,65L88,48%20M45,260L85,240%20M175,195L205,245%20M180,145L155,120%20M160,0L118,38%20M100,260L145,230%20M0,260L0,220%20M210,165L240,210%20M120,130L90,160%20M88,48L105,85%20M240,210L265,235%20M195,30L235,60%20M155,175L115,210%20M220,0L260,40%20M120,130L100,160%20M110,65L148,55%20M300,110L300,175%20M90,160L100,160%20M180,145L155,175%20M0,0L30,35%20M300,220L275,175%20M300,220L265,235%20M200,100L180,145%20M160,260L205,245%20M30,35L50,70%20M0,220L35,170%20M0,220L30,235%20M45,0L100,0%20M45,0L30,35%20M245,130L210,165%20M140,110L105,85%20M80,95L120,130%20M100,260L115,210%20M0,110L55,135%20M110,65L140,110%20M25,100L80,95%20M60,200L30,235%20M200,100L155,120%20M220,0L235,60%20M90,160L60,200%20M100,0L160,0%20M55,135L35,170%20M165,80L200,100%20M100,0L75,25%20M130,45L148,55%20M160,0L220,0%20M275,175L265,235%20M115,210L85,240%20M220,260L240,210%20M115,210L100,160%20M45,260L30,235%20M300,110L270,90%20M175,195L145,230%20M235,60L270,90%20M300,110L275,175%20M200,100L270,90%20M0,110L25,100%20M210,165L175,195%20M220,0L300,0%20M0,110L35,170%20M120,130L155,120%20M100,0L118,38%20M0,0L45,0%20M220,260L300,260%20M300,0L260,40%20M300,260L300,220%20M0,260L45,260%20M160,0L148,55%20M50,70L80,95%20M275,175L240,210%20M60,200L115,210%20M120,130L155,175%20M220,260L205,245%20M300,175L275,175%20M195,30L200,100%20M0,0L0,50%20M0,175L35,170%20M155,175L100,160%20M140,110L148,55%20M75,25L118,38%20M300,110L245,130%20M45,260L100,260%27%20stroke=%27rgba(255,255,255,0.05)%27%20stroke-width=%270.5%27%20fill=%27none%27/%3E%3Cg%20fill=%27rgba(255,255,255,0.09)%27%3E%3Ccircle%20cx=%270%27%20cy=%270%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2745%27%20cy=%270%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27100%27%20cy=%270%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27160%27%20cy=%270%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27220%27%20cy=%270%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27300%27%20cy=%270%27%20r=%271.3%27/%3E%3Ccircle%20cx=%270%27%20cy=%27260%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2745%27%20cy=%27260%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27100%27%20cy=%27260%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27160%27%20cy=%27260%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27220%27%20cy=%27260%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27300%27%20cy=%27260%27%20r=%271.3%27/%3E%3Ccircle%20cx=%270%27%20cy=%2750%27%20r=%271.3%27/%3E%3Ccircle%20cx=%270%27%20cy=%27110%27%20r=%271.3%27/%3E%3Ccircle%20cx=%270%27%20cy=%27175%27%20r=%271.3%27/%3E%3Ccircle%20cx=%270%27%20cy=%27220%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27300%27%20cy=%2750%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27300%27%20cy=%27110%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27300%27%20cy=%27175%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27300%27%20cy=%27220%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2730%27%20cy=%2735%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2775%27%20cy=%2725%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27130%27%20cy=%2745%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27195%27%20cy=%2730%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27260%27%20cy=%2740%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2750%27%20cy=%2770%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27110%27%20cy=%2765%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27165%27%20cy=%2780%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27235%27%20cy=%2760%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2725%27%20cy=%27100%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2780%27%20cy=%2795%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27140%27%20cy=%27110%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27200%27%20cy=%27100%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27270%27%20cy=%2790%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2755%27%20cy=%27135%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27120%27%20cy=%27130%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27180%27%20cy=%27145%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27245%27%20cy=%27130%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2735%27%20cy=%27170%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2790%27%20cy=%27160%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27155%27%20cy=%27175%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27210%27%20cy=%27165%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27275%27%20cy=%27175%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2760%27%20cy=%27200%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27115%27%20cy=%27210%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27175%27%20cy=%27195%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27240%27%20cy=%27210%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2730%27%20cy=%27235%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2785%27%20cy=%27240%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27145%27%20cy=%27230%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27205%27%20cy=%27245%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27265%27%20cy=%27235%27%20r=%271.3%27/%3E%3Ccircle%20cx=%2788%27%20cy=%2748%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27118%27%20cy=%2738%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27148%27%20cy=%2755%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27105%27%20cy=%2785%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27155%27%20cy=%27120%27%20r=%271.3%27/%3E%3Ccircle%20cx=%27100%27%20cy=%27160%27%20r=%271.3%27/%3E%3C/g%3E%3C/svg%3E');
      background-repeat: repeat;
      background-size: 300px 260px;
      animation: mesh-drift 120s linear infinite;
    }}

    @keyframes mesh-drift {{
      from {{ background-position: 0 0; }}
      to {{ background-position: 300px 260px; }}
    }}

    /* Ocean wave layers */
    .ocean {{
      position: fixed;
      bottom: 0;
      left: 0;
      width: 100%;
      height: 40vh;
      min-height: 160px;
      overflow: hidden;
      pointer-events: none;
      z-index: 1;
    }}

    .wave {{
      position: absolute;
      bottom: 0;
      left: 0;
      width: 200%;
      background-repeat: repeat-x;
      background-size: 50% 100%;
    }}

    .wave-1 {{
      height: 130px;
      animation: wave-flow 8s linear infinite;
    }}

    .wave-2 {{
      height: 110px;
      bottom: -4px;
      animation: wave-flow 12s linear infinite reverse;
    }}

    .wave-3 {{
      height: 90px;
      bottom: -8px;
      animation: wave-flow 16s linear infinite;
    }}

    @keyframes wave-flow {{
      from {{ transform: translateX(0); }}
      to {{ transform: translateX(-50%); }}
    }}

    /* Rising bubbles */
    .bubbles {{
      position: fixed;
      inset: 0;
      pointer-events: none;
      overflow: hidden;
      z-index: 0;
    }}

    .bbl {{
      position: absolute;
      bottom: -20px;
      border-radius: 50%;
      background: radial-gradient(circle at 30% 30%,
        rgba(255,255,255,0.35), rgba(255,255,255,0.06));
      box-shadow: inset 0 0 6px rgba(255,255,255,0.08);
      animation: rise linear infinite;
    }}

    @keyframes rise {{
      0%   {{ transform: translateY(0) translateX(0); opacity: 0; }}
      12%  {{ opacity: 0.7; }}
      50%  {{ transform: translateY(-50vh) translateX(18px); }}
      88%  {{ opacity: 0.12; }}
      100% {{ transform: translateY(-105vh) translateX(-8px); opacity: 0; }}
    }}

    /* Underwater light shimmer */
    .shimmer {{
      position: fixed;
      top: -30%;
      left: -30%;
      width: 160%;
      height: 160%;
      pointer-events: none;
      z-index: 0;
      background:
        radial-gradient(ellipse 500px 350px at 25% 30%,
          rgba(45,156,186,0.09), transparent),
        radial-gradient(ellipse 400px 300px at 75% 65%,
          rgba(100,200,230,0.06), transparent);
      animation: shimmer-drift 22s ease-in-out infinite alternate;
    }}

    @keyframes shimmer-drift {{
      0%   {{ transform: translate(0, 0) rotate(0deg); }}
      100% {{ transform: translate(6%, 4%) rotate(1.5deg); }}
    }}

    @media (max-width: 480px) {{
      .login-card {{
        padding: 28px 22px;
      }}
      .brand h1 {{
        font-size: 1.4rem;
      }}
      .ocean {{
        height: 25vh;
        min-height: 100px;
      }}
    }}
  </style>
</head>
<body>
  <!-- FEM mesh patchwork -->
  <div class="fem-mesh"></div>

  <!-- Underwater light shimmer -->
  <div class="shimmer"></div>

  <!-- Rising bubbles -->
  <div class="bubbles">
    <div class="bbl" style="left:7%;width:3px;height:3px;animation-duration:16s;animation-delay:0s"></div>
    <div class="bbl" style="left:18%;width:5px;height:5px;animation-duration:22s;animation-delay:3s"></div>
    <div class="bbl" style="left:33%;width:4px;height:4px;animation-duration:18s;animation-delay:1s"></div>
    <div class="bbl" style="left:48%;width:6px;height:6px;animation-duration:25s;animation-delay:5s"></div>
    <div class="bbl" style="left:62%;width:3px;height:3px;animation-duration:17s;animation-delay:2s"></div>
    <div class="bbl" style="left:76%;width:5px;height:5px;animation-duration:23s;animation-delay:4s"></div>
    <div class="bbl" style="left:87%;width:4px;height:4px;animation-duration:19s;animation-delay:6s"></div>
    <div class="bbl" style="left:94%;width:3px;height:3px;animation-duration:15s;animation-delay:8s"></div>
  </div>

  <!-- Ocean waves -->
  <div class="ocean">
    <div class="wave wave-1" style="background-image:url('data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 1000 100%27 preserveAspectRatio=%27none%27%3E%3Cpath d=%27M0,30 C166,0 333,60 500,30 C666,0 833,60 1000,30 V100 H0 Z%27 fill=%27rgba(255,255,255,0.07)%27/%3E%3C/svg%3E')"></div>
    <div class="wave wave-2" style="background-image:url('data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 1000 100%27 preserveAspectRatio=%27none%27%3E%3Cpath d=%27M0,50 C150,20 350,80 500,50 C650,20 850,80 1000,50 V100 H0 Z%27 fill=%27rgba(255,255,255,0.05)%27/%3E%3C/svg%3E')"></div>
    <div class="wave wave-3" style="background-image:url('data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 1000 100%27 preserveAspectRatio=%27none%27%3E%3Cpath d=%27M0,65 C80,45 180,75 280,55 C380,35 480,70 580,55 C680,40 780,70 880,55 C940,45 1000,60 1000,65 V100 H0 Z%27 fill=%27rgba(255,255,255,0.035)%27/%3E%3C/svg%3E')"></div>
  </div>

  <div class="login-card">
    <div class="brand">
      <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M4 28c4-4 8-6 12-2s8 2 12-2 8-6 12-2" stroke="rgba(255,255,255,0.9)"
              stroke-width="2.5" stroke-linecap="round" fill="none"/>
        <path d="M4 34c4-4 8-6 12-2s8 2 12-2 8-6 12-2" stroke="rgba(255,255,255,0.5)"
              stroke-width="2" stroke-linecap="round" fill="none"/>
        <path d="M4 22c4-4 8-6 12-2s8 2 12-2 8-6 12-2" stroke="rgba(255,255,255,0.3)"
              stroke-width="1.5" stroke-linecap="round" fill="none"/>
      </svg>
      <h1>SHYFEM Workbench</h1>
      <div class="tagline">Finite element hydrodynamic simulation platform</div>
      <div class="tagline" style="margin-top:2px;font-size:0.75rem;opacity:0.7;">
        Maintained by Marine Research Institute of Klaip\u0117da University
      </div>
    </div>

    <div class="info">
      <ul>
        <li>\u2248 Lagoons, coastal seas &amp; estuaries</li>
        <li>\u2248 2D/3D modeling with MPI parallelization</li>
        <li>\u2248 Wind, tidal, baroclinic &amp; transport physics</li>
      </ul>
    </div>

    {error}

    <form method="post" action="{login_action}">
      <input type="hidden" name="csrf_token" value="{csrf_token}">
      <div class="form-group">
        <label for="username">Username</label>
        <input type="text" id="username" name="username" required autofocus
               placeholder="Enter your username">
      </div>
      <div class="form-group">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" required
               placeholder="Enter your password">
      </div>
      <div class="form-group btn-group">
        <button type="submit" class="btn-signin">Sign In</button>
      </div>
    </form>

    <div class="footer">
      <a href="https://shyfem.org" target="_blank" rel="noopener">shyfem.org</a>
      &middot; System of HydroDYnamic Finite Element Modules
    </div>
  </div>
</body>
</html>
"""


# ------------------------------------------------------------------
# Logout confirmation page HTML
# ------------------------------------------------------------------
#
# GET /logout is CSRF-unsafe to treat as a mutation: a cross-site GET (an
# <img> tag, an auto-following top-level navigation, a <meta refresh>, ...)
# can be triggered without any user interaction, and the session cookie
# would still be attached under SameSite=Lax. So GET only ever renders this
# confirm page; the actual logout is a POST, which SameSite=Lax cookies are
# NOT attached to on a cross-site request -- a forged cross-site POST here
# arrives without the session cookie and is a no-op.

_LOGOUT_CONFIRM_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Log out - SHYFEM Workbench</title>
</head>
<body>
  <p>Log out of SHYFEM Workbench?</p>
  <form method="post" action="{logout_action}">
    <button type="submit">Log out</button>
  </form>
  <p><a href="{home}">Cancel</a></p>
</body>
</html>
"""


# ------------------------------------------------------------------
# ASGI Middleware
# ------------------------------------------------------------------


class SessionAuthMiddleware:
    """ASGI middleware that enforces cookie-based session authentication.

    Parameters
    ----------
    app:
        The inner ASGI application.
    auth_service:
        An :class:`AuthService` instance (or compatible mock).
    local_mode:
        When ``True``, bypass all authentication and inject a synthetic
        admin user into every request.
    session_ttl_hours:
        Default session time-to-live passed to ``create_session``.
    trusted_proxies:
        CIDR ranges (e.g. ``["127.0.0.0/8"]``) whose X-Forwarded-For header
        is trusted for client-IP resolution (audit logging). An untrusted
        peer's X-Forwarded-For is attacker-controlled and is ignored;
        ``scope["client"][0]`` is used instead. Defaults to none trusted.
    """

    def __init__(
        self,
        app,
        auth_service,
        local_mode=False,
        session_ttl_hours=24,
        root_path="",
        use_secure_cookies=False,
        audit_service=None,
        feedback_service=None,
        trusted_proxies=None,
    ):
        self.app = app
        self.auth_service = auth_service
        self.local_mode = local_mode
        self.session_ttl_hours = session_ttl_hours
        self.root_path = root_path.rstrip("/")
        self.use_secure_cookies = use_secure_cookies
        self.audit_service = audit_service
        self.feedback_service = feedback_service
        self.trusted_proxies = trusted_proxies or []

    async def __call__(self, scope, receive, send):
        # ----------------------------------------------------------
        # Local mode: skip everything, inject synthetic admin
        # ----------------------------------------------------------
        if self.local_mode:
            token = _user_var.set(_SYNTHETIC_LOCAL_USER)
            try:
                await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)
            return

        # ----------------------------------------------------------
        # Extract session cookie and root_path from scope
        # ----------------------------------------------------------
        session_token = self._extract_session_token(scope)
        root_path = scope.get("root_path", "") or self.root_path

        # ----------------------------------------------------------
        # HTTP requests
        # ----------------------------------------------------------
        if scope["type"] == "http":
            path = scope.get("path", "/")
            method = scope.get("method", "GET")

            # GET /login -- serve the login page
            if path == "/login" and method == "GET":
                await self._serve_login_page(send, root_path=root_path)
                return

            # POST /login -- authenticate credentials
            if path == "/login" and method == "POST":
                await self._handle_login_post(scope, receive, send, root_path=root_path)
                return

            # GET /logout -- CSRF-safe confirm page only; does not mutate
            # state (see the _LOGOUT_CONFIRM_HTML comment above for why).
            if path == "/logout" and method == "GET":
                await self._serve_logout_confirm(send, root_path=root_path)
                return

            # POST /logout -- destroy session. A forged cross-site POST
            # arrives without the SameSite=Lax session cookie, so it is a
            # no-op (session_token is None, delete_session is skipped).
            if path == "/logout" and method == "POST":
                user = None
                if session_token:
                    user = self.auth_service.validate_session(session_token)
                await self._handle_logout(
                    session_token,
                    send,
                    root_path=root_path,
                    username=(user or {}).get("username"),
                    client_ip=self._client_ip(scope),
                )
                return

            # GET /api/whoami -- return current user as JSON
            if path == "/api/whoami" and method == "GET":
                await self._handle_whoami(session_token, send)
                return

            # /api/feedback -- anonymous POST (submit), admin-only GET (list).
            # MUST stay above the auth gate below so anonymous POST is not
            # redirected to /login. Per-IP rate limiting is supplied by the
            # outer RateLimitMiddleware.
            if path == "/api/feedback":
                if method == "POST":
                    await self._handle_feedback_post(scope, receive, send)
                    return
                if method == "GET":
                    await self._handle_feedback_get(scope, session_token, send)
                    return

            # All other paths: require valid session
            user = None
            if session_token:
                user = self.auth_service.validate_session(session_token)

            if user is None:
                await self._redirect(send, f"{root_path}/login")
                return

            token = _user_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)
            return

        # ----------------------------------------------------------
        # WebSocket connections
        # ----------------------------------------------------------
        if scope["type"] == "websocket":
            user = None
            if session_token:
                user = self.auth_service.validate_session(session_token)

            if user is None:
                # Allow unauthenticated WS only from localhost behind
                # reverse proxy (Shiny Server's internal WS connection
                # doesn't forward cookies, but connects from 127.0.0.1).
                client = scope.get("client")
                client_host = client[0] if client else None
                is_local = client_host in ("127.0.0.1", "::1")
                if not (self.root_path and is_local):
                    await send({"type": "websocket.close", "code": 4001})
                    return

            token = _user_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)
            return

        # ----------------------------------------------------------
        # Other scope types (e.g. lifespan): pass through
        # ----------------------------------------------------------
        await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_session_token(scope) -> str | None:
        """Read the ``shyfem_session`` cookie from ASGI scope headers."""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                cookies = _parse_cookie(header_value)
                return cookies.get("shyfem_session")
        return None

    def _client_ip(self, scope) -> str | None:
        """Return the client IP for audit logging.

        Honors X-Forwarded-For only when the direct socket peer
        (``scope["client"][0]``) is a configured trusted proxy (see
        ``trusted_proxies``); otherwise X-Forwarded-For is attacker
        controlled (any client can set it) and is ignored in favor of the
        real peer. Delegates to the same rightmost-untrusted algorithm the
        rate limiter uses (``middleware.rate_limit.get_client_ip``).
        """
        return get_client_ip(scope, self.trusted_proxies)

    def _audit(self, username, action, detail=None, ip_address=None):
        """Best-effort audit log. Never propagates exceptions."""
        if self.audit_service is None:
            return
        try:
            self.audit_service.log(
                username=username,
                action=action,
                detail=detail,
                ip_address=ip_address,
            )
        except Exception:
            logger.exception("Failed to write audit log entry")

    async def _serve_login_page(self, send, error: str = "", root_path: str = ""):
        """Send the login page HTML as a 200 response."""
        csrf_token = secrets.token_urlsafe(32)
        cookie_path = root_path or "/"
        html = _LOGIN_HTML.format(
            error=error,
            login_action=f"{root_path}/login",
            csrf_token=csrf_token,
        )
        body = html.encode("utf-8")
        csrf_cookie = f"csrf_token={csrf_token}; Path={cookie_path}; HttpOnly; SameSite=Lax"
        if self.use_secure_cookies:
            csrf_cookie += "; Secure"
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"set-cookie", csrf_cookie.encode("utf-8")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    async def _serve_logout_confirm(self, send, root_path: str = ""):
        """Send the CSRF-safe logout confirm page as a 200 response.

        GET here never destroys the session -- it only renders a form that
        POSTs to ``{root_path}/logout``, which is where the actual logout
        happens (see ``_handle_logout``, invoked from the POST branch).
        """
        html = _LOGOUT_CONFIRM_HTML.format(
            logout_action=f"{root_path}/logout",
            home=f"{root_path}/" if root_path else "/",
        )
        body = html.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    async def _handle_login_post(self, scope, receive, send, root_path: str = ""):
        """Parse POST form data, authenticate, and redirect or re-render."""
        message = await receive()
        raw_body = message.get("body", b"")
        form = urllib.parse.parse_qs(raw_body.decode("utf-8"))

        # CSRF double-submit cookie validation
        form_csrf = form.get("csrf_token", [""])[0]
        cookie_csrf = ""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                cookies = _parse_cookie(header_value)
                cookie_csrf = cookies.get("csrf_token", "")
                break
        if not form_csrf or not cookie_csrf or form_csrf != cookie_csrf:
            error_html = (
                '<div class="error-alert" role="alert">'
                "Invalid request. Please try again."
                "</div>"
            )
            await self._serve_login_page(send, error=error_html, root_path=root_path)
            return

        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]

        user = self.auth_service.authenticate(username, password)
        if user is None:
            self._audit(
                username=username or "<empty>",
                action="login_failed",
                ip_address=self._client_ip(scope),
            )
            error_html = (
                '<div class="error-alert" role="alert">' "Invalid username or password." "</div>"
            )
            await self._serve_login_page(send, error=error_html, root_path=root_path)
            return

        self._audit(
            username=user["username"],
            action="login_success",
            ip_address=self._client_ip(scope),
        )

        # Create session and set cookie
        token = self.auth_service.create_session(user["id"], ttl_hours=self.session_ttl_hours)
        ttl_seconds = self.session_ttl_hours * 3600
        cookie_path = root_path or "/"
        secure = "; Secure" if self.use_secure_cookies else ""
        cookie = (
            f"shyfem_session={token}; "
            f"Path={cookie_path}; HttpOnly; SameSite=Lax; Max-Age={ttl_seconds}{secure}"
        )
        redirect_to = f"{root_path}/" if root_path else "/"
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [
                    (b"location", redirect_to.encode("utf-8")),
                    (b"set-cookie", cookie.encode("utf-8")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def _handle_logout(
        self, session_token, send, root_path: str = "", username=None, client_ip=None
    ):
        """Delete the session and redirect to /login with cookie cleared."""
        if session_token:
            self.auth_service.delete_session(session_token)

        self._audit(
            username=username or "unknown",
            action="logout",
            ip_address=client_ip,
        )

        cookie_path = root_path or "/"
        cookie = f"shyfem_session=; Path={cookie_path}; HttpOnly; SameSite=Lax; Max-Age=0"
        redirect_to = f"{root_path}/login"
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [
                    (b"location", redirect_to.encode("utf-8")),
                    (b"set-cookie", cookie.encode("utf-8")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def _handle_whoami(self, session_token, send):
        """Return the current user as JSON, or 401 if not authenticated."""
        import json

        user = None
        if session_token:
            user = self.auth_service.validate_session(session_token)

        if user is None:
            body = b'{"error":"not authenticated"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        ws_token = self.auth_service.create_ws_token(user["id"], session_token)
        body = json.dumps(
            {
                "username": user.get("username", ""),
                "display_name": user.get("display_name", ""),
                "role": user.get("role", ""),
                "ws_token": ws_token,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _send_json(send, status: int, obj: dict):
        """Send a JSON response with the given status code."""
        import json

        body = json.dumps(obj).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    def _get_feedback_service(self):
        """Return the injected FeedbackService, or build a default one."""
        if self.feedback_service is not None:
            return self.feedback_service
        from shyfem_ui.services.feedback_service import FeedbackService

        return FeedbackService()

    async def _handle_feedback_get(self, scope, session_token, send):
        """Admin-only: return feedback rows as JSON ({"data": [...], "total": N})."""
        from urllib.parse import parse_qs

        user = self.auth_service.validate_session(session_token) if session_token else None
        if user is None or user.get("role") != "admin":
            await self._send_json(send, 403, {"error": "admin access required"})
            return

        qs = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="replace"))
        status = (qs.get("status", [None])[0]) or None
        ftype = (qs.get("type", [None])[0]) or None
        try:
            limit = int(qs.get("limit", ["100"])[0])
            offset = int(qs.get("offset", ["0"])[0])
        except (ValueError, TypeError):
            limit, offset = 100, 0

        svc = self._get_feedback_service()
        data = svc.list(status=status, feedback_type=ftype, limit=limit, offset=offset)
        total = svc.count(status=status, feedback_type=ftype)
        await self._send_json(send, 200, {"data": data, "total": total})

    # Cap the accumulated request body for the anonymous feedback endpoint.
    # Comfortably above the largest valid payload (8000-char description + the
    # other fields) but bounds memory for a deliberately oversized chunked POST,
    # which the field-length caps in FeedbackService cannot prevent (they run
    # only after the whole body is in memory). The endpoint is anonymous and, in
    # local mode, not request-count rate-limited, so the cap is the only guard.
    _MAX_FEEDBACK_BODY = 64 * 1024

    async def _handle_feedback_post(self, scope, receive, send):
        """Anonymous: store a submitted bug report / suggestion."""
        import json

        body_bytes = b""
        while True:
            message = await receive()
            body_bytes += message.get("body", b"")
            if len(body_bytes) > self._MAX_FEEDBACK_BODY:
                await self._send_json(send, 413, {"error": "payload too large"})
                return
            if not message.get("more_body", False):
                break

        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._send_json(send, 400, {"error": "invalid JSON"})
            return
        if not isinstance(payload, dict):
            await self._send_json(send, 400, {"error": "invalid JSON"})
            return

        svc = self._get_feedback_service()
        try:
            rec = svc.create(
                feedback_type=payload.get("type"),
                title=payload.get("title"),
                description=payload.get("description"),
                severity=payload.get("severity"),
                contact_email=payload.get("contact_email"),
                page=payload.get("page"),
                app_version=payload.get("app_version"),
            )
        except ValueError as e:
            await self._send_json(send, 400, {"error": str(e)})
            return
        except Exception:
            logger.exception("Failed to store feedback")
            await self._send_json(send, 500, {"error": "internal error"})
            return

        self._audit(
            "anonymous",
            "feedback_submit",
            detail=f"{rec['feedback_type']}: {rec['title']}",
            ip_address=self._client_ip(scope),
        )
        await self._send_json(send, 201, {"id": rec["id"], "status": rec["status"]})

    @staticmethod
    async def _redirect(send, location: str, status: int = 302):
        """Send a minimal HTTP redirect."""
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"location", location.encode("utf-8")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})
