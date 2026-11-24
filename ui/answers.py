"""Edit and save portal answers in the Streamlit application workspace."""

import re
from uuid import uuid4

import streamlit as st
from pydantic import ValidationError

from models.portal_answers import AnswerQuestion
from models.profile import Profile
from services.portal_answers import MAX_QUESTIONS

copy_controls = st.components.v2.component(
    "copy_portal_answer",
    html='<button type="button">Copy answer</button> <span aria-live="polite"></span>',
    css="""
        button {font: inherit; color: inherit; background: transparent; border: 1px solid #8b9692;
            border-radius: .45rem; padding: .35rem .65rem; cursor: pointer;}
        button:focus-visible {outline: 3px solid #b6801d; outline-offset: 2px;}
        button:disabled {opacity: .55; cursor: default;}
        span {font: inherit; font-size: .9rem;}
    """,
    js="""
        export default function ({ parentElement, data }) {
            const button = parentElement.querySelector('button');
            const status = parentElement.querySelector('span');
            const editor = parentElement.host.closest('.' + CSS.escape('st-key-' + data.row));
            const field = editor?.querySelector('textarea');
            const text = () => field?.value ?? data.text;
            const count = () => {
                const answer = text();
                const words = answer.trim() ? answer.trim().split(/\\s+/).length : 0;
                const chars = answer.length;
                button.disabled = !answer.trim();
                const charLimit = data.maxCharacters ? ` / ${data.maxCharacters}` : '';
                const wordLimit = data.maxWords ? ` / ${data.maxWords}` : '';
                const exceeds = (data.maxCharacters && chars > data.maxCharacters)
                    || (data.maxWords && words > data.maxWords);
                return `${chars}${charLimit} characters · ${words}${wordLimit} words`
                    + (exceeds ? ' · Over limit' : '');
            };
            const update = () => { status.textContent = count(); };
            update();
            field?.addEventListener('input', update);
            button.onclick = async () => {
                const answer = text();
                try {
                    await navigator.clipboard.writeText(answer);
                    status.textContent = `Copied · ${count()}`;
                } catch (_) {
                    field?.focus();
                    field?.select();
                    status.textContent = 'Use Ctrl+C or Command+C to copy the selected answer.';
                }
            };
            return () => {
                field?.removeEventListener('input', update);
                button.onclick = null;
            };
        }
    """,
)


def is_editor_input(key):
    """Keep input widget state when leaving Answers for another workspace section."""
    return str(key).startswith("review_") and "_answer_input_" in str(key)


def _input_key(prefix, question_id, field):
    return f"{prefix}_answer_input_{question_id}_{field}"


def _load_editor(config, profile_id, job_id, prefix, state_key):
    from services.portal_answer_store import load_answer_sheet

    sheet = load_answer_sheet(config, profile_id=profile_id, job_id=job_id)
    edits = {edit.question_id: edit.text for edit in sheet.edits}
    for question in sheet.questions:
        for name in ("text", "max_characters", "max_words", "notes", "manual_only"):
            st.session_state[_input_key(prefix, question.id, name)] = getattr(
                question, name
            )
        st.session_state[_input_key(prefix, question.id, "facts")] = "\n".join(
            question.confirmed_facts
        )
        st.session_state[_input_key(prefix, question.id, "answer")] = edits.get(
            question.id, ""
        )
    editor = {
        "rows": [question.id for question in sheet.questions],
        "public_sources": list(sheet.public_sources),
        "revision": sheet.revision,
        "drafts": {},
        "evidence": {},
        "suggestions": {},
        "warnings": list(sheet.warnings),
    }
    st.session_state[state_key] = editor
    return editor


def _render_add_questions(prefix, editor):
    paste_key = _input_key(prefix, "batch", "paste")
    with st.expander("Paste multiple questions", expanded=not editor["rows"]):
        pasted = st.text_area(
            "Portal questions, separated by a blank line",
            key=paste_key,
            help="A question can span multiple lines. Check the editable questions after adding them.",
        )
        if st.button(
            "Add pasted questions",
            key=f"{prefix}_add_pasted",
            disabled=not pasted.strip(),
        ):
            questions = [
                part.strip()
                for part in re.split(r"\r?\n[ \t]*\r?\n", pasted)
                if part.strip()
            ]
            if len(questions) + len(editor["rows"]) > MAX_QUESTIONS:
                st.warning(f"Keep up to {MAX_QUESTIONS} questions in this editor.")
            else:
                for text in questions:
                    question_id = uuid4().hex
                    editor["rows"].append(question_id)
                    st.session_state[_input_key(prefix, question_id, "text")] = text
    if st.button(
        "Add one question",
        key=f"{prefix}_add_question",
        disabled=len(editor["rows"]) >= MAX_QUESTIONS,
    ):
        editor["rows"].append(uuid4().hex)


def _render_question(prefix, editor, question_id, number):
    def key(name):
        return _input_key(prefix, question_id, name)

    with st.container(border=True):
        text = st.text_area(f"Question {number}", key=key("text"), max_chars=4000)
        with st.expander("Limits, notes and facts"):
            characters, words = st.columns(2)
            max_characters = characters.number_input(
                "Character limit", 1, 8000, None, step=1, key=key("max_characters")
            )
            max_words = words.number_input(
                "Word limit", 1, 1500, None, step=1, key=key("max_words")
            )
            notes = st.text_area("Personal notes", key=key("notes"), max_chars=2000)
            facts = st.text_area("Confirmed facts, one per line", key=key("facts"))
            manual = st.checkbox(
                "Enter this answer myself",
                key=key("manual_only"),
                help="Use this for salary, availability, authorization and answers you want to control.",
            )
        pick, remove = st.columns([3, 1])
        if key("selected") not in st.session_state:
            st.session_state[key("selected")] = True
        selected = pick.checkbox(
            "Draft this answer", key=key("selected"), disabled=manual
        )
        if remove.button("Remove", key=f"{prefix}_remove_{question_id}"):
            editor["rows"].remove(question_id)
            editor["drafts"].pop(question_id, None)
            st.rerun()
    return {
        "id": question_id,
        "text": text,
        "max_characters": max_characters,
        "max_words": max_words,
        "notes": notes,
        "confirmed_facts": tuple(
            line.strip() for line in facts.splitlines() if line.strip()
        ),
        "manual_only": manual,
    }, selected and not manual and bool(text.strip())


def _render_public_sources(prefix, editor):
    from models.portal_answers import PublicAnswerSource

    with st.expander("Public company sources"):
        st.caption(
            "Add a public URL and an excerpt to use as evidence for employer claims."
        )
        url = st.text_input("Public page URL", key=_input_key(prefix, "source", "url"))
        snippet = st.text_area(
            "Public page excerpt", key=_input_key(prefix, "source", "snippet")
        )
        if st.button(
            "Add public source",
            key=f"{prefix}_add_source",
            disabled=not (url.strip() and snippet.strip()),
        ):
            try:
                editor["public_sources"].append(
                    PublicAnswerSource(url=url, snippet=snippet)
                )
            except ValueError as error:
                st.error(str(error))
        for index, source in enumerate(editor["public_sources"]):
            st.text(str(source.url))
            st.text(source.snippet)
            if st.button("Remove source", key=f"{prefix}_remove_source_{index}"):
                editor["public_sources"].pop(index)
                st.rerun()


def _draft(config, profile_id, job_id, prefix, editor, questions, use_current_profile):
    from config import ConfigError
    from services.portal_answers import draft_answers
    from services.profile_store import ProfileStoreError
    from services.provider import ProviderError, build_provider

    try:
        with st.spinner("Drafting selected answers…"):
            batch = draft_answers(
                config,
                profile_id=profile_id,
                job_id=job_id,
                questions=[AnswerQuestion(**question) for question in questions],
                provider=build_provider(config),
                use_current_profile=use_current_profile,
                public_sources=editor["public_sources"],
            )
    except (ConfigError, ProviderError, ProfileStoreError, OSError, ValueError) as error:
        st.error(str(error))
        return
    evidence = {item.id: item for item in batch.evidence}
    for draft in batch.drafts:
        editor["drafts"][draft.question_id] = draft
        editor["evidence"][draft.question_id] = [
            evidence[item] for item in draft.evidence_ids if item in evidence
        ]
        editor["suggestions"].pop(draft.question_id, None)
        if draft.text:
            key = _input_key(prefix, draft.question_id, "answer")
            if st.session_state.get(key, "").strip():
                editor["suggestions"][draft.question_id] = draft.text
            else:
                st.session_state[key] = draft.text
    for warning in batch.warnings:
        st.warning(warning)
    if batch.usage:
        st.caption(
            f"Drafting cost {batch.usage.cost_usd:.6f} USD ({batch.usage.cost_source})"
        )


def _render_answer(prefix, editor, question, number):
    question_id = question["id"]
    key = _input_key(prefix, question_id, "answer")
    suggestion = editor["suggestions"].get(question_id)
    if suggestion:
        with st.expander(f"New suggested draft for question {number}"):
            st.text(suggestion)
            if st.button("Use this draft", key=f"{prefix}_use_{question_id}"):
                st.session_state[key] = editor["suggestions"].pop(question_id)
    row = f"answer-copy-{question_id}"
    with st.container(key=row):
        text = st.text_area(f"Answer {number}", key=key, max_chars=8000)
        copy_controls(
            key=f"{prefix}_copy_{question_id}",
            data={
                "row": row,
                "text": text,
                "maxCharacters": question["max_characters"],
                "maxWords": question["max_words"],
            },
        )
    draft = editor["drafts"].get(question_id)
    if draft:
        if draft.message:
            st.warning(draft.message)
        for missing in draft.missing_facts:
            st.warning(f"Missing fact · {missing}")
        evidence = editor["evidence"].get(question_id)
        if evidence:
            with st.expander(f"Evidence for question {number}"):
                for item in evidence:
                    st.caption(item.source.replace("_", " ").title())
                    if item.url:
                        st.text(item.url)
                    st.text(item.text)
    return text


def _can_use_snapshot(snapshot):
    try:
        Profile.model_validate(snapshot)
    except ValidationError:
        return False
    return True


def render_answers(config, profile_id, job_id, prefix, detail):
    from models.portal_answers import AnswerEdit
    from services.portal_answer_store import save_answer_sheet

    state_key = f"{prefix}_answer_editor"
    try:
        editor = st.session_state.get(state_key) or _load_editor(
            config, profile_id, job_id, prefix, state_key
        )
    except (OSError, ValueError) as error:
        st.error(str(error))
        return
    for warning in editor["warnings"]:
        st.warning(warning)
    _render_add_questions(prefix, editor)
    questions = []
    selected_questions = []
    for number, question_id in enumerate(editor["rows"], 1):
        values, selected = _render_question(prefix, editor, question_id, number)
        questions.append(values)
        if selected:
            selected_questions.append(values)
    _render_public_sources(prefix, editor)
    use_current = False
    if not _can_use_snapshot(detail["snapshot"]):
        use_current = st.checkbox(
            "Use the current profile for this application",
            key=_input_key(prefix, "source", "current_profile"),
            help="This application has no usable saved profile snapshot.",
        )
    if st.button(
        "Draft selected answers",
        key=f"{prefix}_draft_answers",
        type="primary",
        disabled=not selected_questions,
        help="Send selected questions and saved evidence to the configured model. Drafting may incur provider charges.",
    ):
        _draft(
            config, profile_id, job_id, prefix, editor, selected_questions, use_current
        )
    if questions:
        st.subheader("Review and edit answers")
    edits = []
    for number, question in enumerate(questions, 1):
        text = _render_answer(prefix, editor, question, number)
        if text.strip():
            edits.append(AnswerEdit(question_id=question["id"], text=text))
    if st.button(
        "Save answers",
        key=f"{prefix}_save_answers",
        disabled=bool(editor["warnings"])
        or (not questions and editor["revision"] is None),
    ):
        try:
            saved = save_answer_sheet(
                config,
                profile_id=profile_id,
                job_id=job_id,
                expected_revision=editor["revision"],
                questions=[AnswerQuestion(**values) for values in questions],
                edits=edits,
                public_sources=editor["public_sources"],
            )
        except (OSError, ValueError) as error:
            st.error(str(error))
        else:
            if saved.warnings:
                editor["warnings"] = list(saved.warnings)
                for warning in saved.warnings:
                    st.warning(warning)
            else:
                editor["revision"] = saved.revision
                st.success("Answers saved in this application folder.")
