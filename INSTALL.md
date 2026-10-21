# LeaveFlow frontend redesign — installation

This is a **frontend overlay** for your existing LeaveFlow repository, not a standalone backend distribution.

## Install
1. Back up or commit your existing repository.
2. Copy `app.py`, `utils/ui.py`, `utils/components.py`, `.streamlit/config.toml`, the `views/` files, and the new `frontend/` folder into your existing `leaveflow/` project, preserving their paths.
3. Your original `auth/`, `analytics/`, `database/`, `services/`, `workflows/`, `config.py`, `.env`, and tests must stay in place.
4. From the project root, activate your environment, install your existing `requirements.txt`, and run `streamlit run app.py`.
5. Log in with your existing demo accounts and verify all three role workflows. Appearance is selectable in the sidebar.

## Scope
- 15 views, original application entry point, existing shared components, theme configuration, CSS design system.
- Cloud, Midnight, Lavender themes share a consistent layout and typography.
- No database schema, authentication, service logic, or workflow engine changes.
- Static syntax verification completed; browser/database integration tests require your original project and PostgreSQL.

## Compatibility notes
- Keep `views/` as the directory registered in `app.py`. If your actual project uses `pages/`, reconcile that before copying.
- This overlay assumes the same Streamlit version/API as the uploaded source (including `st.navigation`, `st.Page`, and `width="stretch"`).
- CSS targets Streamlit internals, so visually inspect after Streamlit upgrades.
- Theme choice is session-scoped and is reset on a fresh session. The base `config.toml` uses Cloud.
- Existing hardcoded chart colors and some status badge colors are intentionally semantic, not accent colors.
