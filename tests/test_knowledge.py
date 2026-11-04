import pytest

from whatsapp_agent_ar.knowledge import KnowledgeBase


@pytest.fixture
def kb(biz):
    return KnowledgeBase(biz.faq)


@pytest.mark.parametrize(
    "question,expected",
    [
        ("بكم التبييض؟", "prices"),
        ("كم اسعاركم", "prices"),
        ("وين مكانكم بالضبط", "location"),
        ("متى تسكرون اليوم؟", "hours"),
        ("فاتحين يوم الجمعة؟", "hours"),
        ("وين اوقف الموتر", "parking"),
        ("تقبلون تأمين ضمان؟", "insurance"),
        ("اقدر ادفع بالتقسيط؟", "payment"),
        ("ضرسي يعورني وايد", "emergency"),
        ("عندكم تقويم شفاف", "braces"),
        ("Do you accept insurance?", "insurance"),
        ("what time do you open", "hours"),
        ("How much is cleaning", "prices"),
    ],
)
def test_dialect_and_english_questions_hit_right_entry(kb, question, expected):
    hit = kb.best(question)
    assert hit is not None, question
    assert hit.faq.id == expected


@pytest.mark.parametrize("question", ["شو رايك في الطقس اليوم", "who won the football match", "ههههه"])
def test_unrelated_questions_do_not_guess(kb, question):
    assert kb.best(question) is None
