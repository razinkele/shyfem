"""Entry point for Shiny Server."""

from shyfem_ui.app import create_app

# Create the Shiny app instance for Shiny Server
app = create_app()
