"""Tests for next_step_card component."""
import dataclasses

import pytest

from shyfem_ui.components.next_step_card import NextStepLink, next_step_card


class TestNextStepLink:

    def test_frozen_dataclass(self):
        """frozen=True means link can't be mutated after construction."""
        link = NextStepLink("L", "Run", "D")
        with pytest.raises(dataclasses.FrozenInstanceError):
            link.label = "X"

    def test_named_access(self):
        link = NextStepLink(label="L", nav_target="Run", description="D")
        assert link.label == "L"
        assert link.nav_target == "Run"


class TestNextStepCard:

    def test_renders_with_one_link(self):
        link = NextStepLink("Watch progress", "Run", "Live log here")
        card = next_step_card(title="Job submitted", links=[link])
        # Render to HTML to check structure
        html = str(card)
        assert "Job submitted" in html
        assert "Watch progress" in html
        assert "Live log here" in html
        assert "shyfemNavTo" in html

    def test_renders_hyphenated_nav_target(self):
        """'Post-Process' (hyphen) is a real data-nav value and must work."""
        link = NextStepLink("Postprocess", "Post-Process", "Run shyelab")
        card = next_step_card(title="Done", links=[link])
        html = str(card)
        # The JS string is double-quoted JSON inside the onclick:
        # shyfemNavTo("Post-Process")
        assert '"Post-Process"' in html or "Post-Process" in html

    def test_rejects_invalid_nav_target_with_quote(self):
        """Single-quote in nav_target must be rejected."""
        with pytest.raises(ValueError, match="alphanumeric"):
            link = NextStepLink("Bad", "It's bad", "D")
            next_step_card(title="x", links=[link])

    def test_rejects_invalid_nav_target_with_paren(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            link = NextStepLink("Bad", "evil(", "D")
            next_step_card(title="x", links=[link])

    def test_rejects_empty_nav_target(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            link = NextStepLink("Bad", "", "D")
            next_step_card(title="x", links=[link])

    def test_accepts_underscored_nav_target(self):
        """Underscore is allowed (defense-in-depth for hypothetical future labels)."""
        link = NextStepLink("L", "Foo_bar", "D")
        # Must not raise
        card = next_step_card(title="x", links=[link])
        assert "Foo_bar" in str(card)

    def test_typeof_guard_in_onclick(self):
        """The onclick must guard against shyfemNavTo being undefined."""
        link = NextStepLink("L", "Run", "D")
        card = next_step_card(title="x", links=[link])
        html = str(card)
        assert "typeof shyfemNavTo" in html
