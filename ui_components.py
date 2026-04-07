import html
import inspect
from typing import List, Tuple

import streamlit as st
from html_templates import render_fragment

def inject_global_styles(theme_mode: str = "Dark") -> None:
    is_light = str(theme_mode or "Dark").strip().lower() == "light"
    theme_vars = render_fragment("theme_vars_light.css" if is_light else "theme_vars_dark.css")
    css = render_fragment("global_styles.html", theme_vars=theme_vars)
    st.markdown(css, unsafe_allow_html=True)


def render_top_bar() -> None:
    st.markdown('<div class="topbar-row-anchor"></div>', unsafe_allow_html=True)
    left, middle, right = columns_compat([1.32, 1.38, 1.30], gap="medium", vertical_alignment="center")
    left.markdown(render_fragment("topbar_brand.html"), unsafe_allow_html=True)
    middle.markdown(render_fragment("topbar_nav.html"), unsafe_allow_html=True)
    is_light = st.session_state.get("ui_theme_light", False)
    theme_state = "Light mode" if is_light else "Dark mode"
    right.markdown(
        render_fragment("topbar_appearance.html", theme_state=html.escape(theme_state)),
        unsafe_allow_html=True,
    )
    mode_button_label = "☀️ Light mode" if is_light else "🌙 Dark mode"
    right.markdown('<div class="theme-mode-toggle-anchor"></div>', unsafe_allow_html=True)
    mode_changed = right.button(
        mode_button_label,
        key="theme_mode_button",
        help="Switch between light and dark interface modes",
        use_container_width=True,
    )
    if mode_changed:
        st.session_state.ui_theme_light = not is_light
        st.session_state.ui_theme_mode = "Light" if st.session_state.ui_theme_light else "Dark"
        st.rerun()


def render_auth_shell() -> None:
    st.markdown(render_fragment("auth_shell.html"), unsafe_allow_html=True)


def render_app_hero() -> None:
    st.markdown(render_fragment("app_hero.html"), unsafe_allow_html=True)


def render_steps_showcase() -> None:
    st.markdown(render_fragment("steps_showcase.html"), unsafe_allow_html=True)


def render_parser_intro() -> None:
    st.markdown(render_fragment("parser_intro.html"), unsafe_allow_html=True)


def render_tool_card_header(icon: str, title: str, subtitle: str) -> None:
    st.markdown(
        render_fragment(
            "tool_card_header.html",
            icon=html.escape(icon),
            title=html.escape(title),
            subtitle=html.escape(subtitle),
        ),
        unsafe_allow_html=True,
    )


def close_tool_card() -> None:
    return None


def _current_progress_step(uploaded_files: List, status: str, has_results: bool) -> int:
    if has_results:
        return 4
    if str(status or "").lower() == "running":
        return 3
    if uploaded_files:
        return 2
    return 1


def render_progress_panel(status: str, uploaded_files: List, has_results: bool) -> None:
    current_step = _current_progress_step(uploaded_files, status, has_results)
    status_key = str(status or "idle").strip().lower()
    status_label = {"idle": "Idle", "running": "Running", "stopped": "Stopped"}.get(status_key, status.title())
    steps = [
        ("Select Your Bank", "Current step" if current_step == 1 else "Choose the parser format"),
        ("Upload Statement", "Ready when PDF files are added"),
        ("Process & Analyse", "Start the parser to extract data"),
        ("View Results", "Review tables and download reports"),
    ]

    steps_html = "".join(
        f'<div class="progress-step{" is-active" if idx == current_step else ""}"><div class="progress-index">{idx}</div><div><div class="progress-step-title">{html.escape(title)}</div><div class="progress-step-copy">{html.escape(copy)}</div></div></div>'
        for idx, (title, copy) in enumerate(steps, start=1)
    )
    st.markdown(
        f"""
        <section class="progress-shell">
            <div class="progress-title">Progress</div>
            <div class="progress-steps">{steps_html}</div>
            <div class="progress-divider"></div>
            <div class="progress-footer"><span>Status</span><span class="mini-pill">{html.escape(status_label)}</span></div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_section_header(label: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="section-head">
            <span class="section-badge">{html.escape(label)}</span>
            <h2 class="section-title">{html.escape(title)}</h2>
            <p class="section-copy">{html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_card(status: str) -> None:
    status_key = (status or "idle").strip().lower()
    status_copy = {
        "idle": "Ready to accept uploads and begin parsing.",
        "running": "Processing uploaded statements and generating outputs.",
        "stopped": "Run paused. You can resume or reset the workspace.",
    }
    status_label = {
        "idle": "Idle",
        "running": "Running",
        "stopped": "Stopped",
    }.get(status_key, status.upper())
    st.markdown(
        f"""
        <div class="status-card is-{html.escape(status_key)}">
            <div class="status-card__group">
                <span class="status-card__dot"></span>
                <div>
                    <div class="status-card__title">Processing status</div>
                    <div class="status-card__copy">{html.escape(status_copy.get(status_key, "Workspace updated."))}</div>
                </div>
            </div>
            <span class="status-pill">{html.escape(status_label)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_file_chips(uploaded_files: List, encrypted_files: List[str]) -> None:
    if not uploaded_files:
        return

    chips = []
    encrypted_set = set(encrypted_files or [])
    for uploaded_file in uploaded_files:
        name = getattr(uploaded_file, "name", str(uploaded_file))
        extra_class = " is-encrypted" if name in encrypted_set else ""
        icon = "🔒" if name in encrypted_set else "📎"
        chips.append(f'<span class="file-chip{extra_class}">{icon} {html.escape(name)}</span>')

    st.markdown(f'<div class="file-chip-row">{"".join(chips)}</div>', unsafe_allow_html=True)


def _supports_streamlit_kwarg(func, name: str) -> bool:
    try:
        return name in inspect.signature(func).parameters
    except Exception:
        return False


def columns_compat(spec, **kwargs):
    call_kwargs = dict(kwargs)
    if "vertical_alignment" in call_kwargs and not _supports_streamlit_kwarg(st.columns, "vertical_alignment"):
        call_kwargs.pop("vertical_alignment", None)
    return st.columns(spec, **call_kwargs)


def button_compat(label: str, primary: bool = False, **kwargs):
    call_kwargs = dict(kwargs)
    if primary and _supports_streamlit_kwarg(st.button, "type"):
        call_kwargs["type"] = "primary"
    if "use_container_width" in call_kwargs and not _supports_streamlit_kwarg(st.button, "use_container_width"):
        call_kwargs.pop("use_container_width", None)
    return st.button(label, **call_kwargs)


def form_submit_button_compat(label: str, primary: bool = False, **kwargs):
    call_kwargs = dict(kwargs)
    if primary and _supports_streamlit_kwarg(st.form_submit_button, "type"):
        call_kwargs["type"] = "primary"
    if "use_container_width" in call_kwargs and not _supports_streamlit_kwarg(st.form_submit_button, "use_container_width"):
        call_kwargs.pop("use_container_width", None)
    return st.form_submit_button(label, **call_kwargs)


def toggle_compat(label: str, **kwargs):
    call_kwargs = dict(kwargs)
    if hasattr(st, "toggle"):
        if "label_visibility" in call_kwargs and not _supports_streamlit_kwarg(st.toggle, "label_visibility"):
            call_kwargs.pop("label_visibility", None)
        return st.toggle(label, **call_kwargs)
    call_kwargs.pop("label_visibility", None)
    return st.checkbox(label, **call_kwargs)


def download_button_compat(label: str, *args, **kwargs):
    call_kwargs = dict(kwargs)
    if "use_container_width" in call_kwargs and not _supports_streamlit_kwarg(st.download_button, "use_container_width"):
        call_kwargs.pop("use_container_width", None)
    return st.download_button(label, *args, **call_kwargs)


def render_metric_cards(items: List[Tuple[str, str]]) -> None:
    if not items:
        return
    cards_html = "".join(
        f'<div class="metric-card"><div class="metric-card__label">{html.escape(label)}</div><div class="metric-card__value">{html.escape(value)}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="metric-grid">{cards_html}</div>', unsafe_allow_html=True)
