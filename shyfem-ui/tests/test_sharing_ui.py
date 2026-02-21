"""Tests for sharing UI pure functions."""

import pytest


class TestShouldShowShareButton:
    def test_owner_sees_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        user = {"id": 10, "role": "user"}
        assert _should_show_share_button(project, user) is True

    def test_admin_sees_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        user = {"id": 99, "role": "admin"}
        assert _should_show_share_button(project, user) is True

    def test_non_owner_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        user = {"id": 20, "role": "user"}
        assert _should_show_share_button(project, user) is False

    def test_none_user_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        assert _should_show_share_button(project, None) is False

    def test_none_owner_id_admin_sees(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": None}
        user = {"id": 99, "role": "admin"}
        assert _should_show_share_button(project, user) is True

    def test_none_owner_id_user_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": None}
        user = {"id": 20, "role": "user"}
        assert _should_show_share_button(project, user) is False


class TestBuildPermissionsTableData:
    def test_empty_list(self):
        from shyfem_ui.pages.home import _build_permissions_table_data
        assert _build_permissions_table_data([]) == []

    def test_formats_permissions(self):
        from shyfem_ui.pages.home import _build_permissions_table_data
        perms = [
            {"user_id": 2, "username": "bob", "display_name": "Bob", "role": "editor"},
            {"user_id": 3, "username": "charlie", "display_name": None, "role": "viewer"},
        ]
        result = _build_permissions_table_data(perms)
        assert len(result) == 2
        assert result[0]["username"] == "bob"
        assert result[0]["display_name"] == "Bob"
        assert result[0]["role"] == "editor"
        assert result[1]["display_name"] == "charlie"  # fallback to username
