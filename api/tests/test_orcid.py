"""An ORCID iD on the profile: a labelled link on CVs, and an answer for forms that ask for it."""
import pytest

from app import agent, answers, doc_render
from app.models import CoreInfo

ID = "0009-0009-7786-8549"


@pytest.mark.parametrize("value, url", [
    (ID, f"https://orcid.org/{ID}"),
    (f"https://orcid.org/{ID}", f"https://orcid.org/{ID}"),
    (f"orcid.org/{ID}/", f"https://orcid.org/{ID}"),
    ("0000-0002-1825-009x", "https://orcid.org/0000-0002-1825-009X"),   # the check digit can be X
    ("", ""),
    ("my orcid", ""),
    ("https://example.com/0009-0009-7786-8549", ""),
])
def test_an_orcid_id_becomes_its_orcid_org_link(value, url):
    assert doc_render._orcid_url(value) == url


def test_the_cv_header_links_orcid_after_the_other_profiles():
    items = doc_render._contact_items({"email": "ada@example.com", "github": "github.com/ada", "orcid": ID})
    assert items[-2:] == [{"text": "GitHub", "href": "https://github.com/ada"},
                          {"text": "ORCID", "href": f"https://orcid.org/{ID}"}]
    assert all(i["text"] != "ORCID" for i in doc_render._contact_items({"orcid": "not an id"}))


def test_the_cv_gets_the_orcid_id_from_the_profile():
    persona = {"core_info": {"first_name": "Ada", "orcid": ID}}
    assert agent._persona_to_cvdoc(persona)["contact"]["orcid"] == ID
    assert CoreInfo().orcid == ""


def test_a_form_asking_for_an_orcid_id_can_be_answered_from_the_profile():
    facts = {f.id: f for f in answers.profile_facts({"core_info": {"orcid": ID}})}
    assert facts["orcid"].value == ID and not facts["orcid"].private
    assert "orcid" not in {f.id for f in answers.profile_facts({"core_info": {}})}
