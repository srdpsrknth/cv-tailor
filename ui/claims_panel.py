"""The "Suggested claims" panel on a saved application: confirm-first, never automatic."""

import streamlit as st
from ui import services_bridge as bridge

TITLE = "Suggested claims (confirm only what is true)"


def _target(attach_to):
    from services.suggested_claims import describe_target

    return describe_target(attach_to)


def _begin_confirmation(prefix, numbers):
    """Button callback: remember what was ticked and move to the confirmation step."""
    chosen = [n for n in numbers if st.session_state.get(f"{prefix}_claim_{n}")]
    if chosen:
        st.session_state[f"{prefix}_claims_confirm"] = chosen


def _cancel(prefix):
    st.session_state.pop(f"{prefix}_claims_confirm", None)


def _accept(config, profile_id, job_id, prefix):
    """Button callback: write the confirmed claims into the profile and keep the outcome."""
    numbers = st.session_state.pop(f"{prefix}_claims_confirm", [])
    try:
        result = bridge.accept_claims(config, profile_id, job_id, numbers)
    except ValueError as error:
        st.session_state[f"{prefix}_claims_error"] = str(error)
        return
    for number in numbers:
        st.session_state.pop(f"{prefix}_claim_{number}", None)
    st.session_state[f"{prefix}_claims_done"] = (
        f"Added {len(result.changes)} statement(s) to your profile "
        f"(backup: {result.backup.name if result.backup else 'none'}). "
        "Regenerate this application for them to appear in the documents."
    )


def _dismiss(config, profile_id, job_id, prefix, numbers):
    """Button callback: mark the ticked suggestions rejected. The profile is never touched."""
    chosen = [n for n in numbers if st.session_state.get(f"{prefix}_claim_{n}")]
    if not chosen:
        return
    try:
        done = bridge.reject_claims(config, profile_id, job_id, chosen)
    except ValueError as error:
        st.session_state[f"{prefix}_claims_error"] = str(error)
        return
    for number in chosen:
        st.session_state.pop(f"{prefix}_claim_{number}", None)
    st.session_state[f"{prefix}_claims_done"] = (
        f"Dismissed {len(done)} suggestion(s). Your profile was not changed."
    )


def render_claims_panel(config, profile_id, job_id, prefix):
    """List the model's questions; add the ones the candidate confirms to the profile.

    Nothing is written until the explicit confirmation step, and the documents do not
    change: a regeneration is needed before an accepted claim can appear in them.
    """
    try:
        suggestions = bridge.claims_for(config, profile_id, job_id)
    except (OSError, ValueError):
        return
    if not suggestions:
        return
    pending = [item for item in suggestions if item.get("status", "pending") == "pending"]
    confirm_key = f"{prefix}_claims_confirm"
    done = st.session_state.pop(f"{prefix}_claims_done", None)
    failure = st.session_state.pop(f"{prefix}_claims_error", None)
    with st.expander(TITLE, expanded=bool(pending) or bool(done)):
        st.caption(
            "The model proposes statements that look plausible from your profile. They are "
            "questions, not facts, and are not in your documents. Tick only what is TRUE "
            "of you; those are added to your private profile. Regenerate the application "
            "afterwards: the existing documents do not change."
        )
        if done:
            st.success(done)
        if failure:
            st.error(failure)
        confirming = confirm_key in st.session_state
        for item in suggestions:
            status = item.get("status", "pending")
            if status != "pending":
                st.markdown(f"{item['proposed_text']} · **{status}**")
                continue
            st.checkbox(
                item["proposed_text"], key=f"{prefix}_claim_{item['number']}", disabled=confirming
            )
            st.caption(f"For: {item.get('requirement', '')} · Adds to {_target(item['attach_to'])}")
            if item.get("rationale"):
                st.caption(f"Why plausible: {item['rationale']}")
        if not pending:
            return

        if not confirming:
            chosen = [i["number"] for i in pending if st.session_state.get(f"{prefix}_claim_{i['number']}")]
            numbers = [i["number"] for i in pending]
            add_column, dismiss_column = st.columns(2)
            with add_column:
                st.button(
                    "Add selected to my profile", key=f"{prefix}_claims_add",
                    disabled=not chosen, on_click=_begin_confirmation,
                    args=(prefix, numbers),
                )
            with dismiss_column:
                st.button(
                    "Dismiss selected", key=f"{prefix}_claims_dismiss",
                    disabled=not chosen, on_click=_dismiss,
                    args=(config, profile_id, job_id, prefix, numbers),
                    help="Marks the ticked suggestions as not true. Your profile is not changed.",
                )
            return

        try:
            plan = bridge.plan_claims(config, profile_id, job_id, st.session_state[confirm_key])
        except ValueError as error:
            st.error(str(error))
            st.button("Cancel", key=f"{prefix}_claims_cancel", on_click=_cancel, args=(prefix,))
            return
        st.warning(
            "Confirm: these statements will be written into your private profile "
            f"({profile_id}). A timestamped backup is saved first."
        )
        for change in plan.changes:
            st.markdown(f"- {change.description}")
        for number, reason in plan.skipped:
            st.caption(f"Skipping #{number}: {reason}")
        for warning in plan.warnings:
            st.warning(warning)
        yes_column, cancel_column = st.columns(2)
        with yes_column:
            st.button(
                "Yes, these are true: add them", key=f"{prefix}_claims_yes", type="primary",
                disabled=not plan.changes, on_click=_accept,
                args=(config, profile_id, job_id, prefix),
            )
        with cancel_column:
            st.button("Cancel", key=f"{prefix}_claims_cancel", on_click=_cancel, args=(prefix,))
