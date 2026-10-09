"""CV document building: persona → CVDoc → rendered HTML."""
from app import agent, doc_render


def test_certifications_keep_issuer_and_date_through_to_the_rendered_cv():
    persona = {"core_info": {"first_name": "Ada", "last_name": "Lovelace"},
               "certifications": [{"name": "AWS Solutions Architect", "issuing_organization": "Amazon",
                                   "issue_date": "2024-05"},
                                  {"name": "Legacy Cert", "issuer": "Old Co", "year": "2021"}]}
    cv = agent._persona_to_cvdoc(persona)
    assert cv["certifications"] == [
        {"name": "AWS Solutions Architect", "issuer": "Amazon", "year": "05/2024"},
        {"name": "Legacy Cert", "issuer": "Old Co", "year": "2021"},
    ]
    html = doc_render.render_cv_html(cv)
    assert "AWS Solutions Architect" in html and "Amazon" in html and "05/2024" in html
