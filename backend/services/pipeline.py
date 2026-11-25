"""The generation pipeline: drive the model until its response validates.

`DocumentGenerator` calls the provider, validates each response, corrects a failure up
to `MAX_VALIDATION_ATTEMPTS` times and drives the layout-retry loop. It holds no
filesystem state -- `tailor_service` persists whatever comes back, which is what makes
the flow testable in parts.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

from models.profile import Profile
from models.job import normalise_country
from models.tailored_output import TailoredCV, TailoredCoverLetter

from services.cv_delta import (
    apply_cv_delta,
    extract_explanation,
    looks_like_cv_delta,
    parse_json_response,
)
from services.prompts import layout_budget, layout_retry_instruction
# The gates are called **through their module** rather than imported as bare names, so
# `services.validation` stays the one place a caller patches to observe them. Rebinding
# a re-export on the `services.generation` facade would not intercept the call, because
# the facade is an alias rather than a lookup path.
from services import validation
from services.validation import ProfileRules

logger = logging.getLogger(__name__)

#: Attempts per document before giving up and reporting the last validation error.
MAX_VALIDATION_ATTEMPTS = 3

#: Layout attempts before the two-page target is declared unreachable.
MAX_LAYOUT_ATTEMPTS = 4

_SUPPORT = re.compile(
    r"\b(?:sponsor(?:ship|ed|ing)?|employer (?:permit )?support|(?:work|employment) permit support)\b",
    re.I,
)
_IMMIGRATION = re.compile(
    r"\b(?:blue card|green card|(?:work|employment|residence) (?:permit|visa)|"
    r"(?:immigration|visa) (?:status|support|requirements?|sponsorship)|"
    r"work (?:authori[sz]ation|rights|eligibility)|right to work|authori[sz]ed to work|"
    r"permanent residen(?:t|ce|cy)|citizen(?:ship)?|H[-‑]?1B)\b", re.I,
)
_STATUS = re.compile(r"\b(?:blue card|green card|permanent residen(?:t|ce|cy)|citizen(?:ship)?|H[-‑]?1B)\b", re.I)
_HELD_PERMIT = re.compile(
    r"\b(?:hold|have|possess)\s+(?:(?:a|an|valid|current|[a-z]+-issued)\s+)*"
    r"(?:[a-z]+\s+)?((?:work|employment|residence) (?:permit|visa))\b", re.I,
)
_NEED_SUPPORT = re.compile(r"\b(?:need|require)\s+(?:[a-z]+\s+){0,3}" + _SUPPORT.pattern, re.I)
_EXEMPTION = re.compile(
    r"\b(?:no (?:employer )?(?:support|sponsorship)|"
    r"(?:does not|do not|would not|don.t|won.t|without) (?:need |require )?(?:employer )?(?:support|sponsorship)|"
    r"(?:sponsorship|employer support) (?:is not (?:needed|required)|is unnecessary)|"
    r"(?:existing|unrestricted|automatic|full) (?:local )?(?:work rights|right to work|work authori[sz]ation))\b",
    re.I,
)


@dataclass
class TokenCounts:
    """Input tokens, output tokens and call count, tracked per component."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, inputs: int, outputs: int) -> None:
        self.input_tokens += inputs
        self.output_tokens += outputs
        self.calls += 1

    def as_list(self) -> list:
        return [self.input_tokens, self.output_tokens, self.calls]

class DocumentGenerator:
    """Produces a validated CV and cover letter from a profile and a posting.

    Holds no filesystem state; ``tailor_service`` persists whatever comes back.
    """

    def __init__(
        self,
        service,
        profile: Profile,
        rules: Optional[ProfileRules] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        *,
        layout_guidance: str = "",
    ):
        self.service = service
        self.profile = profile
        # Resolve rules from the profile unless the caller supplied an explicit set,
        # so a multi-profile setup validates each candidate against its own facts.
        self.rules = rules or ProfileRules.from_profile(profile)
        self.status_callback = status_callback
        self.layout_guidance = layout_guidance
        self.counts = {"cv": TokenCounts(), "cover_letter": TokenCounts()}
        self.drafts: list = []

    # --- one document ------------------------------------------------------------------

    def _status(self, message: str) -> None:
        if self.status_callback:
            self.status_callback(message)

    def generate(
        self,
        prompt: str,
        kind: str,
        work_country: Optional[str] = None,
        company_name: Optional[str] = None,
        role_title: Optional[str] = None,
        base_cv: Optional[TailoredCV] = None,
    ):
        """Call the model until its response validates, or raise after three attempts.

        ``base_cv`` names the document a CV retry is shortening. When it is supplied, a
        response may be a *delta* (:func:`apply_cv_delta`) as well as a complete CV, and
        either way the result re-enters :meth:`_build_model`, so ``validate_cv`` gates it
        exactly as it gates a draft. There is no branch that returns a document the gate
        has not seen, and no branch that quietly keeps ``base_cv`` when the model fails:
        a retry that cannot be applied is retried and then raises.

        ``kind`` is also forwarded to the provider as the *response contract*: it selects
        the structured-output schema. ``base_cv`` is what marks the one call that may
        return a delta, and that call is sent no schema -- see
        :func:`response_schema_for`.
        """
        last_error = ""
        previous = ""
        for _ in range(MAX_VALIDATION_ATTEMPTS):
            feedback = (
                f"\nCORRECTION REQUIRED: {last_error}\nPREVIOUS RESPONSE:\n{previous}\n"
                "Return the corrected complete JSON document."
                if last_error
                else ""
            )
            response, inputs, outputs = self.service._call_provider(
                prompt + feedback, kind=kind, allow_delta=base_cv is not None,
            )
            self.counts[kind].add(inputs, outputs)
            self.drafts.append({"component": kind, "response": response})
            try:
                data = parse_json_response(response, accept_delta=base_cv is not None)
                if base_cv is not None and looks_like_cv_delta(data):
                    # A delta is merged onto the *validated* CV, then gated again. The
                    # two checks are complementary: the merge guarantees employers,
                    # titles and dates are unchanged; the gate guarantees the new prose
                    # does not claim a banned tool, a forbidden summary verb, or
                    # sponsorship.
                    model = self._build_model(
                        {"cv": apply_cv_delta(base_cv, data).model_dump()},
                        kind, work_country, company_name, role_title,
                    )
                else:
                    model = self._build_model(data, kind, work_country, company_name, role_title)
                if base_cv is not None and model.standalone_projects != base_cv.standalone_projects:
                    raise ValueError("Keep the selected standalone projects in the same order during layout retries.")
                return model, data
            except ValueError as error:
                last_error = str(error)
                previous = response
                logger.warning("%s document validation failed: %s", kind, last_error)
        raise ValueError(
            f"Could not produce a valid {kind} document after three attempts: {last_error}"
        )

    def restore(
        self,
        cv_data: dict,
        cl_data: dict,
        work_country: Optional[str] = None,
        company_name: Optional[str] = None,
        role_title: Optional[str] = None,
    ):
        """Re-admit a **stored** CV and cover letter through the same gate.

        Phase 3 item 5 serves an identical generation from the cache instead of
        paying for it twice. The one thing that must not happen is a stored document
        reaching the renderer without being validated again: the cache is a file on
        disk that a person can edit, truncate or hand-craft, so "it was validated
        when it was stored" is a claim about the past, not about these bytes.

        Re-validating is free -- no API call -- so a cache hit runs exactly the same
        gate a fresh generation runs, through exactly the same method. A stored
        document that no longer validates (because the profile changed, or the file
        was edited) raises here, and the caller turns that into a miss and generates
        the document instead.

        The question this answers honestly: a cache entry that *fails* the gate
        cannot be served. It is not deleted -- the read path never writes -- and the
        next identical request re-generates, overwriting the entry.
        """
        cv = self._build_model(
            {"cv": cv_data}, "cv", work_country, company_name, role_title
        )
        cl = self._build_model(
            {"cover_letter": cl_data}, "cover_letter", work_country, company_name, role_title
        )
        return cv, cl

    def _build_model(
        self,
        data: dict,
        kind: str,
        work_country: Optional[str],
        company_name: Optional[str],
        role_title: Optional[str],
    ):
        """Validate one parsed response and apply country/company/role adjustments."""
        if kind == "cv":
            model = TailoredCV.model_validate(data.get("cv", data))
            label = model.work_authorization
            override = self.rules.country_override(work_country)
            allowed = override["work_authorization"] if override is not None else (
                self.rules.visa_label or self.profile.identity.visa_status
            )
            if label and (not allowed or label.strip().casefold() != allowed.strip().casefold()):
                raise ValueError("Use only the profile's confirmed work authorization label.")
            prose = model.model_dump_json(exclude={"work_authorization"})
            self._check_country_override_wording(prose, work_country)
            if _SUPPORT.search(model.model_dump_json()) or (allowed and _SUPPORT.search(allowed)):
                raise ValueError(
                    "Sponsorship and work permit support requirements belong only in the "
                    "cover letter, never in the CV."
                )
            if _IMMIGRATION.search(prose):
                raise ValueError("Keep immigration and work authorization out of CV prose.")
            self._apply_visa_label(model, work_country)
            validation.validate_cv(model, self.profile, self.rules)
        else:
            model = TailoredCoverLetter.model_validate(data.get("cover_letter", data))
            validation.validate_cover_letter(model, self.profile, self.rules)
            self._check_sponsorship_sentence(model, work_country)
            if company_name:
                model.company_name = company_name
            if role_title:
                model.role_title = role_title
        return model

    def _apply_visa_label(self, cv: TailoredCV, work_country: Optional[str]) -> None:
        """Keep immigration status separate from sponsorship wording."""
        override = self.rules.country_override(work_country)
        if override is not None:
            cv.work_authorization = override["work_authorization"]
            return
        cv.work_authorization = (
            self.rules.visa_label if work_country and not self._is_home(work_country) else None
        )

    def _is_home(self, work_country: str) -> bool:
        country = normalise_country(work_country) or work_country.strip().casefold()
        return any(
            (normalise_country(home) or home.strip().casefold()) == country
            for home in self.rules.home_countries
        )

    def _check_country_override_wording(self, text: str, work_country: Optional[str]) -> None:
        override = self.rules.country_override(work_country)
        if override is not None and not override["requires_employer_support"] and (
            _IMMIGRATION.search(text) or _SUPPORT.search(text)
        ):
            raise ValueError(
                f"The profile confirms existing work rights in {work_country}. "
                "Remove immigration and sponsorship wording and use the "
                "country-specific tailoring guidance instead."
            )

    def _check_sponsorship_sentence(self, cl: TailoredCoverLetter, work_country: Optional[str]) -> None:
        """Overseas letters must address permit support; home-country letters must not leak visa wording."""
        override = self.rules.country_override(work_country)
        if override is not None and not override["requires_employer_support"]:
            self._check_country_override_wording(" ".join(cl.paragraphs), work_country)
            return
        body = " ".join(cl.paragraphs)
        if not work_country or (override is None and self._is_home(work_country)):
            if _IMMIGRATION.search(body) or _SUPPORT.search(body):
                raise ValueError(
                    "Do not include immigration or sponsorship wording in a cover letter "
                    "for a role in the candidate's home country or without a confirmed work country."
                )
            return
        visa = self.profile.identity.visa_status or ""
        blue_card_policy = bool(
            self.rules.visa_label and self.rules.home_countries and "blue card" in visa.casefold()
        )
        if override is None and not blue_card_policy:
            if _IMMIGRATION.search(body) or _SUPPORT.search(body):
                raise ValueError("Remove unsupported immigration and sponsorship claims.")
            return
        closing = cl.paragraphs[-1]
        if not _NEED_SUPPORT.search(closing) or _EXEMPTION.search(body) or (
            blue_card_policy and override is None and "blue card" not in closing.casefold()
        ):
            raise ValueError(
                f"State the confirmed status and employer permit support needed for "
                f"{work_country} in the final cover-letter paragraph."
            )
        evidence = f"{visa} {override['work_authorization'] if override else self.rules.visa_label or ''}"
        status_claims = _STATUS.findall(body) + _HELD_PERMIT.findall(body)
        if any(claim.casefold() not in evidence.casefold() for claim in status_claims):
            raise ValueError("Remove immigration status claims absent from the selected profile.")
        # Preserve the issuer words supplied by the profile, while allowing either
        # the adjective before the status or the country after 'issued by'.
        issuer_terms = re.findall(r"\b([a-z]+)(?:-issued)? (?:EU )?blue card\b", body, re.I)
        issuer_terms += re.findall(r"\bblue card issued by ([a-z]+)\b", body, re.I)
        evidence_words = set(re.findall(
            r"[a-z]+", f"{evidence} {' '.join(self.rules.home_countries)}".casefold()
        ))
        qualifier_words = {"a", "an", "the", "my", "valid", "eu", "existing", "current"}
        if any(term.casefold() not in evidence_words | qualifier_words for term in issuer_terms):
            raise ValueError(
                "Use only the Blue Card issuer confirmed by the selected profile."
            )

    # --- the full sequence -------------------------------------------------------------

    def generate_pair(
        self,
        cv_prompt: str,
        cl_prompt: str,
        work_country: Optional[str] = None,
        company_name: Optional[str] = None,
        role_title: Optional[str] = None,
    ):
        """Draft the CV, then generate the letter. Returns (cv, cl, explanation).

        The CV is produced by **one** call. Until Phase 3 increment 2 the draft was
        followed by a second, whole-CV editorial pass; its requirements now ship inside
        the draft prompt (:data:`EDITORIAL_REQUIREMENTS`), which removes a call and
        ~25% of input tokens without lowering the bar -- the returned draft is still the
        only document that reaches validation, and the ``tailoring_explanation`` now
        comes from the draft response rather than the review's.
        """
        self._status("Drafting CV...")
        cv, data = self.generate(cv_prompt, "cv", work_country, company_name, role_title)
        explanation = extract_explanation(data)

        # Generate the letter only once the CV's wording has passed validation.
        cl, _ = self.generate(cl_prompt, "cover_letter", work_country, company_name, role_title)
        return cv, cl, explanation

    def shorten_cv(
        self,
        cv: TailoredCV,
        page_count: int,
        attempt: int,
        cv_prompt: str,
        work_country: Optional[str],
        company_name: Optional[str],
        role_title: Optional[str],
        explanation: Optional[dict],
    ):
        """One layout retry: shorten the *current* candidate with a tighter budget.

        What is sent is the retry brief and the current CV, not the whole context again:
        the context was already sent on the draft call, and a delta response can replace
        only the units that need shortening. ``cv_prompt`` stays in the signature so
        callers are unchanged, but it is deliberately no longer re-sent.

        The gate is unchanged: see :meth:`generate`. ``extract_explanation`` is read
        first from the retry's own response, so a retry that returns its own explanation
        supersedes the draft's.
        """
        self._status(f"CV is {page_count} pages; shortening content...")
        budget = layout_budget(attempt)
        cv, data = self.generate(
            layout_retry_instruction(
                cv, page_count, budget, attempt, self.rules, guidance=self.layout_guidance
            )
            + cv.model_dump_json(indent=2),
            "cv", work_country, company_name, role_title,
            base_cv=cv,
        )
        return cv, extract_explanation(data) or explanation

    def usage_kwargs(self) -> dict:
        """Token counts in the shape ``calculate_token_usage`` expects."""
        cv, cl = self.counts["cv"], self.counts["cover_letter"]
        return {
            "cv_input_tokens": cv.input_tokens,
            "cv_output_tokens": cv.output_tokens,
            "cl_input_tokens": cl.input_tokens,
            "cl_output_tokens": cl.output_tokens,
            "cv_attempts": cv.calls,
            "cl_attempts": cl.calls,
        }
