from whatsapp_agent_ar.arabic import contains_any, is_arabic, normalize, stem, tokens


def test_normalize_hamza_taa_diacritics_tatweel():
    assert normalize("إِجَازَةٌ سَنَوِيَّـــة") == "اجازه سنويه"
    assert normalize("أسعار الاستشارة") == normalize("اسعار الاستشاره")


def test_normalize_digits_and_repeats_and_invisible():
    assert normalize("٩٧١‏٥٠") == "97150"
    assert normalize("واااايد") == "وايد"
    assert normalize("Helllooo") == "helo"


def test_is_arabic():
    assert is_arabic("مرحبا كيف الحال")
    assert not is_arabic("What are your hours?")
    assert is_arabic("ابي احجز cleaning")
    assert is_arabic("123")


def test_gulf_synonyms_share_canonical_token():
    # "وين" (Gulf) and "العنوان" (MSA) and "location" all map to the same concept
    assert "موقع" in tokens("وين مكانكم")
    assert "موقع" in tokens("ما هو العنوان")
    assert "موقع" in tokens("where is your location")
    assert "طبيب" in tokens("الدختر موجود؟")
    assert "سعر" in tokens("بكم التنظيف")


def test_stopwords_and_stem():
    assert tokens("شو هذا") == []
    assert stem("والمواعيد") == "مواعيد"
    assert stem("doctors") == "doctor"


def test_contains_any_whole_words():
    assert contains_any("ابي اكلم موظف لو سمحت", ["موظف"])
    assert not contains_any("موظفين العيادة محترمين", ["موظف"])
    assert contains_any("I want a HUMAN please", ["human"])
