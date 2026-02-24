"""Custom Plotly theme for SHYFEM UI -- ocean/environmental palette.

Provides light and dark templates matching the SHYFEM CSS design system.
Usage: fig.update_layout(template=get_plotly_template(dark=is_dark))
Or globally: register_shyfem_template(dark=False)
"""

SHYFEM_OCEAN_COLORSCALE = [
    [0.0, "#0B3D5B"],
    [0.2, "#1A6B8A"],
    [0.4, "#2D9CBA"],
    [0.6, "#3DB8A0"],
    [0.8, "#E6A641"],
    [1.0, "#E8725A"],
]

SHYFEM_CATEGORICAL_COLORS = [
    "#1A6B8A",
    "#3DB8A0",
    "#E8725A",
    "#E6A641",
    "#7B6CB5",
    "#4ECDC4",
]

_SHARED = {
    "font": {
        "family": "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        "size": 13,
    },
    "colorway": SHYFEM_CATEGORICAL_COLORS,
    "colorscale": {"sequential": SHYFEM_OCEAN_COLORSCALE},
    "margin": {"l": 60, "r": 20, "t": 40, "b": 50},
    "hoverlabel": {"font_size": 12},
    "modebar": {
        "orientation": "v",
        "bgcolor": "rgba(0,0,0,0)",
    },
}


def get_plotly_template(dark: bool = False) -> dict:
    """Return a Plotly layout template dict for the SHYFEM ocean theme.

    Args:
        dark: If True, return the dark-mode variant.

    Returns:
        Dict suitable for plotly fig.update_layout(template=...).
    """
    if dark:
        theme = {
            "paper_bgcolor": "#2A3545",
            "plot_bgcolor": "#1A2332",
            "xaxis": {
                "gridcolor": "rgba(255,255,255,0.08)",
                "zerolinecolor": "rgba(255,255,255,0.08)",
                "color": "#E0E8F0",
            },
            "yaxis": {
                "gridcolor": "rgba(255,255,255,0.08)",
                "zerolinecolor": "rgba(255,255,255,0.08)",
                "color": "#E0E8F0",
            },
            "title": {"font": {"color": "#2D9CBA", "size": 16}},
            "font": {"color": "#E0E8F0"},
        }
    else:
        theme = {
            "paper_bgcolor": "#F5F0E8",
            "plot_bgcolor": "#FFFFFF",
            "xaxis": {
                "gridcolor": "rgba(0,0,0,0.06)",
                "zerolinecolor": "rgba(0,0,0,0.06)",
                "color": "#2C3E50",
            },
            "yaxis": {
                "gridcolor": "rgba(0,0,0,0.06)",
                "zerolinecolor": "rgba(0,0,0,0.06)",
                "color": "#2C3E50",
            },
            "title": {"font": {"color": "#0B3D5B", "size": 16}},
            "font": {"color": "#2C3E50"},
        }

    layout = {**_SHARED, **theme}
    # Merge font dicts (shared base + theme-specific color)
    layout["font"] = {**_SHARED["font"], **theme.get("font", {})}

    return {"layout": layout}


def register_shyfem_template(dark: bool = False) -> None:
    """Register the SHYFEM template as the Plotly default.

    Call once at app startup. All subsequent go.Figure() calls
    will use this template automatically.

    Args:
        dark: If True, register the dark-mode variant.
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    template_dict = get_plotly_template(dark=dark)
    pio.templates["shyfem"] = go.layout.Template(layout=template_dict["layout"])
    pio.templates.default = "shyfem"
