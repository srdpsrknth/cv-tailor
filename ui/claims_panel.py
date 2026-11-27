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
    numbers = st.session_state.pop(f"{prefix}_claims_confirm", [])
    for number in numbers:
        st.session_state.pop(f"{prefix}_claim_draft_{number}", None)


def _draft(config, profile_id, job_id, prefix, number):
    try:
        result = bridge.draft_claim(
            config, profile_id, job_id, number, st.session_state[f"{prefix}_claim_notes_{number}"],
        )
    except ValueError as error:
        st.session_state[f"{prefix}_claims_error"] = str(error)
        return
    st.session_state[f"{prefix}_claim_edit_{number}"] = result.profile_entry
    st.session_state[f"{prefix}_claim_draft_{number}"] = result


def _accept(config, profile_id, job_id, prefix):
    """Button callback: write the confirmed claims into the profile and keep the outcome."""
    numbers = st.session_state.get(f"{prefix}_claims_confirm", [])
    edits = {number: st.session_state[f"{prefix}_claim_edit_{number}"] for number in numbers}
    try:
        result = bridge.accept_claims(config, profile_id, job_id, numbers, edits=edits)
    except ValueError as error:
        st.session_state[f"{prefix}_claims_error"] = str(error)
        return
    st.session_state.pop(f"{prefix}_claims_confirm", None)
    for number in numbers:
        st.session_state.pop(f"{prefix}_claim_{number}", None)
    st.session_state[f"{prefix}_claims_done"] = (
        f"Added {len(result.changes)} statement(s) to your profile "
        f"(backup: {result.backup.name if result.backup else 'none'}). "
        "You can now review a CV edit for this application."
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


def _save_cv_revision(config, profile_id, job_id, prefix, number, source_id, replace_at, edit_key):
    from services.claim_cv_revision import save_claim_cv_revision

    try:
        revision = save_claim_cv_revision(
            config, profile_id, job_id, number, st.session_state[edit_key], replace_at, source_id,
        )
    except (ValueError, OSError) as error:
        st.session_state[f"{prefix}_claims_error"] = str(error)
    else:
        st.session_state[f"{prefix}_claim_revisions"] = revision
        st.session_state[f"{prefix}_claims_done"] = "Saved an updated CV revision for this application."


def _render_cv_revisions(config, profile_id, job_id, prefix, suggestions):
    from services.claim_cv_revision import (
        ARTIFACTS, claim_cv_options, list_claim_cv_revisions, read_claim_cv_artifact,
    )
    from services.suggested_claims import MAX_BULLET_CHARS, MAX_SKILL_CHARS

    accepted = {item["number"]: item for item in suggestions if item.get("status") == "accepted"}
    if not accepted:
        return
    try:
        revisions = list_claim_cv_revisions(config, profile_id, job_id)
    except (OSError, ValueError) as error:
        st.warning(str(error))
        return
    if revisions:
        versions = {item["id"]: item for item in revisions}
        selected = st.selectbox(
            "Revised CVs", options=list(versions), key=f"{prefix}_claim_revisions",
            format_func=lambda key: f"Revision {len(versions) - list(versions).index(key)} · claim #{versions[key]['claim']}",
        )
        if selected:
            for label, column in zip(ARTIFACTS, st.columns(len(ARTIFACTS))):
                try:
                    data = read_claim_cv_artifact(config, profile_id, job_id, selected, label)
                except (OSError, ValueError):
                    continue
                with column:
                    st.download_button(
                        f"Download revised {label}", data, file_name=ARTIFACTS[label],
                        key=f"{prefix}_{selected}_{label}", on_click="ignore",
                    )
    if not st.checkbox("Use a confirmed claim in this CV", key=f"{prefix}_claim_cv_open"):
        return
    number = st.selectbox(
        "Confirmed claim", options=list(accepted), key=f"{prefix}_claim_cv_number",
        format_func=lambda n: f"#{n} · {_target(accepted[n]['attach_to'])}",
    )
    item = accepted[number]
    try:
        source_id, current = claim_cv_options(config, profile_id, job_id, number)
    except (ValueError, OSError) as error:
        st.info(str(error))
        return
    replace_at = st.selectbox(
        "Add or replace wording", options=[None, *range(len(current))],
        format_func=lambda index: "Add a new entry" if index is None else f"Replace entry {index + 1}",
        key=f"{prefix}_claim_cv_target_{number}_{source_id}",
    )
    if replace_at is not None:
        st.text(f"Current wording: {current[replace_at]}")
    draft = st.session_state.get(f"{prefix}_claim_draft_{number}")
    confirmed = item.get("accepted_text") or item["proposed_text"]
    limit = MAX_SKILL_CHARS if item["attach_to"]["type"] == "skill" else MAX_BULLET_CHARS
    proposed = draft.cv_bullet if draft and draft.profile_entry == confirmed else confirmed
    key = f"{prefix}_claim_cv_text_{number}"
    wording = st.text_area(
        "Wording for this CV", value=proposed if len(proposed) <= limit else "",
        max_chars=limit, key=key, help="Use only facts you confirmed.",
    )
    st.button(
        "Approve wording and save CV revision", key=f"{prefix}_claim_cv_save",
        disabled=not wording.strip(), on_click=_save_cv_revision,
        args=(config, profile_id, job_id, prefix, number, source_id, replace_at, key),
        help="Renders PDF, Word and text locally and keeps the original application files.",
    )


def render_claims_panel(config, profile_id, job_id, prefix):
    """List the model's questions; add the ones the candidate confirms to the profile.

    Profile confirmation and saving a CV revision are separate actions.
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
            "of you, or edit the statement before confirming it. You can then use the "
            "confirmed fact in a CV revision."
        )
        if done:
            st.success(done)
        if failure:
            st.error(failure)
        confirming = confirm_key in st.session_state
        for item in suggestions:
            status = item.get("status", "pending")
            if status != "pending":
                text = item.get("accepted_text", item["proposed_text"])
                label = "saved to profile" if status == "accepted" else status
                st.text(f"{text} ({label})")
                continue
            st.checkbox(
                item["proposed_text"], key=f"{prefix}_claim_{item['number']}", disabled=confirming
            )
            st.caption(f"For: {item.get('requirement', '')} · Adds to {_target(item['attach_to'])}")
            if item.get("rationale"):
                st.caption(f"Why plausible: {item['rationale']}")
        if not pending:
            _render_cv_revisions(config, profile_id, job_id, prefix, suggestions)
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
            _render_cv_revisions(config, profile_id, job_id, prefix, suggestions)
            return

        from services.claim_acceptance import MAX_CONFIRMED_TEXT
        from services.suggested_claims import MAX_SKILL_CHARS

        edits = {}
        numbers = st.session_state[confirm_key]
        for item in pending:
            number = item["number"]
            if number not in numbers:
                continue
            edit_key = f"{prefix}_claim_edit_{number}"
            st.session_state.setdefault(edit_key, item["proposed_text"])
            is_skill = item["attach_to"]["type"] == "skill"
            edits[number] = st.text_area(
                f"Profile entry for claim #{number}", key=edit_key,
                max_chars=MAX_SKILL_CHARS if is_skill else MAX_CONFIRMED_TEXT,
            )
            if not is_skill:
                notes_key = f"{prefix}_claim_notes_{number}"
                notes = st.text_area(
                    f"Confirmed context for AI drafting on claim #{number} (optional)",
                    key=notes_key, max_chars=MAX_CONFIRMED_TEXT,
                    help="Add what you did, how you did it, or what changed. To save it locally as written, use the profile entry field.",
                )
                st.caption(
                    f"AI drafting sends these notes, the selected role or project's facts, and "
                    f"the posting requirement to {config.provider} ({config.model_for('cv')})."
                )
                st.button(
                    "Send notes and draft with AI (paid)", key=f"{prefix}_claim_ai_{number}",
                    disabled=not notes.strip() or not config.has_api_key,
                    on_click=_draft, args=(config, profile_id, job_id, prefix, number),
                )
                draft = st.session_state.get(f"{prefix}_claim_draft_{number}")
                if draft:
                    st.caption(f"{'Estimated cost' if draft.cost_estimated else 'Reported cost'}: ${draft.cost_usd:.6f}")
                    st.text(f"Proposed CV bullet: {draft.cv_bullet}")
        try:
            plan = bridge.plan_claims(config, profile_id, job_id, numbers, edits=edits)
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
